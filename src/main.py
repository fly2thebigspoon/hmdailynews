import json
from market_data import (
    get_index_data, get_ticker_details,
    get_fear_greed, get_put_call_ratio
)
from gemini_client import generate_brief
from telegram_sender import send


def main():
    market = {
        "指数": get_index_data(),
        "标的明细": get_ticker_details(),
        "恐惧贪婪指数": get_fear_greed(),
        "PutCall比率": get_put_call_ratio(),
    }
    market_json = json.dumps(market, ensure_ascii=False, indent=2)

    brief = generate_brief(market_json)
    header = "📊 <b>Good Morning,Daily News</b>\n\n"
    send(header + brief)
    print("已推送。")


if __name__ == "__main__":
    main()
