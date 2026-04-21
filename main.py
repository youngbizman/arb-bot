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
    """Strips everything but letters/numbers for perfect matching."""
    return re.sub(r'[^a-z0-9]', '', text.lower())

def get_1xbet():
    """Fetches real NBA Winner (h2h) odds."""
    print("📡 Fetching 1xBet...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        data = {}
        for game in res:
            h, a = game['home_team'], game['away_team']
            print(f"📍 1xBet: {h} vs {a}")
            bookie = next((b for b in game['bookmakers'] if b['key'] == '1xbet'), None)
            if bookie:
                mkt = next((m for m in bookie['markets'] if m['key'] == 'h2h'), None)
                if mkt:
                    for o in mkt['outcomes']:
                        # Key = 'celtics-win' or '76ers-win'
                        key = f"{clean(o['name'])}-win"
                        data[key] = {"prob": (1/o['price'])*100, "team": o['name'], "game": f"{h} vs {a}"}
        return data
    except: return {}

def get_polymarket():
    """Scans Polymarket for matching team names in the questions."""
    print("📡 Scanning Polymarket...")
    # We pull all active events (no tag filtering to be safe)
    url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=200"
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            for m in event.get('markets', []):
                q = m.get('question', '').lower()
                # Check if this is a "Who will win" market
                if "win" in q or "beat" in q:
                    prices = m.get('outcomePrices')
                    if isinstance(prices, str): prices = json.loads(prices)
                    if not prices: continue
                    
                    # We look for which 1xBet teams are mentioned in this question
                    # If the question says 'Celtics', we map it to the 'Celtics-win' key
                    outcomes = m.get('outcomes', [])
                    for i, outcome_name in enumerate(outcomes):
                        # Poly 'Yes' usually means the team mentioned in the question wins
                        if outcome_name.lower() == "yes":
                            # We search for the team name inside the question text
                            # (This is the most reliable way to match Polymarket)
                            data[q] = {"prob": float(prices[i])*100, "question": m.get('question')}
        return data
    except: return {}

def run_scan():
    xbet = get_1xbet()
    poly = get_polymarket()
    
    print("\n--- 🔍 SEARCHING FOR CROSS-SITE OVERLAP ---")
    found_any = False
    
    # We loop through every 1xBet team and see if Polymarket is asking a question about them
    for x_key, x_val in xbet.items():
        team_name = clean(x_val['team'])
        
        for q_text, p_val in poly.items():
            # If the Polymarket question mentions the 1xBet team name
            if team_name in clean(q_text):
                print(f"✅ MATCH FOUND: {x_val['team']} (1xBet) <-> '{p_val['question']}' (Poly)")
                
                # Now we need the OPPOSITE side probability to check for Arb
                # We need the 1xBet probability for the OTHER team in that same game
                game_name = x_val['game']
                other_team_x = next((v for k, v in xbet.items() if v['game'] == game_name and v['team'] != x_val['team']), None)
                
                if other_team_x:
                    p_prob = p_val['prob']
                    x_prob = other_team_x['prob']
                    total = p_prob + x_prob
                    
                    print(f"   📊 Stats: Poly={round(p_prob,1)}% | 1xBet={round(x_prob,1)}% | Total={round(total,1)}%")
                    
                    if total < 100:
                        found_any = True
                        profit = (100 / (total / 100)) - 100
                        msg = (
                            f"💰 ARB FOUND: {game_name}\n"
                            f"Benefit: {round(profit, 2)}%\n\n"
                            f"🔵 Poly: {round(p_prob/total*100, 1)}% on '{x_val['team']}'\n"
                            f"🟢 1xBet: {round(x_prob/total*100, 1)}% on '{other_team_x['team']}'"
                        )
                        send_telegram_alert(msg)

    if not found_any:
        print("⚖️ No gaps found in the matched markets.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scan()
