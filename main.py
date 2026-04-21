import os
import requests
import json
import re
from datetime import datetime
import pytz

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def get_1xbet_data():
    """Fetches real game odds from 1xBet."""
    print("📡 Fetching 1xBet...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        data = {}
        for game in res:
            h, a = game['home_team'].lower(), game['away_team'].lower()
            game_id = f"{clean(h)}-{clean(a)}"
            print(f"📍 1xBet Game Found: {game['home_team']} vs {game['away_team']}")
            for b in game.get("bookmakers", []):
                for m in b.get("markets", []):
                    if m['key'] == 'h2h':
                        for o in m['outcomes']:
                            data[f"{game_id}-win-{clean(o['name'])}"] = {"prob": (1/o['price'])*100, "label": f"{o['name']} Win"}
        return data
    except: return {}

def get_polymarket_data():
    """Fetches directly from the /markets endpoint (Highest Volume)."""
    print("📡 Fetching Polymarket Markets (High Volume)...")
    # Using the /markets endpoint directly often works better than /events
    url = "https://gamma-api.polymarket.com/markets?limit=100&active=true&closed=false&order=volume24hr&dir=desc"
    try:
        res = requests.get(url).json()
        data = {}
        for m in res:
            # We look for team names in the question (e.g., "Will the Celtics win?")
            q = m.get('question', '').lower()
            
            # Print everything that looks like NBA for debugging
            if "nba" in q or "celtics" in q or "76ers" in q or "lakers" in q:
                print(f"📍 Poly Market Found: {m.get('question')}")
                
                # Identify which game this belongs to
                # We extract two team names from the question
                # Simple Logic: if a question has 'celtics' and '76ers', it's that game
                matched_teams = []
                for team in ["celtics", "76ers", "philadelphia", "lakers", "rockets", "nuggets", "spurs", "blazers"]:
                    if team in q: matched_teams.append(team)
                
                if len(set(matched_teams)) >= 2:
                    sorted_teams = sorted(list(set(matched_teams)))
                    game_id = f"{clean(sorted_teams[0])}-{clean(sorted_teams[1])}"
                    
                    prices = m.get('outcomePrices')
                    if isinstance(prices, str): prices = json.loads(prices)
                    
                    if "win" in q and prices:
                        for i, outcome in enumerate(m.get('outcomes', [])):
                            team_key = clean(outcome)
                            data[f"{game_id}-win-{team_key}"] = {"prob": float(prices[i])*100, "label": f"{outcome} Win"}
        return data
    except Exception as e:
        print(f"❌ Poly Error: {e}")
        return {}

def run_scanner():
    print(f"⏰ Scan Started: {datetime.now(pytz.timezone('America/Toronto')).strftime('%H:%M:%S')}")
    xbet = get_1xbet_data()
    poly = get_polymarket_data()
    
    print("\n--- 🔍 CROSS-CHECKING ---")
    found_any = False
    for key in xbet:
        if key in poly:
            x_p, p_p = xbet[key]['prob'], poly[key]['prob']
            total = x_p + p_p
            print(f"📊 Match: {xbet[key]['label']} | 1xBet: {round(x_p,1)}% | Poly: {round(p_p,1)}% | Total: {round(total,1)}%")
            
            if total < 100:
                found_any = True
                profit = (100 / (total / 100)) - 100
                msg = f"💰 ARB FOUND: {xbet[key]['label']}\nProfit: {round(profit,2)}%\n\n🔵 Poly: {round(p_p/total*100,1)}%\n🟢 1xBet: {round(x_p/total*100,1)}%"
                send_telegram_alert(msg)

    if not found_any:
        print("⚖️ No arbitrage found at this moment.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scanner()
