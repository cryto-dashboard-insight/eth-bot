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
    "logs": ["v61.1 LIVE ENGINE READY.", "Ready for $10 trades on $11 balance."],
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
            # Fix: Pass 'price' to satisfy Bitget API requirements
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
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
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
        except: time.sleep(10)
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

# ---------------------------------------------------------
# 4. API & WEB UI (Fixed for Render Port)
# ---------------------------------------------------------
@app.get("/api/status")
def get_status(): return state

@app.post("/pause")
def pause(): 
    state["is_paused"] = True
    add_log("Engine stopped.")

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
    add_log("REAL MONEY ENGINE ENGAGED.")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<html>... (Use the same HTML from v61.0) ...</html>"""

# CRITICAL: Added for Render Port Binding
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
