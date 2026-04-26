import os
import ccxt
import threading
import time
import pandas as pd
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse

app = FastAPI()

state = {
    "status": "WAITING FOR KEYS",
    "price": 0.00,
    "rsi": 0.0,
    "ema_200": 0.0,
    "signal": "STANDBY",
    "is_paused": True,
    "active_position": None,
    "trade_history": [],
    "logs": ["v62.0 MANUAL INPUT MODE READY."],
    "api_key": "",
    "api_secret": ""
}

SYMBOL = "ETH/USDT"
exchange = None 

def add_log(msg):
    state["logs"].insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")
    state["logs"] = state["logs"][:30] 

def execute_trade(side, amount_usd=10):
    global exchange
    if not exchange: return
    try:
        price = state["price"]
        amount_crypto = amount_usd / price
        if side == 'buy':
            order = exchange.create_market_buy_order(SYMBOL, amount_crypto, {"price": price})
            state["active_position"] = {"entry": price, "amount": amount_crypto, "time": time.strftime('%H:%M:%S'), "current_pnl": "0.000%"}
            add_log(f"LIVE BUY: {SYMBOL} at ${price}")
        elif side == 'sell':
            order = exchange.create_market_sell_order(SYMBOL, state["active_position"]["amount"])
            pnl_val = ((price - state['active_position']['entry']) / state['active_position']['entry']) * 100
            state["trade_history"].insert(0, {"action": "CLOSE", "price": price, "pnl": f"{round(pnl_val, 3)}%", "time": time.strftime('%H:%M:%S')})
            state["active_position"] = None
            add_log(f"LIVE EXIT: Closed at ${price} | PnL: {round(pnl_val, 3)}%")
    except Exception as e: add_log(f"API ERROR: {str(e)}")

def bot_loop():
    global exchange
    data_fetcher = ccxt.bitget()
    while True:
        try:
            bars = data_fetcher.fetch_ohlcv(SYMBOL, timeframe='1m', limit=210)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df['ema_200'] = df['c'].ewm(span=200, adjust=False).mean()
            delta = df['c'].diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            df['rsi'] = 100 - (100 / (1 + (gain / loss)))
            last = df.iloc[-1]
            state["price"], state["rsi"], state["ema_200"] = round(last['c'], 2), round(last['rsi'], 1), round(last['ema_200'], 2)
            if state["active_position"]:
                state["active_position"]["current_pnl"] = f"{round(((state['price'] - state['active_position']['entry']) / state['active_position']['entry']) * 100, 3)}%"
            if not state["is_paused"]:
                if state["rsi"] < 35 and state["price"] > state["ema_200"] and not state["active_position"]: execute_trade('buy')
                elif state["rsi"] > 70 and state["active_position"]: execute_trade('sell')
        except: time.sleep(10)
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

@app.get("/api/status")
def get_status(): return state

@app.post("/resume")
async def resume(request: Request):
    global exchange
    form = await request.form()
    state["api_key"] = form.get("key")
    state["api_secret"] = form.get("secret")
    exchange = ccxt.bitget({
        'apiKey': state["api_key"], 'secret': state["api_secret"],
        'enableRateLimit': True, 'options': {'defaultType': 'future', 'createMarketBuyOrderRequiresPrice': False}
    })
    state["is_paused"] = False
    state["status"] = "LIVE TRADING ACTIVE"
    add_log("Keys Loaded. Real Money Engine Engaged.")

@app.get("/", response_class=HTMLResponse)
def home():
    return f"""
    <html>
    <head><style>
        body {{ background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }}
        .card {{ background: #181a20; padding: 20px; border-radius: 8px; margin-bottom: 10px; }}
        input {{ width: 100%; padding: 10px; margin: 5px 0; background: #2b3139; border: none; color: white; }}
        button {{ width: 100%; padding: 15px; background: #0ecb81; border: none; font-weight: bold; cursor: pointer; }}
        .terminal {{ background: black; color: #848e9c; padding: 10px; height: 200px; overflow-y: auto; font-size: 12px; }}
    </style></head>
    <body>
        <div style="display:flex; gap:20px;">
            <div style="width: 350px;">
                <div class="card">
                    <h3>Bitget Credentials</h3>
                    <input type="text" id="key" placeholder="API Key">
                    <input type="password" id="sec" placeholder="API Secret">
                    <button onclick="start()">START ENGINE</button>
                </div>
                <div class="terminal" id="logs"></div>
            </div>
            <div style="flex:1;">
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px;">
                    <div class="card">Price: <h2 id="pr">$0</h2></div>
                    <div class="card">RSI: <h2 id="rsi">0</h2></div>
                    <div class="card">EMA: <h2 id="ema">$0</h2></div>
                </div>
                <div class="card" style="text-align:center; padding:40px;">
                    <h1 id="sig">STANDBY</h1>
                    <div id="pos">No Active Position</div>
                </div>
            </div>
        </div>
        <script>
            async function start() {{
                let fd = new FormData();
                fd.append('key', document.getElementById('key').value);
                fd.append('secret', document.getElementById('sec').value);
                await fetch('/resume', {{method:'POST', body: fd}});
            }}
            async function update() {{
                const res = await fetch('/api/status'); const d = await res.json();
                document.getElementById('pr').innerText = "$" + d.price;
                document.getElementById('rsi').innerText = d.rsi;
                document.getElementById('ema').innerText = "$" + d.ema_200;
                document.getElementById('sig').innerText = d.rsi < 35 ? "BUY SIGNAL" : (d.rsi > 70 ? "EXIT SIGNAL" : "NEUTRAL");
                document.getElementById('pos').innerText = d.active_position ? "LONG: " + d.active_position.current_pnl : "No Position";
                document.getElementById('logs').innerHTML = d.logs.map(l => "<div>"+l+"</div>").join("");
            }}
            setInterval(update, 3000);
        </script>
    </body></html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
