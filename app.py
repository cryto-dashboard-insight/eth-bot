import ccxt
import threading
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# -------------------------
# 1. ADDED PAUSE STATE
# -------------------------
state = {
    "status": "STARTING",
    "price": 0,
    "position": None,
    "volatility": 0,
    "is_paused": False  # <-- NEW: Smart Pause Control
}

exchange = ccxt.bitget({
    "enableRateLimit": True,
    "timeout": 30000
})

symbol = "ETH/USDT"

# -------------------------
# BOT LOOP (NOW WITH PAUSE LOGIC)
# -------------------------
def bot_loop():
    while True:
        # 🛑 SMART PAUSE CHECK
        if state["is_paused"]:
            state["status"] = "PAUSED 🛑"
            time.sleep(5)
            continue # Skips the trading logic below until resumed

        try:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker["last"]

            state["price"] = price
            state["status"] = "RUNNING 🟢"
            state["position"] = "LONG"
            state["volatility"] = round(price * 0.001, 2)

            print("UPDATED:", price)

        except Exception as e:
            state["status"] = "ERROR 🔴"
            print("ERROR:", e)

        time.sleep(5)

# Force start background thread
threading.Thread(target=bot_loop, daemon=True).start()


# -------------------------
# 📈 2. VISUAL DASHBOARD UI
# -------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    # We are serving a real HTML webpage directly from FastAPI!
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Crypto Bot Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #121212; color: #ffffff; text-align: center; padding: 50px; }
            .card { background: #1e1e1e; padding: 30px; border-radius: 10px; display: inline-block; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
            h1 { color: #00ffcc; }
            .btn { padding: 15px 25px; margin: 10px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 16px; }
            .btn-pause { background-color: #ff4c4c; color: white; }
            .btn-pause:hover { background-color: #ff1c1c; }
            .btn-resume { background-color: #4caf50; color: white; }
            .btn-resume:hover { background-color: #3e8e41; }
            .data-value { color: #00ffcc; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>📈 Trading Bot Dashboard</h1>
            <h2>Status: <span id="status" class="data-value">LOADING...</span></h2>
            <h3>Current Price: $<span id="price" class="data-value">0</span></h3>
            <p>Position: <span id="position" class="data-value">-</span> | Volatility: <span id="volatility" class="data-value">0</span></p>

            <br>
            <button class="btn btn-pause" onclick="sendCommand('pause')">🛑 PAUSE BOT</button>
            <button class="btn btn-resume" onclick="sendCommand('resume')">▶️ RESUME BOT</button>
        </div>

        <script>
            // This JavaScript fetches your bot's data in the background every 3 seconds
            async function fetchData() {
                try {
                    const res = await fetch('/api/status');
                    const data = await res.json();
                    document.getElementById('status').innerText = data.status;
                    document.getElementById('price').innerText = data.price;
                    document.getElementById('position').innerText = data.position;
                    document.getElementById('volatility').innerText = data.volatility;
                } catch (error) {
                    console.error("Error fetching data:", error);
                }
            }
            
            // This handles clicking the Pause/Resume buttons
            async function sendCommand(action) {
                await fetch('/' + action, { method: 'POST' });
                fetchData(); // Immediately refresh UI after clicking
            }

            setInterval(fetchData, 3000); // Loop every 3 seconds
            fetchData(); // Run once immediately on load
        </script>
    </body>
    </html>
    """
    return html_content

# -------------------------
# 🛠️ 3. API & CONTROL ENDPOINTS
# -------------------------
@app.get("/api/status")
def get_status():
    return state # The UI uses this endpoint to get the raw numbers

@app.post("/pause")
def pause_bot():
    state["is_paused"] = True
    return {"message": "Bot Paused"}

@app.post("/resume")
def resume_bot():
    state["is_paused"] = False
    return {"message": "Bot Resumed"}
