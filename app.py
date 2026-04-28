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
TRADE_PERCENT = float(os.getenv("TRADE_PERCENT", 0.05))   # 5% of balance

# === TESTNET CONFIG ===
BASE_URL = "https://api-testnet.gateapi.io/api/v4"   # ← Testnet URL (as requested)
WS_URL = "wss://api.gateio.ws/ws/v4/"                # WebSocket usually stays the same

# ====================== STATE ======================
state = {
    "price": 0.0,
    "position": None,
    "usdt_balance": 0.0,
    "eth_balance": 0.0,
    "status": "starting",
    "last_error": "",
    "last_update": ""
}

ws_price = 0.0

# ====================== SIGNATURE ======================
def get_sign_headers(method: str, path: str, query_string: str = "", body: str = ""):
    if not API_KEY or not API_SECRET:
        raise ValueError("GATE_API_KEY or GATE_API_SECRET is missing in environment variables")

    timestamp = str(int(time.time() * 1000))
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
    except:
        pass


def on_open(ws):
    print("✅ WebSocket connected to Gate.io")
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
            print("WebSocket error, reconnecting...", e)
            time.sleep(5)


# ====================== BALANCES ======================
def get_balances():
    try:
        path = "/spot/accounts"
        headers = get_sign_headers("GET", path)
        r = requests.get(BASE_URL + path, headers=headers, timeout=10)

        if r.status_code != 200:
            state["last_error"] = f"Balance API Error: {r.status_code} - {r.text[:100]}"
            return 0.0, 0.0

        data = r.json()
        usdt = 0.0
        eth = 0.0

        for asset in data:
            curr = asset.get("currency")
            avail = float(asset.get("available", 0))
            if curr == "USDT":
                usdt = avail
            elif curr == "ETH":
                eth = avail

        state["usdt_balance"] = usdt
        state["eth_balance"] = eth
        return usdt, eth
    except Exception as e:
        state["last_error"] = f"Balance exception: {str(e)[:100]}"
        return 0.0, 0.0


# ====================== PLACE ORDER ======================
def place_order(side: str):
    try:
        path = "/spot/orders"
        usdt, eth = get_balances()

        if side.lower() == "buy":
            amount = usdt * TRADE_PERCENT
            if amount < 10:
                return
            amount_str = str(round(amount, 2))
        else:  # sell
            amount = eth
            if amount < 0.001:
                return
            amount_str = str(round(amount, 6))

        body_dict = {
            "currency_pair": SYMBOL,
            "type": "market",
            "account": "spot",
            "side": side.lower(),
            "amount": amount_str,
            "time_in_force": "ioc"
        }

        body_json = json.dumps(body_dict)
        headers = get_sign_headers("POST", path, body=body_json)
        headers["Content-Type"] = "application/json"

        r = requests.post(BASE_URL + path, headers=headers, data=body_json, timeout=10)
        
        print(f"→ {side.upper()} ORDER | Status: {r.status_code}")
        if r.status_code not in (200, 201):
            state["last_error"] = f"Order failed: {r.text[:150]}"
        else:
            state["last_error"] = ""  # clear previous error on success
    except Exception as e:
        state["last_error"] = f"Order exception: {str(e)[:100]}"


# ====================== BOT LOOP ======================
def run_bot():
    global state
    print("🚀 Testnet Trading Bot Started...")

    while True:
        try:
            price = ws_price
            usdt, eth = get_balances()

            state["status"] = "running"
            state["price"] = price
            state["last_update"] = time.strftime("%H:%M:%S")

            if price > 0:
                if price % 2 > 1 and state["position"] != "LONG" and usdt > 12:
                    print("🟢 Buying condition met")
                    place_order("buy")
                    state["position"] = "LONG"

                elif price % 2 <= 1 and state["position"] == "LONG" and eth > 0.001:
                    print("🔴 Selling condition met")
                    place_order("sell")
                    state["position"] = None

            print(f"Price: {price:.2f} | USDT: {usdt:.2f} | ETH: {eth:.4f} | Position: {state['position']}")

        except Exception as e:
            state["status"] = "error"
            state["last_error"] = str(e)[:120]
            print("Bot loop error:", e)

        time.sleep(10)


# ====================== ROUTES ======================
@app.route("/")
def home():
    return render_template("index.html", state=state)


@app.route("/api/state")
def get_state():
    return jsonify(state)


# ====================== START ======================
if __name__ == "__main__":
    Thread(target=start_ws, daemon=True).start()
    Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"✅ Flask app starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
