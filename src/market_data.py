import yfinance as yf
import requests

TICKERS = ["QQQM", "SCHD", "SPYM", "RKLB"]
INDICES = {
    "^GSPC": "标普500", "^IXIC": "纳斯达克", "^DJI": "道琼斯",
    "^KS11": "KOSPI", "^N225": "日经225", "000001.SS": "上证指数",
    "^VIX": "VIX恐慌指数"
}


def get_index_data():
    out = {}
    for sym, name in INDICES.items():
        try:
            t = yf.Ticker(sym)
            h = t.history(period="5d")
            if len(h) >= 2:
                last = h["Close"].iloc[-1]
                prev = h["Close"].iloc[-2]
                pct = (last - prev) / prev * 100
                out[name] = {"price": round(last, 2), "pct": round(pct, 2)}
        except Exception as e:
            out[name] = {"error": str(e)}
    return out


def get_ticker_details():
    """收盘价 + 涨跌幅 + 52周最高回撤率"""
    out = {}
    for sym in TICKERS:
        try:
            t = yf.Ticker(sym)
            h = t.history(period="1y")
            last = h["Close"].iloc[-1]
            prev = h["Close"].iloc[-2]
            pct = (last - prev) / prev * 100
            high_52w = h["High"].max()
            drawdown = (last - high_52w) / high_52w * 100
            out[sym] = {
                "close": round(last, 2),
                "pct": round(pct, 2),
                "high_52w": round(high_52w, 2),
                "drawdown_pct": round(drawdown, 2),
            }
        except Exception as e:
            out[sym] = {"error": str(e)}
    return out


def get_fear_greed():
    """CNN Fear & Greed 指数"""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        d = r.json()["fear_and_greed"]
        return {"score": round(d["score"], 1), "rating": d["rating"]}
    except Exception as e:
        return {"error": str(e)}


def get_put_call_ratio():
    """由 LLM 通过搜索检索最新 CBOE Put/Call ratio"""
    return {"note": "由 LLM 检索最新 CBOE Put/Call ratio"}
