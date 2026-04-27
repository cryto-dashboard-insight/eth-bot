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
    "logs": ["Gate.io Mode Enabled"],
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
            usdt = bal.get('total', {}).get('USDT') or bal.get('free', {}).get('USDT') or 0
            if float(usdt) > 0.5:
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
            exchange.create_order(SYMBOL, 'market', 'buy', amount)

            state["active_position"] = {
                "entry": price,
                "amount": float(amount),
                "time": time.strftime('%H:%M:%S'),
                "side": "LONG",
                "sl_price": round(price * (1 - STOP_LOSS_PCT), 2),
                "tp_price": round(price * (1 + TAKE_PROFIT_PCT), 2)
            }
            add_log("✅ LONG OPENED")

        elif side in ['sell', 'short'] and not state["active_position"]:
            exchange.create_order(SYMBOL, 'market', 'sell', amount)

            state["active_position"] = {
                "entry": price,
                "amount": float(amount),
                "time": time.strftime('%H:%M:%S'),
                "side": "SHORT",
                "sl_price": round(price * (1 + STOP_LOSS_PCT), 2),
                "tp_price": round(price * (1 - TAKE_PROFIT_PCT), 2)
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

            state["history"].insert(0, {
                "time": time.strftime('%H:%M:%S'),
                "action": f"CLOSE {pos['side']}",
                "price": f"${price:.2f}",
                "pnl": f"${pnl:.2f}"
            })

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
            state["price"] = round(float(last['c']), 2)
            state["rsi"] = round(float(last['rsi']), 1)

            if not state["is_paused"]:
                check_sl_tp()

                if last['ema_fast'] > last['ema_slow'] and state["rsi"] < 45:
                    state["signal"] = "LONG SIGNAL"
                    execute_trade('long')
                elif last['ema_fast'] < last['ema_slow'] and state["rsi"] > 55:
                    state["signal"] = "SHORT SIGNAL"
                    execute_trade('short')
                elif state["active_position"]:
                    state["signal"] = f"HOLDING {state['active_position'].get('side', '')}"
                else:
                    state["signal"] = "MONITORING"

        except Exception as e:
            add_log(str(e))

        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

@app.get("/api/status")
def get_status():
    if state["active_position"]:
        entry = state["active_position"]["entry"]
        multiplier = 1 if state["active_position"].get("side") == "LONG" else -1
        pnl_pct = ((state["price"] - entry) / entry) * 100 * multiplier
        state["active_position"]["current_pnl"] = f"{pnl_pct:.2f}%"
    return state

@app.post("/api/start")
async def start_engine(request: Request):
    global exchange
    data = await request.json()
    try:
        mode = data.get("mode", "FUTURES").upper()
        state["mode"] = mode

        exchange = ccxt.gateio({
            'apiKey': data.get("key"),
            'secret': data.get("secret"),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap' if mode == "FUTURES" else 'spot'}
        })

        exchange.check_required_credentials()
        get_usdt_balance()
        state["is_paused"] = False
        state["status"] = "LIVE - RUNNING"
        add_log(f"🚀 Gate.io Connected | Balance ${state['balance']:.2f}")

    except Exception as e:
        add_log(f"❌ STARTUP ERROR: {str(e)}")

@app.post("/api/stop")
def stop_engine():
    state["is_paused"] = True
    state["status"] = "OFFLINE"
    add_log("HALT: Trading paused.")

@app.post("/api/force")
async def force_trade(request: Request):
    data = await request.json()
    action = data.get("action", "long")
    execute_trade(action)
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def home():
    return """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Alpha v69.1</title>
    <style>
        :root { --bg: #0b0e11; --card: #1e2329; --border: #363c4e; --text: #eaecef; --green: #0ecb81; --red: #f6465d; --yellow: #fcd535; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; padding: 10px; }
        .container { display: grid; grid-template-columns: 1fr; gap: 15px; max-width: 1200px; margin: 0 auto; }
        @media(min-width: 900px) { .container { grid-template-columns: 380px 1fr; } }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-bottom: 15px; }
        input, select, button { width: 100%; padding: 12px; margin-bottom: 10px; background: #2b3139; border: 1px solid var(--border); color: white; border-radius: 6px; }
        button { font-weight: 800; cursor: pointer; border: none; }
        .btn-start { background: var(--green); color: #000; }
        .btn-stop { background: var(--red); color: #fff; }
        .grid-force-btns { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 10px; }
        .btn-force { background: #fcd535; color: #000; margin: 0; font-size: 11px; padding: 10px; }
        .btn-close { background: var(--red); color: white; margin: 0; font-size: 11px; padding: 10px; }
        .grid-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px; }
        .stat-box { background: #2b3139; padding: 12px; border-radius: 8px; text-align: center; }
        .stat-box h4 { margin: 0; color: #848e9c; font-size: 10px; text-transform: uppercase; }
        .stat-box h2 { margin: 6px 0 0 0; font-size: 16px; }
        .logs { background: #000; color: #0ecb81; padding: 15px; font-family: 'Courier New', monospace; font-size: 11px; height: 280px; overflow-y: auto; border-radius: 8px; }
    </style></head>
    <body>
        <div class="container">
            <div>
                <div class="card">
                    <div class="header"><span style="font-weight:bold; font-size:18px;">ALPHA v69.1</span></div>
                    <div style="display:flex; justify-content:space-between; margin-bottom: 15px; font-size: 13px;">
                        <span>System Status:</span><b id="status" style="color: var(--red);">OFFLINE</b>
                    </div>
                    <select id="mode_select">
                        <option value="FUTURES" selected>Futures</option>
                        <option value="SPOT">Spot</option>
                    </select>
                    <input type="text" id="k" placeholder="API Key">
                    <input type="password" id="s" placeholder="API Secret">
                    <button class="btn-start" onclick="startBot()">START</button>
                    <button class="btn-stop" onclick="stopBot()">STOP</button>
                    <div class="grid-force-btns">
                        <button class="btn-force" onclick="forceTrade('long')">LONG</button>
                        <button class="btn-force" onclick="forceTrade('short')">SHORT</button>
                        <button class="btn-close" onclick="forceTrade('close')">CLOSE</button>
                    </div>
                </div>
                <div class="card"><
