import json
from market_data import (
    get_index_data, get_ticker_details
)
from gemini_client import generate_brief
from telegram_sender import send


def main():
    market = {
        "指数": get_index_data(),
        "标的明细": get_ticker_details(),
    market_json = json.dumps(market, ensure_ascii=False, indent=2)

    brief = generate_brief(market_json)
    header = "📊 <b>Good Morning Sir!</b>\n\n"
    send(header + brief)
    print("已推送。")


if __name__ == "__main__":
    main()
