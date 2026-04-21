import os
import time
import requests
import json
import re
from datetime import datetime
import pytz

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def normalize_name(name):
    """Simplifies: 'Philadelphia 76ers' -> 'philadelphia'"""
    name = name.lower()
    nicknames = ["cavaliers", "rockets", "nuggets", "lakers", "heat", "celtics", "mavericks", "spurs", "76ers", "blazers", "warriors", "bucks"]
    for n in nicknames:
        name = name.replace(n, "")
    name = re.sub(r'[^a-z\s]', '', name)
    return name.strip()

def safe_parse_prices(prices_raw):
    """Handles cases where Polymarket sends prices as strings or lists."""
    if isinstance(prices_raw, str):
        try:
            return json.loads(prices_raw)
        except:
            return []
    return prices_raw if isinstance(prices_raw, list) else []

def get_1xbet_live():
    """Fetches 1xBet odds and handles API errors gracefully."""
    print("📡 Fetching 1xBet via The Odds API...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu", # 1xBet is usually in EU region
        "markets": "totals",
        "bookmakers": "1xbet"
    }
    
    try:
        response = requests.get(url, params=params)
        res_data = response.json()
        
        # DEBUG: If the API returns a dictionary instead of a list, it's an error!
        if isinstance(res_data, dict):
            print(f"⚠️ API Error Message: {res_data.get('message', 'Unknown Error')}")
            return {}

        data = {}
        for game in res_data:
            home = normalize_name(game['home_team'])
            away = normalize_name(game['away_team'])
            
            for bookie in game.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == "Under":
                            line = outcome["point"]
                            prob = (1 / outcome["price"]) * 100
                            # Key format: 'city-city-line'
                            key = f"{home}-{away}-{line}"
                            data[key] = {"prob": prob, "market": f"under {line}"}
        return data
    except Exception as e:
        print(f"❌ 1xBet Request Failed: {e}")
        return {}

def get_polymarket_live():
    """Fetches Polymarket NBA Over/Under markets."""
    print("📡 Fetching Polymarket Gamma API...")
    url = "https://gamma-api.polymarket.com/events?limit=200&active=true&closed=false"
    
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            title = event.get("title", "")
            # Look for NBA games or specific playoff teams
            if any(x in title for x in ["NBA", "Celtics", "76ers", "Lakers", "Rockets"]):
                for m in event.get("markets", []):
                    q = m.get("question", "").lower()
                    if "over" in q and "points" in q:
                        prices = safe_parse_prices(m.get("outcomePrices"))
                        if not prices: continue
                        
                        yes_price = float(prices[0]) # Price for "Yes"
                        line_match = re.search(r"(\d+\.?\d*)", q)
                        if line_match:
                            line = float(line_match.group(1))
                            # Clean the title for matching
                            clean_title = normalize_name(title.replace(" at ", " vs "))
                            key = f"{clean_title}-{line}"
                            data[key] = {"prob": yes_price * 100, "market": q, "full_title": title}
        return data
    except Exception as e:
        print(f"❌ Polymarket Request Failed: {e}")
        return {}

def find_arbitrage():
    print(f"⏰ Scan Started: {datetime.now().strftime('%H:%M:%S')}")
    xbet = get_1xbet_live()
    poly = get_polymarket_live()
    
    found_any = False
    for key in poly:
        # Search for a match in 1xBet
        if key in xbet:
            p_prob = poly[key]["prob"]
            x_prob = xbet[key]["prob"]
            total = p_prob + x_prob
            
            if total < 100:
                found_any = True
                profit = (100 / (total / 100)) - 100
                p_stake = round((p_prob / total) * 100, 1)
                x_stake = round((x_prob / total) * 100, 1)
                
                msg = (
                    f"🏀 NBA: {poly[key]['full_title'].upper()}\n"
                    f"💰 Total Benefit: {round(profit, 2)}%\n\n"
                    f"🔵 Polymarket: Put {p_stake}% on '{poly[key]['market']}'\n"
                    f"🟢 1xBet: Put {x_stake}% on '{xbet[key]['market']}'\n\n"
                    f"⏱ {datetime.now().strftime('%B %d %H:%M et').lower()}"
                )
                send_telegram_alert(msg)

    if not found_any:
        print("⚖️ Markets are balanced. No arbitrage found.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    find_arbitrage()
