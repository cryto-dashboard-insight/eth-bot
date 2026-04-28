import os
import time
import hmac
import hashlib
import json
import requests
import websocket
from flask import Flask, jsonify, render_template
from threading import Thread

app = Flask(__name__)

# ====================== CONFIG ======================
API_KEY = os.getenv("GATE_API_KEY")
API_SECRET = os.getenv("GATE_API_SECRET")
SYMBOL = "ETH_USDT"
TRADE_PERCENT = float(os.getenv("TRADE_PERCENT", 0.05))   # Default 5% - safer than 10%

BASE_URL = "https://api.gateio.ws/api/v4"
WS_URL = "wss://api.gateio.ws/ws/v4/"

# ====================== STATE ======================
state = {
    "price": 0.0,
    "position": None,      # "LONG" or None
    "usdt_balance": 0.0,
    "eth_balance": 0.0,
    "status": "starting",
    "last_error": ""
}

ws_price = 0.0

# ====================== SIGNATURE (Fixed for Gate.io v4) ======================
def get_sign_headers(method: str, path: str, query_string: str = "", body: str = ""):
    if not API_KEY or not API_SECRET:
        raise ValueError("API_KEY or API_SECRET not set in environment variables")

    timestamp = str(int(time.time() * 1000))  # milliseconds
    payload = f"{method}\n{path}\n{query_string}\n{body}\n{timestamp}"

    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha512
    ).hexdigest()

    return {
        "KEY": API_KEY,
        "Timestamp": timestamp,
        "SIGN": signature,
        "Accept": "application/json",
        "Content-Type": "application/json" if body else ""
    }


# ====================== WEBSOCKET ======================
def on_message(ws, message):
    global ws_price, state
    try:
        data = json.loads(message)
        if data.get("channel") == "spot.tickers" and data.get("event") == "update":
            ticker = data.get("result", {})
            if ticker and "last" in ticker:
                ws_price = float(ticker["last"])
                state["price"] = ws_price
    except Exception as e:
        print("WebSocket parse error:", e)


def on_open(ws):
    print("WebSocket connected")
    msg = {
        "time": int(time.time()),
        "channel": "spot.tickers",
        "event": "subscribe",
        "payload": [SYMBOL]
    }
    ws.send(json.dumps(msg))


def start_ws():
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message
            )
            ws.run_forever(ping_interval=20)
        except Exception as e:
            print("WebSocket error, reconnecting in 5s...", e)
            time.sleep(5)


# ====================== BALANCE ======================
def get_balances():
    try:
        path = "/spot/accounts"
        headers = get_sign_headers("GET", path)
        r = requests.get(BASE_URL + path, headers=headers, timeout=10)
        
        if r.status_code != 200:
            print("Balance API error:", r.text)
            return 0.0, 0.0

        data = r.json()
        usdt = 0.0
        eth = 0.0

        for asset in data:
            currency = asset.get("currency")
            available = float(asset.get("available", 0))
            if currency == "USDT":
                usdt = available
            elif currency == SYMBOL.split("_")[0]:   # ETH
                eth = available

        state["usdt_balance"] = usdt
        state["eth_balance"] = eth
        return usdt, eth
    except Exception as e:
        print("Get balance error:", e)
        state["last_error"] = str(e)
        return 0.0, 0.0


# ====================== PLACE ORDER ======================
def place_order(side: str, amount: float):
    try:
        path = "/spot/orders"
        body_dict = {
            "currency_pair": SYMBOL,
            "type": "market",
            "account": "spot",
            "side": side.lower(),
            "amount": str(amount),
            "time_in_force": "ioc"
        }

        body_json = json.dumps(body_dict)
        headers = get_sign_headers("POST", path, body=body_json)
        headers["Content-Type"] = "application/json"

        r = requests.post(BASE_URL + path, headers=headers, data=body_json, timeout=10)
        
        print(f"Order {side} response: {r.status_code} - {r.text}")
        
        if r.status_code not in (200, 201):
            state["last_error"] = r.text
        return r.json()
    except Exception as e:
        print("Place order error:", e)
        state["last_error"] = str(e)


# ====================== BOT LOGIC ======================
def run_bot():
    global state
    print("🚀 Trading Bot Started...")

    while True:
        try:
            price = ws_price
            usdt, eth = get_balances()

            state["status"] = "running"
            state["price"] = price

            if price > 0:
                # Very simple demo logic - replace with your real strategy
                if price % 2 > 1 and state["position"] != "LONG" and usdt > 10:
                    # Buy: amount in ETH
                    buy_amount = (usdt * TRADE_PERCENT) / price
                    if buy_amount > 0.001:   # minimum size check
                        place_order("buy", buy_amount)
                        state["position"] = "LONG"

                elif price % 2 <= 1 and state["position"] == "LONG" and eth > 0.001:
                    place_order("sell", eth)
                    state["position"] = None

            print(f"Price: {price:.2f} | USDT: {usdt:.2f} | ETH: {eth:.4f} | Position: {state['position']}")

        except Exception as e:
            print("Bot loop error:", e)
            state["status"] = "error"
            state["last_error"] = str(e)

        time.sleep(10)


# ====================== ROUTES ======================
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/state")
def get_state():
    return jsonify(state)


# ====================== START ======================
if __name__ == "__main__":
    # Start background threads
    Thread(target=start_ws, daemon=True).start()
    Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
