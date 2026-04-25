import time
import os

import state
import data
import config
import strategy


while True:
    price = data.get_price()

    # update state safely
    if price is not None:
        state.state["price"] = price
        strategy.add_price(price)

    # volatility check (pause system)
    if strategy.is_volatile(config.VOLATILITY_THRESHOLD):
        state.state["status"] = "PAUSED 🔴"
    else:
        state.state["status"] = "RUNNING 🟢"

        if state.state["position"] is None:
            state.state["position"] = "LONG"

    os.system("cls" if os.name == "nt" else "clear")

    print("🤖 ETH BOT RUNNING")
    print("-------------------")
    print("Status:", state.state["status"])
    print("Price:", state.state["price"])
    print("Position:", state.state["position"])

    time.sleep(5)