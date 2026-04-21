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
    """Simplifies names: 'Philadelphia 76ers' -> 'philadelphia'"""
    name = name.lower()
    # Remove common team nicknames
    nicknames = ["cavaliers", "rockets", "nuggets", "lakers", "heat", "celtics", "mavericks", "spurs", "76ers", "trail blazers", "blazers"]
    for n in nicknames:
        name = name.replace(n, "")
    # Remove symbols and extra spaces
    name = re.sub(r'[^a-z\s]', '', name)
    return name.strip()

def get_1xbet_debug():
    """Fetches and PRINTS what 1xBet is showing."""
    print("\n--- 📡 1xBET (THE ODDS API) DIAGNOSTICS ---")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "totals", "bookmakers": "1xbet"}
    
    try:
        res = requests.get(url, params=params).json()
        data = {}
        if not res: print("⚠️ No NBA games found on 1xBet right now.")
        
        for game in res:
            home = normalize_name(game['home_team'])
            away = normalize_name(game['away_team'])
            print(f"📍 Found Game: {game['home_team']} vs {game['away_team']} (ID: {home}-{away})")
            
            for bookie in game.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == "Under":
                            line = outcome["point"]
                            prob = (1 / outcome["price"]) * 100
                            key = f"{home}-{away}-{line}"
                            data[key] = {"prob": prob, "market": f"under {line}"}
                            print(f"   💰 1xBet Under {line}: {round(prob, 1)}% (Odds: {outcome['price']})")
        return data
    except Exception as e:
        print(f"❌ 1xBet Error: {e}")
        return {}

def get_polymarket_debug():
    """Fetches and PRINTS what Polymarket is showing."""
    print("\n--- 📡 POLYMARKET DIAGNOSTICS ---")
    url = "https://gamma-api.polymarket.com/events?limit=100&active=true&closed=false"
    
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            title = event.get("title", "")
            # Check for today's specific playoff teams
            if any(team in title for team in ["Celtics", "76ers", "Lakers", "Rockets", "Spurs", "Blazers"]):
                print(f"📍 Found Poly Event: {title}")
                
                for m in event.get("markets", []):
                    q = m.get("question", "").lower()
                    if "over" in q and "points" in q:
                        # FIX: outcomePrices can be a string, we must parse it!
                        prices_raw = m.get("outcomePrices")
                        if isinstance(prices_raw, str):
                            prices = json.loads(prices_raw)
                        else:
                            prices = prices_raw
                        
                        yes_price = float(prices[0]) if prices else 0
                        
                        # Extract the point line (e.g., 220.5)
                        line_match = re.search(r"(\d+\.?\d*)", q)
                        if line_match:
                            line = float(line_match.group(1))
                            # Try to match names in the title
                            title_norm = normalize_name(title)
                            # Simple key for debugging
                            print(f"   💰 Poly Over {line}: {round(yes_price * 100, 1)}% (Price: {yes_price})")
                            data[f"{title_norm}-{line}"] = {"prob": yes_price * 100, "market": q}
        return data
    except Exception as e:
        print(f"❌ Polymarket Error: {e}")
        return {}

def run_diagnostics():
    print(f"⏰ Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    xbet = get_1xbet_debug()
    poly = get_polymarket_debug()
    
    print("\n--- 🔍 CROSS-MATCHING ATTEMPT ---")
    matches = 0
    # Simple logic to see if any partial match exists
    for x_key in xbet:
        for p_key in poly:
            # If the line (e.g. 216.5) and one team match, we count it as a potential link
            if x_key.split('-')[-1] == p_key.split('-')[-1]: 
                print(f"💎 POTENTIAL MATCH FOUND: {x_key} vs {p_key}")
                matches += 1
    
    if matches == 0:
        print("❌ Zero games matched between the two sites.")

if __name__ == "__main__":
    run_diagnostics()
