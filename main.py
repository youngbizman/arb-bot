import os
import requests
import json
from datetime import datetime, timezone
import pytz
from decimal import Decimal, getcontext

getcontext().prec = 28

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean(text):
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def parse_iso8601_to_epoch(time_str):
    if not time_str: return 0
    t = time_str.replace(" ", "T")
    if t.endswith("+00"): t += ":00" 
    if t.endswith("Z"): t = t.replace("Z", "+00:00")
    try: return int(datetime.fromisoformat(t).timestamp())
    except:
        try: return int(datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except: return 0

def is_target_single_game(fiat_commence_time, gamma_market):
    t_commence = parse_iso8601_to_epoch(fiat_commence_time)
    poly_game_start_str = gamma_market.get("gameStartTime") or gamma_market.get("eventStartTime")
    poly_end_date_str = gamma_market.get("endDate")
    t_game = parse_iso8601_to_epoch(poly_game_start_str)
    t_end = parse_iso8601_to_epoch(poly_end_date_str)

    if t_game > 0 and abs(t_game - t_commence) > 14400: return False
    if t_end > 0 and abs(t_end - t_commence) > (48 * 3600): return False
    return True

def get_clob_best_ask(token_id):
    if not token_id: return None
    try:
        book = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id}, timeout=10).json()
        asks = book.get("asks", [])
        prices = [Decimal(str(ask["price"])) for ask in asks if "price" in ask]
        return min(prices) if prices else None
    except: return None

def get_fiat_data():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    # Utilizing Pinnacle, the sharpest global bookie that is active on your API key
    params = {"apiKey": ODDS_API_KEY, "regions": "eu,us,uk", "markets": "h2h,totals", "bookmakers": "pinnacle"}
    try:
        res = requests.get(url, params=params).json()
        games = {}
        if not isinstance(res, list): return {}
        
        for game in res:
            h, a = game['home_team'], game['away_team']
            commence_time = game.get('commence_time', '')
            game_data = {"home": h, "away": a, "commence_time": commence_time, "moneyline": {}, "totals": {}}
            
            if game.get("bookmakers"):
                b = game["bookmakers"][0] 
                for m in b.get("markets", []):
                    if m['key'] == 'h2h':
                        for o in m['outcomes']: game_data["moneyline"][clean(o['name'])] = Decimal(str(o['price']))
                    elif m['key'] == 'totals':
                        for o in m['outcomes']:
                            line = round(float(o['point']), 1)
                            if line not in game_data["totals"]: game_data["totals"][line] = {}
                            game_data["totals"][line][o['name'].lower()] = Decimal(str(o['price']))
                games[f"{clean(h)}_{clean(a)}"] = game_data
        return games
    except: return {}

def run_scan():
    print("📡 Initializing Arbitrage Node (Pinnacle vs Polymarket)...")
    xbet_games = get_fiat_data()
    
    try:
        res = requests.get("https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100").json()
        poly_events = res if isinstance(res, list) else res.get('events', [])
    except: poly_events = []
    
    print("\n--- 📊 LIVE ARBITRAGE TABLE ---")
    print(f"{'MARKET':<35} | {'PINNACLE':<10} | {'POLY ASK'}")
    print("-" * 65)
    
    found_any = False
    for game_key, x_data in xbet_games.items():
        home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
        target_event = next((e for e in poly_events if home_nick in e.get('title','').lower() and away_nick in e.get('title','').lower()), None)
        if not target_event: continue
        
        for m in target_event.get('markets', []):
            if not m.get('acceptingOrders') or not is_target_single_game(x_data["commence_time"], m): continue
            m_type = str(m.get('sportsMarketType', '')).lower()
            
            if m_type == 'moneyline':
                outcomes = json.loads(m['outcomes']) if isinstance(m['outcomes'], str) else m['outcomes']
                tokens = json.loads(m['clobTokenIds']) if isinstance(m['clobTokenIds'], str) else m['clobTokenIds']
                for idx, t_name in enumerate(outcomes):
                    p_nick = clean(t_name)
                    if p_nick in x_data["moneyline"]:
                        poly_ask = get_clob_best_ask(tokens[idx])
                        if poly_ask:
                            print(f"{t_name:<35} | {float(x_data['moneyline'][p_nick]):<10} | {round(float(poly_ask)*100, 1)}%")
                            opp_nick = home_nick if p_nick == away_nick else away_nick
                            if opp_nick in x_data["moneyline"]:
                                arb_sum = poly_ask + (Decimal("1") / x_data["moneyline"][opp_nick])
                                if arb_sum < 1:
                                    found_any = True
                                    send_telegram_alert(f"💰 ARB: {x_data['home']} vs {x_data['away']}\nProfit: {round(float((1/arb_sum-1)*100), 2)}%")

            elif m_type in ['total', 'totals']:
                try: poly_line = round(float(m.get("line", 0.0)), 1)
                except: continue
                if poly_line in x_data["totals"]:
                    raw_outcomes = json.loads(m['outcomes']) if isinstance(m['outcomes'], str) else m['outcomes']
                    raw_tokens = json.loads(m['clobTokenIds']) if isinstance(m['clobTokenIds'], str) else m['clobTokenIds']
                    normalized = [str(o).lower().strip() for o in raw_outcomes]
                    try:
                        over_idx, under_idx = normalized.index("over"), normalized.index("under")
                        over_token, under_token = raw_tokens[over_idx], raw_tokens[under_idx]
                    except: continue

                    p_over_ask, p_under_ask = get_clob_best_ask(over_token), get_clob_best_ask(under_token)
                    if p_over_ask:
                        xb_under = x_data["totals"][poly_line].get('under')
                        if xb_under:
                            print(f"Poly OVER / Pin UNDER {poly_line:<12} | {float(xb_under):<10} | {round(float(p_over_ask)*100, 1)}%")
                            if (p_over_ask + (Decimal("1") / xb_under)) < 1:
                                found_any = True
                                send_telegram_alert(f"🏀 ARB: {x_data['home']} OVER {poly_line}")

                    if p_under_ask:
                        xb_over = x_data["totals"][poly_line].get('over')
                        if xb_over:
                            print(f"Poly UNDER / Pin OVER {poly_line:<12} | {float(xb_over):<10} | {round(float(p_under_ask)*100, 1)}%")
                            if (p_under_ask + (Decimal("1") / xb_over)) < 1:
                                found_any = True
                                send_telegram_alert(f"🏀 ARB: {x_data['home']} UNDER {poly_line}")

    if not found_any: print("\n⚖️ Markets efficient. No gaps found.")

def send_telegram_alert(message):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": message})

if __name__ == "__main__":
    run_scan()
