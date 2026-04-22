import os
import requests
import json

# Secure keys
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def run_diagnostic_dump():
    print("📡 Fetching Raw Data for GPT Analysis...\n")
    
    # 1. Fetch 1xBet Raw
    url_1xbet = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params_1xbet = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h"}
    try:
        xbet_raw = requests.get(url_1xbet, params=params_1xbet).json()
    except Exception as e:
        print(f"1xBet Error: {e}")
        return

    # 2. Fetch Polymarket Gamma Raw
    url_poly = "https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100"
    try:
        poly_raw = requests.get(url_poly).json()
    except Exception as e:
        print(f"Poly Error: {e}")
        return

    print("==========================================")
    print("--- RAW 1XBET JSON (TARGET GAME) ---")
    if isinstance(xbet_raw, list) and len(xbet_raw) > 0:
        # Pick the first available game
        target_game = xbet_raw[0]
        print(json.dumps(target_game, indent=2))
        
        h_nick = target_game.get('home_team', '').lower().split()[-1]
        a_nick = target_game.get('away_team', '').lower().split()[-1]
    else:
        print("No 1xBet data found.")
        return

    print("\n==========================================")
    print("--- RAW POLYMARKET GAMMA JSON (MATCHING GAME) ---")
    poly_events = poly_raw if isinstance(poly_raw, list) else poly_raw.get('events', [])
    
    target_event = None
    for event in poly_events:
        title = event.get('title', '').lower()
        if h_nick in title or a_nick in title:
            target_event = event
            print(json.dumps(target_event, indent=2))
            break
            
    if not target_event:
        print("\nNo matching Polymarket event found for this game.")
        return
        
    print("\n==========================================")
    print("--- RAW POLYMARKET CLOB JSON (ORDERBOOKS) ---")
    for m in target_event.get('markets', []):
        if m.get('sportsMarketType') == 'moneyline':
            outcomes_str = m.get('outcomes', "[]")
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            token_ids_str = m.get("clobTokenIds", "[]")
            token_ids = json.loads(token_ids_str) if isinstance(token_ids_str, str) else token_ids_str
            
            for idx, team_name in enumerate(outcomes):
                token_id = token_ids[idx] if idx < len(token_ids) else None
                if token_id:
                    print(f"\n--> CLOB FOR TEAM: {team_name} | TOKEN: {token_id}")
                    try:
                        book = requests.get(
                            "https://clob.polymarket.com/book",
                            params={"token_id": token_id},
                            timeout=10
                        ).json()
                        print(json.dumps(book, indent=2))
                    except Exception as e:
                        print(f"Error fetching CLOB: {e}")
                        
    print("\n==========================================")
    print("✅ DIAGNOSTIC COMPLETE. COPY TERMINAL OUTPUT TO GPT.")

if __name__ == "__main__":
    run_diagnostic_dump()
