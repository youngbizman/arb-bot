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

def clean_id(text):
    """Simplified city-based ID: 'Boston Celtics' -> 'boston'"""
    text = text.lower()
    # If it's a team with a two-word city, we take the first word (e.g. 'Los Angeles' -> 'los')
    return text.split()[0].replace('76ers', 'philadelphia').replace('trail', 'portland')

def get_1xbet_data():
    """Fetches real game odds from 1xBet."""
    print("📡 Fetching 1xBet (The Odds API)...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        data = {}
        for game in res:
            h_city, a_city = clean_id(game['home_team']), clean_id(game['away_team'])
            print(f"📍 1xBet Found: {game['home_team']} vs {game['away_team']}")
            
            for b in game.get("bookmakers", []):
                for m in b.get("markets", []):
                    if m['key'] == 'h2h':
                        for o in m['outcomes']:
                            # Key format: 'city1-city2-teamcity'
                            key = f"{h_city}-{a_city}-{clean_id(o['name'])}"
                            data[key] = {"prob": (1/o['price'])*100, "label": f"{o['name']} Win"}
        return data
    except: return {}

def get_polymarket_data():
    """Fetches all NBA-related events by searching the entire Gamma API."""
    print("📡 Searching Polymarket for NBA Games...")
    # We search the 'Events' endpoint directly for 'NBA'
    url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=200"
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            title = event.get('title', '').lower()
            # Only focus on individual games, skip 'Champion' or 'MVP' futures
            if "nba" in title and "at" in title or "vs" in title:
                if any(x in title for x in ["champion", "mvp", "rookie"]): continue
                
                print(f"📍 Poly Match Found: {event.get('title')}")
                # Extract city names from 'Team A at Team B'
                teams = title.replace(" at ", " vs ").split(" vs ")
                h_city, a_city = clean_id(teams[0]), clean_id(teams[1])

                for m in event.get('markets', []):
                    q = m.get('question', '').lower()
                    prices = m.get('outcomePrices')
                    if isinstance(prices, str): prices = json.loads(prices)
                    if not prices: continue

                    if "win" in q:
                        for i, outcome in enumerate(m.get('outcomes', [])):
                            # Identify which team this outcome belongs to
                            winner_city = clean_id(outcome)
                            key = f"{h_city}-{a_city}-{winner_city}"
                            data[key] = {"prob": float(prices[i])*100, "label": f"{outcome} Win"}
        return data
    except: return {}

def run_scanner():
    print(f"⏰ Scan Started: {datetime.now(pytz.timezone('America/Toronto')).strftime('%H:%M:%S')}")
    xbet = get_1xbet_data()
    poly = get_polymarket_data()
    
    print("\n--- 🔍 CROSS-MATCHING ---")
    found_any = False
    
    # We check every Poly match against the 1xBet database
    for key in poly:
        # Check for exact key match OR a reverse city match (since Home/Away can swap)
        alt_key = "-".join(key.split("-")[1::-1]) + f"-{key.split('-')[-1]}"
        match_key = key if key in xbet else (alt_key if alt_key in xbet else None)
        
        if match_key:
            x_p, p_p = xbet[match_key]['prob'], poly[key]['prob']
            total = x_p + p_p
            print(f"📊 MATCH: {poly[key]['label']} | 1xBet: {round(x_p,1)}% | Poly: {round(p_p,1)}% | Sum: {round(total,1)}%")
            
            if total < 99.5: # 0.5% buffer for safety
                found_any = True
                profit = (100 / (total / 100)) - 100
                p_stake = round((p_p / total) * 100, 1)
                x_stake = round((x_p / total) * 100, 1)
                
                alert = (
                    f"💰 ARB FOUND: {poly[key]['label']}\n"
                    f"Benefit: {round(profit, 2)}%\n\n"
                    f"🔵 Poly: {p_stake}% on '{poly[key]['label']}'\n"
                    f"🟢 1xBet: {x_stake}% on '{xbet[match_key]['label']}'\n\n"
                    f"⏱ {datetime.now(pytz.timezone('America/Toronto')).strftime('%B %d %H:%M et')}"
                )
                send_telegram_alert(alert)

    if not found_any:
        print("\n⚖️ Results: All markets balanced (No arbitrage found).")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scanner()
