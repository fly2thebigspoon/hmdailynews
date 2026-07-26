import os
from google import genai
from google.genai import types

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

PROMPT_TEMPLATE = """你是一位专业的金融与国际政治资深分析师。严格按照我要求提供内容。

顶部只显示日期 日期格式:2026-**-**

以下是通过行情 API 硬拉的实时数字，请直接引用，不要改动或编造数字：
{market_json}

1. 大盘指数 SPX+NDX+DJI+KOSPI+VIX (只要5种 用我给你代码）
2. 美股市场动向（大盘走向 / 核心驱动因素 / 科技巨头 / 热门异动股 / 航天板块）
3. 全球主要地缘政治动态3条（重大事件及其对全球经济 / 能源 / 供应链的潜在影响）
4. 韩国头条 
5. 中国头条 
6. QQQM / SCHD / SPYM / RKLB 收盘价格含涨跌幅,52周最高回撤率=52W MDD  如 QQQM:284.98 （-1.87%）52W(-7.43%)
7. 以一位专业的金融与国际政治资深分析师短评本日全球概况


输出要求：
-各指标名称使用英文  如标普500 用  S&P500 7408 (-1.21%)  
-1~6项标题都是用英文 第一项大盘指数 用 Index ,每个标题签名排序数字不要
-【重要排版规则】这是发到 Telegram 的，只能用以下格式，绝对不要用 Markdown 的 # 号标题或 ** 星号：
- 中文输出，语言精炼、客观、要点化
  · 章节标题用 Telegram HTML 粗体标签，格式：<b>📊 一、核心情绪指标</b>
  · 需要强调的词也用 <b>词</b>，不要用 **词**
  · 每个要点用「• 」开头（圆点加空格），不要用 * 号或 - 号
  · 章节之间空一行分隔，不要用 --- 分隔线
- 每条新闻要有真实出处，不得捏造，隐藏来源和日期，请精简。
- 每个标题前面加入符合内容的EMOJI
- 标的价格信息不要用表格，一行一个标的
-中国头条新闻3条用境外大型媒体 股市，经济，地缘政治 各一条 每条信息空一行
-韩国头条新闻3条用韩国国内媒体 股市，经济，地缘政治 各一套 每条信息空一行
- 整个简报信息控制在 600-800 字以内
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
