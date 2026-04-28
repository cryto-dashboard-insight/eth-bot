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

BASE_URL = "https://api.gateio.ws/api/v4"
WS_URL = "wss://api.gateio.ws/ws/v4/"

# ====================== STATE ======================
state = {
    "price": 0.0,
    "position": None,      # "LONG" or None
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
        raise ValueError("API_KEY or API_SECRET environment variables are missing")

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
        pass  # Silent fail for noisy WS


def on_open(ws):
    print("✅ WebSocket connected")
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
            print("WS reconnecting...", e)
            time.sleep(5)


# ====================== BALANCES ======================
def get_balances():
    try:
        path = "/spot/accounts"
        headers = get_sign_headers("GET", path)
        r = requests.get(BASE_URL + path, headers=headers, timeout=10)

        if r.status_code != 200:
            state["last_error"] = f"Balance API: {r.status_code}"
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
        state["last_error"] = f"Balance error: {str(e)[:100]}"
        return 0.0, 0.0


# ====================== PLACE ORDER ======================
def place_order(side: str):
    try:
        path = "/spot/orders"
        usdt, eth = get_balances()

        if side.lower() == "buy":
            amount = usdt * TRADE_PERCENT
            if amount < 10:   # Gate.io minimum \~10 USDT
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
        print(f"→ {side} order placed | Status: {r.status_code} | Response: {r.text[:200]}")

        if r.status_code not in (200, 201):
            state["last_error"] = r.text[:150]
    except Exception as e:
        state["last_error"] = f"Order error: {str(e)[:100]}"


# ====================== BOT LOOP ======================
def run_bot():
    global state
    print("🚀 Trading Bot Started on Render...")

    while True:
        try:
            price = ws_price
            usdt, eth = get_balances()

            state["status"] = "running"
            state["price"] = price
            state["last_update"] = time.strftime("%H:%M:%S")

            if price > 0:
                # Simple demo logic (replace later with real strategy)
                if price % 2 > 1 and state["position"] != "LONG" and usdt > 12:
                    place_order("buy")
                    state["position"] = "LONG"

                elif price % 2 <= 1 and state["position"] == "LONG" and eth > 0.001:
                    place_order("sell")
                    state["position"] = None

            print(f"Price: {price:.2f} | USDT: {usdt:.2f} | ETH: {eth:.4f} | Pos: {state['position']}")

        except Exception as e:
            state["
