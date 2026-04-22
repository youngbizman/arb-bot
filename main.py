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
    """Extracts the team nickname for perfect matching."""
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def get_1xbet():
    """Fetches real NBA Winner odds from The Odds API."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    # Removed specific '1xbet' bookmaker restriction to ensure we always get data
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h"}
    try:
        res = requests.get(url, params=params).json()
        data = {}
        if isinstance(res, list):
            for game in res:
                h, a = game['home_team'], game['away_team']
                
                # Grab the first available bookie's odds for this game
                if game.get("bookmakers"):
                    b = game["bookmakers"][0] 
                    for m in b.get("markets", []):
                        if m['key'] == 'h2h':
                            for o in m['outcomes']:
                                key = f"{clean(o['name'])}-win"
                                data[key] = {"prob": (1/o['price'])*100, "team": o['name'], "game": f"{h} vs {a}"}
        return data
    except: return {}

def get_polymarket():
    """Sniper scan using NBA Moneyline JSON parsing."""
    url = "https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100"
    try:
        res = requests.get(url).json()
        data = {}
        events = res if isinstance(res, list) else res.get('events', [])
        
        for event in events:
            title = event.get('title', '')
            for m in event.get('markets', []):
                if m.get('sportsMarketType') == 'moneyline':
                    outcomes_str = m.get('outcomes', "[]")
                    prices_str = m.get('outcomePrices', "[]")
                    
                    outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                    
                    if outcomes and prices:
                        for i, team_name in enumerate(outcomes):
                            team_id = clean(team_name)
                            data[f"{team_id}-win"] = {"prob": float(prices[i])*100, "label": team_name}
        return data
    except: return {}

def run_scan():
    print("📡 Fetching Market Data...")
    xbet = get_1xbet()
    poly = get_polymarket()
    
    print("\n--- 📊 INTERNAL DATA TABLE ---")
    print(f"{'TEAM':<20} | {'1XBET %':<10} | {'POLY %':<10}")
    print("-" * 46)
    
    found_any = False
    
    # Show the raw math for every matching team
    for key, x_val in xbet.items():
        if key in poly:
            x_prob = x_val['prob']
            p_prob = poly[key]['prob']
            print(f"{x_val['team']:<20} | {round(x_prob, 1)}%      | {round(p_prob, 1)}%")
            
            # Arbitrage Logic: We need Team A from Poly + Team B from 1xBet
            game_name = x_val['game']
            other_x = next((v for k, v in xbet.items() if v['game'] == game_name and v['team'] != x_val['team']), None)
            
            if other_x:
                total_arb_sum = p_prob + other_x['prob']
                
                if total_arb_sum < 100:
                    found_any = True
                    profit = (100 / (total_arb_sum / 100)) - 100
                    alert = (
                        f"💰 ARB FOUND: {game_name}\n"
                        f"Profit: {round(profit, 2)}%\n\n"
                        f"🔵 Poly: {round(p_prob/total_arb_sum*100, 1)}% on '{poly[key]['label']}'\n"
                        f"🟢 1xBet: {round(other_x['prob']/total_arb_sum*100, 1)}% on '{other_x['team']}'"
                    )
                    send_telegram_alert(alert)

    print("\n--- 🔍 ARBITRAGE VERDICT ---")
    if not found_any:
        print("⚖️ All markets are efficient. No gaps below 100% found.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scan()
