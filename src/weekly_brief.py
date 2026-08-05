"""
주간 리포트의 서술 부분만 담당.
일간 버전(gemini_client.py)의 2단계 구조 — Stage A 사실 추출 → Stage B 렌더 — 를 그대로 따르되
검색 창을 일(d) 에서 주(w) 로 넓혔다.

원칙: 숫자는 코드가 계산해서 넘긴다. 모델은 계산하지 않고 설명만 한다.
"""

import os
import json
import datetime
import pytz
from google import genai
from google.genai import types
from ddgs import DDGS

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-pro")
SEOUL = pytz.timezone("Asia/Seoul")
NO_DATA = "__NO_DATA__"


def fetch_news(query, region="wt-wt", max_results=12):
    """timelimit='w' — 지난 한 주. 실패 시 환각을 허용하지 않고 NO_DATA 를 돌려준다."""
    items = []
    try:
        with DDGS() as d:
            items = list(d.news(query=query, region=region, safesearch="off",
                                timelimit="w", max_results=max_results))
    except Exception as e:
        print(f"[news] 실패: {type(e).__name__}")
    if not items:
        try:
            with DDGS() as d:
                items = list(d.text(query=query, region=region, safesearch="off",
                                    timelimit="w", max_results=max_results))
        except Exception as e:
            print(f"[text] 실패: {type(e).__name__}")
            return NO_DATA
    lines = []
    for i, it in enumerate(items, 1):
        date = (it.get("date") or "날짜미상")[:10]
        src = it.get("source") or "-"
        title = (it.get("title") or "").strip()
        body = (it.get("body") or "").strip().replace("\n", " ")[:400]
        lines.append(f"[S{i}] date={date} | src={src} | {title} :: {body}")
    return "\n".join(lines) if lines else NO_DATA


def collect(week_label):
    return {
        "us": fetch_news(f"stock market week in review {week_label} S&P 500 Nasdaq drivers",
                         region="us-en", max_results=14),
        "kr": fetch_news(f"코스피 주간 시황 {week_label} 외국인 수급 반도체", region="kr-kr"),
        "macro": fetch_news(f"Fed treasury yields inflation week {week_label}", region="us-en"),
    }


EXTRACT = """너는 금융 사실 추출 엔진이다. 완성된 글을 쓰지 말고 검증 가능한 사실만 뽑아라.

기준 주차: {week_label} (서울 시간)

【권위 데이터 — 숫자는 이것만이 정답이다. 뉴스와 어긋나면 이쪽을 따른다】
{market_json}

【미국 시장 자료】
{us}

【한국 시장 자료】
{kr}

【매크로 자료】
{macro}

규칙:
R1. 모든 주장에는 [S번호] 근거를 붙인다. 근거 없는 항목은 반드시 null 로 둔다. 추측 금지.
R2. 자료가 {no_data} 이면 해당 섹션은 통째로 null 이다. 사전 지식으로 메우지 마라.
R3. date 가 기준 주차보다 7일 이상 오래된 자료는 버린다.
R4. 숫자는 위 권위 데이터에서만 인용한다. 뉴스에 나온 수치는 인용하지 마라.

아래 JSON 만 출력한다(코드블록·설명 금지):
{{
  "week_thread": "이번 주를 관통한 한 줄 인과. 근거 없으면 null",
  "us": {{"summary": "2~3문장 또는 null", "evidence": ["S1"]}},
  "kr": {{"summary": "2~3문장 또는 null", "evidence": []}},
  "macro": {{"summary": "금리/인플레 흐름 2문장 또는 null", "evidence": []}},
  "next_week": ["다음 주 예정된 확인 가능한 일정만. 없으면 빈 배열"],
  "consistency_note": "권위 데이터와 뉴스 서술이 어긋나면 지적. 없으면 null"
}}"""

RENDER = """너는 주간 리포트의 서술 파트를 쓰는 편집자다. 아래 JSON 을 중국어 문장으로 옮긴다.

{facts_json}

【이 주의 내 포트폴리오 상황 — 참고용, 숫자를 새로 만들지 마라】
{pf_context}

작성 규칙:
- 중국어로 쓴다. 400~600자.
- 두 단락만 쓴다. 다른 제목·머리말·꼬리말을 붙이지 마라.
  1단락: 이번 주 시장 요약 (week_thread 를 축으로)
  2단락: 그것이 내 포지션에 갖는 의미. 반드시 위에 주어진 포지션 정보만 근거로 쓴다.
- summary 가 null 인 섹션은 "本周该板块无可靠资料" 라고 한 줄로 처리하고 지어내지 마라.
- 매수/매도를 권하지 마라. 관찰과 확인 포인트까지만 쓴다.
- 숫자를 새로 계산하거나 만들어내지 마라. 리포트 상단에 이미 표가 있으니 숫자 나열은 불필요하다.
- Telegram HTML 만 쓴다(<b> <i>). 마크다운 금지.

두 단락 본문만 출력한다."""


def _client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _ask(prompt, as_json):
    cfg = types.GenerateContentConfig(temperature=0.2)
    if as_json:
        cfg.response_mime_type = "application/json"
    r = _client().models.generate_content(model=MODEL, contents=prompt, config=cfg)
    return (r.text or "").strip()


def narrative(market_json, pf_context):
    now = datetime.datetime.now(SEOUL)
    week_label = now.strftime("%Y-%m-%d")
    src = collect(week_label)

    facts_raw = _ask(EXTRACT.format(week_label=week_label, market_json=market_json,
                                    us=src["us"], kr=src["kr"], macro=src["macro"],
                                    no_data=NO_DATA), as_json=True)
    try:
        facts = json.loads(facts_raw)
    except Exception:
        print("[stage-a] JSON 파싱 실패")
        return "<i>本周叙事生成失败，仅提供数据部分。</i>"

    body = _ask(RENDER.format(facts_json=json.dumps(facts, ensure_ascii=False, indent=2),
                              pf_context=pf_context), as_json=False)
    note = facts.get("consistency_note")
    if note:
        body += f"\n\n<i>⚠️ {note}</i>"
    nxt = facts.get("next_week") or []
    if nxt:
        body += "\n\n<b>📌 下周关注</b>\n" + "\n".join(f"· {x}" for x in nxt[:4])
    return body
