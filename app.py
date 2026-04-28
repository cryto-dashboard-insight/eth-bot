import os
import time
import hmac
import hashlib
import requests
import json
import websocket
from statistics import mean
from flask import Flask, jsonify
from threading import Thread

app = Flask(__name__)

API_KEY = os.getenv("GATE_API_KEY")
API_SECRET = os.getenv("GATE_API_SECRET")

BASE_URL = "https://api.gateio.ws/api/v4"
WS_URL = "wss://api.gateio.ws/ws/v4/"

SYMBOL = "ETH_USDT"
INTERVAL = 10

TRADE_PERCENT = float(os.getenv("TRADE_PERCENT", 0.1))

# ======================
# GLOBAL STATE (DASHBOARD)
# ======================
state = {
    "price": 0,
    "position": None,
    "balance": 0,
    "profit": 0,
    "status": "starting"
}

ws_price = 0

# ======================
# SIGNATURE
# ======================
def sign(method, url, query_string="", body=""):
    t = str(int(time.time()))
    payload = f"{method}\n{url}\n{query_string}\n{body}\n{t}"
    sign = hmac.new(API_SECRET.encode(), payload.encode(), hashlib.sha512).hexdigest()
    return {
        "KEY": API_KEY,
        "Timestamp": t,
        "SIGN": sign
    }

# ======================
# WEBSOCKET (LIVE PRICE)
# ======================
def on_message(ws, message):
    global ws_price, state
    data = json.loads(message)

    if "result" in data and data["result"]:
        ticker = data["result"]
        ws_price = float(ticker["last"])
        state["price"] = ws_price

def on_open(ws):
    msg = {
        "time": int(time.time()),
        "channel": "spot.tickers",
        "event": "subscribe",
        "payload": [SYMBOL]
    }
    ws.send(json.dumps(msg))

def start_ws():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message
    )
    ws.run_forever()

# ======================
# GET BALANCE
# ======================
def get_balance():
    url = "/spot/accounts"
    headers = sign("GET", url)
    r = requests.get(BASE_URL + url, headers=headers)
    data = r.json()

    for asset in data:
        if asset["currency"] == "USDT":
            return float(asset["available"])
    return 0

# ======================
# SIMPLE STRATEGY
# ======================
def strategy(price):
    if price == 0:
        return "HOLD"

    # Very simple logic (safe starter)
    if price % 2 > 1:
        return "BUY"
    else:
        return "SELL"

# ======================
# PLACE ORDER
# ======================
def place_order(side, amount):
    url = "/spot/orders"

    body = {
        "currency_pair": SYMBOL,
        "type": "market",
        "account": "spot",
        "side": side.lower(),
        "amount": str(amount)
    }

    body_json = json.dumps(body)
    headers = sign("POST", url, "", body_json)
    headers["Content-Type"] = "application/json"

    r = requests.post(BASE_URL + url, headers=headers, data=body_json)
    return r.json()

# ======================
# BOT LOOP
# ======================
def run_bot():
    global state

    print("🚀 Bot running...")

    while True:
        try:
            price = ws_price
            balance = get_balance()

            state["balance"] = balance
            state["status"] = "running"

            signal = strategy(price)
            print(f"Price: {price} | Signal: {signal}")

            if signal == "BUY" and state["position"] != "LONG":
                amount = balance * TRADE_PERCENT
                place_order("buy", amount)
                state["position"] = "LONG"

            elif signal == "SELL" and state["position"] == "LONG":
                place_order("sell", balance)
                state["position"] = None

        except Exception as e:
            print("Error:", e)
            state["status"] = "error"

        time.sleep(INTERVAL)

# ======================
# API FOR DASHBOARD
# ======================
@app.route("/api/state")
def get_state():
    return jsonify(state)

# ======================
# START EVERYTHING
# ======================
if __name__ == "__main__":
    Thread(target=start_ws).start()   # WebSocket
    Thread(target=run_bot).start()    # Trading bot

    app.run(host="0.0.0.0", port=10000)
