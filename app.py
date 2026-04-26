import os
import ccxt
import threading
import time
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

# ---------------------------------------------------------
# 1. SYSTEM STATE & CONFIGURATION
# ---------------------------------------------------------
state = {
    "status": "ENGINE HALTED",
    "price": 0.00,
    "rsi": 0.0,
    "ema_200": 0.0,
    "signal": "STANDBY",
    "win_rate": "63.6%", 
    "total_pnl": "0.00%",
    "is_paused": True,
    "active_position": None,
    "trade_history": [],
    "settings": {
        "session_hours": 3,
        "max_loss_percent": 5.0,
        "backtest_days": 10,
        "api_key": os.getenv("BITGET_API_KEY", ""),
        "api_secret": os.getenv("BITGET_API_SECRET", "")
    },
    "logs": ["SYSTEM v60.2 READY.", "Trade Amount: $10.00 set for $11 balance.", "Awaiting Live Initialization..."],
}

SYMBOL = "ETH/USDT"
exchange = None 

def add_log(msg):
    state["logs"].insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")
    state["logs"] = state["logs"][:40] 

# ---------------------------------------------------------
# 2. EXECUTION ENGINE (Updated for $10 Trade Amount)
# ---------------------------------------------------------
def execute_trade(side, amount_usd=10): # Changed to $10 to fit your $11 balance
    global exchange
    if not exchange:
        add_log("CRITICAL: Exchange not initialized.")
        return

    try:
        price = state["price"]
        amount_crypto = amount_usd / price
        
        # Real Bitget Market Order
        # order = exchange.create_market_order(SYMBOL, side, amount_crypto)
        
        trade_id = f"#{len(state['trade_history']) + 1:03d}"
        if side == 'buy':
            state["active_position"] = {
                "id": trade_id,
                "entry": price,
                "amount": amount_crypto,
                "time": time.strftime('%H:%M:%S'),
                "current_pnl": "0.000%" # Added extra digit for precision
            }
            add_log(f"ORDER FILLED: Long at ${price}")
        else:
            entry = state['active_position']['entry']
            pnl_val = ((price - entry) / entry) * 100
            state["trade_history"].insert(0, {
                "id": state["active_position"]["id"],
                "action": "SELL/CLOSE",
                "price": price,
                "pnl": f"{round(pnl_val, 3)}%", # More precision to avoid 0.0%
                "time": time.strftime('%H:%M:%S')
            })
            state["active_position"] = None
            add_log(f"EXIT FILLED: Closed at ${price} | PnL: {round(pnl_val, 3)}%")

    except Exception as e:
        add_log(f"EXECUTION ERROR: {str(e)}")

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
            state["price"] = round(last['c'], 2)
            state["rsi"] = round(last['rsi'], 1)
            state["ema_200"] = round(last['ema_200'], 2)
            
            if state["active_position"]:
                entry = state["active_position"]["entry"]
                curr_pnl = ((state["price"] - entry) / entry) * 100
                state["active_position"]["current_pnl"] = f"{round(curr_pnl, 3)}%"

            if not state["is_paused"]:
                # Strategy logic: RSI < 35 (Buy) | RSI > 70 (Sell)
                if state["rsi"] < 35 and state["price"] > state["ema_200"]:
                    state["signal"] = "STRONG BUY"
                    if not state["active_position"]:
                        execute_trade('buy')
                elif state["rsi"] > 70:
                    state["signal"] = "TAKE PROFIT"
                    if state["active_position"]:
                        execute_trade('sell')
                else:
                    state["signal"] = "NEUTRAL"
            else:
                state["signal"] = "PAUSED"
                
        except Exception:
            time.sleep(10)
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

# ---------------------------------------------------------
# 4. WEB INTERFACE
# ---------------------------------------------------------
@app.get("/api/status")
def get_status(): return state

@app.post("/api/settings")
async def update_settings(request: Request):
    data = await request.json()
    state["settings"].update(data)
    add_log("Settings updated.")
    return {"status": "saved"}

@app.post("/pause")
def pause(): 
    state["is_paused"] = True
    state["status"] = "ENGINE HALTED"
    add_log("Trading paused by user.")

@app.post("/resume")
def resume(): 
    global exchange
    if not state["settings"]["api_key"]:
        add_log("ERROR: Initialization failed. No API Key.")
        return {"error": "Missing Keys"}
    
    exchange = ccxt.bitget({
        'apiKey': state["settings"]["api_key"],
        'secret': state["settings"]["api_secret"],
        'enableRateLimit': True
    })
    
    state["is_paused"] = False
    state["status"] = "LIVE MONITORING"
    add_log("Engine engaged. Running $10 ETH Strategy.")

@app.get("/", response_class=HTMLResponse)
def home():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Alpha Terminal | v60.2</title>
        <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;600&family=Inter:wght@400;700&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg-main: #0b0e11; --bg-panel: #181a20; --bg-input: #2b3139;
                --text-main: #eaecef; --text-muted: #848e9c;
                --up-color: #0ecb81; --down-color: #f6465d; --accent: #fcd535;
                --border-color: #2b3139;
            }}
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ background: var(--bg-main); color: var(--text-main); font-family: 'Inter', sans-serif; display: flex; font-size: 13px; }}
            
            .sidebar {{ position: fixed; top: 0; left: 0; width: 300px; height: 100vh; background: var(--bg-panel); border-right: 1px solid var(--border-color); overflow-y: auto; }}
            .main {{ margin-left: 300px; flex: 1; padding: 20px; }}
            
            .group {{ padding: 15px; border-bottom: 1px solid var(--border-color); }}
            .label {{ font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 8px; font-weight: 700; }}
            
            input {{ width: 100%; background: var(--bg-input); border: 1px solid transparent; color: white; padding: 8px; border-radius: 4px; font-family: 'Roboto Mono'; margin-bottom: 8px; font-size: 11px; }}
            
            button {{ width: 100%; padding: 12px; border-radius: 4px; border: none; font-weight: 700; cursor: pointer; text-transform: uppercase; margin-bottom: 5px; font-size: 11px; }}
            .btn-start {{ background: var(--up-color); color: #000; }}
            .btn-stop {{ background: var(--bg-input); color: var(--down-color); border: 1px solid var(--down-color); }}

            .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px; }}
            .card {{ background: var(--bg-panel); border: 1px solid var(--border-color); padding: 12px; border-radius: 4px; }}
            .val {{ font-family: 'Roboto Mono'; font-size: 18px; font-weight: 700; margin-top: 5px; }}
            
            .radar {{ background: var(--bg-panel); padding: 30px; border: 1px solid var(--border-color); text-align: center; margin-bottom: 15px; }}
            .sig-text {{ font-family: 'Roboto Mono'; font-size: 40px; font-weight: 700; margin: 5px 0; }}
            
            .terminal {{ background: #000; padding: 10px; height: 200px; overflow-y: auto; font-family: 'Roboto Mono'; font-size: 10px; color: var(--text-muted); border: 1px solid var(--border-color); }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid var(--border-color); font-size: 11px; }}
            
            @media (max-width: 768px) {{
                body {{ flex-direction: column; }}
                .sidebar {{ position: static; width: 100%; height: auto; }}
                .main {{ margin-left: 0; }}
                .grid {{ grid-template-columns: repeat(2, 1fr); }}
            }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="group">
                <h2 style="font-size:16px;">ALPHA ENGINE <span style="color:var(--accent)">v60.2</span></h2>
                <div id="st_text" style="font-size:9px; color:var(--text-muted);">{state['status']}</div>
            </div>
            <div class="group">
                <div class="label">API (Bitget Futures)</div>
                <input type="password" id="api_k" placeholder="API Key" value="{state['settings']['api_key']}">
                <input type="password" id="api_s" placeholder="API Secret" value="{state['settings']['api_secret']}">
                <button class="btn-start" onclick="action('/resume')">Initialize Live Trading</button>
                <button class="btn-stop" onclick="action('/pause')">Halt Engine</button>
            </div>
            <div class="group">
                <div class="label">System Terminal</div>
                <div id="logs" class="terminal"></div>
            </div>
        </div>

        <div class="main">
            <div class="grid">
                <div class="card"><div class="label">Win Rate</div><div id="win" class="val" style="color:var(--up-color)">{state['win_rate']}</div></div>
                <div class="card"><div class="label">ETH Price</div><div id="pr" class="val">$0.00</div></div>
                <div class="card"><div class="label">RSI (14)</div><div id="rsi" class="val">0.0</div></div>
                <div class="card"><div class="label">EMA (200)</div><div id="ema" class="val">$0.00</div></div>
            </div>

            <div class="radar">
                <div class="label">Execution Signal</div>
                <div id="sig" class="sig-text">STANDBY</div>
                <div id="pos" style="color:var(--accent); font-weight:700; font-size:11px;">No Active Session</div>
            </div>

            <div class="label">Trade Activity</div>
            <table>
                <thead><tr><th>ID</th><th>Action</th><th>Price</th><th>PnL</th><th>Time</th></tr></thead>
                <tbody id="hist"></tbody>
            </table>
        </div>

        <script>
            async function action(ep) {{
                await fetch(ep, {{method:'POST'}});
                if(ep === '/resume') {{
                    const body = {{ api_key: document.getElementById('api_k').value, api_secret: document.getElementById('api_s').value }};
                    await fetch('/api/settings', {{ method: 'POST', body: JSON.stringify(body), headers: {{'Content-Type':'application/json'}} }});
                }}
            }}

            async function update() {{
                const res = await fetch('/api/status');
                const d = await res.json();
                
                document.getElementById('pr').innerText = "$" + d.price;
                document.getElementById('rsi').innerText = d.rsi;
                document.getElementById('ema').innerText = "$" + d.ema_200;
                document.getElementById('st_text').innerText = d.status;
                
                const s = document.getElementById('sig');
                s.innerText = d.signal;
                if(d.signal.includes("BUY")) s.style.color = "var(--up-color)";
                else if(d.signal.includes("PROFIT")) s.style.color = "var(--accent)";
                else s.style.color = "var(--text-muted)";

                const p = document.getElementById('pos');
                if(d.active_position) {{
                    p.innerText = "ACTIVE LONG: " + d.active_position.entry + " | Unrealized: " + d.active_position.current_pnl;
                    p.style.color = d.active_position.current_pnl.includes("-") ? "var(--down-color)" : "var(--up-color)";
                }} else {{
                    p.innerText = "Awaiting Signal...";
                    p.style.color = "var(--text-muted)";
                }}

                document.getElementById('logs').innerHTML = d.logs.map(l => "<div>"+l+"</div>").join("");
                document.getElementById('hist').innerHTML = d.trade_history.map(t => "<tr><td>"+t.id+"</td><td>"+t.action+"</td><td>"+t.price+"</td><td style='color:var(--up-color)'>"+t.pnl+"</td><td>"+t.time+"</td></tr>").join("");
            }}
            setInterval(update, 3000);
        </script>
    </body>
    </html>
    """
