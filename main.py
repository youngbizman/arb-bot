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

def get_1xbet_data():
    """Fetches real game odds from 1xBet via The Odds API."""
    print("📡 Fetching 1xBet...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        return res if isinstance(res, list) else []
    except: return []

def get_polymarket_events():
    """Fetches NBA individual games specifically using Tag 100639."""
    print("📡 Fetching Polymarket NBA Games (Tag 100639)...")
    url = "https://gamma-api.polymarket.com/events?tag_id=100639&active=true&closed=false&limit=100"
    try:
        return requests.get(url).json()
    except: return []

def get_keywords(name):
    """Turns 'Boston Celtics' into ['boston', 'celtics']."""
    return re.sub(r'[^a-z0-9\s]', '', name.lower()).split()

def is_match(title, team_keywords):
    """Checks if any part of the team name is in the title."""
    return any(word in title.lower() for word in team_keywords if len(word) > 2)

def run_arbitrage_scan():
    xbet_raw = get_1xbet_data()
    poly_raw = get_polymarket_events()
    
    timestamp = datetime.now(pytz.timezone('America/Toronto')).strftime("%B %d %H:%M et").lower()
    found_any = False

    print(f"\n--- 🔍 SCANNING {len(poly_raw)} POLY EVENTS ---")
    
    for game in xbet_raw:
        h_full, a_full = game['home_team'], game['away_team']
        h_keys, a_keys = get_keywords(h_full), get_keywords(a_full)
        
        # Handshake: Match 1xBet game to Poly Event
        for event in poly_raw:
            title = event.get('title', '')
            
            # If BOTH team names (or cities) appear in the title
            if is_match(title, h_keys) and is_match(title, a_keys):
                print(f"✅ MATCH FOUND: {h_full} vs {a_full} <-> {title}")
                
                for m in event.get('markets', []):
                    q = m.get('question', '').lower()
                    
                    # We look for 'Winner' or 'Beat' markets
                    if any(x in q for x in ["win", "beat", "winner"]):
                        prices = m.get('outcomePrices')
                        if isinstance(prices, str): prices = json.loads(prices)
                        if not prices or len(prices) < 2: continue
                        
                        bookie = next((b for b in game['bookmakers'] if b['key'] == '1xbet'), None)
                        h2h = next((mkt for mkt in bookie['markets'] if mkt['key'] == 'h2h'), None) if bookie else None
                        if not h2h: continue

                        # Compare outcomes
                        for i, p_team_name in enumerate(m.get('outcomes', [])):
                            p_prob = float(prices[i])
                            
                            # Find the OPPONENT on 1xBet
                            x_opp = next((o for o in h2h['outcomes'] if not is_match(o['name'], get_keywords(p_team_name))), None)
                            
                            if x_opp:
                                x_prob = 1 / x_opp['price']
                                total = p_prob + x_prob
                                
                                if total < 0.99: # Arbitrage threshold
                                    found_any = True
                                    benefit = (1/total - 1) * 100
                                    
                                    msg = (
                                        f"🏀 NBA: {h_full} vs {a_full}\n"
                                        f"💰 Benefit: {round(benefit, 2)}%\n\n"
                                        f"🔵 Poly: {round(p_prob/total*100, 1)}% on '{p_team_name}'\n"
                                        f"🟢 1xBet: {round(x_prob/total*100, 1)}% on '{x_opp['name']}'\n\n"
                                        f"⏱ {timestamp}"
                                    )
                                    send_telegram_alert(msg)

    if not found_any:
        print("⚖️ No arbitrage found. (Checked winner markets only)")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_arbitrage_scan()
