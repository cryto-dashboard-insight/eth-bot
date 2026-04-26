import os, ccxt, threading, time, pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

state = {
    "status": "OFFLINE", "price": 0.00, "rsi": 0.0, "ema_200": 0.0,
    "signal": "STANDBY", "is_paused": True, "active_position": None,
    "logs": ["v67.1 PRO DASHBOARD. Bitget Spot price fix applied."],
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
        price = state["price"]
        
        if side == 'buy':
            # Calculate how much ETH $10 can buy
            amount_crypto = amount_usd / price
            # Format to Bitget's required decimal places
            amt_str = exchange.amount_to_precision(SYMBOL, amount_crypto)
            
            # FIX: Passed 'price' explicitly into the market order
            exchange.create_order(SYMBOL, 'market', 'buy', amt_str, price)
            
            state["active_position"] = {"entry": price, "amount": amt_str, "time": time.strftime('%H:%M:%S')}
            state["history"].insert(0, {"time": time.strftime('%H:%M:%S'), "action": "BUY", "price": f"${price}", "pnl": "-"})
            add_log(f"BUY FILLED: {amt_str} {SYMBOL} at ${price}")
            
        elif side == 'sell':
            if state["active_position"]:
                amt_str = state["active_position"]["amount"]
                entry = state["active_position"]["entry"]
                
                # FIX: Passed 'price' explicitly into the market order
                exchange.create_order(SYMBOL, 'market', 'sell', amt_str, price)
                
                pnl_usd = (price - entry) * float(amt_str)
                pnl_pct = ((price - entry) / entry) * 100
                pnl_str = f"${pnl_usd:.2f} ({pnl_pct:.2f}%)"
                
                state["history"].insert(0, {"time": time.strftime('%H:%M:%S'), "action": "SELL", "price": f"${price}", "pnl": pnl_str})
                state["active_position"] = None
                add_log(f"SELL FILLED: Sold {amt_str} {SYMBOL}. PnL: {pnl_str}")
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
            
            if not state["is_paused"]:
                if state["rsi"] < 35 and not state["active_position"]:
                    state["signal"] = "BUY SIGNAL (EXEC)"
                    execute_trade('buy')
                elif state["rsi"] > 70 and state["active_position"]:
                    state["signal"] = "SELL SIGNAL (EXEC)"
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
        current = state["price"]
        pnl_pct = ((current - entry) / entry) * 100
        state["active_position"]["current_pnl"] = f"{pnl_pct:.2f}%"
    return state

@app.post("/api/start")
async def start_engine(request: Request):
    global exchange
    data = await request.json()
    k, s, p = data.get("key"), data.get("secret"), data.get("pass")
    try:
        exchange = ccxt.bitget({'apiKey': k, 'secret': s, 'password': p, 'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
        exchange.check_required_credentials()
        state["is_paused"] = False
        state["status"] = "LIVE - TRADING ACTIVE"
        add_log("SUCCESS: API Keys Validated. Engine started.")
    except Exception as e: add_log(f"KEY ERROR: {str(e)}")

@app.post("/api/stop")
def stop_engine():
    state["is_paused"] = True
    state["status"] = "OFFLINE"
    add_log("SYSTEM HALTED.")

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Alpha Pro Dashboard</title>
    <style>
        :root { --bg: #0b0e11; --card: #181a20; --border: #2b3139; --text: #eaecef; --green: #0ecb81; --red: #f6465d; --yellow: #fcd535; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 15px; }
        .container { display: grid; grid-template-columns: 1fr; gap: 15px; max-width: 1200px; margin: 0 auto; }
        @media(min-width: 800px) { .container { grid-template-columns: 350px 1fr; } }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
        .title { margin-top: 0; font-size: 16px; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 15px; color: #848e9c; }
        input { width: 100%; padding: 12px; margin-bottom: 12px; background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 4px; box-sizing: border-box; }
        button { width: 100%; padding: 14px; font-weight: bold; border: none; border-radius: 4px; cursor: pointer; margin-bottom: 10px; }
        .btn-start { background: var(--green); color: black; }
        .btn-stop { background: var(--red); color: white; }
        .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .metric { text-align: center; background: var(--bg); padding: 15px; border-radius: 4px; border: 1px solid var(--border); }
        .metric h4 { margin: 0; color: #848e9c; font-size: 12px; }
        .metric h2 { margin: 10px 0 0 0; font-size: 22px; }
        .signal-box { text-align: center; padding: 30px 10px; font-size: 30px; font-weight: bold; border-radius: 8px; background: #0b0e11; border: 1px solid var(--border); margin-bottom: 15px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
        th { color: #848e9c; font-weight: normal; }
        .logs { background: #000; color: var(--green); padding: 15px; font-family: monospace; font-size: 11px; height: 250px; overflow-y: auto; border-radius: 4px; border: 1px solid var(--border); }
        .pos-card { background: #2b3139; padding: 15px; border-radius: 4px; font-size: 14px; text-align: center;}
    </style></head>
    <body>
        <div class="container">
            <div>
                <div class="card" style="margin-bottom:15px;">
                    <h3 class="title">CONTROL PANEL</h3>
                    <div style="display:flex; justify-content:space-between; margin-bottom:15px;">
                        <span style="color:#848e9c">Status:</span><strong id="status" style="color:var(--yellow)">OFFLINE</strong>
                    </div>
                    <input type="text" id="k" placeholder="Bitget API Key">
                    <input type="password" id="s" placeholder="Bitget API Secret">
                    <input type="password" id="p" placeholder="Bitget Passphrase">
                    <button class="btn-start" onclick="action('/api/start')">START ENGINE</button>
                    <button class="btn-stop" onclick="action('/api/stop')">HALT TRADING</button>
                </div>
                <div class="card">
                    <h3 class="title">SYSTEM LOGS</h3>
                    <div class="logs" id="logs"></div>
                </div>
            </div>
            
            <div style="display:flex; flex-direction:column; gap:15px;">
                <div class="card grid-3">
                    <div class="metric"><h4>ETH/USDT</h4><h2 id="price" style="color:var(--yellow)">--</h2></div>
                    <div class="metric"><h4>RSI (14)</h4><h2 id="rsi">--</h2></div>
                    <div class="metric"><h4>EMA (200)</h4><h2 id="ema">--</h2></div>
                </div>
                
                <div class="card">
                    <h3 class="title">ALGORITHM SIGNAL</h3>
                    <div class="signal-box" id="signal">STANDBY</div>
                    <div id="active_pos"></div>
                </div>

                <div class="card">
                    <h3 class="title">TRADE HISTORY</h3>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead><tr><th>Time</th><th>Action</th><th>Price</th><th>PnL</th></tr></thead>
                            <tbody id="history"><tr><td colspan="4" style="text-align:center;color:#848e9c;">No trades yet</td></tr></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <script>
            async function action(endpoint) {
                const payload = { key: document.getElementById('k').value, secret: document.getElementById('s').value, pass: document.getElementById('p').value };
                await fetch(endpoint, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
            }
            
            async function update() {
                const res = await fetch('/api/status'); const d = await res.json();
                
                document.getElementById('status').innerText = d.status;
                document.getElementById('status').style.color = d.is_paused ? "#f6465d" : "#0ecb81";
                
                document.getElementById('price').innerText = "$" + d.price.toFixed(2);
                document.getElementById('rsi').innerText = d.rsi.toFixed(1);
                document.getElementById('ema').innerText = "$" + d.ema_200.toFixed(2);
                
                const sigEl = document.getElementById('signal');
                sigEl.innerText = d.signal;
                if(d.signal.includes("BUY")) sigEl.style.color = "var(--green)";
                else if(d.signal.includes("SELL")) sigEl.style.color = "var(--red)";
                else sigEl.style.color = "var(--text)";
                
                const posEl = document.getElementById('active_pos');
                if (d.active_position) {
                    posEl.innerHTML = `<div class="pos-card"><strong>ACTIVE POSITION:</strong> ${d.active_position.amount} ETH<br>Entry: $${d.active_position.entry} | PnL: <span style="color:var(--green)">${d.active_position.current_pnl}</span></div>`;
                } else { posEl.innerHTML = ""; }

                document.getElementById('logs').innerHTML = d.logs.map(l => `<div>${l}</div>`).join("");
                
                if(d.history.length > 0) {
                    document.getElementById('history').innerHTML = d.history.map(t => 
                        `<tr><td>${t.time}</td><td style="color:${t.action === 'BUY' ? 'var(--green)' : 'var(--red)'}">${t.action}</td>
                        <td>${t.price}</td><td>${t.pnl}</td></tr>`
                    ).join("");
                }
            }
            setInterval(update, 2000);
        </script>
    </body></html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
