"""
주간 리포트 데이터 계층
  1) Firestore REST 로 앱 상태(portfolio/main) 읽기
  2) Cloudflare Worker 로 시장 데이터 수집
  3) 포트폴리오 지표 계산 + 규칙 판정

⚠️ 이 저장소는 Public 입니다.
   보유 종목·금액·평가액은 절대 print() 하지 마세요. Actions 로그는 누구나 볼 수 있습니다.
   진행 상황 로그는 숫자 없는 상태 문자열만 출력합니다.
"""

import os
import time
import datetime
import requests

WORKER = "https://zrp-quote.irisvcorp.workers.dev/"
PROJECT = "zrp-portfolio"
FS = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"

TIMEOUT = 20


# ============================================================
# 1) Firestore
# ============================================================

def fb_login():
    """앱과 동일한 이메일/비밀번호 계정으로 로그인. 관리자 권한을 쓰지 않는다."""
    key = os.environ["FB_API_KEY"]
    r = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={key}",
        json={"email": os.environ["FB_EMAIL"],
              "password": os.environ["FB_PASSWORD"],
              "returnSecureToken": True},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["idToken"]


def _dec(v):
    """Firestore REST 의 타입 래핑을 평범한 파이썬 값으로 되돌린다."""
    if "nullValue" in v:      return None
    if "booleanValue" in v:   return v["booleanValue"]
    if "integerValue" in v:   return int(v["integerValue"])
    if "doubleValue" in v:    return float(v["doubleValue"])
    if "stringValue" in v:    return v["stringValue"]
    if "timestampValue" in v: return v["timestampValue"]
    if "arrayValue" in v:     return [_dec(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:       return {k: _dec(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None


def _enc(o):
    if o is None:                return {"nullValue": None}
    if isinstance(o, bool):      return {"booleanValue": o}
    if isinstance(o, int):       return {"integerValue": str(o)}
    if isinstance(o, float):     return {"doubleValue": o}
    if isinstance(o, str):       return {"stringValue": o}
    if isinstance(o, list):      return {"arrayValue": {"values": [_enc(x) for x in o]}}
    if isinstance(o, dict):      return {"mapValue": {"fields": {k: _enc(v) for k, v in o.items()}}}
    return {"stringValue": str(o)}


def fb_read(token, path="portfolio/main"):
    r = requests.get(f"{FS}/{path}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return {k: _dec(v) for k, v in r.json().get("fields", {}).items()}


def fb_write(token, path, obj):
    """주간 구성비 이력 저장용. 앱이 쓰는 portfolio/main 은 절대 건드리지 않는다."""
    r = requests.patch(
        f"{FS}/{path}",
        headers={"Authorization": f"Bearer {token}"},
        json={"fields": {k: _enc(v) for k, v in obj.items()}},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return True


# ============================================================
# 2) 시장 데이터 (Cloudflare Worker)
# ============================================================

def _worker(params):
    try:
        r = requests.get(WORKER, params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[worker] {params.get('symbol', params)} 실패: {type(e).__name__}")
    return None


def quote(symbol):
    return _worker({"symbol": symbol}) or {}


def week_change(symbol):
    """?wk=1 은 1개월 일봉을 돌려준다. 7일 전 마지막 종가 대비 변화율(%)."""
    j = _worker({"symbol": symbol, "wk": "1"})
    if not j:
        return None
    ds, cs = j.get("dates") or [], j.get("closes") or []
    if len(cs) < 2:
        return None
    cutoff = time.time() - 7 * 86400
    base = None
    for t, c in zip(ds, cs):
        if t <= cutoff:
            base = c
    if not base:
        base = cs[0]
    return (cs[-1] / base - 1) * 100 if base else None


INDICES = {"S&P 500": "^GSPC", "나스닥": "^IXIC", "다우": "^DJI",
           "코스피": "^KS11", "VIX": "^VIX"}


def market_snapshot():
    out = {"indices": {}, "rates": {}, "fg": {}}
    for label, sym in INDICES.items():
        q = quote(sym)
        out["indices"][label] = {
            "price": q.get("price"),
            "day": q.get("changePct"),
            "week": week_change(sym),
        }
    ust = _worker({"ust": "1"}) or {}
    if ust.get("y10") is not None:
        prev = ust.get("prev") or {}
        out["rates"] = {
            "fedLo": ust.get("fedLo"), "fedHi": ust.get("fedHi"),
            "y2": ust.get("y2"), "y10": ust.get("y10"), "y30": ust.get("y30"),
            "spread": (ust["y10"] - ust["y2"]) if ust.get("y2") is not None else None,
            "d10": ((ust["y10"] - prev["y10"]) * 100) if prev.get("y10") is not None else None,
            "date": ust.get("date"),
        }
    fg = _worker({"fg": "1"}) or {}
    if fg.get("score") is not None:
        out["fg"] = {"score": fg["score"], "rating": fg.get("rating")}
    return out


# ============================================================
# 3) 포트폴리오 지표
# ============================================================

def _cny(h, rates):
    return (h.get("qty") or 0) * (h.get("price") or 0) * (rates.get(h.get("cur") or "KRW") or 0)


def _to_display(cny, state):
    """CNY -> 표시통화. 앱의 convDirect 와 같은 우선순위(실제 환율 페어 우선)."""
    cur = (state.get("meta") or {}).get("displayCurrency") or "KRW"
    if cur == "CNY":
        return cny
    fx = ((state.get("fx") or {}).get("data") or {})
    pair = fx.get(f"CNY{cur}=X") or {}
    p = pair.get("price")
    if isinstance(p, (int, float)) and p > 0:
        return cny * p
    r = (state.get("rates") or {}).get(cur) or 0
    return cny / r if r else 0


def analyze(state):
    rates = state.get("rates") or {}
    meta = state.get("meta") or {}
    holdings = [h for h in (state.get("holdings") or []) if isinstance(h, dict)]

    total = sum(_cny(h, rates) for h in holdings)
    rows = []
    for h in holdings:
        v = _cny(h, rates)
        avg, px, qty = h.get("avgCost") or 0, h.get("price") or 0, h.get("qty") or 0
        rows.append({
            "name": h.get("name") or "(미지정)",
            "ticker": (h.get("ticker") or "").upper(),
            "type": h.get("type") or "",
            "account": h.get("account") or "",
            "value_cny": v,
            "share": (v / total * 100) if total else 0,
            "pl_pct": ((px - avg) / avg * 100) if avg > 0 else None,
            "target": h.get("targetPct"),
        })
    rows.sort(key=lambda r: -r["value_cny"])

    by_type = {}
    for r in rows:
        by_type[r["type"]] = by_type.get(r["type"], 0) + r["value_cny"]
    type_share = {k: (v / total * 100 if total else 0) for k, v in by_type.items()}

    # 주간 순자산 변화 — 앱이 매일 남기는 snapshots 사용
    snaps = [s for s in (state.get("snapshots") or []) if isinstance(s, dict) and s.get("d")]
    snaps.sort(key=lambda s: s["d"])
    wow = None
    if snaps:
        target = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        base = None
        for s in snaps:
            if s["d"] <= target:
                base = s
        if base and base.get("cny"):
            wow = (total / base["cny"] - 1) * 100

    return {
        "total_cny": total,
        "total_display": _to_display(total, state),
        "display_cur": meta.get("displayCurrency") or "KRW",
        "rows": rows,
        "type_share": type_share,
        "wow_pct": wow,
        "snap_days": len(snaps),
    }


# ============================================================
# 4) 규칙 판정 — 숫자 판단은 전부 여기서. LLM 은 개입하지 않는다.
# ============================================================

def _is_cash_type(name):
    """현금형/현금/cash 계열 자산군인지. meta.cashFloorType 이 바뀌어 있을 수 있어 이름으로 판정."""
    n = (name or "").lower()
    return ("현금" in n) or ("cash" in n) or ("예수" in n) or ("mmf" in n)


def check_rules(pf, state, market, ticker_week):
    """규칙을 두 갈래로 나눠 돌려준다.
       standing: 매주 거의 항상 참인 구조적 상태(집중도/현금수위/목표배분 이탈)
       changes : 이번 주에 '새로' 또는 '더 심하게' 발생한 것 (낙폭·급변동·금리역전)
    """
    meta = state.get("meta") or {}
    conc = meta.get("concThreshold") or 15
    floor = meta.get("cashFloor") or 40
    reb = meta.get("rebalThreshold") or 5

    standing, changes = [], []

    # 현금성 자산군 실제 비중 (이름 기반 합산)
    cash_share = sum(v for k, v in pf["type_share"].items() if _is_cash_type(k))

    # ── 상시(구조적) ──
    for r in pf["rows"]:
        if _is_cash_type(r["type"]):
            continue                     # 현금성 단일 항목은 집중 위험으로 보지 않음
        if r["share"] > conc:
            standing.append(f"집중도: {r['name']} {r['share']:.1f}% (기준 {conc}%)")

    if cash_share < floor:
        standing.append(f"현금 수위: {cash_share:.1f}% (하한 {floor}% 미달)")
    elif cash_share > 100 - floor:
        # 현금이 과도하게 높은 경우(=투자 비중 낮음)도 알려준다
        standing.append(f"현금 과다: 현금성 {cash_share:.1f}%")

    for t in (state.get("assetTypes") or []):
        name, tgt = t.get("name"), (t.get("target") or 0) * 100
        cur = pf["type_share"].get(name, 0)
        if abs(cur - tgt) >= reb:
            standing.append(f"{name} {cur:.1f}% / 목표 {tgt:.0f}% ({cur - tgt:+.1f}%p)")

    # ── 변화(이번 주 신규/악화) ──
    val = ((state.get("valuation") or {}).get("data") or {})
    for r in pf["rows"]:
        d = val.get(r["ticker"]) or {}
        hi, px = d.get("high52"), d.get("price")
        if isinstance(hi, (int, float)) and isinstance(px, (int, float)) and hi > 0:
            dd = (px - hi) / hi * 100
            if dd <= -20:
                pl = r.get("pl_pct")
                pl_txt = f" · 보유손익 {pl:+.0f}%" if isinstance(pl, (int, float)) else ""
                changes.append(f"낙폭: {r['name']} 52주 고점대비 {dd:.0f}%{pl_txt}")

    for tk, wk in (ticker_week or {}).items():
        if isinstance(wk, (int, float)) and abs(wk) >= 8:
            changes.append(f"주간 급변동: {tk} {wk:+.1f}%")

    rt = market.get("rates") or {}
    if isinstance(rt.get("spread"), (int, float)) and rt["spread"] < 0:
        changes.append(f"장단기 금리 역전: 10Y−2Y {rt['spread']:+.2f}%p")

    return {"standing": standing, "changes": changes}


def diff_vs_last(pf, last):
    """지난주 기록(portfolio/weeklyHistory)과 비교해 '무엇이 바뀌었나'를 만든다.
       last 가 없으면(첫 실행) 빈 리스트를 돌려주고, 다음 주부터 채워진다."""
    if not last:
        return {"first_run": True, "lines": [], "type_delta": {}}
    lines = []
    prev_mix = (last.get("assetMix") or {})
    prev_share = (last.get("topShares") or {})

    # 자산군 비중 변화 (±1.0%p 이상만)
    for k, v in pf["type_share"].items():
        pv = prev_mix.get(k)
        if isinstance(pv, (int, float)) and abs(v - pv) >= 1.0:
            lines.append(f"{k} {pv:.0f}% → {v:.0f}% ({v - pv:+.1f}%p)")

    # 개별 종목 비중 변화 (±1.5%p 이상)
    cur_share = {(r["name"] or r["ticker"]): r["share"] for r in pf["rows"]}
    for name, v in cur_share.items():
        pv = prev_share.get(name)
        if isinstance(pv, (int, float)) and abs(v - pv) >= 1.5:
            lines.append(f"{name} {pv:.1f}% → {v:.1f}% ({v - pv:+.1f}%p)")

    # 신규 편입 / 완전 청산
    new_names = set(cur_share) - set(prev_share)
    gone_names = set(prev_share) - set(cur_share)
    for n in sorted(new_names):
        if cur_share.get(n, 0) >= 0.5:
            lines.append(f"신규 편입: {n} ({cur_share[n]:.1f}%)")
    for n in sorted(gone_names):
        if prev_share.get(n, 0) >= 0.5:
            lines.append(f"청산/제외: {n} (지난주 {prev_share[n]:.1f}%)")

    # 자산군별 지난주 대비 비중 변화(%p) — build 의 자산군 줄에서 사용
    type_delta = {}
    for k, v in pf["type_share"].items():
        pv = prev_mix.get(k)
        if isinstance(pv, (int, float)):
            type_delta[k] = v - pv

    return {"first_run": False, "lines": lines, "type_delta": type_delta}



# ============================================================
# 5) 공회전 추적 (현금 보유의 기회비용)
#    - 매주 '가상 정기투자 1회분'을 벤치마크에 넣었다고 가정하고 누적한다.
#    - 이력(shares 누적, 투입 원금)은 weeklyHistory 문서에 함께 저장한다.
#    - 부추기지 않는다: 시장이 내리면 diff 는 +(회피한 손실), 오르면 -(놓친 수익).
# ============================================================

def _to_cny_amount(amount, cur, state):
    """정기투자 금액(사용자 지정 통화)을 CNY로. analyze 와 같은 rates 사용."""
    r = (state.get("rates") or {}).get(cur or "KRW") or 0
    return amount * r


def _from_cny_to_display(cny, state):
    cur = (state.get("meta") or {}).get("displayCurrency") or "KRW"
    if cur == "CNY":
        return cny, cur
    fx = ((state.get("fx") or {}).get("data") or {})
    pair = (fx.get(f"CNY{cur}=X") or {}).get("price")
    if isinstance(pair, (int, float)) and pair > 0:
        return cny * pair, cur
    r = (state.get("rates") or {}).get(cur) or 0
    return (cny / r if r else 0), cur


def _check_signal(expr, market):
    """'VIX>=25' / 'SPX_DD>=10' 같은 조건이 이번 주에 충족됐는지. 못 알아보면 None."""
    if not expr:
        return None
    import re
    m = re.match(r"^(VIX|SPX_DD)(>=|<=|>|<)([\d.]+)$", expr.strip().upper())
    if not m:
        return None
    key, op, val = m.group(1), m.group(2), float(m.group(3))
    idx = market.get("indices") or {}
    if key == "VIX":
        cur = (idx.get("VIX") or {}).get("price")
    else:  # SPX_DD: S&P 고점대비 하락% (양수). 주간 데이터로는 근사만 가능 → 주간 하락폭으로 대체 근사
        wk = (idx.get("S&P 500") or {}).get("week")
        cur = -wk if isinstance(wk, (int, float)) else None
    if not isinstance(cur, (int, float)):
        return None
    if op == ">=": return cur >= val
    if op == "<=": return cur <= val
    if op == ">":  return cur > val
    if op == "<":  return cur < val
    return None


def idle_tracker(state, market, last):
    """공회전 추적 계산.
       last: 지난주 weeklyHistory (idle 누적 필드 포함 가능).
       반환: 화면에 뿌릴 dict, 그리고 이번 주 저장할 idle 상태.
       설정이 꺼져 있으면 (None, None)."""
    cfg = ((state.get("meta") or {}).get("idleTrack") or {})
    if not cfg.get("enabled") or not (cfg.get("weekly") or 0) > 0:
        return None, None

    weekly = float(cfg["weekly"])
    cur = cfg.get("cur") or "KRW"
    bench = (cfg.get("benchmark") or "VOO").upper()

    # 벤치마크 현재가
    q = quote(bench)
    px = q.get("price") if q else None
    if not isinstance(px, (int, float)) or px <= 0:
        return {"error": f"{bench} 시세를 가져오지 못했습니다"}, None

    # 지난주까지 누적된 상태
    prev = (last or {}).get("idle") or {}
    prev_shares = float(prev.get("shares") or 0)      # 벤치마크 누적 주수
    prev_principal_cny = float(prev.get("principalCny") or 0)
    prev_weeks = int(prev.get("weeks") or 0)
    prev_right = int(prev.get("weeksRight") or 0)     # '기다리길 잘한' 주 수
    prev_bench_px = prev.get("lastBenchPx")           # 지난주 벤치마크가(승패 판정용)

    # 이번 주 1회분 투입 (통화 → 그 통화 기준 주수. 간단히 '표시통화 무관하게 CNY로 환산 후 벤치가로 나눔')
    invest_cny = _to_cny_amount(weekly, cur, state)
    bench_px_cny = px * ((state.get("rates") or {}).get(q.get("currency") or "USD") or 0)
    add_shares = (invest_cny / bench_px_cny) if bench_px_cny > 0 else 0

    shares = prev_shares + add_shares
    principal_cny = prev_principal_cny + invest_cny
    weeks = prev_weeks + 1

    # 가상 포트폴리오 현재가치 (CNY)
    value_cny = shares * bench_px_cny

    # 현금 보유분의 현재가치: 원금 그대로(이자 무시, 보수적) — 필요시 SGOV로 대체 가능하나 단순화
    cash_value_cny = principal_cny

    diff_cny = value_cny - cash_value_cny    # +면 투자가 나았음(놓친 수익), -면 현금이 나았음(회피한 손실)

    # 이번 주 '기다린 게 옳았나': 지난주 대비 벤치마크가 내렸으면 현금이 옳았음(+1)
    right_delta = 0
    if isinstance(prev_bench_px, (int, float)) and prev_bench_px > 0:
        if px < prev_bench_px:
            right_delta = 1
    weeks_right = prev_right + right_delta

    # 신호 체크
    sig_hit = _check_signal(cfg.get("waitSignal"), market)
    prev_sig_seen = int(prev.get("signalSeenCount") or 0)
    sig_seen = prev_sig_seen + (1 if sig_hit else 0)

    disp_diff, dcur = _from_cny_to_display(diff_cny, state)

    view = {
        "bench": bench,
        "weeks": weeks,
        "diff_disp": disp_diff,
        "diff_cur": dcur,
        "missed": diff_cny > 0,          # True=놓친 수익 / False=회피한 손실
        "weeks_right": weeks_right,
        "signal_note": cfg.get("signalNote") or "",
        "signal_expr": cfg.get("waitSignal") or "",
        "signal_hit": sig_hit,           # True/False/None
        "signal_seen": sig_seen,
        "deadline": cfg.get("deadline") or "",
    }
    save_idle = {
        "shares": round(shares, 6),
        "principalCny": round(principal_cny, 2),
        "weeks": weeks,
        "weeksRight": weeks_right,
        "lastBenchPx": px,
        "signalSeenCount": sig_seen,
    }
    return view, save_idle
