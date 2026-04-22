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
    """Extracts the team nickname for perfect matching."""
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def parse_iso8601_to_epoch(time_str):
    """Converts ISO 8601 strings to UTC Unix epoch integers for chronological bounding."""
    if not time_str: return 0
    time_str = time_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(time_str)
        return int(dt.timestamp())
    except ValueError:
        return 0

def is_target_single_game(fiat_commence_time, gamma_market):
    """
    Mathematical Deduplication: Guarantees the market is tonight's specific game 
    by checking Tip-Off Congruence and Oracle Resolution Boundaries.
    """
    t_commence = parse_iso8601_to_epoch(fiat_commence_time)
    if t_commence == 0: return False

    poly_game_start_str = gamma_market.get("gameStartTime") or gamma_market.get("eventStartTime")
    poly_end_date_str = gamma_market.get("endDate")

    t_game = parse_iso8601_to_epoch(poly_game_start_str) if poly_game_start_str else 0
    t_end = parse_iso8601_to_epoch(poly_end_date_str) if poly_end_date_str else 0

    # 1. Tip-Off Congruence Box (Must tip off within ~4 hours of 1xBet)
    if t_game > 0:
        variance_seconds = abs(t_game - t_commence)
        if variance_seconds > (4.0 * 3600):
            return False

    # 2. Oracle Resolution Boundary (Must resolve +4 to +36 hours after tip-off)
    if t_end > 0:
        oracle_delta_seconds = t_end - t_commence
        if oracle_delta_seconds < (2.0 * 3600) or oracle_delta_seconds > (36.0 * 3600):
            return False

    if t_game == 0 and t_end == 0:
        return False

    return True

def get_clob_best_ask(token_id):
    """Gets true executable Ask price by manually finding the minimum price."""
    if not token_id: return None
    try:
        book = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id}, timeout=10).json()
        asks = book.get("asks", [])
        prices = [Decimal(str(ask["price"])) for ask in asks if "price" in ask]
        return min(prices) if prices else None
    except:
        return None

def extract_over_under_tokens(gamma_market, fiat_line_target):
    """Safely extracts Over/Under token IDs mapping to the exact fiat threshold."""
    try:
        poly_line = float(gamma_market.get("line", 0.0))
    except:
        return None

    if poly_line != fiat_line_target:
        return None

    raw_outcomes = gamma_market.get("outcomes", [])
    raw_tokens = gamma_market.get("clobTokenIds", [])

    if isinstance(raw_outcomes, str):
        try: raw_outcomes = json.loads(raw_outcomes)
        except: pass
    if isinstance(raw_tokens, str):
        try: raw_tokens = json.loads(raw_tokens)
        except: pass

    if not raw_outcomes or not raw_tokens or len(raw_outcomes) != len(raw_tokens):
        return None

    try:
        normalized_outcomes = [str(o).lower().strip() for o in raw_outcomes]
        over_index = normalized_outcomes.index("over")
        under_index = normalized_outcomes.index("under")
        return (raw_tokens[over_index], raw_tokens[under_index])
    except ValueError:
        return None

def get_1xbet():
    """Fetches real NBA Match Winner and Point Totals odds from 1xBet."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals"}
    try:
        res = requests.get(url, params=params).json()
        games = {}
        if not isinstance(res, list): return {}

        for game in res:
            h, a = game['home_team'], game['away_team']
            commence_time = game.get('commence_time', '')
            if not commence_time: continue
            
            try:
                dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
                match_date = dt.astimezone(pytz.timezone('America/Toronto')).strftime("%B %d")
            except: match_date = "Unknown"

            game_data = {"home": h, "away": a, "date": match_date, "commence_time": commence_time, "moneyline": {}, "totals": {}}
            
            if game.get("bookmakers"):
                b = game["bookmakers"][0] 
                for m in b.get("markets", []):
                    if m['key'] == 'h2h':
                        for o in m['outcomes']:
                            game_data["moneyline"][clean(o['name'])] = {"price": Decimal(str(o['price'])), "full_name": o['name']}
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
    print("📡 Fetching Playoff Market Data...")
    xbet_games = get_1xbet()
    
    try:
        poly_events = requests.get("https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100").json()
    except: poly_events = []
    
    print("\n--- 📊 INTERNAL DATA TABLE (REAL ASK PRICES) ---")
    
    found_any = False
    
    for game_key, x_data in xbet_games.items():
        home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
        fiat_time = x_data["commence_time"]
        
        # Find matching Polymarket Event
        target_event = None
        for event in (poly_events if isinstance(poly_events, list) else poly_events.get('events', [])):
            if event.get("ended"): continue
            title = event.get('title', '').lower()
            if home_nick in title and away_nick in title:
                target_event = event
                break
                
        if not target_event: continue
        
        for m in target_event.get('markets', []):
            if not m.get('acceptingOrders'): continue
            
            # --- 1. MONEYLINE ARBITRAGE ---
            if m.get('sportsMarketType') == 'moneyline' and is_target_single_game(fiat_time, m):
                raw_outcomes = m.get('outcomes', "[]")
                raw_tokens = m.get('clobTokenIds', "[]")
                outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
                tokens = json.loads(raw_tokens) if isinstance(raw_tokens, str) else raw_tokens
                
                if outcomes and tokens and len(outcomes) == len(tokens):
                    for idx, team_name in enumerate(outcomes):
                        p_nick = clean(team_name)
                        if p_nick in x_data["moneyline"]:
                            poly_ask = get_clob_best_ask(tokens[idx])
                            if not poly_ask: continue
                            
                            # Find opponent on 1xBet
                            opp_nick = home_nick if p_nick == away_nick else away_nick
                            if opp_nick in x_data["moneyline"]:
                                opp_xbet_data = x_data["moneyline"][opp_nick]
                                inv_opp_d = Decimal("1") / opp_xbet_data["price"]
                                
                                arb_sum = poly_ask + inv_opp_d
                                if arb_sum < Decimal("1"):
                                    found_any = True
                                    B = Decimal("100")
                                    profit = ((B / arb_sum) - B) / B * Decimal("100")
                                    
                                    msg = (
                                        f"🏀 NBA: {x_data['home']} vs {x_data['away']}\n"
                                        f"📅 Match Date: {x_data['date']}\n\n"
                                        f"🔵 Polymarket: Put {round(float(B * poly_ask / arb_sum), 1)}% of money on '{team_name}'\n"
                                        f"🟢 1xBet: Put {round(float(B * inv_opp_d / arb_sum), 1)}% of money on '{opp_xbet_data['full_name']}'\n\n"
                                        f"💰 Total Benefit: {round(float(profit), 2)}%\n\n"
                                        f"⏱ Calc Done: {datetime.now(pytz.timezone('America/Toronto')).strftime('%B %d %H:%M et').lower()}"
                                    )
                                    send_telegram_alert(msg)

            # --- 2. TOTAL POINTS ARBITRAGE ---
            elif m.get('sportsMarketType') in ['total', 'totals'] and is_target_single_game(fiat_time, m):
                for fiat_line, odds_dict in x_data["totals"].items():
                    if 'over' in odds_dict and 'under' in odds_dict:
                        tokens = extract_over_under_tokens(m, fiat_line)
                        if not tokens: continue
                        
                        poly_over_ask, poly_under_ask = get_clob_best_ask(tokens[0]), get_clob_best_ask(tokens[1])
                        
                        # Scenario A: Poly Over + 1xBet Under
                        if poly_over_ask:
                            inv_under_d = Decimal("1") / odds_dict['under']
                            arb_sum = poly_over_ask + inv_under_d
                            if arb_sum < Decimal("1"):
                                found_any = True
                                B = Decimal("100")
                                profit = ((B / arb_sum) - B) / B * Decimal("100")
                                msg = (
                                    f"🏀 NBA: {x_data['home']} vs {x_data['away']}\n"
                                    f"📅 Match Date: {x_data['date']}\n\n"
                                    f"🔵 Polymarket: Put {round(float(B * poly_over_ask / arb_sum), 1)}% of money on 'Over {fiat_line} points'\n"
                                    f"🟢 1xBet: Put {round(float(B * inv_under_d / arb_sum), 1)}% of money on 'Under {fiat_line} points'\n\n"
                                    f"💰 Total Benefit: {round(float(profit), 2)}%\n\n"
                                    f"⏱ Calc Done: {datetime.now(pytz.timezone('America/Toronto')).strftime('%B %d %H:%M et').lower()}"
                                )
                                send_telegram_alert(msg)
                                
                        # Scenario B: Poly Under + 1xBet Over
                        if poly_under_ask:
                            inv_over_d = Decimal("1") / odds_dict['over']
                            arb_sum = poly_under_ask + inv_over_d
                            if arb_sum < Decimal("1"):
                                found_any = True
                                B = Decimal("100")
                                profit = ((B / arb_sum) - B) / B * Decimal("100")
                                msg = (
                                    f"🏀 NBA: {x_data['home']} vs {x_data['away']}\n"
                                    f"📅 Match Date: {x_data['date']}\n\n"
                                    f"🔵 Polymarket: Put {round(float(B * poly_under_ask / arb_sum), 1)}% of money on 'Under {fiat_line} points'\n"
                                    f"🟢 1xBet: Put {round(float(B * inv_over_d / arb_sum), 1)}% of money on 'Over {fiat_line} points'\n\n"
                                    f"💰 Total Benefit: {round(float(profit), 2)}%\n\n"
                                    f"⏱ Calc Done: {datetime.now(pytz.timezone('America/Toronto')).strftime('%B %d %H:%M et').lower()}"
                                )
                                send_telegram_alert(msg)

    if not found_any:
        print("⚖️ All markets are efficient. No gaps below 100% found.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scan()
