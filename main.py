import os
import requests
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, getcontext

# Set precision and configure strict logging
getcontext().prec = 28
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Secure keys
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Create a persistent session for faster API calls
session = requests.Session()

def clean(text):
    """Normalize team names safely."""
    if not text: return ""
    return text.lower().replace("trail blazers", "blazers").split()[-1]

def parse_iso8601_to_epoch(time_str):
    if not time_str: return 0
    t = time_str.replace(" ", "T")
    if t.endswith("+00"): t += ":00" 
    if t.endswith("Z"): t = t.replace("Z", "+00:00")
    try: return int(datetime.fromisoformat(t).timestamp())
    except ValueError:
        try: return int(datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError: return 0

def is_target_single_game(fiat_commence_time, poly_start, poly_end):
    """Strict temporal bounding box."""
    t_commence = parse_iso8601_to_epoch(fiat_commence_time)
    t_game = parse_iso8601_to_epoch(poly_start)
    t_end = parse_iso8601_to_epoch(poly_end)

    if t_commence == 0: return False
    if t_game > 0 and abs(t_game - t_commence) > 14400: return False
    if t_end > 0 and abs(t_end - t_commence) > (48 * 3600): return False
    return True

def get_clob_best_ask(token_id):
    if not token_id: return None
    try:
        res = session.get("https://clob.polymarket.com/book", params={"token_id": token_id}, timeout=5)
        res.raise_for_status()
        book = res.json()
        asks = book.get("asks", [])
        prices = [Decimal(str(ask["price"])) for ask in asks if "price" in ask]
        return min(prices) if prices else None
    except requests.RequestException: return None
    except ValueError: return None

def get_fiat_data():
    """Ingests Source A (Pinnacle) expanding to all 5 core markets."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY, 
        "regions": "eu,us", 
        # Added team_totals to complete the Rule of 5
        "markets": "h2h,totals,spreads,h2h_h1,team_totals", 
        "bookmakers": "pinnacle"
    }
    try:
        res = session.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        games = {}
        if not isinstance(data, list): return {}
        
        for game in data:
            h, a = game.get('home_team', ''), game.get('away_team', '')
            commence_time = game.get('commence_time', '')
            game_data = {
                "home": h, "away": a, "commence_time": commence_time, 
                "moneyline": {}, "totals": {}, "spreads": {}, "1h_moneyline": {}, "team_totals": {clean(h): {}, clean(a): {}}
            }
            
            if game.get("bookmakers"):
                b = game["bookmakers"][0] 
                for m in b.get("markets", []):
                    key = m.get('key')
                    outcomes = m.get('outcomes', [])
                    
                    for o in outcomes:
                        name_clean = clean(o.get('name', ''))
                        price = Decimal(str(o.get('price', 0)))
                        point = round(float(o.get('point', 0)), 1) if 'point' in o else None
                        
                        if key == 'h2h':
                            game_data["moneyline"][name_clean] = price
                        elif key == 'h2h_h1':
                            game_data["1h_moneyline"][name_clean] = price
                        elif key == 'totals' and point is not None:
                            if point not in game_data["totals"]: game_data["totals"][point] = {}
                            game_data["totals"][point][name_clean] = price
                        elif key == 'spreads' and point is not None:
                            if point not in game_data["spreads"]: game_data["spreads"][point] = {}
                            game_data["spreads"][point][name_clean] = price
                        elif key == 'team_totals' and point is not None:
                            # Odds API usually puts the team name in 'description' for team totals
                            team_desc = clean(o.get('description', ''))
                            if team_desc in game_data["team_totals"]:
                                if point not in game_data["team_totals"][team_desc]:
                                    game_data["team_totals"][team_desc][point] = {}
                                game_data["team_totals"][team_desc][point][name_clean] = price

                games[f"{clean(h)}_{clean(a)}"] = game_data
        return games
    except requests.RequestException as e:
        logging.error(f"Fiat API Error: {e}")
        return {}

def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except requests.RequestException: pass

def run_scan():
    logging.info("📡 Initializing High-Density Multi-Market Sniper...")
    fiat_games = get_fiat_data()
    
    try:
        res = session.get("https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100", timeout=10)
        res.raise_for_status()
        poly_data = res.json()
        poly_events = poly_data if isinstance(poly_data, list) else poly_data.get('events', [])
    except requests.RequestException as e:
        logging.error(f"Polymarket API Error: {e}")
        poly_events = []
    
    arbitrage_opportunities = []
    
    for game_key, x_data in fiat_games.items():
        home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
        fiat_time = x_data["commence_time"]
        
        # STRICTER EVENT MATCHING
        target_event = None
        for e in poly_events:
            title = e.get('title', '').lower()
            if home_nick in title and away_nick in title:
                p_start = e.get("gameStartTime") or e.get("eventStartTime")
                p_end = e.get("endDate")
                if is_target_single_game(fiat_time, p_start, p_end):
                    target_event = e
                    break
                    
        if not target_event: continue
        
        game_output = []
        
        for m in target_event.get('markets', []):
            if not m.get('acceptingOrders'): continue
            
            m_type = str(m.get('sportsMarketType', '')).lower()
            
            # SAFE JSON PARSING
            try:
                raw_outcomes = json.loads(m.get('outcomes', '[]')) if isinstance(m.get('outcomes'), str) else m.get('outcomes', [])
                raw_tokens = json.loads(m.get('clobTokenIds', '[]')) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds', [])
            except json.JSONDecodeError: continue

            # LENGTH VALIDATION TO PREVENT INDEX ERRORS
            if not raw_outcomes or len(raw_outcomes) != len(raw_tokens): continue

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
                                        "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {fiat_time[:10]}\nPATH: {display_name} | Bet on {opp_nick} @ {float(fiat_opp_odds)} vs Buy YES on {t_name} @ {float(poly_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                                    })

            # --- Attribute 2: Total Points ---
            elif m_type in ['total', 'totals']:
                try: poly_line = round(float(m.get("line", 0.0)), 1)
                except ValueError: continue
                
                if poly_line in x_data["totals"]:
                    normalized = [str(o).lower().strip() for o in raw_outcomes]
                    if "over" in normalized and "under" in normalized:
                        over_idx, under_idx = normalized.index("over"), normalized.index("under")
                        p_over_ask = get_clob_best_ask(raw_tokens[over_idx])
                        p_under_ask = get_clob_best_ask(raw_tokens[under_idx])
                        xb_under, xb_over = x_data["totals"][poly_line].get('under'), x_data["totals"][poly_line].get('over')

                        # Unconditional logging
                        if p_over_ask and xb_under:
                            game_output.append(f"   [Total {poly_line}] Poly O / Pin U | Pin: {float(xb_under):<5} | Poly: {round(float(p_over_ask)*100, 1)}%")
                            arb_sum = p_over_ask + (Decimal("1") / xb_under)
                            if arb_sum < 1:
                                roi = round(float((1/arb_sum - 1) * 100), 2)
                                arbitrage_opportunities.append({"roi": roi, "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {fiat_time[:10]}\nPATH: Total {poly_line} | Bet UNDER @ {float(xb_under)} vs Buy OVER @ {float(p_over_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"})
                        
                        if p_under_ask and xb_over:
                            game_output.append(f"   [Total {poly_line}] Poly U / Pin O | Pin: {float(xb_over):<5} | Poly: {round(float(p_under_ask)*100, 1)}%")
                            arb_sum = p_under_ask + (Decimal("1") / xb_over)
                            if arb_sum < 1:
                                roi = round(float((1/arb_sum - 1) * 100), 2)
                                arbitrage_opportunities.append({"roi": roi, "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {fiat_time[:10]}\nPATH: Total {poly_line} | Bet OVER @ {float(xb_over)} vs Buy UNDER @ {float(p_under_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"})

            # --- Attribute 3: Point Spreads (Inverse Logic Implemented) ---
            elif m_type in ['spread', 'spreads']:
                try: poly_line = round(float(m.get("line", 0.0)), 1)
                except ValueError: continue
                
                # If Poly line is Team A -1.5, we must check Fiat for Team B +1.5. 
                inverse_fiat_line = -poly_line 
                
                if inverse_fiat_line in x_data["spreads"]:
                    for idx, t_name in enumerate(raw_outcomes):
                        p_nick = clean(t_name)
                        opp_nick = home_nick if p_nick == away_nick else away_nick
                        
                        fiat_opp_odds = x_data["spreads"][inverse_fiat_line].get(opp_nick)
                        if fiat_opp_odds:
                            poly_ask = get_clob_best_ask(raw_tokens[idx])
                            if poly_ask:
                                game_output.append(f"   [Spread {poly_line}] Poly {p_nick} / Pin {opp_nick} | Pin: {float(fiat_opp_odds):<5} | Poly: {round(float(poly_ask)*100, 1)}%")
                                arb_sum = poly_ask + (Decimal("1") / fiat_opp_odds)
                                if arb_sum < 1:
                                    roi = round(float((1/arb_sum - 1) * 100), 2)
                                    arbitrage_opportunities.append({"roi": roi, "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {fiat_time[:10]}\nPATH: Spread | Bet {opp_nick} ({inverse_fiat_line}) @ {float(fiat_opp_odds)} vs Buy {p_nick} ({poly_line}) YES @ {float(poly_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"})

            # --- Attribute 5: Team Totals ---
            elif m_type == 'team_totals':
                try: poly_line = round(float(m.get("line", 0.0)), 1)
                except ValueError: continue
                
                # Determine which team this total belongs to by parsing the market title
                market_title = str(m.get('question', '')).lower()
                target_team = home_nick if home_nick in market_title else (away_nick if away_nick in market_title else None)
                
                if target_team and poly_line in x_data["team_totals"].get(target_team, {}):
                    normalized = [str(o).lower().strip() for o in raw_outcomes]
                    if "over" in normalized and "under" in normalized:
                        over_idx, under_idx = normalized.index("over"), normalized.index("under")
                        p_over_ask = get_clob_best_ask(raw_tokens[over_idx])
                        p_under_ask = get_clob_best_ask(raw_tokens[under_idx])
                        
                        xb_under = x_data["team_totals"][target_team][poly_line].get('under')
                        xb_over = x_data["team_totals"][target_team][poly_line].get('over')

                        if p_over_ask and xb_under:
                            game_output.append(f"   [{target_team.title()} Total {poly_line}] Poly O / Pin U | Pin: {float(xb_under):<5} | Poly: {round(float(p_over_ask)*100, 1)}%")
                            arb_sum = p_over_ask + (Decimal("1") / xb_under)
                            if arb_sum < 1:
                                roi = round(float((1/arb_sum - 1) * 100), 2)
                                arbitrage_opportunities.append({"roi": roi, "message": f"MATCHUP: {x_data['home']} vs {x_data['away']}\nDATE: {fiat_time[:10]}\nPATH: {target_team.title()} Total {poly_line} | Bet UNDER @ {float(xb_under)} vs Buy OVER @ {float(p_over_ask)}\nROI: {roi}%\nCALC TIME: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"})

        if game_output:
            logging.info(f"\n🏀 {x_data['home']} vs {x_data['away']} | Date: {fiat_time[:10]}")
            logging.info("-" * 80)
            for row in game_output:
                logging.info(row)

    # --- TOP 3 SNIPER TELEGRAM MODE ---
    logging.info("\n" + "="*80)
    if not arbitrage_opportunities:
        logging.info("⚖️ Markets efficient. No arbitrage gaps found below 100%.")
    else:
        # Deduplicate and Sort
        unique_arbs = {arb['message']: arb for arb in arbitrage_opportunities}.values()
        sorted_arbs = sorted(unique_arbs, key=lambda x: x['roi'], reverse=True)
        top_3 = sorted_arbs[:3]
        
        logging.info(f"🔥 Found {len(sorted_arbs)} unique arbs. Broadcasting Top {len(top_3)} to Telegram.")
        for op in top_3:
            logging.info(f"-> Sending Alert: ROI {op['roi']}%")
            send_telegram_alert(op['message'])
    logging.info("="*80)

if __name__ == "__main__":
    run_scan()
