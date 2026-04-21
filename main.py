import os
import time
import requests
from datetime import datetime
import pytz

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    """Sends the formatted text to all phones listed in the secret."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram credentials missing! Please check GitHub Secrets.")
        return

    # Split the IDs by the comma
    chat_ids = TELEGRAM_CHAT_ID.split(',')
    
    # Loop through and send the text to everyone on the list
    for chat_id in chat_ids:
        clean_id = chat_id.strip() # Removes any accidental spaces
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": clean_id, "text": message}
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            print(f"✅ Alert sent to {clean_id}")
        else:
            print(f"❌ Failed to send to {clean_id}")

def get_eastern_time():
    """Generates the exact timestamp format you requested in ET."""
    eastern = pytz.timezone('America/Toronto')
    now = datetime.now(eastern)
    return now.strftime("%B %d %H:%M et").lower()

def get_current_date():
    """Gets just the date for the match header."""
    eastern = pytz.timezone('America/Toronto')
    now = datetime.now(eastern)
    return now.strftime("%B %d")

def calculate_profit(poly_prob, xbet_prob):
    """The Arbitrage Math Engine."""
    total_implied = poly_prob + xbet_prob
    if total_implied < 100:
        profit_pct = (100 / (total_implied / 100)) - 100
        return round(profit_pct, 2)
    return 0

def get_1xbet_live_odds():
    """PLACEHOLDER: Dummy data for testing."""
    return {
        "Cleveland vs Rockets": {"market": "under 216.5 points", "prob": 51.5},
        "Lakers vs Nuggets": {"market": "over 205.5 points", "prob": 48.0},
        "Celtics vs Heat": {"market": "under 220.5 points", "prob": 45.4},
        "Spurs vs Mavericks": {"market": "over 210.5 points", "prob": 58.0}
    }

def get_polymarket_live_odds():
    """PLACEHOLDER: Matching dummy data for Top-3 sorting test."""
    return {
        "Cleveland vs Rockets": {"market": "over 216.5 point yes", "prob": 46.0},
        "Lakers vs Nuggets": {"market": "under 205.5 point yes", "prob": 49.0},
        "Celtics vs Heat": {"market": "over 220.5 point yes", "prob": 52.0},
        "Spurs vs Mavericks": {"market": "under 210.5 point yes", "prob": 43.0}
    }

def find_top_3_arbitrages():
    print("🏀 Calculating Arbitrages...")
    
    xbet_data = get_1xbet_live_odds()
    poly_data = get_polymarket_live_odds()
    timestamp = get_eastern_time()
    match_date = get_current_date()
    
    found_arbs = []

    for game in poly_data:
        if game in xbet_data:
            poly_prob = poly_data[game]["prob"]
            poly_market = poly_data[game]["market"]
            
            xbet_prob = xbet_data[game]["prob"]
            xbet_market = xbet_data[game]["market"]
            
            profit = calculate_profit(poly_prob, xbet_prob)
            
            if profit > 0:
                # ---------------------------------------------------------
                # Scaling your money to equal 100% exactly
                # ---------------------------------------------------------
                total_implied = poly_prob + xbet_prob
                poly_stake = round((poly_prob / total_implied) * 100, 1)
                xbet_stake = round((xbet_prob / total_implied) * 100, 1)

                message = (
                    f"🏀 NBA: {game}\n"
                    f"📅 Match Date: {match_date}\n\n"
                    f"🔵 Polymarket: Put {poly_stake}% of money on {poly_market}\n"
                    f"🟢 1xBet: Put {xbet_stake}% of money on {xbet_market}\n\n"
                    f"💰 Total Benefit: {profit}%\n\n"
                    f"⏱ Calc Done: {timestamp}"
                )
                
                found_arbs.append({
                    "profit": profit,
                    "message": message
                })

    found_arbs.sort(key=lambda x: x["profit"], reverse=True)
    top_3 = found_arbs[:3]
    
    for rank, arb in enumerate(top_3, 1):
        print(f"\n✅ Found Rank #{rank} (Profit: {arb['profit']}%)")
        send_telegram_alert(arb["message"])
        time.sleep(1) # Anti-spam pause

if __name__ == "__main__":
    find_top_3_arbitrages()
