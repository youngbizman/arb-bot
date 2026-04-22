import logging
import json
from datetime import datetime, timezone
from decimal import Decimal, getcontext

from .api_clients import ApiClients
from .config import ConfigError, load_settings
from .models import ArbitrageOpportunity

logger = logging.getLogger(__name__)
getcontext().prec = 28

# --- HELPER FUNCTIONS FROM OUR ORIGINAL MATH ---
def clean(text: str) -> str:
    if not text: return ""
    return str(text).lower().replace("trail blazers", "blazers").split()[-1]

def parse_iso8601_to_epoch(time_str):
    if not time_str: return 0
    t = str(time_str).replace(" ", "T")
    if t.endswith("+00"): t += ":00" 
    if t.endswith("Z"): t = t.replace("Z", "+00:00")
    try: return int(datetime.fromisoformat(t).timestamp())
    except ValueError:
        try: return int(datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError: return 0

def is_target_single_game(fiat_commence_time, poly_start, poly_end):
    t_commence = parse_iso8601_to_epoch(fiat_commence_time)
    t_game = parse_iso8601_to_epoch(poly_start)
    t_end = parse_iso8601_to_epoch(poly_end)
    if t_commence == 0: return False
    if t_game > 0 and abs(t_game - t_commence) > 14400: return False
    if t_end > 0 and abs(t_end - t_commence) > (48 * 3600): return False
    return True

# --- MAIN ORCHESTRATOR ---
def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error(f"Configuration error: {exc}")
        return

    clients = ApiClients(settings)
    
    try:
        logger.info("📡 Initializing High-Density Multi-Market Sniper...")
        
        # 1. Fetch Raw Data using your new robust clients
        raw_odds_data = clients.get_fiat_data()
        raw_poly_events = clients.get_polymarket_events()
        
        # Format the fiat data safely
        fiat_games = {}
        for game in raw_odds_data:
            h, a = game.get('home_team'), game.get('away_team')
            if not h or not a: continue
            commence_time = game.get('commence_time', '')
            game_data = {"home": h, "away": a, "commence_time": commence_time, "moneyline": {}, "totals": {}, "spreads": {}, "1h_moneyline": {}, "team_totals": {clean(h): {}, clean(a): {}}}
            
            if game.get("bookmakers"):
                b = game["bookmakers"][0] 
                bookie_name = b.get("title", "Pinnacle")
                game_data['bookmaker'] = bookie_name
                for m in b.get("markets", []):
                    key = m.get('key')
                    for o in m.get('outcomes', []):
                        name_clean = clean(o.get('name'))
                        if o.get('price') is None: continue
                        price = Decimal(str(o.get('price')))
                        point = round(float(o.get('point')), 1) if o.get('point') is not None else None
                        
                        if key == 'h2h': game_data["moneyline"][name_clean] = price
                        elif key == 'h2h_h1': game_data["1h_moneyline"][name_clean] = price
                        elif key == 'totals' and point is not None:
                            if point not in game_data["totals"]: game_data["totals"][point] = {}
                            game_data["totals"][point][name_clean] = price
                        elif key == 'spreads' and point is not None:
                            if point not in game_data["spreads"]: game_data["spreads"][point] = {}
                            game_data["spreads"][point][name_clean] = price
                        elif key == 'team_totals' and point is not None:
                            team_desc = clean(o.get('description'))
                            if team_desc in game_data["team_totals"]:
                                if point not in game_data["team_totals"][team_desc]: game_data["team_totals"][team_desc][point] = {}
                                game_data["team_totals"][team_desc][point][name_clean] = price
                fiat_games[f"{clean(h)}_{clean(a)}"] = game_data

        opportunities = []

        # 2. Iterate and Match (Protecting the API rate limit)
        for game_key, x_data in fiat_games.items():
            home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
            fiat_time = x_data["commence_time"]
            
            target_event = None
            for e in raw_poly_events:
                title = str(e.get('title', '')).lower()
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
                
                try:
                    outcomes_val, tokens_val = m.get('outcomes'), m.get('clobTokenIds')
                    if not outcomes_val or not tokens_val: continue
                    raw_outcomes = json.loads(outcomes_val) if isinstance(outcomes_val, str) else outcomes_val
                    raw_tokens = json.loads(tokens_val) if isinstance(tokens_val, str) else tokens_val
                except (json.JSONDecodeError, TypeError): continue

                if not isinstance(raw_outcomes, list) or not isinstance(raw_tokens, list): continue
                if len(raw_outcomes) != len(raw_tokens) or len(raw_outcomes) == 0: continue

                # Attribute 1 & 4: Moneylines
                if m_type in ['moneyline', 'first_half_moneyline']:
                    fiat_target = "moneyline" if m_type == 'moneyline' else "1h_moneyline"
                    display = "Moneyline" if m_type == 'moneyline' else "1H Moneyline"
                    for idx, t_name in enumerate(raw_outcomes):
                        p_nick = clean(t_name)
                        fiat_odds = x_data[fiat_target].get(p_nick)
                        if fiat_odds:
                            # ONLY FETCH CLOB IF THERE IS A FIAT MATCH
                            poly_ask = clients.get_clob_best_ask(raw_tokens[idx])
                            if poly_ask:
                                game_output.append(f"   [{display}] {t_name:<15} | Pin: {float(fiat_odds):<5} | Poly: {round(float(poly_ask)*100, 1)}%")
                                opp_nick = home_nick if p_nick == away_nick else away_nick
                                fiat_opp_odds = x_data[fiat_target].get(opp_nick)
                                if fiat_opp_odds:
                                    arb_sum = poly_ask + (Decimal("1") / fiat_opp_odds)
                                    if arb_sum < 1:
                                        opportunities.append(_build_opp(x_data, fiat_opp_odds, poly_ask, arb_sum, display, t_name, opp_nick))

                # Extract line for Totals/Spreads
                raw_line = m.get("line")
                if raw_line is None: continue
                try: poly_line = round(float(raw_line), 1)
                except ValueError: continue

                # Attribute 2: Totals
                if m_type in ['total', 'totals'] and poly_line in x_data["totals"]:
                    norm = [str(o).lower().strip() for o in raw_outcomes]
                    if "over" in norm and "under" in norm:
                        o_idx, u_idx = norm.index("over"), norm.index("under")
                        xb_under, xb_over = x_data["totals"][poly_line].get('under'), x_data["totals"][poly_line].get('over')
                        
                        if xb_under:
                            p_over_ask = clients.get_clob_best_ask(raw_tokens[o_idx])
                            if p_over_ask:
                                game_output.append(f"   [Total {poly_line}] Poly O / Pin U | Pin: {float(xb_under):<5} | Poly: {round(float(p_over_ask)*100, 1)}%")
                                arb_sum = p_over_ask + (Decimal("1") / xb_under)
                                if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_under, p_over_ask, arb_sum, f"Total {poly_line}", "OVER", "UNDER"))
                        
                        if xb_over:
                            p_under_ask = clients.get_clob_best_ask(raw_tokens[u_idx])
                            if p_under_ask:
                                game_output.append(f"   [Total {poly_line}] Poly U / Pin O | Pin: {float(xb_over):<5} | Poly: {round(float(p_under_ask)*100, 1)}%")
                                arb_sum = p_under_ask + (Decimal("1") / xb_over)
                                if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_over, p_under_ask, arb_sum, f"Total {poly_line}", "UNDER", "OVER"))

                # Attribute 3: Spreads (Inverse logic restored!)
                elif m_type in ['spread', 'spreads']:
                    inv_fiat = -poly_line 
                    if inv_fiat in x_data["spreads"]:
                        for idx, t_name in enumerate(raw_outcomes):
                            p_nick = clean(t_name)
                            opp_nick = home_nick if p_nick == away_nick else away_nick
                            fiat_opp_odds = x_data["spreads"][inv_fiat].get(opp_nick)
                            if fiat_opp_odds:
                                poly_ask = clients.get_clob_best_ask(raw_tokens[idx])
                                if poly_ask:
                                    game_output.append(f"   [Spread {poly_line}] Poly {p_nick} / Pin {opp_nick} | Pin: {float(fiat_opp_odds):<5} | Poly: {round(float(poly_ask)*100, 1)}%")
                                    arb_sum = poly_ask + (Decimal("1") / fiat_opp_odds)
                                    if arb_sum < 1: opportunities.append(_build_opp(x_data, fiat_opp_odds, poly_ask, arb_sum, f"Spread {poly_line}", p_nick, f"{opp_nick} ({inv_fiat})"))

                # Attribute 5: Team Totals
                elif m_type == 'team_totals':
                    market_title = str(m.get('question', '')).lower()
                    target_team = home_nick if home_nick in market_title else (away_nick if away_nick in market_title else None)
                    if target_team and poly_line in x_data["team_totals"].get(target_team, {}):
                        norm = [str(o).lower().strip() for o in raw_outcomes]
                        if "over" in norm and "under" in norm:
                            o_idx, u_idx = norm.index("over"), norm.index("under")
                            xb_under, xb_over = x_data["team_totals"][target_team][poly_line].get('under'), x_data["team_totals"][target_team][poly_line].get('over')

                            if xb_under:
                                p_over_ask = clients.get_clob_best_ask(raw_tokens[o_idx])
                                if p_over_ask:
                                    game_output.append(f"   [{target_team.title()} Total {poly_line}] Poly O / Pin U | Pin: {float(xb_under):<5} | Poly: {round(float(p_over_ask)*100, 1)}%")
                                    arb_sum = p_over_ask + (Decimal("1") / xb_under)
                                    if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_under, p_over_ask, arb_sum, f"{target_team.title()} Total {poly_line}", "OVER", "UNDER"))
                            
                            if xb_over:
                                p_under_ask = clients.get_clob_best_ask(raw_tokens[u_idx])
                                if p_under_ask:
                                    game_output.append(f"   [{target_team.title()} Total {poly_line}] Poly U / Pin O | Pin: {float(xb_over):<5} | Poly: {round(float(p_under_ask)*100, 1)}%")
                                    arb_sum = p_under_ask + (Decimal("1") / xb_over)
                                    if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_over, p_under_ask, arb_sum, f"{target_team.title()} Total {poly_line}", "UNDER", "OVER"))

            if game_output:
                logger.info(f"\n🏀 {x_data['home']} vs {x_data['away']} | Date: {fiat_time[:10]}")
                logger.info("-" * 80)
                for row in game_output:
                    logger.info(row)

        # 3. Top 3 Telegram Sniper using your alerts.py!
        logger.info("\n" + "="*80)
        if not opportunities:
            logger.info("⚖️ Markets efficient. No arbitrage gaps found below 100%.")
        else:
            # Sort, deduplicate, and limit to 3
            unique_arbs = {arb.expected_profit_percent: arb for arb in opportunities}.values()
            sorted_arbs = sorted(unique_arbs, key=lambda x: x.expected_profit_percent, reverse=True)[:3]
            
            logger.info(f"🔥 Found opportunities! Broadcasting Top {len(sorted_arbs)} to Telegram.")
            
            # Use your beautiful alerts class to format the string
            from .alerts import format_opportunity_alert
            for op in sorted_arbs:
                msg = format_opportunity_alert(op)
                logger.info(f"-> Sending Alert: ROI {op.expected_profit_percent}%")
                clients.send_telegram_alert(msg)
        logger.info("="*80)

    finally:
        clients.close()

def _build_opp(x_data, fiat_odds, poly_price, arb_sum, m_title, poly_side, fiat_side):
    """Helper to cleanly build the ArbitrageOpportunity object for alerts.py"""
    roi = round(float((1/arb_sum - 1) * 100), 2)
    edge = round(float((Decimal("1") - arb_sum) * 100), 2)
    return ArbitrageOpportunity(
        sport_key="basketball_nba",
        home_team=x_data['home'], away_team=x_data['away'], commence_time=x_data['commence_time'],
        market_title=m_title, selection_name=poly_side, bookmaker=x_data.get('bookmaker', 'Pinnacle'),
        odds_decimal=float(fiat_odds), poly_price=float(poly_price),
        implied_total=float(arb_sum), edge_percent=edge, expected_profit_percent=roi
    )
