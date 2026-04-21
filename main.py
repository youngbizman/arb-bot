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
    print("📡 Fetching 1xBet (The Odds API)...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "bookmakers": "1xbet"}
    try:
        res = requests.get(url, params=params).json()
        if isinstance(res, dict): return []
        return res
    except: return []

def get_polymarket_events():
    """Fetches all active events from Polymarket as per Event List documentation."""
    print("📡 Fetching Polymarket Events (Top 250)...")
    # Fetching up to 250 active events to ensure we catch all tonight's games
    url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=250"
    try:
        return requests.get(url).json()
    except: return []

def clean_name(name):
    """Simplifies 'Philadelphia 76ers' to 'philadelphia' or '76ers' for matching."""
    name = name.lower()
    # Map cities to common short names used in titles
    mapping = {"philadelphia": "76ers", "portland": "blazers", "minnesota": "timberwolves"}
    for city, nickname in mapping.items():
        if city in name: return nickname
    return name.split()[-1] # Default to the last word (the nickname)

def run_arbitrage_scan():
    xbet_raw = get_1xbet_data()
    poly_raw = get_polymarket_events()
    
    timestamp = datetime.now(pytz.timezone('America/Toronto')).strftime("%B %d %H:%M et").lower()
    found_any = False

    print("\n--- 🔍 CROSS-MATCHING ---")
    
    for game in xbet_raw:
        # Get team names from 1xBet (e.g., 'Boston Celtics')
        home_full = game['home_team']
        away_full = game['away_team']
        
        # Simplified nicknames for matching
        h_nick = clean_name(home_full)
        a_nick = clean_name(away_full)
        
        # Scan Polymarket events for a title that mentions BOTH teams
        for event in poly_raw:
            title = event.get('title', '').lower()
            
            if h_nick in title and a_nick in title:
                print(f"✅ MATCH FOUND: {home_full} vs {away_full}")
                
                for m in event.get('markets', []):
                    q = m.get('question', '').lower()
                    
                    # Target Winner (Moneyline) markets
                    if "win" in q and "point" not in q:
                        prices = m.get('outcomePrices')
                        if isinstance(prices, str): prices = json.loads(prices)
                        if not prices: continue
                        
                        p_outcomes = m.get('outcomes', [])
                        bookie = next((b for b in game['bookmakers'] if b['key'] == '1xbet'), None)
                        if not bookie: continue
                        h2h = next((mkt for mkt in bookie['markets'] if mkt['key'] == 'h2h'), None)
                        if not h2h: continue
                        
                        # Arbitrage Math: Prob(Side A) + Prob(Side B) < 1.0
                        for i, p_team_name in enumerate(p_outcomes):
                            # Probability of this team winning on Polymarket
                            prob_poly = float(prices[i]) 
                            
                            # Find the OPPOSITE team on 1xBet to complete the arbitrage
                            other_x = next((o for o in h2h['outcomes'] if clean_name(o['name']) != clean_name(p_team_name)), None)
                            
                            if other_x:
                                prob_xbet = 1 / other_x['price']
                                total_prob = prob_poly + prob_xbet
                                
                                if total_prob < 0.995: # Arbitrage exists (with 0.5% buffer)
                                    found_any = True
                                    benefit = (1 / total_prob - 1) * 100
                                    
                                    # Calculate how to split your $100
                                    p_stake = (prob_poly / total_prob) * 100
                                    x_stake = (prob_xbet / total_prob) * 100
                                    
                                    alert = (
                                        f"💰 ARB FOUND: {home_full} vs {away_full}\n"
                                        f"Benefit: {round(benefit, 2)}%\n\n"
                                        f"🔵 Poly: {round(p_stake, 1)}% on '{p_team_name}'\n"
                                        f"🟢 1xBet: {round(x_stake, 1)}% on '{other_x['name']}'\n\n"
                                        f"⏱ {timestamp}"
                                    )
                                    send_telegram_alert(alert)

    if not found_any:
        print("⚖️ No arbitrage found. Markets are balanced.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_arbitrage_scan()
