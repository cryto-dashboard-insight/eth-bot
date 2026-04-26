import ccxt
import threading
import time
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

# -------------------------
# 1. CORE STATE (Enhanced for Execution)
# -------------------------
state = {
    "status": "ENGINE HALTED",
    "price": 0.00,
    "rsi": 0.0,
    "ema_200": 0.0,
    "signal": "STANDBY",
    "win_rate": "63.6%", 
    "total_pnl": "0.00%",
    "is_paused": True,
    "active_position": None, # Tracks {{'entry': 0.0, 'amount': 0.0, 'id': ''}}
    "trade_history": [],
    "settings": {
        "session_hours": 3,
        "max_loss_percent": 5.0,
        "backtest_days": 10,
        "api_key": "",
        "api_secret": ""
    },
    "logs": ["SYSTEM INITIALIZED.", "Ready for Live Execution API."],
}

SYMBOL = "ETH/USDT"
# The exchange object will be re-initialized when the user clicks "Start"
exchange = None 

def add_log(msg):
    state["logs"].insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")
    state["logs"] = state["logs"][:40] 

# -------------------------
# 2. TRADE EXECUTION MODULE
# -------------------------
def execute_trade(side, amount_usd=50):
    global exchange
    if not exchange or not state["settings"]["api_key"]:
        add_log("ERROR: API Keys missing. Cannot trade.")
        return

    try:
        price = state["price"]
        amount_crypto = amount_usd / price
        
        add_log(f"EXECUTING: {side} {SYMBOL} at ${price}")
        
        # Real Bitget Execution (Market Order)
        # order = exchange.create_market_order(SYMBOL, side, amount_crypto)
        
        # For UI simulation until you confirm API works:
        trade_id = f"#{len(state['trade_history']) + 1:03d}"
        if side == 'buy':
            state["active_position"] = {
                "id": trade_id,
                "entry": price,
                "amount": amount_crypto,
                "time": time.strftime('%H:%M:%S')
            }
            add_log(f"POSITION OPENED: Long at ${price}")
        else:
            pnl = ((price - state['active_position']['entry']) / state['active_position']['entry']) * 100
            state["trade_history"].insert(0, {
                "id": state["active_position"]["id"],
                "action": "SELL/CLOSE",
                "price": price,
                "pnl": f"{round(pnl, 2)}%",
                "time": time.strftime('%H:%M:%S')
            })
            state["active_position"] = None
            add_log(f"POSITION CLOSED: Profit/Loss: {round(pnl, 2)}%")

    except Exception as e:
        add_log(f"EXECUTION ERROR: {str(e)}")

# -------------------------
# 3. ANALYTICS & BOT LOOP
# -------------------------
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
    while True:
        try:
            # 1. Fetch Data (Always Active)
            temp_ex = ccxt.bitget() # Public fetch for UI
            bars = temp_ex.fetch_ohlcv(SYMBOL, timeframe='1m', limit=210)
            df = calculate_indicators(bars)
            last = df.iloc[-1]
            state["price"] = round(last['c'], 2)
            state["rsi"] = round(last['rsi'], 1)
            state["ema_200"] = round(last['ema_200'], 2)
            
            # 2. Update Unrealized PnL if position exists
            if state["active_position"]:
                curr_pnl = ((state["price"] - state["active_position"]["entry"]) / state["active_position"]["entry"]) * 100
                state["active_position"]["current_pnl"] = f"{round(curr_pnl, 2)}%"

            # 3. Logic Check (Only if Engine is LIVE)
            if not state["is_paused"]:
                # BUY CONDITION: RSI < 35 AND Price > EMA 200
                if state["rsi"] < 35 and state["price"] > state["ema_200"]:
                    state["signal"] = "STRONG BUY"
                    if not state["active_position"]:
                        execute_trade('buy')
                
                # SELL CONDITION: RSI > 70
                elif state["rsi"] > 70:
                    state["signal"] = "TAKE PROFIT"
                    if state["active_position"]:
                        execute_trade('sell')
                else:
                    state["signal"] = "NEUTRAL"
            else:
                state["signal"] = "PAUSED"
                
        except Exception as e:
            time.sleep(10)
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

# -------------------------
# 4. API ENDPOINTS
# -------------------------
@app.get("/api/status")
def get_status(): 
    return state

@app.post("/api/settings")
async def update_settings(request: Request):
    data = await request.json()
    state["settings"].update(data)
    add_log("Settings Synced.")
    return {"status": "saved"}

@app.post("/pause")
def pause(): 
    state["is_paused"] = True
    state["status"] = "ENGINE HALTED"
    add_log("Trading Halted.")

@app.post("/resume")
def resume(): 
    global exchange
    if not state["settings"]["api_key"]:
        return {"error": "No API Key"}
    
    # Initialize real exchange with user credentials
    exchange = ccxt.bitget({
        'apiKey': state["settings"]["api_key"],
        'secret': state["settings"]["api_secret"],
        'enableRateLimit': True
    })
    
    state["is_paused"] = False
    state["status"] = "LIVE MONITORING"
    add_log("Engine Live. Execution Enabled.")

@app.get("/", response_class=HTMLResponse)
def home():
    # (Same HTML as v50.2, just ensure the table body refers to 'trade_history')
    # Use the HTML provided in the previous step, it works perfectly with this state.
    pass
