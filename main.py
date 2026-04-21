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

def get_1xbet_live():
    """Fetches real game odds from 1xBet."""
    print("📡 Fetching 1xBet Game Odds...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "1xbet"}
    
    try:
        res = requests.get(url, params=params).json()
        if isinstance(res, dict): return []
        return res
    except: return []

def get_polymarket_games():
    """Fetches ONLY actual NBA games using the specific NBA Games Tag (100639)."""
    print("📡 Fetching Polymarket NBA Game Markets...")
    # Tag 100639 filters for NBA individual games, skipping futures like 'NBA Champion'
    url = "https://gamma-api.polymarket.com/events?tag_id=100639&active=true&closed=false"
    try:
        return requests.get(url).json()
    except: return []

def normalize(name):
    return name.lower().replace("76ers", "philadelphia").replace("trail blazers", "portland").strip()

def run_arbitrage_scan():
    xbet_raw = get_1xbet_live()
    poly_raw = get_polymarket_games()
    
    timestamp = datetime.now(pytz.timezone('America/Toronto')).strftime("%B %d %H:%M et").lower()
    found_any = False

    print("\n--- 🔍 SCANNING FOR MATCHES ---")
    
    for game in xbet_raw:
        home_1x = game['home_team'].lower()
        away_1x = game['away_team'].lower()
        
        # Look for this game in the Polymarket list
        for event in poly_raw:
            title = event.get('title', '').lower()
            
            # Match if both teams (or their city names) appear in the title
            if (home_1x.split()[-1] in title or home_1x.split()[0] in title) and \
               (away_1x.split()[-1] in title or away_1x.split()[0] in title):
                
                print(f"✅ MATCH: {game['home_team']} vs {game['away_team']}")
                
                # Check each market inside the event (Winner, Over/Under, etc.)
                for m in event.get('markets', []):
                    q = m.get('question', '').lower()
                    prices = m.get('outcomePrices')
                    if isinstance(prices, str): prices = json.loads(prices)
                    if not prices: continue

                    # 1. Check Winner (Moneyline)
                    if "win" in q and "points" not in q:
                        bookie = next((b for b in game['bookmakers'] if b['key'] == '1xbet'), None)
                        if not bookie: continue
                        h2h = next((mkt for mkt in bookie['markets'] if mkt['key'] == 'h2h'), None)
                        if h2h:
                            for i, outcome in enumerate(m.get('outcomes', [])):
                                # Find matching team in 1xBet
                                x_outcome = next((o for o in h2h['outcomes'] if normalize(o['name']) in normalize(outcome)), None)
                                if x_outcome:
                                    p_prob = float(prices[i]) * 100
                                    x_prob = (1 / x_outcome['price']) * 100
                                    
                                    total = p_prob + x_prob
                                    if total < 100:
                                        found_any = True
                                        profit = (100 / (total / 100)) - 100
                                        alert = (
                                            f"🏀 NBA: {game['home_team']} vs {game['away_team']}\n"
                                            f"💰 Benefit: {round(profit, 2)}%\n\n"
                                            f"🔵 Poly: {round(p_prob/total*100, 1)}% on '{outcome} Win'\n"
                                            f"🟢 1xBet: {round(x_prob/total*100, 1)}% on '{x_outcome['name']} Win'\n\n"
                                            f"⏱ {timestamp}"
                                        )
                                        send_telegram_alert(alert)

    if not found_any:
        print("⚖️ No arbitrage found. Markets are efficient right now.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_arbitrage_scan()
