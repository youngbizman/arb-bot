import os
import requests
import json
import re
from datetime import datetime
import pytz

# Secure keys
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    """Normalized ID: 'Philadelphia 76ers' -> 'philadelphia'"""
    text = text.lower()
    # Map common nicknames to cities to ensure a match
    mapping = {"76ers": "philadelphia", "blazers": "portland", "cavs": "cleveland", "mavs": "dallas"}
    for nick, city in mapping.items():
        if nick in text: return city
    return text.split()[0] # Take the first word (usually the city)

def get_1xbet():
    """Fetches real NBA Winner odds from 1xBet."""
    print("📡 Fetching 1xBet...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        data = {}
        for game in res:
            h, a = game['home_team'], game['away_team']
            print(f"📍 1xBet Game: {h} vs {a}")
            bookie = next((b for b in game['bookmakers'] if b['key'] == '1xbet'), None)
            if bookie:
                mkt = next((m for m in bookie['markets'] if m['key'] == 'h2h'), None)
                if mkt:
                    for o in mkt['outcomes']:
                        # Key format: 'boston-win'
                        key = f"{clean(o['name'])}-win"
                        data[key] = {"prob": (1/o['price'])*100, "team": o['name'], "game": f"{h} vs {a}"}
        return data
    except: return {}

def get_polymarket():
    """Sniper scan using NBA Series ID (10345) and Game Tag (100639)."""
    print("📡 Sniping Polymarket NBA Games...")
    # Using specific Series and Tag IDs found in 2026 docs
    url = "https://gamma-api.polymarket.com/events?series_id=10345&tag_id=100639&active=true&closed=false"
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            title = event.get('title', '')
            print(f"📍 Poly Game Found: {title}")
            for m in event.get('markets', []):
                q = m.get('question', '').lower()
                # We only want the 'Who will win' or 'Winner' markets
                if "win" in q or "winner" in q or "beat" in q:
                    prices = m.get('outcomePrices')
                    if isinstance(prices, str): prices = json.loads(prices)
                    if not prices: continue
                    
                    for i, outcome_name in enumerate(m.get('outcomes', [])):
                        # Match 'Yes' or the specific team name
                        team_id = clean(q) if outcome_name.lower() == "yes" else clean(outcome_name)
                        data[f"{team_id}-win"] = {"prob": float(prices[i])*100, "label": outcome_name}
        return data
    except: return {}

def run_scan():
    xbet = get_1xbet()
    poly = get_polymarket()
    
    print("\n--- 🔍 CALCULATING ARBITRAGE ---")
    found_any = False
    
    for key, x_val in xbet.items():
        if key in poly:
            # We need the 1xBet prob for the OTHER team to check for the gap
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
                        f"🔵 Poly: {round(p_prob/total*100, 1)}% on '{x_val['team']}'\n"
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
