import os
import requests
import json
import re
import time
from datetime import datetime
import pytz

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Today's Playoff Teams (To make matching faster)
NBA_TEAMS = ["celtics", "76ers", "philadelphia", "spurs", "blazers", "portland", "lakers", "rockets", "nuggets", "timberwolves", "knicks", "hawks"]

def clean(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def get_1xbet_data():
    """Fetches real game odds (Winner & Totals) from 1xBet."""
    print("📡 Fetching 1xBet...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        if isinstance(res, dict): 
            print(f"⚠️ 1xBet API Error: {res.get('message')}")
            return {}
        
        data = {}
        for game in res:
            h, a = game['home_team'].lower(), game['away_team'].lower()
            game_id = f"{clean(h)}-{clean(a)}"
            print(f"📍 1xBet Found: {game['home_team']} vs {game['away_team']}")
            
            for b in game.get("bookmakers", []):
                for m in b.get("markets", []):
                    # Winner Odds
                    if m['key'] == 'h2h':
                        for o in m['outcomes']:
                            data[f"{game_id}-win-{clean(o['name'])}"] = {"prob": (1/o['price'])*100, "label": f"{o['name']} Win", "odds": o['price']}
                    # Over/Under Odds
                    if m['key'] == 'totals':
                        for o in m['outcomes']:
                            if o['name'] == "Under":
                                data[f"{game_id}-under-{o['point']}"] = {"prob": (1/o['price'])*100, "label": f"Under {o['point']} pts", "odds": o['price']}
        return data
    except: return {}

def get_polymarket_data():
    """Fetches all active events and finds NBA games manually."""
    print("📡 Fetching Polymarket (Scanning 200 events)...")
    url = "https://gamma-api.polymarket.com/events?limit=200&active=true&closed=false"
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            title = event.get('title', '').lower()
            # Only look at events containing our Playoff teams
            if any(team in title for team in NBA_TEAMS):
                print(f"📍 Poly Found: {event.get('title')}")
                
                # Match teams to create a game_id
                matched_teams = [t for t in NBA_TEAMS if t in title]
                if len(matched_teams) < 2: continue
                game_id = "-".join(sorted([clean(matched_teams[0]), clean(matched_teams[1])]))

                for m in event.get('markets', []):
                    q = m.get('question', '').lower()
                    prices = m.get('outcomePrices')
                    if isinstance(prices, str): prices = json.loads(prices)
                    if not prices: continue

                    # Winner Market
                    if "win" in q and "points" not in q:
                        for i, outcome in enumerate(m.get('outcomes', [])):
                            team_name = outcome.lower()
                            data[f"{game_id}-win-{clean(team_name)}"] = {"prob": float(prices[i])*100, "label": f"{outcome} Win"}
                    
                    # Totals Market
                    if "over" in q and "points" in q:
                        line_match = re.search(r"(\d+\.?\d*)", q)
                        if line_match:
                            line = line_match.group(1)
                            # Polymarket usually prices 'Yes' for Over. So Under prob = 100 - Over prob.
                            data[f"{game_id}-under-{line}"] = {"prob": (1.0 - float(prices[0]))*100, "label": f"Under {line} pts"}
        return data
    except: return {}

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
            
            if total < 99.5: # 0.5% margin for safety
                found_any = True
                profit = (100 / (total / 100)) - 100
                p_stake = round((p_p / total) * 100, 1)
                x_stake = round((x_p / total) * 100, 1)
                
                alert = (
                    f"💰 ARB FOUND: {xbet[key]['label']}\n"
                    f"Benefit: {round(profit, 2)}%\n\n"
                    f"🔵 Poly: {p_stake}% of cash\n"
                    f"🟢 1xBet: {x_stake}% of cash\n\n"
                    f"⏱ {datetime.now(pytz.timezone('America/Toronto')).strftime('%B %d %H:%M et')}"
                )
                send_telegram_alert(alert)

    if not found_any:
        print("\n⚖️ Results: No arbs found. Markets are balanced.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scanner()
