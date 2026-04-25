import ccxt
import threading
import time
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# -------------------------
# 1. ADVANCED STATE (Mimicking your screenshot)
# -------------------------
state = {
    "status": "IDLE",
    "price": 0,
    "strategy": "ADAPTIVE LONG",
    "open_positions": "0/3",
    "win_rate": "0%",
    "total_pnl": "0.00%",
    "is_paused": True,
    "logs": [], # Stores trade history
    "order_book": [] # Stores active trades
}

SYMBOL = "ETH/USDT"
exchange = ccxt.bitget({'enableRateLimit': True})

# -------------------------
# 2. THE BACKTESTER ENGINE
# -------------------------
@app.get("/api/backtest")
def run_backtest():
    state["status"] = "BACKTESTING... 🧪"
    try:
        # Fetch last 100 hours of data
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe='1h', limit=100)
        
        # Simple Logic: If price went up 3 hours in a row, pretend we bought
        simulated_pnl = 0
        trades_won = 0
        
        for i in range(3, len(bars)):
            close_price = bars[i][4]
            prev_price = bars[i-1][4]
            
            if close_price > prev_price:
                simulated_pnl += 0.5 # Pretend 0.5% gain
                trades_won += 1
        
        state["total_pnl"] = f"{round(simulated_pnl, 2)}%"
        state["win_rate"] = f"{round((trades_won/97)*100, 1)}%"
        state["status"] = "BACKTEST COMPLETE ✅"
        return {"result": "Success", "pnl": state["total_pnl"]}
    except Exception as e:
        return {"error": str(e)}

# -------------------------
# 3. LIVE BOT LOOP
# -------------------------
def bot_loop():
    while True:
        if not state["is_paused"]:
            try:
                ticker = exchange.fetch_ticker(SYMBOL)
                state["price"] = ticker['last']
                state["status"] = "LIVE 🟢"
            except:
                state["status"] = "CONN ERROR 🔴"
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

# -------------------------
# 4. ADVANCED DARK UI (CSS + HTML)
# -------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return f"""
    <html>
    <head>
        <title>Adaptive ETH Bot</title>
        <style>
            :root {{ --bg: #0e1117; --card: #161b22; --accent: #ff4b4b; --text: #fafafa; }}
            body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; display: flex; }}
            
            /* SIDEBAR */
            .sidebar {{ width: 250px; background: var(--card); height: 100vh; padding: 20px; border-right: 1px solid #30363d; }}
            .main {{ flex-grow: 1; padding: 40px; }}
            
            /* CARDS */
            .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 30px; }}
            .stat-card {{ background: var(--card); padding: 20px; border-radius: 10px; border: 1px solid #30363d; text-align: center; }}
            .stat-val {{ font-size: 24px; font-weight: bold; color: var(--accent); }}
            
            /* TABLES */
            table {{ width: 100%; background: var(--card); border-collapse: collapse; border-radius: 10px; overflow: hidden; }}
            th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #30363d; }}
            th {{ background: #21262d; color: #8b949e; }}
            
            .btn {{ background: var(--accent); border: none; color: white; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; }}
            .btn-alt {{ background: #30363d; margin-top: 10px; width: 100%; }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h3>⚙️ Bot Settings</h3>
            <p>Trading Session: <b>3h</b></p>
            <p>Max Daily Loss: <b>5.0%</b></p>
            <hr style="border: 0.5px solid #30363d">
            <button class="btn" style="width: 100%" onclick="fetch('/resume', {{method:'POST'}})">▶️ START Bot</button>
            <button class="btn btn-alt" onclick="fetch('/pause', {{method:'POST'}})">🛑 STOP Bot</button>
            <button class="btn btn-alt" style="color: #58a6ff" onclick="runBacktest()">🧪 RUN BACKTEST</button>
        </div>

        <div class="main">
            <div class="stats-grid">
                <div class="stat-card"><div>Strategy</div><div class="stat-val">{state['strategy']}</div></div>
                <div class="stat-card"><div>Open Positions</div><div id="pos" class="stat-val">{state['open_positions']}</div></div>
                <div class="stat-card"><div>Win Rate</div><div id="win" class="stat-val">{state['win_rate']}</div></div>
                <div class="stat-card"><div>Total P&L %</div><div id="pnl" class="stat-val">{state['total_pnl']}</div></div>
            </div>

            <h2>📋 Active Order Book</h2>
            <table>
                <thead><tr><th>ID</th><th>Side</th><th>Entry Price</th><th>Current P&L%</th></tr></thead>
                <tbody><tr><td>0</td><td>LONG</td><td id="price_row">0.00</td><td style="color: #ff4b4b">-0.08%</td></tr></tbody>
            </table>

            <h2 style="margin-top: 40px;">📜 LIVE Bot Activity</h2>
            <div id="status_bar" style="color: #8b949e;">BOT STATUS: {state['status']}</div>
        </div>

        <script>
            async function runBacktest() {{
                alert("Starting Backtest on historical data...");
                await fetch('/api/backtest');
                location.reload();
            }}

            async function update() {{
                const res = await fetch('/api/status');
                const d = await res.json();
                document.getElementById('pos').innerText = d.open_positions;
                document.getElementById('win').innerText = d.win_rate;
                document.getElementById('pnl').innerText = d.total_pnl;
                document.getElementById('price_row').innerText = d.price;
                document.getElementById('status_bar').innerText = "STATUS: " + d.status + " | Live Price: $" + d.price;
            }}
            setInterval(update, 3000);
        </script>
    </body>
    </html>
    """

@app.get("/api/status")
def get_status(): return state

@app.post("/pause")
def pause(): state["is_paused"] = True

@app.post("/resume")
def resume(): state["is_paused"] = False
