import os
import ccxt
import threading
import time
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

SYMBOL = "ETH/USDT"
RISK_PERCENT = 0.008
MAX_DAILY_LOSS_PCT = 0.06
STOP_LOSS_PCT = 0.08
TAKE_PROFIT_PCT = 0.16
LEVERAGE = 10
MIN_ORDER_USDT = 6.0
FORCED_BALANCE = 11.16   # <--- Your actual balance - change if you add more

state = {
    "status": "OFFLINE", 
    "price": 0.00, 
    "rsi": 0.0, 
    "ema_200": 0.0,
    "signal": "INITIALIZING", 
    "trend": "WAITING", 
    "is_paused": True, 
    "active_position": None,
    "balance": FORCED_BALANCE,
    "mode": "FUTURES",
    "logs": ["v68.9 - Forced Balance Fallback + Clean Version"],
    "history": [] 
}

exchange = None
daily_pnl = 0.0
daily_reset_time = datetime.now()

def add_log(msg):
    timestamp = time.strftime('%H:%M:%S')
    state["logs"].insert(0, f"[{timestamp}] {msg}")
    state["logs"] = state["logs"][:80]

def get_usdt_balance():
    # Try normal detection first
    try:
        if exchange:
            for params in [{'type': 'swap'}, {'productType': 'USDT-FUTURES'}, {}]:
                try:
                    bal = exchange.fetch_balance(params=params)
                    usdt = (bal.get('total', {}).get('USDT') or bal.get('USDT', {}).get('total') or bal.get('USDT', {}).get('free') or 0)
                    if float(usdt) > 0.5:
                        state["balance"] = round(float(usdt), 2)
                        return float(usdt)
                except:
                    continue
    except:
        pass
    # Fallback to forced balance
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

        if side == 'buy' and not state["active_position"]:
            risk_amount = usdt_balance * RISK_PERCENT
            cost = max(risk_amount * 12, MIN_ORDER_USDT + 3)
            cost = min(cost, usdt_balance * 0.30)

            add_log(f"Attempting LONG | Balance ${usdt_balance:.2f} | Size ${cost:.2f}")

            exchange.set_leverage(LEVERAGE, SYMBOL)
            amount = exchange.amount_to_precision(SYMBOL, cost / price)
            order = exchange.create_order(SYMBOL, 'market', 'buy', amount, params={'marginMode': 'cross'})

            filled_cost = float(order.get('cost', cost))
            filled_amount = float(order.get('filled', filled_cost / price))

            state["active_position"] = {
                "entry": price,
                "amount": round(filled_amount, 6),
                "time": time.strftime('%H:%M:%S'),
                "usdt_invested": round(filled_cost, 2),
                "sl_price": round(price * (1 - STOP_LOSS_PCT), 2),
                "tp_price": round(price * (1 + TAKE_PROFIT_PCT), 2)
            }
            add_log(f"✅ LONG OPENED: ${filled_cost:.2f}")

        elif side == 'sell' and state["active_position"]:
            pos = state["active_position"]
            amt = exchange.amount_to_precision(SYMBOL, pos["amount"])
            order = exchange.create_order(SYMBOL, 'market', 'sell', amt, params={'marginMode': 'cross'})

            current_price = state["price"]
            pnl_usd = (current_price - pos["entry"]) * float(pos["amount"])
            pnl_pct = ((current_price - pos["entry"]) / pos["entry"]) * 100
            pnl_str = f"${pnl_usd:.2f} ({pnl_pct:.2f}%)"
            daily_pnl += pnl_usd

            state["history"].insert(0, {"time": time.strftime('%H:%M:%S'), "action": "CLOSE", "price": f"${current_price:.2f}", "pnl": pnl_str})
            add_log(f"✅ CLOSED | PnL: {pnl_str}")
            state["active_position"] = None

    except Exception as e:
        add_log(f"TRADE ERROR: {str(e)}")

def check_sl_tp():
    if not state.get("active_position"): return
    pos = state["active_position"]
    price = state["price"]
    if price <= pos.get("sl_price", 0):
        add_log("🛑 STOP-LOSS HIT")
        execute_trade('sell')
    elif price >= pos.get("tp_price", 999999):
        add_log("🎯 TAKE-PROFIT HIT")
        execute_trade('sell')

def bot_loop():
    global daily_pnl, daily_reset_time
    fetcher = ccxt.bitget({'enableRateLimit': True})

    while True:
        try:
            now = datetime.now()
            if now.date() > daily_reset_time.date():
                daily_pnl = 0.0
                daily_reset_time = now

            get_usdt_balance()

            if daily_pnl < -(state["balance"] * MAX_DAILY_LOSS_PCT) and not state["is_paused"]:
                state["is_paused"] = True
                state["status"] = "PAUSED - DAILY LOSS LIMIT"
                add_log("🚨 DAILY LOSS LIMIT REACHED")

            # Data fetching (same as before)
            bars_1m = fetcher.fetch_ohlcv(SYMBOL, timeframe='1m', limit=210)
            df_1m = pd.DataFrame(bars_1m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df_1m['ema_200'] = df_1m['c'].ewm(span=200, adjust=False).mean()
            delta = df_1m['c'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            df_1m['rsi'] = 100 - (100 / (1 + gain / loss))

            last = df_1m.iloc[-1]
            state["price"] = round(float(last['c']), 2)
            state["rsi"] = round(float(last['rsi']), 1)
            state["ema_200"] = round(float(last['ema_200']), 2)

            bars_15m = fetcher.fetch_ohlcv(SYMBOL, timeframe='15m', limit=100)
            df_15m = pd.DataFrame(bars_15m, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df_15m['ema_200'] = df_15m['c'].ewm(span=200, adjust=False).mean()
            trend_15m = "BULLISH" if float(df_15m.iloc[-1]['c']) > float(df_15m.iloc[-1]['ema_200']) else "BEARISH"

            state["trend"] = "BULLISH" if state["price"] > state["ema_200"] else "BEARISH"

            if not state["is_paused"]:
                check_sl_tp()

                if (state["rsi"] < 35 and state["price"] > state["ema_200"] and trend_15m == "BULLISH" and not state["active_position"]):
                    state["signal"] = "LONG SIGNAL (15m Confirmed)"
                    execute_trade('buy')
                elif state["rsi"] > 70 and state["active_position"]:
                    state["signal"] = "CLOSE LONG"
                    execute_trade('sell')
                else:
                    state["signal"] = "MONITORING" if not state["active_position"] else "HOLDING"

        except Exception as e:
            add_log(f"Loop error: {str(e)}")
        time.sleep(5)

threading.Thread(target=bot_loop, daemon=True).start()

# API Endpoints and Dashboard (same as before)
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
        mode = data.get("mode", "FUTURES").upper()
        state["mode"] = mode
        exchange = ccxt.bitget({
            'apiKey': data.get("key"), 
            'secret': data.get("secret"), 
            'password': data.get("pass"), 
            'enableRateLimit': True,
            'options': {'defaultType': 'swap' if mode == "FUTURES" else 'spot'}
        })
        exchange.check_required_credentials()
        balance = get_usdt_balance()
        state["is_paused"] = False
        state["status"] = f"LIVE - {mode} MODE RUNNING"
        add_log(f"✅ Started in {mode} mode | Using ${balance:.2f} USDT")
    except Exception as e:
        add_log(f"❌ STARTUP ERROR: {str(e)}")

@app.post("/api/stop")
def stop_engine():
    state["is_paused"] = True
    state["status"] = "OFFLINE"
    add_log("HALT: Trading paused.")

@app.get("/", response_class=HTMLResponse)
def home():
    # The dashboard HTML is the same as v68.8 (with toggle)
    return """
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Alpha v68.9</title>
    <style>
        :root { --bg: #0b0e11; --card: #1e2329; --border: #363c4e; --text: #eaecef; --green: #0ecb81; --red: #f6465d; --yellow: #fcd535; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; margin: 0; padding: 10px; }
        .container { display: grid; grid-template-columns: 1fr; gap: 15px; max-width: 1200px; margin: 0 auto; }
        @media(min-width: 900px) { .container { grid-template-columns: 380px 1fr; } }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-bottom: 20px; }
        input, select { width: 100%; padding: 12px; margin-bottom: 10px; background: #2b3139; border: 1px solid var(--border); color: white; border-radius: 6px; }
        button { width: 100%; padding: 14px; font-weight: 800; border: none; border-radius: 6px; cursor: pointer; margin-top: 10px;}
        .btn-start { background: var(--green); color: #000; }
        .btn-stop { background: var(--red); color: #fff; }
        .grid-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px; }
        .stat-box { background: #2b3139; padding: 12px; border-radius: 8px; text-align: center; }
        .stat-box h4 { margin: 0; color: #848e9c; font-size: 10px; text-transform: uppercase; }
        .stat-box h2 { margin: 6px 0 0 0; font-size: 16px; }
        .logs { background: #000; color: #0ecb81; padding: 15px; font-family: 'Courier New', monospace; font-size: 11px; height: 320px; overflow-y: auto; border-radius: 8px; }
    </style></head>
    <body>
        <div class="container">
            <div>
                <div class="card" style="margin-bottom:15px;">
                    <div class="header"><span style="font-weight:bold; font-size:18px;">ALPHA v68.9</span><span id="mode_display" style="color:var(--yellow)"></span></div>
                    <div style="margin-bottom:15px; font-size:13px;"><span>Status: </span><b id="status">OFFLINE</b></div>
                    <select id="mode_select">
                        <option value="FUTURES" selected>Futures (Recommended)</option>
                        <option value="SPOT">Spot</option>
                    </select>
                    <input type="text" id="k" placeholder="API Key">
                    <input type="password" id="s" placeholder="API Secret">
                    <input type="password" id="p" placeholder="Passphrase">
                    <button class="btn-start" onclick="startBot()">INITIALIZE LIVE TRADING</button>
                    <button class="btn-stop" onclick="stopBot()">EMERGENCY STOP</button>
                </div>
                <div class="card"><h3 style="margin:0 0 15px 0; color:#848e9c; font-size:14px;">SYSTEM TERMINAL</h3><div class="logs" id="logs"></div></div>
            </div>
            <div style="display:flex; flex-direction:column; gap:15px;">
                <div class="grid-stats">
                    <div class="stat-box"><h4>ETH Price</h4><h2 id="price" style="color:var(--yellow)">--</h2></div>
                    <div class="stat-box"><h4>RSI (14)</h4><h2 id="rsi">--</h2></div>
                    <div class="stat-box"><h4>Trend</h4><h2 id="trend">--</h2></div>
                    <div class="stat-box"><h4>Balance</h4><h2 id="balance" style="color:var(--green)">$0</h2></div>
                </div>
                <div class="card"><div style="padding:40px 10px; text-align:center; border:2px solid var(--border); border-radius:12px;" id="sig_area">
                    <div style="color:#848e9c; font-size:12px; margin-bottom:10px;">MARKET ANALYSIS</div>
                    <div style="font-size:34px; font-weight:900;" id="signal">STANDBY</div>
                    <div id="active_pos" style="margin-top:20px;"></div>
                </div></div>
                <div class="card"><h3 style="margin:0 0 15px 0; color:#848e9c; font-size:14px;">TRADE HISTORY</h3><div style="max-height:200px; overflow-y:auto;"><table><thead><tr><th>Time</th><th>Action</th><th>Price</th><th>PnL</th></tr></thead><tbody id="history"></tbody></table></div></div>
            </div>
        </div>
        <script>
            function startBot() {
                const body = JSON.stringify({
                    key: document.getElementById('k').value,
                    secret: document.getElementById('s').value,
                    pass: document.getElementById('p').value,
                    mode: document.getElementById('mode_select').value
                });
                fetch('/api/start', {method:'POST', headers:{'Content-Type':'application/json'}, body});
            }
            function stopBot() {
                fetch('/api/stop', {method:'POST'});
            }
            async function update() {
                const r = await fetch('/api/status'); const d = await r.json();
                document.getElementById('status').innerText = d.status;
                document.getElementById('status').style.color = d.is_paused ? "var(--red)" : "var(--green)";
                document.getElementById('price').innerText = "$" + d.price;
                document.getElementById('rsi').innerText = d.rsi;
                document.getElementById('trend').innerText = d.trend;
                document.getElementById('balance').innerText = "$" + (d.balance || 0);
                document.getElementById('mode_display').innerText = d.mode || "FUTURES";

                const sig = document.getElementById('signal');
                sig.innerText = d.signal;
                if(d.signal.includes("LONG")) sig.style.color = "var(--green)";
                else if(d.signal.includes("CLOSE")) sig.style.color = "var(--red)";

                const logs = document.getElementById('logs');
                logs.innerHTML = d.logs.map(l => `<div>${l}</div>`).join("");

                if(d.active_position) {
                    document.getElementById('active_pos').innerHTML = `<div style="background:#2b3139; padding:12px; border-radius:8px;">POSITION: \( {d.active_position.amount} ETH | PnL: <b style="color:var(--green)"> \){d.active_position.current_pnl}</b></div>`;
                } else {
                    document.getElementById('active_pos').innerHTML = "";
                }
            }
            setInterval(update, 2000);
        </script>
    </body></html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
