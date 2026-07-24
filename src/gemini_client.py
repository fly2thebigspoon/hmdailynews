import os
from google import genai
from google.genai import types

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

PROMPT_TEMPLATE = """你是一位专业的金融与国际政治资深分析师。请为我生成一份【每日早间情报摘要】。

以下是通过行情 API 硬拉的实时数字，请直接引用，不要改动或编造数字：
{market_json}

注意：若上方 PutCall 比率为空或标注需检索，请你通过搜索获取最新 CBOE Put/Call ratio，并标注来源与时间。

请检索并汇总过去 24 小时内发生的最新动态，重点聚焦：

首先呈现：各大指数、VIX、Fear & Greed 指数、Put/Call ratio。

1. 美国大盘指数 + KOSPI + 日经 + 中国
2. 美股市场动向（大盘走向 / 核心驱动因素 / 科技巨头 / 热门异动股 / 航天板块）
3. 全球主要地缘政治动态（重大事件及其对全球经济 / 能源 / 供应链的潜在影响）
4. 韩国主要地缘政治及股市简要
5. 中国重大事件
6. QQQM / SCHD / SPYM / RKLB 收盘价格含涨跌幅、52周最高回撤率（用上方硬拉数字）

输出要求：
- 中文输出，语言精炼、客观、要点化（Bullet points）
- 排版适合 Telegram 快速阅读，适当加入 Emoji 增强视觉排版；标的价格信息不要用表格形式
- 控制在 600-800 字以内，突出核心逻辑而非流水账
- 中国重大新闻优先引用 AP / Bloomberg / Reuters / CNN / BBC / 联合早报
- 韩国地缘政治及市场新闻引用韩国国内媒体
- 新闻和重大事件必须有出处，不得捏造；美股动向也要基于事实简要
- 每条新闻给出【来源 + 时间戳】
"""


def generate_brief(market_json: str) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = PROMPT_TEMPLATE.format(market_json=market_json)

    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        ),
    )
    return resp.text
