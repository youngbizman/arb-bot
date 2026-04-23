import logging
import json
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from zoneinfo import ZoneInfo  # Python 3.9+ standard for timezone handling

from .api_clients import ApiClients
from .config import ConfigError, load_settings
from .models import ArbitrageOpportunity

logger = logging.getLogger(__name__)
getcontext().prec = 28

# --- HELPERS ---
def clean(text: str) -> str:
    if not text: return ""
    return str(text).lower().replace("trail blazers", "blazers").split()[-1]

def format_to_local(iso_str: str) -> str:
    """Converts UTC ISO string to Toronto (Eastern) Time string."""
    try:
        # Handle trailing Z or +00:00
        clean_iso = iso_str.replace("Z", "+00:00")
        utc_dt = datetime.fromisoformat(clean_iso)
        local_dt = utc_dt.astimezone(ZoneInfo("America/Toronto"))
        return local_dt.strftime("%Y-%m-%d %I:%M %p")
    except:
        return iso_str[:10]  # Fallback to raw date if parsing fails

def parse_iso8601_to_epoch(time_str):
    if not time_str: return 0
    t = str(time_str).replace(" ", "T")
    if t.endswith("+00"): t += ":00" 
    if t.endswith("Z"): t = t.replace("Z", "+00:00")
    try: return int(datetime.fromisoformat(t).timestamp())
    except: return 0

def is_target_single_game(fiat_time, poly_start, poly_end):
    """Temporal Bounding Box: Ensures we match a single game, not a series."""
    t_f = parse_iso8601_to_epoch(fiat_time)
    t_s = parse_iso8601_to_epoch(poly_start)
    t_e = parse_iso8601_to_epoch(poly_end)
    if t_f == 0: return False
    
    # Tip-off Alignment (within 4 hours)
    if t_s > 0 and abs(t_s - t_f) > 14400: return False
    
    # Oracle Integrity Filter (EndDate within 48 hours of tip-off)
    if t_e > 0 and (t_e - t_f) > 172800: return False
    return True

# --- MAIN RUNNER ---
def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error(f"Config error: {exc}")
        return
        
    clients = ApiClients(settings)
    
    try:
        logger.info("📡 Initializing High-Density Multi-Market Sniper...")
        raw_odds = clients.get_fiat_data()
        raw_poly = clients.get_polymarket_events()
        
        fiat_games = {}
        for game in raw_odds:
            h, a = game.get('home_team'), game.get('away_team')
            if not h or not a: continue
            k = f"{clean(h)}_{clean(a)}"
            if k not in fiat_games:
                fiat_games[k] = {"home": h, "away": a, "time": game.get('commence_time'), "bookies": []}
            
            for b in game.get("bookmakers", []):
                b_data = {"name": b.get("title"), "h2h": {}, "totals": {}, "spreads": {}}
                for m in b.get("markets", []):
                    mk = m.get('key')
                    for o in m.get('outcomes', []):
                        nm = clean(o.get('name'))
                        if o.get('price') is None: continue
                        pr = Decimal(str(o.get('price')))
                        pt = round(float(o.get('point', 0)), 1)
                        if mk == 'h2h': b_data["h2h"][nm] = pr
                        elif mk == 'totals':
                            if pt not in b_data["totals"]: b_data["totals"][pt] = {}
                            b_data["totals"][pt][nm.lower()] = pr
                        elif mk == 'spreads':
                            if pt not in b_data["spreads"]: b_data["spreads"][pt] = {}
                            b_data["spreads"][pt][nm] = pr
                fiat_games[k]["bookies"].append(b_data)

        opportunities = []
        for gk, x in fiat_games.items():
            h_nk, a_nk = clean(x["home"]), clean(x["away"])
            target = next((e for e in raw_poly if h_nk in e.get('title','').lower() and a_nk in e.get('title','').lower()), None)
            
            if not target or not is_target_single_game(x["time"], target.get("gameStartTime"), target.get("endDate")):
                continue
            
            local_time_str = format_to_local(x['time'])
            logger.info(f"\n🏀 MATCHED: {x['home']} vs {x['away']} | Local Time: {local_time_str}")
            logger.info("-" * 80)
            
            for b in x["bookies"]:
                for m in target.get('markets', []):
                    if not m.get('acceptingOrders'): continue
                    mt = str(m.get('sportsMarketType', '')).lower()
                    try:
                        out_v, tok_v = m.get('outcomes'), m.get('clobTokenIds')
                        outs = json.loads(out_v) if isinstance(out_v, str) else out_v
                        toks = json.loads(tok_v) if isinstance(tok_v, str) else tok_v
                    except: continue
                    if not outs or len(outs) != len(toks): continue

                    # --- Attribute 1: Moneyline ---
                    if mt == 'moneyline':
                        for idx, t_nm in enumerate(outs):
                            p_nk = clean(t_nm)
                            f_odds = b["h2h"].get(p_nk)
                            if f_odds:
                                p_ask = clients.get_clob_best_ask(toks[idx])
                                if p_ask:
                                    logger.info(f"   [ML] {b['name']:<12} | {t_nm[:10]:<10} | {b['name']}: {float(f_odds):<5} vs Poly {round(float(p_ask)*100,1)}%")
                                    opp_nk = h_nk if p_nk == a_nk else a_nk
                                    f_opp = b["h2h"].get(opp_nk)
                                    if f_opp:
                                        sm = p_ask + (Decimal("1") / f_opp)
                                        if sm < 1: opportunities.append(_build_opp(x, b["name"], f_opp, p_ask, sm, "ML", t_nm, opp_nk))

                    # --- Attribute 2: Totals ---
                    elif mt in ['total', 'totals']:
                        try: lne = round(float(m.get("line", 0)), 1)
                        except: continue
                        if lne in b["totals"]:
                            norm = [str(o).lower() for o in outs]
                            if "over" in norm and "under" in norm:
                                o_idx, u_idx = norm.index("over"), norm.index("under")
                                p_ov, p_un = clients.get_clob_best_ask(toks[o_idx]), clients.get_clob_best_ask(toks[u_idx])
                                f_un, f_ov = b["totals"][lne].get('under'), b["totals"][lne].get('over')
                                
                                if p_ov and f_un:
                                    logger.info(f"   [Total {lne}] {b['name']:<12} | OVER vs UNDER | {b['name']}: {float(f_un):<5} vs Poly: {round(float(p_ov)*100,1)}%")
                                    sm = p_ov + (Decimal("1") / f_un)
                                    if sm < 1: opportunities.append(_build_opp(x, b["name"], f_un, p_ov, sm, f"Total {lne}", "OVER", "UNDER"))
                                if p_un and f_ov:
                                    logger.info(f"   [Total {lne}] {b['name']:<12} | UNDER vs OVER | {b['name']}: {float(f_ov):<5} vs Poly: {round(float(p_un)*100,1)}%")
                                    sm = p_un + (Decimal("1") / f_ov)
                                    if sm < 1: opportunities.append(_build_opp(x, b["name"], f_ov, p_un, sm, f"Total {lne}", "UNDER", "OVER"))

                    # --- Attribute 3: Spreads ---
                    elif mt in ['spread', 'spreads']:
                        try: lne = round(float(m.get("line", 0)), 1)
                        except: continue
                        inv = -lne
                        if inv in b["spreads"]:
                            for idx, t_nm in enumerate(outs):
                                p_nk = clean(t_nm)
                                opp_nk = h_nk if p_nk == a_nk else a_nk
                                f_opp = b["spreads"][inv].get(opp_nk)
                                if f_opp:
                                    p_ask = clients.get_clob_best_ask(toks[idx])
                                    if p_ask:
                                        logger.info(f"   [Spread {lne}] {b['name']:<12} | {t_nm[:10]} vs {opp_nk[:10]} | {b['name']}: {float(f_opp):<5} vs Poly {round(float(p_ask)*100,1)}%")
                                        sm = p_ask + (Decimal("1") / f_opp)
                                        if sm < 1: opportunities.append(_build_opp(x, b["name"], f_opp, p_ask, sm, f"Spread {lne}", t_nm, f"{opp_nk} ({inv})"))

        # --- FINAL SUMMARY ---
        logger.info("\n" + "="*80)
        if opportunities:
            unq = {o.expected_profit_percent: o for o in opportunities}.values()
            best = sorted(unq, key=lambda i: i.expected_profit_percent, reverse=True)[:3]
            from .alerts import format_opportunity_alert
            for op in best: 
                clients.send_telegram_alert(format_opportunity_alert(op))
            
            logger.info(f"✅ SCAN COMPLETE: Found {len(opportunities)} total opportunities.")
            logger.info(f"🔥 Sent the top {len(best)} most profitable alerts to Telegram.")
        else:
            logger.info("⚖️ SCAN COMPLETE: All bookmakers are currently efficient.")
            logger.info("❌ No arbitrage gaps found above 0.00% ROI in this cycle.")
        logger.info("="*80)
        
    finally:
        clients.close()

def _build_opp(x, b_nm, f_o, p_p, sm, m_tl, p_sd, f_sd):
    roi = round(float((1/sm - 1) * 100), 2)
    local_date = format_to_local(x['time'])
    return ArbitrageOpportunity(
        sport_key="nba", home_team=x['home'], away_team=x['away'], commence_time=local_date,
        market_title=m_tl, selection_name=p_sd, 
        fiat_selection=f_sd,  # <--- Now mapping this name correctly
        bookmaker=b_nm, odds_decimal=float(f_o),
        poly_price=float(p_p), implied_total=float(sm), edge_percent=0.0, expected_profit_percent=roi
    )
