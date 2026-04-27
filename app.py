import os
import ccxt
import threading
import time
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

# ================== CONFIG ==================
SYMBOL = "ETH/USDT:USDT"
RISK_PERCENT = 0.008
MAX_DAILY_LOSS_PCT = 0.06
STOP_LOSS_PCT = 0.08
TAKE_PROFIT_PCT = 0.16
LEVERAGE = 10
MIN_ORDER_USDT = 6.0
FORCED_BALANCE = 11.16
# ===========================================

state = {
    "status": "OFFLINE", 
    "price": 0.00, 
    "rsi": 0.0, 
    "ema_fast": 0.0,
    "ema_slow": 0.0,
    "signal": "INITIALIZING", 
    "trend": "WAITING", 
    "is_paused": True, 
    "active_position": None,
    "balance": FORCED_BALANCE,
    "mode": "FUTURES",
    "logs": ["Gate.io Connected"],
    "history": [] 
}

exchange = None
daily_pnl = 0.0
daily_reset_time = datetime.now()

def add_log(msg):
    timestamp = time.strftime('%H:%M:%S')
    state["logs"].insert(0, f"[{timestamp}] {msg}")
    state["logs"] = state["logs"][:100]

def get_usdt_balance():
    try:
        if exchange:
            bal = exchange.fetch_balance()
            usdt = bal.get('total', {}).get('USDT', 0)
            if float(usdt) > 0:
                state["balance"] = round(float(usdt), 2)
                return float(usdt)
    except:
        pass
    state["balance"] = FORCED_BALANCE
    return FORCED_BALANCE

def execute_trade(side):
    global exchange, daily_pnl
    if not exchange or state["is_paused"]: return

    try:
        price = state.get("price", 0)
        if price <= 0: return

        usdt_balance = get_usdt_balance()

        if usdt_balance < MIN_ORDER_USDT:
            add_log(f"❌ Balance too low: ${usdt_balance:.2f}")
            return

        risk_amount = usdt_balance * RISK_PERCENT
        cost = max(risk_amount * 12, MIN_ORDER_USDT + 3)
        cost = min(cost, usdt_balance * 0.30)

        exchange.set_leverage(LEVERAGE, SYMBOL, params={"marginMode": "cross"})
        amount = exchange.amount_to_precision(SYMBOL, cost / price)

        if side in ['buy', 'long'] and not state["active_position"]:
            order = exchange.create_order(SYMBOL, 'market', 'buy', amount)

            state["active_position"] = {
                "entry": price,
                "amount": float(amount),
                "side": "LONG",
                "sl_price": price * (1 - STOP_LOSS_PCT),
                "tp_price": price * (1 + TAKE_PROFIT_PCT)
            }
            add_log("✅ LONG OPENED")

        elif side in ['sell', 'short'] and not state["active_position"]:
            order = exchange.create_order(SYMBOL, 'market', 'sell', amount)

            state["active_position"] = {
                "entry": price,
                "amount": float(amount),
                "side": "SHORT",
                "sl_price": price * (1 + STOP_LOSS_PCT),
                "tp_price": price * (1 - TAKE_PROFIT_PCT)
            }
            add_log("✅ SHORT OPENED")

        elif side == 'close' and state["active_position"]:
            pos = state["active_position"]
            direction = 'sell' if pos["side"] == "LONG" else 'buy'
            exchange.create_order(SYMBOL, 'market', direction, pos["amount"])

            pnl = (price - pos["entry"]) * pos["amount"]
            if pos["side"] == "SHORT":
                pnl *= -1

            daily_pnl += pnl
            add_log(f"✅ CLOSED {pos['side']} | PnL: ${pnl:.2f}")
            state["active_position"] = None

    except Exception as e:
        add_log(f"ERROR: {str(e)}")

def check_sl_tp():
    if not state.get("active_position"): return
    pos = state["active_position"]
    price = state["price"]

    if pos["side"] == "LONG":
        if price <= pos["sl_price"] or price >= pos["tp_price"]:
            execute_trade('close')
    else:
        if price >= pos["sl_price"] or price <= pos["tp_price"]:
            execute_trade('close')

def bot_loop():
    global daily_pnl, daily_reset_time
    fetcher = ccxt.gateio({'enableRateLimit': True})

    while True:
        try:
            bars = fetcher.fetch_ohlcv(SYMBOL, timeframe='1m', limit=210)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])

            df['ema_fast'] = df['c'].ewm(span=50).mean()
            df['ema_slow'] = df['c'].ewm(span=200).mean()

            delta = df['c'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            df['rsi'] = 100 - (100 / (1 + gain / loss))

            last = df.iloc[-1]
            state["price"] = float(last['c'])
            state["rsi"] = float(last['rsi'])

            if not state["is_paused"]:
                check_sl_tp()

                if last['ema_fast'] > last['ema_slow'] and state["rsi"] < 45:
                    execute_trade('long')
                elif last['ema_fast'] < last['ema_slow'] and state["rsi"] > 55:
                    execute_trade('short')

        except Exception as e:
            add_log(str(e))

        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

@app.post("/api/start")
async def start_engine(request: Request):
    global exchange
    data = await request.json()
    try:
        exchange = ccxt.gateio({
            'apiKey': data.get("key"),
            'secret': data.get("secret"),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        exchange.check_required_credentials()
        state["is_paused"] = False
        state["status"] = "LIVE"
        add_log("🚀 Gate.io Connected")
    except Exception as e:
        add_log(str(e))

@app.post("/api/stop")
def stop_engine():
    state["is_paused"] = True
    state["status"] = "OFFLINE"

@app.get("/api/status")
def get_status():
    return state

@app.get("/", response_class=HTMLResponse)
def home():
    return "<h1>Bot is running on Gate.io 🚀</h1>"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
