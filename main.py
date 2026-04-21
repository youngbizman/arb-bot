import os
import time
import requests
from datetime import datetime
import pytz

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    """Sends the formatted text to your phone."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram credentials missing! Please check GitHub Secrets.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, json=payload)

def get_eastern_time():
    """Generates the exact timestamp format you requested in ET."""
    eastern = pytz.timezone('America/Toronto') # Aligns perfectly with ET
    now = datetime.now(eastern)
    # Formats as: april 20 14:23 ET
    return now.strftime("%B %d %H:%M ET").lower()

def calculate_profit(poly_prob, xbet_prob):
    """The Arbitrage Math Engine."""
    total_implied = poly_prob + xbet_prob
    if total_implied < 100:
        # Profit formula: (100 / Combined Probability) - 100
        profit_pct = (100 / (total_implied / 100)) - 100
        return round(profit_pct, 2)
    return 0

def get_1xbet_live_odds():
    """
    PLACEHOLDER: This is where we will attach the Playwright stealth bot.
    For now, it feeds dummy data so the math engine can run and text you.
    """
    return {
        "Cleveland vs Rockets": {"market": "under 216.5", "prob": 51.5},
        "Lakers vs Nuggets": {"market": "over 205.5", "prob": 48.0},
        "Celtics vs Heat": {"market": "under 220.5", "prob": 45.4},
        "Spurs vs Mavericks": {"market": "over 210.5", "prob": 58.0}
    }

def get_polymarket_live_odds():
    """
    PLACEHOLDER: Feeds matching dummy data to test the Top-3 sorting.
    """
    return {
        "Cleveland vs Rockets": {"market": "over 216.5 point yes", "prob": 46.0}, # Profit: 2.56%
        "Lakers vs Nuggets": {"market": "under 205.5 point yes", "prob": 49.0},   # Profit: 3.09%
        "Celtics vs Heat": {"market": "over 220.5 point yes", "prob": 52.0},      # Profit: 2.67%
        "Spurs vs Mavericks": {"market": "under 210.5 point yes", "prob": 43.0}   # Profit: -1.0% (Will be ignored)
    }

def find_top_3_arbitrages():
    print("🏀 Calculating Arbitrages...")
    
    # 1. Fetch the data
    xbet_data = get_1xbet_live_odds()
    poly_data = get_polymarket_live_odds()
    timestamp = get_eastern_time()
    
    found_arbs = []

    # 2. Compare the odds and do the math
    for game in poly_data:
        if game in xbet_data:
            poly_prob = poly_data[game]["prob"]
            poly_market = poly_data[game]["market"]
            
            xbet_prob = xbet_data[game]["prob"]
            xbet_market = xbet_data[game]["market"]
            
            profit = calculate_profit(poly_prob, xbet_prob)
            
            # 3. If profit exists, format the exact message you requested
            if profit > 0:
                message = (
                    f"NBA - {game} - april 21\n"
                    f"{poly_prob}% of money on {poly_market} on poly market\n"
                    f"{xbet_prob}% of {xbet_market} points in 1 xbet\n"
                    f"total benefit is {profit}%\n"
                    f"this calculation was done on {timestamp}"
                )
                
                found_arbs.append({
                    "profit": profit,
                    "message": message
                })

    # 4. Sort the list by highest profit and slice the Top 3
    found_arbs.sort(key=lambda x: x["profit"], reverse=True)
    top_3 = found_arbs[:3]
    
    # 5. Send the Top 3 to Telegram
    for rank, arb in enumerate(top_3, 1):
        print(f"✅ Found Rank #{rank} (Profit: {arb['profit']}%)")
        send_telegram_alert(arb["message"])
        time.sleep(1) # Anti-spam pause

if __name__ == "__main__":
    find_top_3_arbitrages()
