import os
from google import genai
from google.genai import types

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

PROMPT_TEMPLATE = """你是一位专业的金融与国际政治资深分析师。请为我生成一份【每日早间情报摘要】带日期。

以下是通过行情 API 硬拉的实时数字，请直接引用，不要改动或编造数字：
{market_json}

请检索并汇总过去 24 小时内发生的最新动态，重点聚焦：

首先呈现：各大指数、VIX、Fear & Greed 指数。

1. 美国大盘指数 + KOSPI + 日经 + 中国
2. 美股市场动向（大盘走向 / 核心驱动因素 / 科技巨头 / 热门异动股 / 航天板块）
3. 全球主要地缘政治动态（重大事件及其对全球经济 / 能源 / 供应链的潜在影响）
4. 韩国头条
5. 中国头条
6. QQQM / SCHD / SPYM / RKLB 收盘价格含涨跌幅、52周最高回撤率（用上方硬拉数字）

输出要求：
- 中文输出，语言精炼、客观、要点化
- 【重要排版规则】这是发到 Telegram 的，只能用以下格式，绝对不要用 Markdown 的 # 号标题或 ** 星号：
  · 章节标题用 Telegram HTML 粗体标签，格式：<b>📊 一、核心情绪指标</b>
  · 需要强调的词也用 <b>词</b>，不要用 **词**
  · 每个要点用「• 」开头（圆点加空格），不要用 * 号或 - 号
  · 章节之间空一行分隔，不要用 --- 分隔线
- 来源和日期请极度精简：统一放在该条末尾，用小括号包裹，格式如「（路透 07-23）」，不要写「[*来源：xxx，2026-07-23*]」这种长格式，年份省略
- 适当加入 Emoji 增强视觉，但每个要点最多一个
- 标的价格信息不要用表格，一行一个标的
- 控制在 600-800 字以内
- 每条新闻要有出处，不得捏造
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
