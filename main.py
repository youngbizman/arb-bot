import os
import requests
import json
from datetime import datetime
import pytz

# Secure keys
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    """Extracts the team nickname (e.g., 'celtics') for perfect matching."""
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def get_1xbet():
    """Fetches real NBA Winner odds from 1xBet."""
    print("📡 Fetching 1xBet...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        data = {}
        if isinstance(res, list):
            for game in res:
                h, a = game['home_team'], game['away_team']
                print(f"📍 1xBet Game: {h} vs {a}")
                for b in game.get("bookmakers", []):
                    if b['key'] == '1xbet':
                        for m in b.get("markets", []):
                            if m['key'] == 'h2h':
                                for o in m['outcomes']:
                                    # Key format: 'celtics-win'
                                    key = f"{clean(o['name'])}-win"
                                    data[key] = {"prob": (1/o['price'])*100, "team": o['name'], "game": f"{h} vs {a}"}
        return data
    except: return {}

def get_polymarket():
    """Sniper scan using NBA Moneyline JSON parsing."""
    print("📡 Sniping Polymarket Moneyline Markets...")
    url = "https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100"
    try:
        res = requests.get(url).json()
        data = {}
        events = res if isinstance(res, list) else res.get('events', [])
        
        for event in events:
            title = event.get('title', '')
            for m in event.get('markets', []):
                
                # Target the exact moneyline market
                if m.get('sportsMarketType') == 'moneyline':
                    outcomes_str = m.get('outcomes', "[]")
                    prices_str = m.get('outcomePrices', "[]")
                    
                    # Defeat the "Stringification Trap"
                    outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                    
                    if outcomes and prices:
                        print(f"📍 Poly Moneyline Found: {title}")
                        for i, team_name in enumerate(outcomes):
                            team_id = clean(team_name)
                            data[f"{team_id}-win"] = {"prob": float(prices[i])*100, "label": team_name, "game": title}
        return data
    except Exception as e:
        print(f"❌ Poly Error: {e}")
        return {}

def run_scan():
    xbet = get_1xbet()
    poly = get_polymarket()
    
    print("\n--- 🔍 CALCULATING ARBITRAGE ---")
    found_any = False
    
    for key, x_val in xbet.items():
        if key in poly:
            # We need the 1xBet prob for the OPPONENT to check for the gap
            game_name = x_val['game']
            other_x = next((v for k, v in xbet.items() if v['game'] == game_name and v['team'] != x_val['team']), None)
            
            if other_x:
                p_prob = poly[key]['prob'] # Prob Team A wins on Poly
                x_prob = other_x['prob']   # Prob Team B wins on 1xBet
                total = p_prob + x_prob
                
                print(f"📊 {game_name} | Sum: {round(total, 1)}%")
                
                if total < 100:
                    found_any = True
                    profit = (100 / (total / 100)) - 100
                    alert = (
                        f"💰 ARB FOUND: {game_name}\n"
                        f"Profit: {round(profit, 2)}%\n\n"
                        f"🔵 Poly: {round(p_prob/total*100, 1)}% on '{poly[key]['label']}'\n"
                        f"🟢 1xBet: {round(x_prob/total*100, 1)}% on '{other_x['team']}'"
                    )
                    send_telegram_alert(alert)

    if not found_any:
        print("⚖️ All markets are efficient (Total > 100%).")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scan()
