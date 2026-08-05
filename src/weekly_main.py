"""
주간 리포트 엔트리. 매주 토요일 아침 1회 실행.

⚠️ Public 저장소 — 로그에 금액·보유 종목을 남기지 않는다.
   아래 print 는 전부 숫자 없는 진행 상태 문자열이다.
"""

import datetime
import json
import pytz

from weekly_data import (fb_login, fb_read, fb_write, market_snapshot,
                         week_change, analyze, check_rules, diff_vs_last)
from weekly_brief import narrative
from telegram_sender import send

SEOUL = pytz.timezone("Asia/Seoul")

CUR_SIGN = {"KRW": "₩", "USD": "$", "CNY": "¥"}


def money(v, cur):
    if not isinstance(v, (int, float)):
        return "—"
    s = CUR_SIGN.get(cur, "")
    return f"{s}{v:,.0f}" if cur == "KRW" else f"{s}{v:,.2f}"


def pct(v, digits=2):
    return f"{v:+.{digits}f}%" if isinstance(v, (int, float)) else "—"


def build(pf, market, rules, diff, tw, week_note):
    cur = pf["display_cur"]
    L = []
    today = datetime.datetime.now(SEOUL).strftime("%Y-%m-%d")
    L.append(f"<b>📅 주간 리포트</b> · {today} (토)")
    L.append(f"<i>기준: 직전 미국 종가{week_note}</i>\n")

    # ── 이번 주 변화 (맨 위로) ──
    L.append("<b>🔄 이번 주 변화</b>")
    if diff["first_run"]:
        L.append("· 다음 주부터 지난주 대비 변화가 표시됩니다")
    elif diff["lines"]:
        L += [f"· {x}" for x in diff["lines"][:10]]
    else:
        L.append("· 지난주와 비교해 눈에 띄는 구성 변화 없음")
    # 이번 주 새로 잡힌 리스크성 신호
    if rules["changes"]:
        L.append("")
        L.append("<b>⚡ 주목 신호</b>")
        L += [f"· {x}" for x in rules["changes"][:8]]
    L.append("")

    # ── 포트폴리오 스냅샷 ──
    L.append("<b>💼 포트폴리오</b>")
    L.append(f"총평가액 {money(pf['total_display'], cur)}"
             + (f"  (주간 {pct(pf['wow_pct'])})" if pf["wow_pct"] is not None else "  (주간 비교 데이터 축적 중)"))
    for r in pf["rows"][:6]:
        wk = tw.get(r["ticker"])
        tag = r["ticker"] or r["name"]
        L.append(f"· {tag} {r['share']:.1f}%"
                 + (f" ｜ 주간 {pct(wk,1)}" if wk is not None else "")
                 + (f" ｜ 누적 {pct(r['pl_pct'],1)}" if r["pl_pct"] is not None else ""))
    if len(pf["rows"]) > 6:
        L.append(f"<i>… 외 {len(pf['rows']) - 6}개</i>")
    ts = pf["type_share"]
    if ts:
        L.append("자산군 " + " ｜ ".join(f"{k} {v:.0f}%" for k, v in ts.items()))
    L.append("")

    # ── 구조적 상태 (접어서 맨 아래, 참고용) ──
    if rules["standing"]:
        L.append("<b>📐 구조적 상태</b> <i>(상시 항목)</i>")
        L += [f"· {h}" for h in rules["standing"][:8]]
        L.append("")

    # ── 시장 환경 ──
    L.append("<b>📊 시장 환경</b>")
    for name, d in market["indices"].items():
        p = d["price"]
        p_s = f"{p:,.2f}" if isinstance(p, (int, float)) else "—"
        L.append(f"· {name} {p_s} ｜ 주간 {pct(d['week'],1)}")
    rt = market.get("rates") or {}
    if rt.get("y10") is not None:
        if rt.get("fedHi") is not None:
            L.append(f"· 기준금리 {rt['fedLo']:.2f}~{rt['fedHi']:.2f}%")
        sp = rt.get("spread")
        L.append(f"· 10Y {rt['y10']:.2f}%"
                 + (f" ({rt['d10']:+.0f}bp)" if rt.get("d10") is not None else "")
                 + (f" ｜ 장단기차 {sp:+.2f}%p" if sp is not None else ""))
    fg = market.get("fg") or {}
    if fg.get("score") is not None:
        L.append(f"· Fear & Greed {fg['score']:.0f} ({fg.get('rating') or '-'})")
    L.append("")
    return "\n".join(L)


def main():
    token = fb_login()
    print("firestore: 로그인 성공")

    state = fb_read(token)
    print(f"firestore: 상태 로드 완료 (보유 항목 {len(state.get('holdings') or [])}건)")

    pf = analyze(state)
    print("포트폴리오: 지표 계산 완료")

    # 지난주 기록을 읽어 변화 비교의 기준선으로 쓴다 (첫 실행이면 없음)
    last = None
    try:
        last = fb_read(token, "portfolio/weeklyHistory")
        print("firestore: 지난주 기록 로드")
    except Exception:
        print("firestore: 지난주 기록 없음 (첫 실행)")

    tickers = [r["ticker"] for r in pf["rows"][:8] if r["ticker"]]
    tw = {}
    for t in tickers:
        w = week_change(t)
        if w is not None:
            tw[t] = w
    print(f"시세: 주간 변화 {len(tw)}/{len(tickers)}건 수집")

    market = market_snapshot()
    print("시장: 지표 수집 완료")

    rules = check_rules(pf, state, market, tw)
    diff = diff_vs_last(pf, last)
    print(f"규칙: 상시 {len(rules['standing'])} · 변화 {len(rules['changes'])} · 구성변화 {len(diff['lines'])}")

    note = "" if pf["wow_pct"] is not None else " · 주간 비교는 다음 주부터"
    head = build(pf, market, rules, diff, tw, note)

    # LLM 에 넘기는 컨텍스트: 비중과 규칙만. 금액은 넘기지 않는다.
    pf_context = json.dumps({
        "top_positions": [{"ticker": r["ticker"] or r["name"], "share_pct": round(r["share"], 1),
                           "week_pct": round(tw.get(r["ticker"], 0), 1) if r["ticker"] in tw else None}
                          for r in pf["rows"][:6]],
        "asset_mix_pct": {k: round(v, 1) for k, v in pf["type_share"].items()},
        "portfolio_week_pct": round(pf["wow_pct"], 2) if pf["wow_pct"] is not None else None,
        "changes_this_week": (diff["lines"][:6] + rules["changes"][:4]),
        "standing_state": rules["standing"][:5],
    }, ensure_ascii=False)

    market_json = json.dumps(market, ensure_ascii=False, indent=2)
    body = narrative(market_json, pf_context)
    print("gemini: 서술 생성 완료")

    send(head + "\n<b>🔍 이번 주 정리</b>\n" + body)
    print("텔레그램: 전송 완료")

    # 구성비 이력 — 앱이 쓰는 portfolio/main 이 아닌 별도 문서에 기록
    try:
        fb_write(token, "portfolio/weeklyHistory", {
            "updatedAt": datetime.datetime.now(SEOUL).strftime("%Y-%m-%d"),
            "assetMix": {k: round(v, 2) for k, v in pf["type_share"].items()},
            "topShares": {r["ticker"] or r["name"]: round(r["share"], 2) for r in pf["rows"][:10]},
        })
        print("firestore: 구성비 이력 기록 완료")
    except Exception as e:
        print(f"firestore: 이력 기록 건너뜀 ({type(e).__name__})")


if __name__ == "__main__":
    main()
