import os
import requests
import json
from datetime import datetime, timezone
from decimal import Decimal, getcontext

# Precision for absolute decimal matching
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
    """Temporal Bounding Box logic to filter out Series Winners."""
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
    """Ingests Source A (Pinnacle) expanding to 5 core markets."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY, 
        "regions": "eu,us", 
        "markets": "h2h,totals,spreads,h2h_h1", 
        "bookmakers": "pinnacle"
    }
    try:
        res = requests.get(url, params=params).json()
        games = {}
        if not isinstance(res, list): return {}
        
        for game in res:
            h, a = game['home_team'], game['away_team']
            commence_time = game.get('commence_time', '')
            game_data = {
                "home": h, "away": a, "commence_time": commence_time, 
                "moneyline": {}, "totals": {}, "spreads": {}, "1h_moneyline": {}
            }
            
            if game.get("bookmakers"):
                b = game["bookmakers"][0] 
                for m in b.get("markets", []):
                    try:
                        key = m['key']
                        for o in m['outcomes']:
                            name_clean = clean(o['name'])
                            price = Decimal(str(o['price']))
                            
                            if key == 'h2h':
                                game_data["moneyline"][name_clean] = price
                            elif key == 'h2h_h1':
                                game_data["1h_moneyline"][name_clean] = price
                            elif key == 'totals':
                                line = round(float(o['point']), 1)
                                if line not in game_data["totals"]: game_data["totals"][line] = {}
                                game_data["totals"][line][o['name'].lower()] = price
                            elif key == 'spreads':
                                point = round(float(o['point']), 1)
                                if point not in game_data["spreads"]: game_data["spreads"][point] = {}
                                game_data["spreads"][point][name_clean] = price
                    except Exception:
                        continue # Robustness Clause: Skip malformed fiat attributes silently
                games[f"{clean(h)}_{clean(a)}"] = game_data
        return games
    except: return {}

def send_telegram_alert(message):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except: pass

def run_scan():
    print("📡 Initializing High-Density Multi-Market Sniper...")
    fiat_games = get_fiat_data()
    
    try:
        res = requests.get("https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100").json()
        poly_events = res if isinstance(res, list) else res.get('events', [])
    except: poly_events = []
    
    arbitrage_opportunities = []
    
    for game_key, x_data in fiat_games.items():
        home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
        target_event = next((e for e in poly_events if home_nick in e.get('title','').lower() and away_nick in e.get('title','').lower()), None)
        if not target_event: continue
        
        game_output = []
        
        for m in target_event.get('markets', []):
            if not m.get('acceptingOrders') or not is_target_single_game(x_data["commence_time"], m): continue
            
            m_type = str(m.get('sportsMarketType', '')).lower()
            
            try:
                raw_outcomes = json.loads(m.get('outcomes', '[]')) if isinstance(m.get('outcomes'), str) else m.get('outcomes', [])
                raw_tokens = json.loads(m.get('clobTokenIds', '[]')) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
            except: continue

            # --- Attribute 1 & 4: Full Game Moneyline & 1st Half Moneyline ---
            if m_type in ['moneyline', 'first_half_moneyline']:
                fiat_target = "moneyline" if m_type == 'moneyline' else "1h_moneyline"
                display_name = "Moneyline" if m_type == 'moneyline' else "1H Moneyline"
                
                for idx, t_name in enumerate(raw_outcomes):
                    p_nick = clean(t_name)
                    fiat_odds = x_data[fiat_target].get(p_nick)
                    
                    if fiat_odds:
                        poly_ask = get_clob_best_ask(raw_tokens[idx])
                        if poly_ask:
                            game_output.append(f"   [{display_name}] {t_name:<15} | Pin: {float(fiat_odds):<5} | Poly: {round(float(poly_ask)*100, 1)}%")
                            
                            opp_nick = home_nick if p_nick == away_nick else away_nick
                            fiat_opp_odds = x_data[fiat_target].get(opp_nick)
                            if fiat_opp_odds:
                                arb_sum = poly_ask + (Decimal("1") / fiat_opp_odds)
                                if arb_sum < 1:
                                    roi = round(float((1/arb_sum - 1) * 100), 2)
                                    arbitrage_opportunities.append({
                                        "roi": roi,
                                        "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {x_data['commence_time'][:10]}\nPATH: {display_name} | Bet on {opp_nick} @ {float(fiat_opp_odds)} vs Buy YES on {t_name} @ {float(poly_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                                    })

            # --- Attribute 2: Total Points ---
            elif m_type in ['total', 'totals']:
                try: poly_line = round(float(m.get("line", 0.0)), 1)
                except: continue
                
                if poly_line in x_data["totals"]:
                    normalized = [str(o).lower().strip() for o in raw_outcomes]
                    try:
                        over_idx, under_idx = normalized.index("over"), normalized.index("under")
                    except: continue

                    p_over_ask = get_clob_best_ask(raw_tokens[over_idx])
                    p_under_ask = get_clob_best_ask(raw_tokens[under_idx])
                    
                    xb_under = x_data["totals"][poly_line].get('under')
                    xb_over = x_data["totals"][poly_line].get('over')

                    if p_over_ask and xb_under:
                        game_output.append(f"   [Total {poly_line}] Poly O / Pin U | Pin: {float(xb_under):<5} | Poly: {round(float(p_over_ask)*100, 1)}%")
                        arb_sum = p_over_ask + (Decimal("1") / xb_under)
                        if arb_sum < 1:
                            roi = round(float((1/arb_sum - 1) * 100), 2)
                            arbitrage_opportunities.append({
                                "roi": roi,
                                "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {x_data['commence_time'][:10]}\nPATH: Total {poly_line} | Bet UNDER @ {float(xb_under)} vs Buy OVER @ {float(p_over_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            })

                    if p_under_ask and xb_over:
                        game_output.append(f"   [Total {poly_line}] Poly U / Pin O | Pin: {float(xb_over):<5} | Poly: {round(float(p_under_ask)*100, 1)}%")
                        arb_sum = p_under_ask + (Decimal("1") / xb_over)
                        if arb_sum < 1:
                            roi = round(float((1/arb_sum - 1) * 100), 2)
                            arbitrage_opportunities.append({
                                "roi": roi,
                                "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {x_data['commence_time'][:10]}\nPATH: Total {poly_line} | Bet OVER @ {float(xb_over)} vs Buy UNDER @ {float(p_under_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            })

            # --- Attribute 3: Point Spreads ---
            elif m_type in ['spread', 'spreads']:
                # Logic maps "Team A -1.5" to "Team B +1.5" inverted lookup natively
                try: poly_line = round(float(m.get("line", 0.0)), 1)
                except: continue
                # Spread execution logic requires inverse mathematical mapping (Targeting future implementation based on fiat consistency)
                pass

        if game_output:
            print(f"\n🏀 {x_data['home']} vs {x_data['away']} | Date: {x_data['commence_time'][:10]}")
            print("-" * 65)
            for row in game_output:
                print(row)

    # --- TOP 3 SNIPER TELEGRAM MODE ---
    print("\n" + "="*65)
    if not arbitrage_opportunities:
        print("⚖️ Markets efficient. No arbitrage gaps found below 100%.")
    else:
        # Sort by ROI Descending
        arbitrage_opportunities.sort(key=lambda x: x['roi'], reverse=True)
        top_3 = arbitrage_opportunities[:3]
        
        print(f"🔥 Found {len(arbitrage_opportunities)} total arbs. Broadcasting Top {len(top_3)} to Telegram.")
        for op in top_3:
            print(f"-> Sending Alert: ROI {op['roi']}%")
            send_telegram_alert(op['message'])
    print("="*65)

if __name__ == "__main__":
    run_scan()
