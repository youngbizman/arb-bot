import os
import requests
import json
from datetime import datetime, timezone

# Secure keys
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    """Normalize team names for matching."""
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def run_inspector():
    print("📡 Fetching raw data from The Odds API...")
    odds_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    # Requesting Moneyline, Totals, and Spreads to get the full fiat picture
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

    print("\n🔍 Searching for Playoff games for Today and Tomorrow...")
    
    now = datetime.now(timezone.utc)
    today_match = None
    tomorrow_match = None
    
    for fiat_game in fiat_response:
        try:
            game_time_str = fiat_game['commence_time'].replace("Z", "+00:00")
            game_time = datetime.fromisoformat(game_time_str)
            hours_diff = (game_time - now).total_seconds() / 3600
            
            # Determine if the game is Today or Tomorrow
            is_today = (0 <= hours_diff <= 24)
            is_tomorrow = (24 < hours_diff <= 48)
            
            if not is_today and not is_tomorrow:
                continue
                
            # If we already found a match for this window, skip to save space
            if is_today and today_match: continue
            if is_tomorrow and tomorrow_match: continue

            home_nick = clean(fiat_game["home_team"])
            away_nick = clean(fiat_game["away_team"])
            
            # Find matching Poly event
            matched_poly = next((e for e in poly_events if home_nick in e.get('title','').lower() and away_nick in e.get('title','').lower()), None)
            
            if matched_poly:
                if is_today:
                    today_match = (fiat_game, matched_poly)
                    print(f"✅ Found Today's Match: {fiat_game['home_team']} vs {fiat_game['away_team']}")
                elif is_tomorrow:
                    tomorrow_match = (fiat_game, matched_poly)
                    print(f"✅ Found Tomorrow's Match: {fiat_game['home_team']} vs {fiat_game['away_team']}")

            # Stop early if we have one of each
            if today_match and tomorrow_match:
                break
        except:
            continue

    # --- FINAL OUTPUT PRINTING ---
    
    if today_match:
        f_data, p_data = today_match
        print("\n" + "#"*40 + " GAME 1: TODAY " + "#"*40)
        print(f"Matchup: {f_data['home_team']} vs {f_data['away_team']}")
        print("\n--- PINNACLE RAW JSON ---")
        print(json.dumps(f_data, indent=4))
        print("\n--- POLYMARKET RAW JSON ---")
        print(json.dumps(p_data, indent=4))
    else:
        print("\n❌ Could not find a matched game for Today.")

    if tomorrow_match:
        f_data, p_data = tomorrow_match
        print("\n" + "#"*40 + " GAME 2: TOMORROW " + "#"*40)
        print(f"Matchup: {f_data['home_team']} vs {f_data['away_team']}")
        print("\n--- PINNACLE RAW JSON ---")
        print(json.dumps(f_data, indent=4))
        print("\n--- POLYMARKET RAW JSON ---")
        print(json.dumps(p_data, indent=4))
    else:
        print("\n❌ Could not find a matched game for Tomorrow.")

    print("\n" + "#"*95)
    print("🛑 SCRIPT COMPLETE: Provide the output above to Deep Research for market mapping.")

if __name__ == "__main__":
    if not ODDS_API_KEY:
        print("⚠️ ERROR: ODDS_API_KEY environment variable is missing.")
    else:
        run_inspector()
