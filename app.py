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

state = {
    "status": "OFFLINE", 
    "price": 0.00, 
    "rsi": 0.0, 
    "ema_200": 0.0,
    "signal": "INITIALIZING", 
    "trend": "WAITING", 
    "is_paused": True, 
    "active_position": None,
    "balance": 0.0,
    "mode": "FUTURES",
    "logs": ["v68.8 - Improved Futures Balance Detection"],
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
    try:
        if not exchange: return 0.0
        
        # Try multiple common ways for Bitget Futures
        for params in [
            {'type': 'swap'},                    # Standard futures
            {'productType': 'USDT-FUTURES'},     # Bitget specific
            {},                                  # Default
            {'type': 'future'}
        ]:
            try:
                balance = exchange.fetch_balance(params=params)
                # Look in different possible locations
                usdt = (balance.get('total', {}).get('USDT') or 
                        balance.get('USDT', {}).get('total') or 
                        balance.get('USDT', {}).get('free') or 0)
                if usdt > 0:
                    return float(usdt)
            except:
                continue
        return 0.0
    except Exception as e:
        add_log(f"Balance fetch error: {str(e)}")
        return 0.0

# (The rest of the code - execute_trade, check_sl_tp, bot_loop, endpoints, and HTML - remains the same as v68.7 for brevity. 
#  If you need the full file again, just say "give full v68.8" and I'll paste the complete thing.)

# Note: For the full file, copy your previous v68.7 and only replace the get_usdt_balance function with the one above. 
# Then restart the server.
