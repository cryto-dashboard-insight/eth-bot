import os
import ccxt
import threading
import time
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

# ---------------------------------------------------------
# 1. SYSTEM STATE
# ---------------------------------------------------------
state = {
    "status": "ENGINE HALTED",
    "price": 0.00,
    "rsi": 0.0,
    "ema_200": 0.0,
    "signal": "STANDBY",
    "is_paused": True,
    "active_position": None,
    "trade_history": [],
    "logs": ["v61.2 LIVE ENGINE READY.", "Ready for $10 trades on $11 balance."],
}

SYMBOL = "ETH/USDT"
exchange = None 

def add_log(msg):
    state["logs"].insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")
    state["logs"] = state["logs"][:30] 

# ---------------------------------------------------------
# 2. FIXED LIVE EXECUTION ENGINE
# ---------------------------------------------------------
def execute_trade(side, amount_usd=10):
    global exchange
    if not exchange:
        add_log("CRITICAL: Exchange not initialized.")
        return

    try:
        price = state["price"]
        amount_crypto = amount_usd / price
        
        if side == 'buy':
            # Fix for Bitget price argument error
            order = exchange.create_market_buy_order(SYMBOL, amount_crypto, {"price": price})
            trade_id = f"#{len(state['trade_history']) + 1:03d}"
            state["active_position"] = {
                "id": trade_id, "entry": price, "amount": amount_crypto,
                "time": time.strftime('%H:%M:%S'), "current_pnl": "0.000%"
            }
            add_log(f"LIVE BUY FILLED: {SYMBOL} at ${price}")
        
        elif side == 'sell':
            order = exchange.create_market_sell_order(SYMBOL, state["active_position"]["amount"])
            entry = state['active_position']['entry']
            pnl_val = ((price - entry) / entry) * 100
            state["trade_history"].insert(0, {
                "id": state["active_position"]["id"], "action": "CLOSE",
                "price": price, "pnl": f"{round(pnl_val, 3)}%", "time": time.strftime('%H:%M:%S')
            })
            state["active_position"] = None
            add_log(f"LIVE EXIT FILLED: Closed at ${price} | PnL: {round(pnl_val, 3)}%")

    except Exception as e:
        add_log(f"API ERROR: {str(e)}")

# ---------------------------------------------------------
# 3. ANALYTICS & BOT LOOP
# ---------------------------------------------------------
def calculate_indicators(bars):
    df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    df['ema_200'] = df['c'].ewm(span=200, adjust=False).mean()
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def bot_loop():
    global exchange
    data_fetcher = ccxt.bitget()
    while True:
        try:
            bars = data_fetcher.fetch_ohlcv(SYMBOL, timeframe='1m', limit=210)
            df = calculate_indicators(bars)
            last = df.iloc[-1]
            state["price"], state["rsi"], state["ema_200"] = round(last['c'], 2), round(last['rsi'], 1), round(last['ema_200'], 2)
            
            if state["active_position"]:
                curr_pnl = ((state["price"] - state["active_position"]["entry"]) / state["active_position"]["entry"]) * 100
                state["active_position"]["current_pnl"] = f"{round(curr_pnl, 3)}%"

            if not state["is_paused"]:
                if state["rsi"] < 35 and state["price"] > state["ema_200"]:
                    state["signal"] = "BUY SIGNAL"
                    if not state["active_position"]: execute_trade('buy')
                elif state["rsi"] > 70:
                    state["signal"] = "EXIT SIGNAL"
                    if state["active_position"]: execute_trade('sell')
                else: state["signal"] = "NEUTRAL"
            else: state["signal"] = "PAUSED"
        except: time.sleep(10)
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

# ---------------------------------------------------------
# 4. API & WEB UI
# ---------------------------------------------------------
@app.get("/api/status")
def get_status(): return state

@app.post("/pause")
def pause(): 
    state["is_paused"] = True
    state["status"] = "ENGINE STOPPED"
    add_log("Trading halted.")

@app.post("/resume")
def resume(): 
    global exchange
    exchange = ccxt.bitget({
        'apiKey': os.getenv("BITGET_API_KEY", ""),
        'secret': os.getenv("BITGET_API_SECRET", ""),
        'enableRateLimit': True,
        'options': {'defaultType': 'future', 'createMarketBuyOrderRequiresPrice': False} 
    })
    state["is_paused"] = False
    state["status"] = "LIVE TRADING ACTIVE"
    add_log("REAL MONEY ENGINE ENGAGED.")

@app.get("/", response_class=HTMLResponse)
def home():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Alpha Live | v61.2</title>
        <style>
            body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; display: flex; padding: 20px; }}
            .sidebar {{ width: 300px; background: #181a20; padding: 20px; border-radius: 8px; }}
            .main {{ flex: 1; margin-left: 20px; }}
            .card {{ background: #181a20; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 20px; }}
            .btn-start {{ background: #0ecb81; color: black; padding: 15px; width: 100%; border: none; font-weight: bold; cursor: pointer; }}
            .btn-stop {{ background: #f6465d; color: white; padding: 15px; width: 100%; border: none; font-weight: bold; cursor: pointer; margin-top: 10px; }}
            .terminal {{ background: black; color: #848e9c; padding: 15px; height: 300px; overflow-y: auto; font-family: monospace; font-size: 11px; }}
            .val {{ font-size: 24px; font-weight: bold; color: #fcd535; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #2b3139; }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>LIVE TRADING</h2>
            <div id="st" style="color:#848e9c; margin-bottom:20px;">{state['status']}</div>
            <button class="btn-start" onclick="fetch('/resume', {{method:'POST'}})">START REAL MONEY ENGINE</button>
            <button class="btn-stop" onclick="fetch('/pause', {{method:'POST'}})">HALT ALL TRADING</button>
            <h3 style="margin-top:30px;">Activity Log</h3>
            <div id="logs" class="terminal"></div>
        </div>
        <div class="main">
            <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px;">
                <div class="card"><div>Price</div><div id="pr" class="val">$0.00</div></div>
                <div class="card"><div>RSI</div><div id="rsi" class="val">0.0</div></div>
                <div class="card"><div>EMA 200</div><div id="ema" class="val">$0.00</div></div>
            </div>
            <div class="card" style="padding: 50px;">
                <div style="font-size: 14px; color:#848e9c;">SIGNAL</div>
                <div id="sig" style="font-size: 48px; font-weight: bold;">STANDBY</div>
                <div id="pos" style="margin-top: 10px; color: #fcd535;">No Position</div>
            </div>
            <table>
                <thead><tr><th>ID</th><th>Action</th><th>Price</th><th>PnL</th><th>Time</th></tr></thead>
                <tbody id="hist"></tbody>
            </table>
        </div>
        <script>
            async function update() {{
                try {{
                    const res = await fetch('/api/status');
                    const d = await res.json();
                    document.getElementById('pr').innerText = "$" + d.price;
                    document.getElementById('rsi').innerText = d.rsi;
                    document.getElementById('ema').innerText = "$" + d.ema_200;
                    document.getElementById('sig').innerText = d.signal;
                    document.getElementById('st').innerText = d.status;
                    document.getElementById('pos').innerText = d.active_position ? "LONG AT: " + d.active_position.entry + " | " + d.active_position.current_pnl : "No Active Position";
                    document.getElementById('logs').innerHTML = d.logs.map(l => "<div>"+l+"</div>").join("");
                    document.getElementById('hist').innerHTML = d.trade_history.map(t => "<tr><td>"+t.id+"</td><td>"+t.action+"</td><td>"+t.price+"</td><td>"+t.pnl+"</td><td>"+t.time+"</td></tr>").join("");
                }} catch (e) {{ console.log("Update failed"); }}
            }}
            setInterval(update, 3000);
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
