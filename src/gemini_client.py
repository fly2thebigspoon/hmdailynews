"""
每日金融简报生成器 v2
渠道不变：ddgs 检索 + Gemini Flash 生成

相对 v1 的核心改动：
1. ddgs.text() -> ddgs.news(timelimit="d")，从"相关性排序"改为"当日新闻"，并保留 date 字段
2. 抓取失败不再授权模型"基于已有知识库总结"，改为硬失败标记，强制该节输出"无资料"
3. 单次调用 -> 两段式：Stage A 只抽事实(JSON, 带证据编号)，Stage B 只排版渲染
4. 新增"当日主线"字段，强制各板块围绕同一条因果线解释
5. 新增行情/叙事一致性检查（VIX 方向 vs 风险评分）
6. 无证据的驱动因素必须为 null，渲染成"当日资料未覆盖"，而不是编一个
"""

import os
import json
import datetime
import pytz
from google import genai
from google.genai import types
from ddgs import DDGS

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
SEOUL = pytz.timezone("Asia/Seoul")

NO_DATA = "__NO_DATA__"


# ============================================================
# 检索层
# ============================================================

def fetch_news(query: str, region: str = "wt-wt", max_results: int = 10,
               timelimit: str = "d") -> str:
    """
    当日新闻检索。

    关键点：
    - 用 news() 而非 text()。text() 按相关性排序且无时效过滤，
      这正是"7月23日的伊朗旧闻被当成7月28日行情驱动"的根因。
    - timelimit="d" 限定近一天。
    - 保留并前置 date 字段，让模型有能力自行剔除过期内容。
    - 每条编号 [S1] [S2]...，供 Stage A 做证据引用。
    - 失败时返回 NO_DATA 哨兵，绝不返回"请基于已有知识库总结"这类幻觉授权。
    """
    lines = []
    try:
        with DDGS() as ddgs:
            items = list(ddgs.news(
                query=query,
                region=region,
                safesearch="off",
                timelimit=timelimit,
                max_results=max_results,
            ))
    except Exception as e:
        print(f"[news] 失败 query={query!r}: {e}")
        items = []

    # news() 不可用时降级到 text()，但仍带 timelimit
    if not items:
        try:
            with DDGS() as ddgs:
                items = list(ddgs.text(
                    query=query,
                    region=region,
                    safesearch="off",
                    timelimit=timelimit,
                    max_results=max_results,
                ))
        except Exception as e:
            print(f"[text-fallback] 失败 query={query!r}: {e}")
            return NO_DATA

    for i, it in enumerate(items, 1):
        date = (it.get("date") or "日期未知")[:10]
        src = it.get("source") or "-"
        title = (it.get("title") or "").strip()
        body = (it.get("body") or "").strip().replace("\n", " ")
        lines.append(f"[S{i}] date={date} | src={src} | {title} :: {body}")

    return "\n".join(lines) if lines else NO_DATA


def collect_sources(today: str) -> dict:
    """
    仍然只发 3 条查询（按你的选择不增加请求数），
    但把当天日期写进 query，并去掉 v1 里那种
    "A OR B today" 的混合式写法 —— DDG 对括号/OR 支持很差，
    混合查询只会让结果变成两个主题的稀释混合物。
    """
    return {
        "us": fetch_news(
            f"stock market close {today} S&P 500 Nasdaq Dow drivers earnings",
            region="us-en", max_results=12,
        ),
        "kr": fetch_news(
            f"코스피 마감 시황 {today} 급락 급등 반도체 외국인",
            region="kr-kr", max_results=10,
        ),
        "cn": fetch_news(
            f"中国 商务部 外交部 出口管制 反制 {today}",
            region="cn-zh", max_results=10,
        ),
    }


# ============================================================
# Stage A：事实抽取（只产出 JSON，不做任何排版）
# ============================================================

EXTRACT_PROMPT = """你是金融事实抽取引擎。你的唯一任务是从参考资料中抽取可核验的事实，不写任何成品文章。

今日日期（首尔时区）：{today}

【权威行情数据】（这是唯一可信的数字来源，新闻若与之矛盾，以此为准）
{market_json}

【美股资料】
{us_news}

【韩股资料】
{kr_news}

【中国资料】
{cn_news}

==================== 铁律 ====================
R1 证据强制：任何"驱动因素"都必须能指向具体的 [Sx] 编号。指不出来，就把 driver 写成 null，
   并把 evidence 写成空数组。绝对禁止用你的训练知识补充驱动因素。
R2 时效过滤：只使用 date 等于 {today} 或前一个交易日的条目。更早的条目一律丢弃，
   即使它看起来很相关。地缘冲突类新闻尤其危险——冲突的"升级"与"缓和"往往只隔几天，
   用错日期会让因果完全颠倒。
R3 行情优先：若新闻描述的方向与行情数据矛盾（例如新闻说避险情绪高涨、但 VIX 下跌），
   以行情数据为准，并在 conflicts 字段记录这个矛盾。
R4 主线唯一：先判断当天全球市场的单一主导逻辑（main_thread），
   再让每个板块说明自己是"跟随主线"还是"背离主线"。
   不同市场的同一个原因，必须归到同一条主线，不得拆成互不相干的故事。
R5 不编数据：任何具体数字（涨跌幅、财报数字、成交量）必须来自行情数据或资料原文。
R6 若某节资料为 "__NO_DATA__"，该节全部 driver 置 null，available 置 false。

只输出 JSON，不要任何解释文字。"""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "as_of_date": {"type": "string"},
        "main_thread": {
            "type": "object",
            "properties": {
                "statement": {"type": "string", "description": "当日全球市场单一主导逻辑，一句话；无法判定则填 null"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["high", "medium", "low", "none"]},
            },
            "required": ["statement", "evidence", "confidence"],
        },
        "us": {
            "type": "array",
            "description": "恰好三项，依次为 NDX / SPX / DJI",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "driver": {"type": "string", "description": "驱动事件；无证据必须为 null"},
                    "specifics": {"type": "string", "description": "具体公司/财报/数字，来自资料原文"},
                    "relation_to_main_thread": {"type": "string", "enum": ["follows", "diverges", "unknown"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["code", "driver", "specifics", "relation_to_main_thread", "evidence"],
            },
        },
        "kr": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "driver": {"type": "string"},
                "specifics": {"type": "string"},
                "relation_to_main_thread": {"type": "string", "enum": ["follows", "diverges", "unknown"]},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["available", "driver", "specifics", "relation_to_main_thread", "evidence"],
        },
        "cn": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "event": {"type": "string"},
                "trigger": {"type": "string", "description": "该事件的直接触发因素；不明则 null"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["available", "event", "trigger", "evidence"],
        },
        "risk": {
            "type": "object",
            "properties": {
                "score": {"type": "integer"},
                "rationale": {"type": "string"},
                "vix_direction": {"type": "string", "enum": ["up", "down", "flat", "unknown"]},
                "consistent_with_vix": {"type": "boolean"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["score", "rationale", "vix_direction", "consistent_with_vix", "evidence"],
        },
        "conflicts": {
            "type": "array",
            "description": "新闻与行情矛盾之处，或资料内部互相矛盾之处",
            "items": {"type": "string"},
        },
    },
    "required": ["as_of_date", "main_thread", "us", "kr", "cn", "risk", "conflicts"],
}


def extract_facts(client, today: str, market_json: str, src: dict) -> dict:
    prompt = EXTRACT_PROMPT.format(
        today=today, market_json=market_json,
        us_news=src["us"], kr_news=src["kr"], cn_news=src["cn"],
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=EXTRACT_SCHEMA,
        ),
    )
    return json.loads(resp.text)


# ============================================================
# Stage B：渲染（只排版，不新增事实）
# ============================================================

RENDER_PROMPT = """你是排版引擎。把下面的事实 JSON 渲染成 Telegram 简报。

日期：{today}

【行情数据】（数字逐字符复制，不要重新计算）
{market_json}

【已核验事实 JSON】
{facts_json}

==================== 渲染铁律 ====================
- 严禁新增任何 JSON 里没有的事实、公司名、数字、因果关系。你不是分析师，你是排版工。
- driver 为 null 的条目，正文写「驱动因素：当日资料未覆盖」，不得用通用表述填补。
- available 为 false 的板块，整节写「当日无可用资料」。
- 严禁出现「面临挑战」「持续升级」「宏观压力」「高度联动」「关键支撑」这类无实质内容的词。
- 若 conflicts 非空，在风险摆锤一节末尾用一行说明该矛盾。

==================== 输出格式 ====================
第一行只写日期：{today}

<b>📊 Index</b>
• SPX: <价格> (<涨跌幅>)
• NDX / DJI / KOSPI / VIX 同上，只用代码不用全称

<b>🎯 Target Detail</b>
• QQQM: <价格> (<涨跌幅>) 距52周高 <回撤>
• SCHD / SPYM 同上

<b>🧭 Main Thread</b>
• 一行写当日主线；main_thread.statement 为 null 时写「当日主线未能从资料中确认」

<b>🇺🇸 US Market Dynamics</b>
• NDX：<驱动 + 具体数据>
• SPX：同上
• DJI：同上

<b>🇰🇷 Korea Market Headline</b>
• <驱动 + 具体数据>

<b>🇨🇳 China Geopolitical Headline</b>
• <事件 + 触发因素>

<b>⚖️ Macro Risk Pendulum</b>
• 全球市场脆弱性指数：<score>/10
• 评估依据：<rationale>

==================== 排版规则 ====================
- 只用 Telegram HTML：<b></b>。绝对不要 Markdown 的 # 或 ** 或 --- 分隔线。
- 每个要点用「• 」开头。
- 章节之间空一行。
- 不标注媒体名称与出处。
- 中文输出，全文 2000 字以内。
"""


def render(client, today: str, market_json: str, facts: dict) -> str:
    prompt = RENDER_PROMPT.format(
        today=today, market_json=market_json,
        facts_json=json.dumps(facts, ensure_ascii=False, indent=2),
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    )
    return resp.text


# ============================================================
# 质检
# ============================================================

def quality_gate(facts: dict, text: str) -> list:
    warns = []
    for bad in ("**", "###", "---", "##"):
        if bad in text:
            warns.append(f"排版泄漏 Markdown 标记: {bad}")

    r = facts.get("risk", {})
    if r.get("consistent_with_vix") is False:
        warns.append(f"风险评分 {r.get('score')} 与 VIX 方向 {r.get('vix_direction')} 不一致，需人工复核")

    mt = facts.get("main_thread", {})
    if mt.get("confidence") in ("low", "none"):
        warns.append("当日主线置信度低，简报因果部分可信度下降")

    for item in facts.get("us", []):
        if item.get("driver") and not item.get("evidence"):
            warns.append(f"{item.get('code')} 写了驱动但无证据编号 —— 疑似幻觉")

    if facts.get("conflicts"):
        warns.append("存在行情/新闻矛盾: " + "; ".join(facts["conflicts"]))

    for k in ("kr", "cn"):
        sec = facts.get(k, {})
        if sec.get("driver") or sec.get("event"):
            if not sec.get("evidence"):
                warns.append(f"{k} 节有内容但无证据编号 —— 疑似幻觉")
    return warns


# ============================================================
# 主流程
# ============================================================

def generate_brief(market_json: str) -> str:
    today = datetime.datetime.now(SEOUL).strftime("%Y-%m-%d")
    print(f"[1/4] 抓取当日新闻 ({today}) ...")
    src = collect_sources(today)
    for k, v in src.items():
        print(f"      {k}: {'无数据' if v == NO_DATA else str(v.count('[S')) + ' 条'}")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    print("[2/4] 抽取事实 ...")
    facts = extract_facts(client, today, market_json, src)

    print("[3/4] 渲染简报 ...")
    text = render(client, today, market_json, facts)

    print("[4/4] 质检 ...")
    for w in quality_gate(facts, text):
        print(f"      ⚠ {w}")

    return text


if __name__ == "__main__":
    print(generate_brief(os.environ.get("MARKET_JSON", "{}")))
