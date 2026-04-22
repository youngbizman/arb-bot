import os
import requests
import json
from datetime import datetime
import pytz
from decimal import Decimal, getcontext

# Set high precision for decimal arbitrage math
getcontext().prec = 28

# Secure keys
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    """Normalize team names for matching[cite: 284]."""
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def parse_iso8601_to_epoch(time_str):
    """Standardized UTC ISO 8601 to Unix epoch converter[cite: 654]."""
    if not time_str: return 0
    time_str = time_str.replace("Z", "+00:00") # Standardize UTC indicator [cite: 412]
    try:
        dt = datetime.fromisoformat(time_str)
        return int(dt.timestamp())
    except ValueError:
        return 0

def is_target_single_game(fiat_commence_time, gamma_market):
    """
    Mathematical Deduplication Protocol:
    Guarantees the market is tonight's specific game using tip-off congruence 
    and oracle resolution boundaries[cite: 634, 669].
    """
    t_commence = parse_iso8601_to_epoch(fiat_commence_time)
    if t_commence == 0: return False

    poly_game_start_str = gamma_market.get("gameStartTime") or gamma_market.get("eventStartTime")
    poly_end_date_str = gamma_market.get("endDate")

    t_game = parse_iso8601_to_epoch(poly_game_start_str) if poly_game_start_str else 0
    t_end = parse_iso8601_to_epoch(poly_end_date_str) if poly_end_date_str else 0

    # 1. Tip-Off Congruence Box: Must tip off within ~2 hours of 1xBet[cite: 641].
    if t_game > 0:
        if abs(t_game - t_commence) > 7200:
            return False

    # 2. Oracle Resolution Boundary: Single games resolve +4 to +36 hours after tip-off.
    # If delta > 72 hours, it's definitively a Series Winner[cite: 646, 647].
    if t_end > 0:
        oracle_delta_seconds = t_end - t_commence
        if oracle_delta_seconds < (4 * 3600) or oracle_delta_seconds > (36 * 3600):
            return False

    if t_game == 0 and t_end == 0:
        return False

    return True

def get_clob_best_ask(token_id):
    """Bypasses array sorting bugs to find the true executable Ask price."""
    if not token_id: return None
    try:
        book = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id}, timeout=10).json()
        asks = book.get("asks", [])
        # Manual min() selection to bypass unsorted API payloads[cite: 176, 871].
        prices = [Decimal(str(ask["price"])) for ask in asks if "price" in ask]
        return min(prices) if prices else None
    except:
        return None

def get_1xbet():
    """Fetches real NBA Match Winner and Point Totals odds from 1xBet[cite: 561]."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals"}
    try:
        res = requests.get(url, params=params).json()
        games = {}
        if not isinstance(res, list): return {}

        for game in res:
            h, a = game['home_team'], game['away_team']
            commence_time = game.get('commence_time', '')
            
            game_data = {
                "home": h, "away": a, "commence_time": commence_time,
                "moneyline": {}, "totals": {}
            }
            
            if game.get("bookmakers"):
                b = game["bookmakers"][0] 
                for m in b.get("markets", []):
                    if m['key'] == 'h2h':
                        for o in m['outcomes']:
                            game_data["moneyline"][clean(o['name'])] = Decimal(str(o['price']))
                    elif m['key'] == 'totals':
                        for o in m['outcomes']:
                            line = float(o['point'])
                            if line not in game_data["totals"]: game_data["totals"][line] = {}
                            game_data["totals"][line][o['name'].lower()] = Decimal(str(o['price']))
            
            games[f"{clean(h)}_{clean(a)}"] = game_data
        return games
    except Exception as e:
        return {}

def run_scan():
    print("📡 Initializing Temporal Arbitrage Scan...")
    xbet_games = get_1xbet()
    
    # Use Gamma for discovery + metadata [cite: 196]
    try:
        poly_events = requests.get("https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100").json()
    except: poly_events = []
    
    found_any = False
    
    for game_key, x_data in xbet_games.items():
        home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
        fiat_time = x_data["commence_time"]
        
        # Locate correct Polymarket Event by team labels [cite: 197]
        target_event = None
        for event in (poly_events if isinstance(poly_events, list) else poly_events.get('events', [])):
            title = event.get('title', '').lower()
            if home_nick in title and away_nick in title:
                target_event = event
                break
                
        if not target_event: continue
        
        for m in target_event.get('markets', []):
            if not m.get('acceptingOrders'): continue
            
            # --- MONEYLINE ARBITRAGE [cite: 711] ---
            if m.get('sportsMarketType') == 'moneyline' and is_target_single_game(fiat_time, m):
                raw_outcomes = json.loads(m.get('outcomes', "[]"))
                raw_tokens = json.loads(m.get('clobTokenIds', "[]"))
                
                for idx, team_name in enumerate(raw_outcomes):
                    p_nick = clean(team_name)
                    if p_nick in x_data["moneyline"]:
                        poly_ask = get_clob_best_ask(raw_tokens[idx])
                        if not poly_ask: continue
                        
                        # Compare against opponent on 1xBet [cite: 67]
                        opp_nick = home_nick if p_nick == away_nick else away_nick
                        if opp_nick in x_data["moneyline"]:
                            inv_opp_d = Decimal("1") / x_data["moneyline"][opp_nick]
                            arb_sum = poly_ask + inv_opp_d
                            
                            if arb_sum < Decimal("1"):
                                found_any = True
                                B = Decimal("100")
                                profit = (Decimal("1") / arb_sum - Decimal("1")) * 100
                                send_telegram_alert(f"💰 ARB FOUND: {x_data['home']} vs {x_data['away']}\nProfit: {round(float(profit), 2)}%")

            # --- TOTAL POINTS ARBITRAGE (Integration of Section 5 [cite: 710]) ---
            elif m.get('sportsMarketType') in ['total', 'totals'] and is_target_single_game(fiat_time, m):
                try:
                    poly_line = float(m.get("line", 0.0)) # Use native 'line' key [cite: 724, 728]
                except: continue
                
                if poly_line in x_data["totals"]:
                    outcomes = [o.lower().strip() for o in json.loads(m.get('outcomes', "[]"))]
                    tokens = json.loads(m.get('clobTokenIds', "[]"))
                    
                    try:
                        over_token = tokens[outcomes.index("over")] # Map by index [cite: 742]
                        under_token = tokens[outcomes.index("under")]
                    except: continue

                    # Scenario: Poly Over + 1xBet Under
                    p_over_ask = get_clob_best_ask(over_token)
                    if p_over_ask:
                        inv_under_d = Decimal("1") / x_data["totals"][poly_line]['under']
                        if (p_over_ask + inv_under_d) < 1:
                            found_any = True
                            send_telegram_alert(f"🏀 TOTALS ARB: {x_data['home']} Over {poly_line}")

    if not found_any: print("⚖️ Markets efficient. No temporal gaps found.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})

if __name__ == "__main__":
    run_scan()
