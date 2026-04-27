import os, ccxt, threading, time, pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

state = {
    "status": "OFFLINE", "price": 0.00, "rsi": 0.0, "ema_200": 0.0,
    "signal": "INITIALIZING", "trend": "WAITING", "is_paused": True, "active_position": None,
    "logs": ["v68.1 - FINAL BITGET FIX APPLIED."],
    "history": [] 
}

SYMBOL = "ETH/USDT"
exchange = None 

def add_log(msg):
    state["logs"].insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")
    state["logs"] = state["logs"][:40] 

def execute_trade(side, amount_usd=10):
    global exchange
    if not exchange: return
    try:
        exchange.load_markets()
        price = state.get("price", 0)
        
        if side == 'buy':
            # FIX: Explicitly passing price as 'None' and using params to satisfy Bitget
            exchange.create_order(SYMBOL, 'market', 'buy', amount_usd, None)
            
            bought_amt = amount_usd / price
            state["active_position"] = {"entry": price, "amount": f"{bought_amt:.4f}", "time": time.strftime('%H:%M:%S')}
            state["history"].insert(0, {"time": time.strftime('%H:%M:%S'), "action": "BUY", "price": f"${price}", "pnl": "-"})
            add_log(f"SUCCESS: Market Buy for ${amount_usd} USDT executed.")
            
        elif side == 'sell' and state["active_position"]:
            amt_to_sell = state["active_position"]["amount"]
            entry_price = state["active_position"]["entry"]
            exchange.create_order(SYMBOL, 'market', 'sell', amt_to_sell)
            
            pnl_usd = (price - entry_price) * float(amt_to_sell)
            pnl_str = f"${pnl_usd:.2f} ({((price - entry_price) / entry_price) * 100:.2f}%)"
            state["history"].insert(0, {"time": time.strftime('%H:%M:%S'), "action": "SELL", "price": f"${price}", "pnl": pnl_str})
            state["active_position"] = None
            add_log(f"SUCCESS: Sold {amt_to_sell} ETH. PnL: {pnl_str}")
            
    except Exception as e:
        add_log(f"TRADE ERROR: {str(e)}")

def bot_loop():
    fetcher = ccxt.bitget()
    while True:
        try:
            bars = fetcher.fetch_ohlcv(SYMBOL, timeframe='1m', limit=210)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df['ema_200'] = df['c'].ewm(span=200, adjust=False).mean()
            delta = df['c'].diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            df['rsi'] = 100 - (100 / (1 + (gain / loss)))
            last = df.iloc[-1]
            
            state["price"], state["rsi"], state["ema_200"] = round(last['c'], 2), round(last['rsi'], 1), round(last['ema_200'], 2)
            state["trend"] = "BULLISH" if state["price"] > state["ema_200"] else "BEARISH"

            if not state["is_paused"]:
                if state["rsi"] < 30 and not state["active_position"]:
                    state["signal"] = "BUY SIGNAL"
                    execute_trade('buy')
                elif state["rsi"] > 70 and state["active_position"]:
                    state["signal"] = "SELL SIGNAL"
                    execute_trade('sell')
                else: 
                    state["signal"] = "HOLDING" if state["active_position"] else "MONITORING"
        except: pass
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

@app.get("/api/status")
def get_status(): 
    if state["active_position"]:
        entry = state["active_position"]["entry"]
        pnl_pct = ((state["price"] - entry) / entry) * 100
        state["active_position"]["current_pnl"] = f"{pnl_pct:.2f}%"
    return state

@app.post("/api/start")
async def start_engine(request: Request):
    global exchange
    data = await request.json()
    try:
        # THE CRITICAL BITGET FIX IS HERE: 'createMarketBuyOrderRequiresPrice': False
        exchange = ccxt.bitget({
            'apiKey': data.get("key"), 
            'secret': data.get("secret"), 
            'password': data.get("pass"), 
            'enableRateLimit': True,
            'options': {'createMarketBuyOrderRequiresPrice': False} 
        })
        exchange.check_required_credentials()
        state["is_paused"], state["status"] = False, "LIVE - ENGINE RUNNING"
        add_log("SUCCESS: Credentials accepted. Engine LIVE.")
    except Exception as e: add_log(f"KEY ERROR: {str(e)}")

@app.post("/api/stop")
def stop_engine():
    state["is_paused"], state["status"] = True, "OFFLINE"
    add_log("HALT: Trading paused.")

@app.get("/", response_class=HTMLResponse)
def home():
    # Dashboard HTML remains the same as previous version
    return """
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Alpha v68.1</title>
    <style>
        :root { --bg: #0b0e11; --card: #1e2329; --border: #363c4e; --text: #eaecef; --green: #0ecb81; --red: #f6465d; --yellow: #fcd535; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; padding: 10px; }
        .container { display: grid; grid-template-columns: 1fr; gap: 15px; max-width: 1200px; margin: 0 auto; }
        @media(min-width: 900px) { .container { grid-template-columns: 380px 1fr; } }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-bottom: 20px; }
        input { width: 100%; padding: 12px; margin-bottom: 10px; background: #2b3139; border: 1px solid var(--border); color: white; border-radius: 6px; }
        button { width: 100%; padding: 14px; font-weight: 800; border: none; border-radius: 6px; cursor: pointer; transition: 0.2s; margin-top: 10px;}
        .btn-start { background: var(--green); color: #000; }
        .btn-stop { background: var(--red); color: #fff; }
        .grid-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 15px; }
        .stat-box { background: #2b3139; padding: 15px; border-radius: 8px; text-align: center; }
        .stat-box h4 { margin: 0; color: #848e9c; font-size: 11px; text-transform: uppercase; }
        .stat-box h2 { margin: 8px 0 0 0; font-size: 18px; }
        .signal-area { background: #0b0e11; padding: 40px 10px; text-align: center; border-radius: 12px; border: 2px solid var(--border); }
        .signal-text { font-size: 38px; font-weight: 900; letter-spacing: 2px; }
        .logs { background: #000; color: #0ecb81; padding: 15px; font-family: 'Courier New', monospace; font-size: 11px; height: 300px; overflow-y: auto; border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 12px; }
    </style></head>
    <body>
        <div class="container">
            <div>
                <div class="card" style="margin-bottom:15px;">
                    <div class="header"><span style="font-weight:bold; font-size:18px;">ALPHA v68.1</span></div>
                    <div style="margin-bottom:20px; font-size:13px;"><div style="display:flex; justify-content:space-between;"><span>Status:</span><b id="status">OFFLINE</b></div></div>
                    <input type="text" id="k" placeholder="API Key"><input type="password" id="s" placeholder="API Secret"><input type="password" id="p" placeholder="Passphrase">
                    <button class="btn-start" onclick="action('/api/start')">INITIALIZE LIVE TRADING</button>
                    <button class="btn-stop" onclick="action('/api/stop')">EMERGENCY STOP</button>
                </div>
                <div class="card"><h3 style="margin:0 0 15px 0; color:#848e9c; font-size:14px;">SYSTEM TERMINAL</h3><div class="logs" id="logs"></div></div>
            </div>
            <div style="display:flex; flex-direction:column; gap:15px;">
                <div class="grid-stats">
                    <div class="stat-box"><h4>ETH Price</h4><h2 id="price" style="color:var(--yellow)">--</h2></div>
                    <div class="stat-box"><h4>RSI (14)</h4><h2 id="rsi">--</h2></div>
                    <div class="stat-box"><h4>Trend</h4><h2 id="trend">--</h2></div>
                </div>
                <div class="card"><div class="signal-area" id="sig_area"><div style="color:#848e9c; font-size:12px; margin-bottom:10px;">MARKET ANALYSIS</div><div class="signal-text" id="signal">STANDBY</div><div id="active_pos" style="margin-top:20px;"></div></div></div>
                <div class="card"><h3 style="margin:0 0 15px 0; color:#848e9c; font-size:14px;">TRADE HISTORY</h3><div style="max-height:200px; overflow-y:auto;"><table><thead><tr><th>Time</th><th>Action</th><th>Price</th><th>PnL</th></tr></thead><tbody id="history"></tbody></table></div></div>
            </div>
        </div>
        <script>
            async function action(path) {
                const body = JSON.stringify({key:document.getElementById('k').value, secret:document.getElementById('s').value, pass:document.getElementById('p').value});
                await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body});
            }
            async function update() {
                const r = await fetch('/api/status'); const d = await r.json();
                document.getElementById('status').innerText = d.status;
                document.getElementById('status').style.color = d.is_paused ? "var(--red)" : "var(--green)";
                document.getElementById('price').innerText = "$" + d.price;
                document.getElementById('rsi').innerText = d.rsi;
                document.getElementById('trend').innerText = d.trend;
                document.getElementById('trend').style.color = d.trend === "BULLISH" ? "var(--green)" : "var(--red)";
                const sig = document.getElementById('signal');
                sig.innerText = d.signal;
                if(d.signal.includes("BUY")) { sig.style.color = "var(--green)"; document.getElementById('sig_area').style.borderColor = "var(--green)"; }
                else if(d.signal.includes("SELL")) { sig.style.color = "var(--red)"; document.getElementById('sig_area').style.borderColor = "var(--red)"; }
                else { sig.style.color = "white"; document.getElementById('sig_area').style.borderColor = "var(--border)"; }
                const logs = document.getElementById('logs');
                logs.innerHTML = d.logs.map(l => `<div>${l}</div>`).join("");
                if(d.active_position) {
                    document.getElementById('active_pos').innerHTML = `<div style="background:#2b3139; padding:10px; border-radius:8px;">POSITION: ${d.active_position.amount} ETH | PnL: <b style="color:var(--green)">${d.active_position.current_pnl}</b></div>`;
                } else { document.getElementById('active_pos').innerHTML = ""; }
                if(d.history.length > 0) {
                    document.getElementById('history').innerHTML = d.history.map(t => `<tr><td>${t.time}</td><td style="color:${t.action==='BUY'?'var(--green)':'var(--red)'}">${t.action}</td><td>${t.price}</td><td>${t.pnl}</td></tr>`).join("");
                }
            }
            setInterval(update, 2000);
        </script>
    </body></html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
