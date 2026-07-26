import requests

# 你的专属 Cloudflare Worker 接口地址
CLOUDFLARE_URL = "https://zrp-quote.irisvcorp.workers.dev/"

def get_market_quote(symbol):
    """通过 Cloudflare Worker 获取单个标的最新数据"""
    try:
        url = f"{CLOUDFLARE_URL}?symbol={symbol}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # 【修复】使用截图中正确的字段名
            price = data.get("price")
            change = data.get("changePct")
            high52 = data.get("high52")
            
            # 如果没查到数据（返回 null），直接输出 NaN
            if price is None:
                return "NaN", "NaN", "NaN"
                
            # 计算 52W MDD ( (当前价 - 52周最高价) / 52周最高价 * 100 )
            try:
                mdd = ((float(price) - float(high52)) / float(high52)) * 100
                mdd_str = str(round(mdd, 2))
            except (TypeError, ValueError, ZeroDivisionError):
                mdd_str = "NaN"
                
            # 保留两位小数格式化
            try:
                price_str = str(round(float(price), 2))
                change_str = str(round(float(change), 2))
            except:
                price_str = str(price)
                change_str = str(change)
                
            return price_str, change_str, mdd_str
        else:
            return "NaN", "NaN", "NaN"
            
    except Exception as e:
        print(f"[{symbol}] 接口异常: {e}")
        return "NaN", "NaN", "NaN"

def get_index_data():
    """获取大盘指数数据"""
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
        
        if price == "NaN":
            result[symbol] = "NaN (NaN%) 52W(NaN%)"
        else:
            result[symbol] = f"{price} ({change}%) 52W({mdd}%)"
            
    return result
