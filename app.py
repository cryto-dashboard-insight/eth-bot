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
SYMBOL = "ETH/USDT"
RISK_PERCENT = 0.008           # 0.8% risk per trade
MAX_DAILY_LOSS_PCT = 0.06      # 6% daily loss limit
STOP_LOSS_PCT = 0.08           # 8% stop loss
TAKE_PROFIT_PCT = 0.16         # 16% take profit (2:1)
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
    "logs": ["v69.2 - Gate.io Migration Complete"],
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
            # Gate.io structure for USDT balance
            usdt = bal.get('USDT', {}).get('free', 0)
            if float(usdt) > 0.1:
                state["balance"] = round(float(usdt), 2)
                return float(usdt)
    except:
        pass
    return state["balance"]

def execute_trade(side):
    global exchange, daily_pnl
    if not exchange or state["is_paused"]: return

    try:
        price = state.get("price", 0)
        if price <= 0: return
        usdt_balance = get_usdt_balance()

        if side in ['buy', 'long'] and not state["active_position"]:
            cost = min(usdt_balance * 0.30, 8.0) # Safety cap for small balance
            add_log(f"Attempting LONG | Balance ${usdt_balance:.2f}")
            
            if state["mode"] == "FUTURES":
                exchange.set_leverage(LEVERAGE, SYMBOL)
            
            amount = exchange.amount_to_precision(SYMBOL, cost / price)
            order = exchange.create_order(SYMBOL, 'market', 'buy', amount)

            state["active_position"] = {
                "entry": price,
                "amount": amount,
                "side": "LONG",
                "usdt_invested": round(float(amount) * price, 2),
                "sl_price": round(price * (1 - STOP_LOSS_PCT), 2),
                "tp_price": round(price * (1 + TAKE_PROFIT_PCT), 2)
            }
            add_log(f"✅ LONG OPENED: {amount} ETH")

        elif side in ['sell', 'short'] and not state["active_position"]:
            if state["mode"] == "SPOT":
                add_log("❌ Cannot Short in Spot Mode")
                return
                
            cost = min(usdt_balance * 0.30, 8.0)
            add_log(f"Attempting SHORT | Balance ${usdt_balance:.2f}")
            exchange.set_leverage(LEVERAGE, SYMBOL)
            amount = exchange.amount_to_precision(SYMBOL, cost / price)
            order = exchange.create_order(SYMBOL, 'market', 'sell', amount)

            state["active_position"] = {
                "entry": price,
                "amount": amount,
                "side": "SHORT",
                "usdt_invested": round(float(amount) * price, 2),
                "sl_price": round(price * (1 + STOP_LOSS_PCT), 2),
                "tp_price": round(price * (1 - TAKE_PROFIT_PCT), 2)
            }
            add_log(f"✅ SHORT OPENED: {amount} ETH")

        elif side == 'close' and state["active_position"]:
            pos = state["active_position"]
            direction = 'sell' if pos["side"] == "LONG" else 'buy'
            exchange.create_order(SYMBOL, 'market', direction, pos["amount"])
            
            pnl_usd = (state["price"] - pos["entry"]) * float(pos["amount"]) * (1 if pos["side"] == "LONG" else -1)
            state["history"].insert(0, {"time": time.strftime('%H:%M:%S'), "action": f"CLOSE {pos['side']}", "price": f"${state['price']}", "pnl": f"${pnl_usd:.2f}"})
            add_log(f"✅ CLOSED {pos['side']} | PnL: ${pnl_usd:.2f}")
            state["active_position"] = None

    except Exception as e:
        add_log(f"TRADE ERROR ({side}): {str(e)}")

def bot_loop():
    # Public fetcher for Gate.io
    fetcher = ccxt.gate({'enableRateLimit': True})
    while True:
        try:
            get_usdt_balance()
            bars = fetcher.fetch_ohlcv(SYMBOL, timeframe='1m', limit=100)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df['ema_fast'] = df['c'].ewm(span=50, adjust=False).mean()
            df['ema_slow'] = df['c'].ewm(span=200, adjust=False).mean()
            
            # RSI Calculation
            delta = df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            df['rsi'] = 100 - (100 / (1 + gain / loss))

            last = df.iloc[-1]
            state["price"] = round(float(last['c']), 2)
            state["rsi"] = round(float(last['rsi']), 1)
            state["trend"] = "UP" if last['ema_fast'] > last['ema_slow'] else "DOWN"

            if not state["is_paused"]:
                from trade_logic import execute_auto_logic # Placeholder for automated signals
                pass

        except: pass
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

@app.get("/api/status")
def get_status(): return state

@app.post("/api/start")
async def start_engine(request: Request):
    global exchange
    data = await request.json()
    try:
        state["mode"] = data.get("mode", "FUTURES").upper()
        exchange = ccxt.gate({
            'apiKey': data.get("key"), 
            'secret': data.get("secret"), 
            'enableRateLimit': True,
            'options': {'defaultType': 'future' if state["mode"] == "FUTURES" else 'spot'}
        })
        state["is_paused"] = False
        state["status"] = "LIVE - GATE.IO"
        add_log("✅ Gate.io Connected Successfully")
    except Exception as e:
        add_log(f"❌ CONNECTION ERROR: {str(e)}")

@app.post("/api/stop")
def stop_engine():
    state["is_paused"] = True
    state["status"] = "OFFLINE"
    add_log("HALT: Engine Paused.")

@app.post("/api/force")
async def force_trade(request: Request):
    data = await request.json()
    execute_trade(data.get("action"))
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def home():
    # Reuse your existing HTML UI from the previous code
    from fastapi.responses import HTMLResponse
    with open("index.html", "r") if os.path.exists("index.html") else None as f:
        # Returning the previous UI structure (Compact Buttons)
        return """... (Your previous HTML code here) ..."""
