import requests

# 你的专属 Cloudflare Worker 接口地址
CLOUDFLARE_URL = "https://zrp-quote.irisvcorp.workers.dev/"

def get_market_quote(symbol):
    """通过 Cloudflare Worker 获取单个标的最新数据"""
    try:
        # 通过 ?symbol=xxx 拼接参数进行请求
        url = f"{CLOUDFLARE_URL}?symbol={symbol}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # 【重要】请核对你 Worker 返回的 JSON 格式
            # 如果你的 Worker 返回的字段名不是 price、changePercent、mdd52，请在这里修改
            price = data.get("price", "NaN")
            change = data.get("changePercent", "NaN")
            mdd = data.get("mdd52", "NaN") 
            
            return price, change, mdd
        else:
            print(f"[{symbol}] 请求失败，状态码: {response.status_code}")
            return "NaN", "NaN", "NaN"
            
    except Exception as e:
        print(f"[{symbol}] 接口异常: {e}")
        return "NaN", "NaN", "NaN"

def get_index_data():
    """获取大盘指数数据"""
    # 【注意】这里的代码（如 ^GSPC）需与你的 Worker 接口支持的格式一致
    # 如果你的接口直接识别 SPX，就把 "^GSPC" 改成 "SPX"
    indices = {
        "SPX": "^GSPC",
        "NDX": "^NDX",
        "DJI": "^DJI",
        "KOSPI": "^KS11",
        "VIX": "^VIX"
    }
    
    result = {}
    for name, symbol in indices.items():
        price, change, _ = get_market_quote(symbol)
        result[name] = f"{price} ({change}%)"
        
    return result

def get_ticker_details():
    """获取具体标的明细"""
    tickers = ["QQQM", "SCHD", "SPYM", "RKLB"]
    
    result = {}
    for symbol in tickers:
        price, change, mdd = get_market_quote(symbol)
        
        # 按照 prompt 要求的格式拼接，如: 284.98 (-1.87%) 52W(-7.43%)
        if str(price) == "NaN":
            result[symbol] = "NaN (NaN%) 52W(NaN%)"
        else:
            result[symbol] = f"{price} ({change}%) 52W({mdd}%)"
            
    return result
