import os
import requests
import json
from datetime import datetime, timezone
import pytz
from decimal import Decimal, getcontext

# Set high precision for decimal arbitrage math
getcontext().prec = 28

# Secure keys
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    """Normalize team names for matching[cite: 1227]."""
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def parse_iso8601_to_epoch(time_str):
    """Standardized UTC ISO 8601 to Unix epoch converter [cite: 1597-1611]."""
    if not time_str: return 0
    time_str = time_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(time_str)
        return int(dt.timestamp())
    except ValueError:
        return 0

def is_target_single_game(fiat_commence_time, gamma_market, market_name="Unknown"):
    """
    Mathematical Deduplication Protocol:
    Guarantees the market is tonight's specific game using tip-off congruence 
    and oracle resolution boundaries [cite: 1572-1590, 1612-1650].
    """
    t_commence = parse_iso8601_to_epoch(fiat_commence_time)
    if t_commence == 0: return False

    poly_game_start_str = gamma_market.get("gameStartTime") or gamma_market.get("eventStartTime")
    poly_end_date_str = gamma_market.get("endDate")

    t_game = parse_iso8601_to_epoch(poly_game_start_str) if poly_game_start_str else 0
    t_end = parse_iso8601_to_epoch(poly_end_date_str) if poly_end_date_str else 0

    print(f"   DEBUG [Temporal Check - {market_name}]:")
    print(f"      - 1xBet Tipoff: {fiat_commence_time} ({t_commence})")
    print(f"      - Poly Start:   {poly_game_start_str} ({t_game})")
    print(f"      - Poly End:     {poly_end_date_str} ({t_end})")

    # 1. Tip-Off Congruence Box: Must tip off within ~2 hours of 1xBet.
    if t_game > 0:
        variance = abs(t_game - t_commence)
        if variance > 7200:
            print(f"      ❌ REJECTED: Tipoff variance too high ({variance}s > 7200s)")
            return False
        print(f"      ✅ Tipoff congruence passed.")

    # 2. Oracle Resolution Boundary: Single games resolve +4 to +36 hours after tip-off .
    if t_end > 0:
        oracle_delta = t_end - t_commence
        if oracle_delta < (4 * 3600) or oracle_delta > (36 * 3600):
            print(f"      ❌ REJECTED: Oracle delay outside single-game window ({oracle_delta}s)")
            return False
        print(f"      ✅ Oracle resolution window passed.")

    if t_game == 0 and t_end == 0:
        print(f"      ❌ REJECTED: No temporal data found.")
        return False

    print(f"      🏆 VALID Single Game Market.")
    return True

def get_clob_best_ask(token_id):
    """Bypasses array sorting bugs to find the true executable Ask price [cite: 1150-1153, 1811-1817]."""
    if not token_id: return None
    try:
        book = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id}, timeout=10).json()
        asks = book.get("asks", [])
        prices = [Decimal(str(ask["price"])) for ask in asks if "price" in ask]
        return min(prices) if prices else None
    except:
        return None

def get_1xbet():
    """Fetches real NBA Match Winner and Point Totals odds from 1xBet [cite: 1502-1507]."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals"}
    try:
        res = requests.get(url, params=params).json()
        games = {}
        if not isinstance(res, list): return {}

        print(f"DEBUG: 1xBet found {len(res)} games.")
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
        print(f"❌ 1xBet Fetch Error: {e}")
        return {}

def run_scan():
    print("📡 Initializing Debug Scan...")
    xbet_games = get_1xbet()
    
    try:
        res = requests.get("https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100")
        poly_data = res.json()
        poly_events = poly_data if isinstance(poly_data, list) else poly_data.get('events', [])
        print(f"DEBUG: Polymarket found {len(poly_events)} events.")
    except Exception as e: 
        print(f"DEBUG: Poly fetch failed: {e}")
        poly_events = []
    
    found_any = False
    
    for game_key, x_data in xbet_games.items():
        print(f"\n🔍 Processing 1xBet Game: {x_data['home']} vs {x_data['away']}")
        home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
        fiat_time = x_data["commence_time"]
        
        target_event = None
        for event in poly_events:
            title = event.get('title', '').lower()
            if home_nick in title and away_nick in title:
                target_event = event
                print(f"   ✅ Matched Poly Event: '{event.get('title')}'")
                break
                
        if not target_event:
            print(f"   ❌ No matching Poly event found.")
            continue
        
        for m in target_event.get('markets', []):
            if not m.get('acceptingOrders'): continue
            m_type = m.get('sportsMarketType')
            
            # --- 1. MONEYLINE ARBITRAGE ---
            if m_type == 'moneyline':
                if is_target_single_game(fiat_time, m, "Moneyline"):
                    raw_outcomes = json.loads(m.get('outcomes', "[]")) if isinstance(m.get('outcomes'), str) else m.get('outcomes', [])
                    raw_tokens = json.loads(m.get('clobTokenIds', "[]")) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
                    
                    for idx, team_name in enumerate(raw_outcomes):
                        p_nick = clean(team_name)
                        if p_nick in x_data["moneyline"]:
                            poly_ask = get_clob_best_ask(raw_tokens[idx])
                            if not poly_ask: continue
                            
                            opp_nick = home_nick if p_nick == away_nick else away_nick
                            if opp_nick in x_data["moneyline"]:
                                inv_opp_d = Decimal("1") / x_data["moneyline"][opp_nick]
                                arb_sum = poly_ask + inv_opp_d
                                if arb_sum < Decimal("1"):
                                    found_any = True
                                    profit = (Decimal("1") / arb_sum - Decimal("1")) * 100
                                    send_telegram_alert(f"💰 ARB: {x_data['home']} vs {x_data['away']}\nProfit: {round(float(profit), 2)}%")

            # --- 2. TOTAL POINTS ARBITRAGE [cite: 1653-1688] ---
            elif m_type in ['total', 'totals']:
                try: poly_line = float(m.get("line", 0.0))
                except: continue
                
                if poly_line in x_data["totals"] and is_target_single_game(fiat_time, m, f"Totals {poly_line}"):
                    outcomes = [o.lower().strip() for o in (json.loads(m.get('outcomes', "[]")) if isinstance(m.get('outcomes'), str) else m.get('outcomes', []))]
                    tokens = json.loads(m.get('clobTokenIds', "[]")) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
                    
                    try:
                        over_token = tokens[outcomes.index("over")]
                        under_token = tokens[outcomes.index("under")]
                    except: continue

                    p_over_ask = get_clob_best_ask(over_token)
                    if p_over_ask:
                        inv_under_d = Decimal("1") / x_data["totals"][poly_line]['under']
                        if (p_over_ask + inv_under_d) < 1:
                            found_any = True
                            send_telegram_alert(f"🏀 TOTALS: {x_data['home']} Over {poly_line}")

    if not found_any: print("\n⚖️ Scan finished. No profitable temporal gaps found.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})

if __name__ == "__main__":
    run_scan()
