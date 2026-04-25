import time

price_history = []

def add_price(price):
    price_history.append((time.time(), price))

    # keep last 10 min
    cutoff = time.time() - 600
    while price_history and price_history[0][0] < cutoff:
        price_history.pop(0)

def is_volatile(threshold):
    if len(price_history) < 2:
        return False

    old = price_history[0][1]
    current = price_history[-1][1]

    change = abs((current - old) / old) * 100

    return change >= threshold