import os
import ccxt
import threading
import time
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

state = {
    "status": "OFFLINE - AWAITING KEYS",
    "price": 0.00,
    "rsi": 0.0,
    "ema_200": 0.0,
    "signal": "STANDBY",
    "is_paused": True,
    "active_position": None,
    "trade_history": [],
    "logs": ["v64.0 READY. Button fixed."],
}

SYMBOL = "ETH/USDT"
exchange = None 

def add_log(msg):
    state["logs"].insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")
    state["logs"] = state["logs"][:25] 

def execute_trade(side, amount_usd=10):
    global exchange
    if not exchange: return
    try:
        price = state["price"]
        amount_crypto = amount_usd / price
        if side == 'buy':
            exchange.create_market_buy_order(SYMBOL, amount_crypto, {"price": price})
            state["active_position"] = {"entry": price, "amount": amount_crypto, "time": time.strftime('%H:%M:%S'), "current_pnl": "0.00%"}
            add_log(f"MANUAL BUY: {SYMBOL} at ${price}")
        elif side == 'sell':
            exchange.create_market_sell_order(SYMBOL, state["active_position"]["amount"])
            state["active_position"] = None
            add_log(f"MANUAL EXIT: Closed at ${price}")
    except Exception as e:
        add_log(f"TRADE ERROR: {str(e)}")

def bot_loop():
    data_fetcher = ccxt.bitget()
    while True:
        try:
            bars = data_fetcher.fetch_ohlcv(SYMBOL, timeframe='1m', limit=210)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df['ema_200'] = df['c'].ewm(span=200, adjust=False).mean()
            delta = df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            df['rsi'] = 100 - (100 / (1 + (gain / loss)))
            last = df.iloc[-1]
            state["price"], state["rsi"], state["ema_200"] = round(last['c'], 2), round(last['rsi'], 1), round(last['ema_200'], 2)
            
            if not state["is_paused"]:
                if state["rsi"] < 35 and not state["active_position"]:
                    state["signal"] = "BUY SIGNAL"
                    execute_trade('buy')
                elif state["rsi"] > 70 and state["active_position"]:
                    state["signal"] = "EXIT SIGNAL"
                    execute_trade('sell')
                else: state["signal"] = "MONITORING"
        except: time.sleep(10)
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

@app.get("/api/status")
def get_status(): return state

@app.post("/start_engine")
async def start_engine(request: Request):
    global exchange
    try:
        data = await request.json()
        k = data.get("key")
        s = data.get("secret")
        
        if not k or not s:
            add_log("ERROR: Please enter both keys.")
            return

        exchange = ccxt.bitget({
            'apiKey': k, 'secret': s, 'enableRateLimit': True,
            'options': {'defaultType': 'future', 'createMarketBuyOrderRequiresPrice': False}
        })
        state["is_paused"] = False
        state["status"] = "LIVE - ENGINE RUNNING"
        add_log("SUCCESS: Engine is now LIVE.")
    except Exception as e:
        add_log(f"START FAILED: {str(e)}")

@app.post("/stop_engine")
def stop_engine():
    state["is_paused"] = True
    state["status"] = "OFFLINE - STOPPED"
    add_log("MANUAL STOP: Engine halted.")

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html><html><head><title>Alpha Manual v64</title>
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }
        .card { background: #181a20; padding: 20px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #2b3139; }
        input { width: 100%; padding: 12px; margin: 8px 0; background: #2b3139; border: 1px solid #474d57; color: white; border-radius: 4px; }
        .btn-green { background: #0ecb81; color: black; padding: 15px; width: 100%; border: none; font-weight: bold; cursor: pointer; border-radius: 4px; font-size: 16px; }
        .btn-red { background: #f6465d; color: white; padding: 10px; width: 100%; border: none; font-weight: bold; cursor: pointer; margin-top: 10px; border-radius: 4px; }
        .log-box { background: black; color: #848e9c; padding: 15px; height: 250px; overflow-y: auto; font-family: monospace; font-size: 12px; border: 1px solid #2b3139; }
        .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    </style></head>
    <body>
        <div style="max-width: 900px; margin: auto; display: flex; gap: 20px;">
            <div style="width: 350px;">
                <div class="card">
                    <h3 style="margin-top:0; color:#fcd535;">MANUAL CONTROL</h3>
                    <div id="st" style="margin-bottom:10px; font-weight:bold; color:#848e9c;">OFFLINE</div>
                    <input type="text" id="k" placeholder="Bitget API Key">
                    <input type="password" id="s" placeholder="Bitget Secret">
                    <button class="btn-green" onclick="handleStart()">START TRADING ENGINE</button>
                    <button class="btn-red" onclick="fetch('/stop_engine', {method:'POST'})">EMERGENCY STOP</button>
                </div>
                <div class="log-box" id="logs"></div>
            </div>
            <div style="flex: 1;">
                <div class="stat-grid">
                    <div class="card">PRICE<h2 id="pr" style="color:#fcd535;">$0.00</h2></div>
                    <div class="card">RSI (14)<h2 id="rsi">0.0</h2></div>
                </div>
                <div class="card" style="text-align:center; padding: 60px;">
                    <div id="sig" style="font-size: 45px; font-weight: bold;">STANDBY</div>
                    <div id="pos" style="margin-top:15px; color:#848e9c;">No Active Position</div>
                </div>
            </div>
        </div>
        <script>
            async function handleStart() {
                const payload = {
                    key: document.getElementById('k').value,
                    secret: document.getElementById('s').value
                };
                await fetch('/start_engine', { 
                    method: 'POST', 
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
            }
            async function refresh() {
                try {
                    const r = await fetch('/api/status'); const d = await r.json();
                    document.getElementById('pr').innerText = "$" + d.price;
                    document.getElementById('rsi').innerText = d.rsi;
                    document.getElementById('st').innerText = d.status;
                    document.getElementById('sig').innerText = d.signal;
                    document.getElementById('pos').innerText = d.active_position ? "LONG: " + d.active_position.current_pnl : "No Active Position";
                    document.getElementById('logs').innerHTML = d.logs.map(l => "<div>"+l+"</div>").join("");
                    if(d.rsi < 35) document.getElementById('sig').style.color = "#0ecb81";
                    else if(d.rsi > 70) document.getElementById('sig').style.color = "#f6465d";
                    else document.getElementById('sig').style.color = "white";
                } catch(e) {}
            }
            setInterval(refresh, 3000);
        </script>
    </body></html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
