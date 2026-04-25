import ccxt

exchange = ccxt.bitget({
    "timeout": 20000,
})

def get_price():
    try:
        exchange.load_markets()
        ticker = exchange.fetch_ticker("ETH/USDT:USDT")
        return ticker["last"]
    except Exception as e:
        print("PRICE ERROR:", e)
        return None