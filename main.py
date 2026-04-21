import os
import requests
import json
import re
from datetime import datetime

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def get_1xbet_raw():
    """Fetches raw data from 1xBet and prints it for debugging."""
    print("\n--- 📡 1xBET RAW DATA ---")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "1xbet"}
    
    try:
        res = requests.get(url, params=params).json()
        if isinstance(res, dict): 
            print(f"⚠️ API Error: {res.get('message')}")
            return []
        
        for game in res:
            print(f"📍 1xBet Game: {game['home_team']} vs {game['away_team']}")
        return res
    except Exception as e:
        print(f"❌ 1xBet Request Failed: {e}")
        return []

def get_polymarket_raw():
    """Fetches raw data from Polymarket and prints titles."""
    print("\n--- 📡 POLYMARKET RAW DATA ---")
    url = "https://gamma-api.polymarket.com/events?limit=200&active=true&closed=false"
    try:
        res = requests.get(url).json()
        nba_events = [e for e in res if any(x in e.get('title', '') for x in ["NBA", "76ers", "Celtics", "Lakers", "Rockets", "Spurs"])]
        
        for event in nba_events:
            print(f"📍 Poly Event: {event.get('title')}")
        return nba_events
    except Exception as e:
        print(f"❌ Polymarket Request Failed: {e}")
        return []

def solve_matching_and_scan():
    xbet_raw = get_1xbet_raw()
    poly_raw = get_polymarket_raw()
    
    print("\n--- 🔍 MATCHING ANALYSIS ---")
    
    # We will build a simple map of 1xBet games
    for game in xbet_raw:
        home_1x = game['home_team'].lower()
        away_1x = game['away_team'].lower()
        
        # Try to find a matching event in Polymarket
        for event in poly_raw:
            title = event.get('title', '').lower()
            
            # If BOTH teams from 1xBet are mentioned in the Polymarket title
            if (home_1x.split()[-1] in title or home_1x.split()[0] in title) and \
               (away_1x.split()[-1] in title or away_1x.split()[0] in title):
                
                print(f"✅ MATCH FOUND: '{game['home_team']} vs {game['away_team']}' matches Poly's '{event.get('title')}'")
                
                # Now compare Winner (H2H) Odds
                # 1xBet Odds
                bookie = next((b for b in game['bookmakers'] if b['key'] == '1xbet'), None)
                if not bookie: continue
                
                h2h_market = next((m for m in bookie['markets'] if m['key'] == 'h2h'), None)
                if h2h_market:
                    for outcome in h2h_market['outcomes']:
                        # Simple debug for Win Probability
                        print(f"   💰 1xBet {outcome['name']} Win: {round(1/outcome['price']*100, 1)}%")

    print("\n⚖️ Scan complete. Check the 'MATCH FOUND' lines above.")

if __name__ == "__main__":
    solve_matching_and_scan()
