import os
import requests
import json
from datetime import datetime, timezone

# Secure keys
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def run_inspector():
    print("📡 Fetching raw data from The Odds API...")
    odds_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    odds_params = {"apiKey": ODDS_API_KEY, "regions": "eu,us", "markets": "h2h,totals,spreads", "bookmakers": "pinnacle"}
    
    try:
        fiat_response = requests.get(odds_url, params=odds_params).json()
    except Exception as e:
        print(f"Error fetching Odds API: {e}")
        return

    print("📡 Fetching raw data from Polymarket Gamma API...")
    poly_url = "https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100"
    
    try:
        poly_response = requests.get(poly_url).json()
        poly_events = poly_response if isinstance(poly_response, list) else poly_response.get('events', [])
    except Exception as e:
        print(f"Error fetching Polymarket: {e}")
        return

    print("\n🔍 Searching for ONE of TODAY'S matched NBA games...")
    
    now = datetime.now(timezone.utc)
    match_found = False
    
    for fiat_game in fiat_response:
        # --- STRICT TIME FILTER FOR "TODAY" ---
        try:
            game_time_str = fiat_game['commence_time'].replace("Z", "+00:00")
            game_time = datetime.fromisoformat(game_time_str)
            hours_diff = (game_time - now).total_seconds() / 3600
            
            # If the game doesn't start in the next 24 hours (or recently started), skip it.
            if not (-12 <= hours_diff <= 24):
                continue
        except:
            continue

        home_nick = clean(fiat_game["home_team"])
        away_nick = clean(fiat_game["away_team"])
        
        matched_poly_event = next((e for e in poly_events if home_nick in e.get('title','').lower() and away_nick in e.get('title','').lower()), None)
        
        if matched_poly_event:
            match_found = True
            print(f"\n✅ MATCH FOUND FOR TODAY: {fiat_game['home_team']} vs {fiat_game['away_team']} (Starts: {fiat_game['commence_time']})")
            print("="*80)
            
            print("\n" + "="*30 + " THE ODDS API (PINNACLE) RAW JSON " + "="*30)
            print(json.dumps(fiat_game, indent=4))
            
            print("\n" + "="*31 + " POLYMARKET (GAMMA API) RAW JSON " + "="*32)
            print(json.dumps(matched_poly_event, indent=4))
            
            print("\n" + "="*80)
            print("🛑 STOPPING SCRIPT: Successfully printed 1 matched game for today.")
            break
            
    if not match_found:
        print("❌ Could not find a matched game happening today.")

if __name__ == "__main__":
    if not ODDS_API_KEY:
        print("⚠️ ERROR: ODDS_API_KEY environment variable is missing.")
    else:
        run_inspector()
