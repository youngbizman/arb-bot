import logging
import json
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from zoneinfo import ZoneInfo

from .api_clients import ApiClients
from .config import ConfigError, load_settings
from .models import ArbitrageOpportunity, FiatArbitrageOpportunity
from .alerts import build_global_alerts

logger = logging.getLogger(__name__)
getcontext().prec = 28

# --- LIQUIDITY MATH CLASSES ---
@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal

@dataclass
class HedgeEstimate:
    best_ask: Optional[Decimal]
    shares: Decimal
    sportsbook_stake: Decimal
    poly_spend: Decimal
    poly_fees: Decimal
    total_outlay: Decimal
    vwap: Optional[Decimal]
    marginal_price: Optional[Decimal]
    locked_profit: Decimal
    passes_liquidity_filter: bool
    reject_reason: Optional[str]

def normalize_asks(asks: Iterable[Mapping[str, str]]) -> list[BookLevel]:
    levels: list[BookLevel] = []
    for row in asks:
        try:
            price, size = Decimal(str(row.get("price", "0"))), Decimal(str(row.get("size", "0")))
            if size > 0: levels.append(BookLevel(price=price, size=size))
        except: pass
    return sorted(levels, key=lambda lvl: lvl.price)

def fee_per_share(price: Decimal, fee_rate: Decimal) -> Decimal:
    return fee_rate * price * (Decimal("1") - price)

def evaluate_buy_hedge_from_asks(
    asks: Iterable[Mapping[str, str]], decimal_odds: Decimal, bankroll: str = "100", fee_rate: str = "0.03", max_avg_impact_rel: str = "0.02"
) -> HedgeEstimate:
    """Calculates real-world VWAP profitability, accounting for depth and 3% sports fees."""
    levels = normalize_asks(asks)
    odds, bankroll_d, fee_r = Decimal(str(decimal_odds)), Decimal(bankroll), Decimal(fee_rate)
    inv_odds = Decimal("1") / odds
    eps = Decimal("0.0000000001")

    if not levels:
        return HedgeEstimate(None, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), None, None, Decimal("0"), False, "Empty Orderbook")

    best = levels[0]
    q = Decimal("0")
    cost, fees = Decimal("0"), Decimal("0")
    marginal = None
    full_bankroll_supported = False

    for lvl in levels:
        lvl_fee_ps = fee_per_share(lvl.price, fee_r)
        lvl_all_in_per_share = lvl.price + lvl_fee_ps + inv_odds
        
        if lvl_all_in_per_share >= Decimal("1"): break
        
        remaining_bankroll = bankroll_d - ((q * inv_odds) + cost + fees)
        if remaining_bankroll <= eps:
            full_bankroll_supported = True
            break
            
        affordable_shares = remaining_bankroll / lvl_all_in_per_share
        take = min(lvl.size, affordable_shares)
        
        if take <= 0: break
        
        q += take
        cost += take * lvl.price
        fees += take * lvl_fee_ps
        marginal = lvl.price
        
        if take < lvl.size:
            full_bankroll_supported = True
            break

    total_outlay = cost + fees + (q * inv_odds)
    if total_outlay >= bankroll_d - eps: full_bankroll_supported = True

    if q <= Decimal("0"):
        return HedgeEstimate(best.price, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), None, None, Decimal("0"), False, "No profitable depth")

    vwap = cost / q
    locked_profit = q - total_outlay
    avg_impact_rel = (vwap / best.price) - Decimal("1")
    reject_reason = None

    if not full_bankroll_supported: reject_reason = "Insufficient depth for $100 bankroll"
    elif avg_impact_rel > Decimal(max_avg_impact_rel): reject_reason = "Slippage exceeds 2% buffer"
    elif locked_profit <= 0: reject_reason = "Negative profit after fees & depth"

    return HedgeEstimate(best.price, q, (q / odds), cost, fees, total_outlay, vwap, marginal, locked_profit, (reject_reason is None), reject_reason)

# --- HELPERS ---
def clean(text: str) -> str:
    if not text: return ""
    return str(text).lower().replace("trail blazers", "blazers").split()[-1]

def format_to_local(iso_str: str) -> str:
    try:
        clean_iso = iso_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_iso).astimezone(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %I:%M %p")
    except: return iso_str[:10]

def parse_iso8601_to_epoch(time_str):
    try: return int(datetime.fromisoformat(str(time_str).replace(" ", "T").replace("Z", "+00:00")).timestamp())
    except: return 0

def is_target_single_game(fiat_time, poly_start, poly_end):
    t_f, t_s, t_e = parse_iso8601_to_epoch(fiat_time), parse_iso8601_to_epoch(poly_start), parse_iso8601_to_epoch(poly_end)
    if t_f == 0: return False
    if t_s > 0 and abs(t_s - t_f) > 14400: return False
    if t_e > 0 and (t_e - t_f) > 172800: return False
    return True

# --- MAIN RUNNER ---
def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try: settings = load_settings()
    except ConfigError as exc:
        logger.error(f"Config error: {exc}"); return
        
    clients = ApiClients(settings)
    
    try:
        logger.info("📡 Initializing VWAP-Aware Multi-Market Sniper...")
        raw_odds, raw_poly = clients.get_fiat_data(), clients.get_polymarket_events()
        
        fiat_games = {}
        for game in raw_odds:
            h, a = game.get('home_team'), game.get('away_team')
            if not h or not a: continue
            k = f"{clean(h)}_{clean(a)}"
            if k not in fiat_games: fiat_games[k] = {"home": h, "away": a, "time": game.get('commence_time'), "bookies": []}
            
            for b in game.get("bookmakers", []):
                b_data = {"name": b.get("title"), "h2h": {}, "totals": {}, "spreads": {}}
                for m in b.get("markets", []):
                    mk = m.get('key')
                    for o in m.get('outcomes', []):
                        nm, pr = clean(o.get('name')), o.get('price')
                        if pr is None: continue
                        pr, pt = Decimal(str(pr)), round(float(o.get('point', 0)), 1)
                        if mk == 'h2h': b_data["h2h"][nm] = pr
                        elif mk == 'totals':
                            if pt not in b_data["totals"]: b_data["totals"][pt] = {}
                            b_data["totals"][pt][nm.lower()] = pr
                        elif mk == 'spreads':
                            if pt not in b_data["spreads"]: b_data["spreads"][pt] = {}
                            b_data["spreads"][pt][nm] = pr
                fiat_games[k]["bookies"].append(b_data)

        opportunities = []
        fiat_opportunities = []

        for gk, x in fiat_games.items():
            h_nk, a_nk = clean(x["home"]), clean(x["away"])
            local_time_str = format_to_local(x['time'])
            
            logger.info(f"\n🏀 MATCHED: {x['home']} vs {x['away']} | Local Time: {local_time_str}")
            logger.info("-" * 80)

            # ==========================================================
            # 1. TRADITIONAL FIAT-TO-FIAT SCANNER (2 by 2)
            # ==========================================================
            for i in range(len(x["bookies"])):
                for j in range(i + 1, len(x["bookies"])):
                    b1, b2 = x["bookies"][i], x["bookies"][j]
                    
                    # --- Attribute 1: Moneyline ---
                    for t_nm, odds1 in b1["h2h"].items():
                        opp_nk = h_nk if t_nm == a_nk else a_nk
                        odds2 = b2["h2h"].get(opp_nk)
                        if odds1 and odds2:
                            imp = (Decimal("1") / odds1) + (Decimal("1") / odds2)
                            if imp < 1: 
                                roi = round(((1/float(imp)) - 1) * 100, 2)
                                if 0 < roi < 15.0: # SANITY FILTER
                                    fiat_opportunities.append(_build_fiat_opp(x, b1["name"], b2["name"], odds1, odds2, "ML", t_nm, opp_nk, imp, roi))

                    # --- Attribute 2: Totals ---
                    for pt, lines1 in b1["totals"].items():
                        if pt in b2["totals"]:
                            ov1, un1 = lines1.get("over"), lines1.get("under")
                            ov2, un2 = b2["totals"][pt].get("over"), b2["totals"][pt].get("under")
                            
                            # B1 Over vs B2 Under
                            if ov1 and un2:
                                imp = (Decimal("1") / ov1) + (Decimal("1") / un2)
                                if imp < 1: 
                                    roi = round(((1/float(imp)) - 1) * 100, 2)
                                    if 0 < roi < 15.0:
                                        fiat_opportunities.append(_build_fiat_opp(x, b1["name"], b2["name"], ov1, un2, f"Total {pt}", "OVER", "UNDER", imp, roi))
                            # B1 Under vs B2 Over
                            if un1 and ov2:
                                imp = (Decimal("1") / un1) + (Decimal("1") / ov2)
                                if imp < 1: 
                                    roi = round(((1/float(imp)) - 1) * 100, 2)
                                    if 0 < roi < 15.0:
                                        fiat_opportunities.append(_build_fiat_opp(x, b1["name"], b2["name"], un1, ov2, f"Total {pt}", "UNDER", "OVER", imp, roi))

                    # --- Attribute 3: Spreads ---
                    for pt, lines1 in b1["spreads"].items():
                        inv = -pt
                        if inv in b2["spreads"]:
                            for t_nm, odds1 in lines1.items():
                                opp_nk = h_nk if t_nm == a_nk else a_nk
                                odds2 = b2["spreads"][inv].get(opp_nk)
                                if odds1 and odds2:
                                    imp = (Decimal("1") / odds1) + (Decimal("1") / odds2)
                                    if imp < 1: 
                                        roi = round(((1/float(imp)) - 1) * 100, 2)
                                        if 0 < roi < 15.0:
                                            fiat_opportunities.append(_build_fiat_opp(x, b1["name"], b2["name"], odds1, odds2, f"Spread {pt}", t_nm, f"{opp_nk} ({inv})", imp, roi))

            # ==========================================================
            # 2. POLYMARKET CLOB SCANNER (Using VWAP logic)
            # ==========================================================
            target = next((e for e in raw_poly if h_nk in e.get('title','').lower() and a_nk in e.get('title','').lower()), None)
            if not target or not is_target_single_game(x["time"], target.get("gameStartTime"), target.get("endDate")): 
                continue
            
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
                            p_nk, f_odds = clean(t_nm), b["h2h"].get(clean(t_nm))
                            if f_odds:
                                asks = clients.get_clob_asks(toks[idx])
                                opp_nk = h_nk if p_nk == a_nk else a_nk
                                f_opp = b["h2h"].get(opp_nk)
                                if asks and f_opp:
                                    hedge = evaluate_buy_hedge_from_asks(asks, f_opp)
                                    logger.info(f"   [ML] {b['name']:<12} | {t_nm[:10]:<10} | {b['name']}: {float(f_opp):<5} | Status: {'✅' if hedge.passes_liquidity_filter else '❌ ' + str(hedge.reject_reason)}")
                                    if hedge.passes_liquidity_filter:
                                        roi = round(float((hedge.locked_profit / hedge.total_outlay) * 100), 2) if hedge.total_outlay > 0 else 0.0
                                        if 0 < roi < 15.0: # SANITY FILTER
                                            opportunities.append(_build_opp(x, b["name"], f_opp, hedge, "ML", t_nm, opp_nk, roi))

                    # --- Attribute 2: Totals ---
                    elif mt in ['total', 'totals']:
                        try: lne = round(float(m.get("line", 0)), 1)
                        except: continue
                        if lne in b["totals"]:
                            norm = [str(o).lower() for o in outs]
                            if "over" in norm and "under" in norm:
                                o_idx, u_idx = norm.index("over"), norm.index("under")
                                asks_ov, asks_un = clients.get_clob_asks(toks[o_idx]), clients.get_clob_asks(toks[u_idx])
                                f_un, f_ov = b["totals"][lne].get('under'), b["totals"][lne].get('over')
                                
                                if asks_ov and f_un:
                                    hedge = evaluate_buy_hedge_from_asks(asks_ov, f_un)
                                    logger.info(f"   [Total {lne}] {b['name']:<12} | OVER vs UNDER | {b['name']}: {float(f_un):<5} | Status: {'✅' if hedge.passes_liquidity_filter else '❌ ' + str(hedge.reject_reason)}")
                                    if hedge.passes_liquidity_filter:
                                        roi = round(float((hedge.locked_profit / hedge.total_outlay) * 100), 2) if hedge.total_outlay > 0 else 0.0
                                        if 0 < roi < 15.0:
                                            opportunities.append(_build_opp(x, b["name"], f_un, hedge, f"Total {lne}", "OVER", "UNDER", roi))
                                if asks_un and f_ov:
                                    hedge = evaluate_buy_hedge_from_asks(asks_un, f_ov)
                                    logger.info(f"   [Total {lne}] {b['name']:<12} | UNDER vs OVER | {b['name']}: {float(f_ov):<5} | Status: {'✅' if hedge.passes_liquidity_filter else '❌ ' + str(hedge.reject_reason)}")
                                    if hedge.passes_liquidity_filter:
                                        roi = round(float((hedge.locked_profit / hedge.total_outlay) * 100), 2) if hedge.total_outlay > 0 else 0.0
                                        if 0 < roi < 15.0:
                                            opportunities.append(_build_opp(x, b["name"], f_ov, hedge, f"Total {lne}", "UNDER", "OVER", roi))

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
                                    asks = clients.get_clob_asks(toks[idx])
                                    if asks:
                                        hedge = evaluate_buy_hedge_from_asks(asks, f_opp)
                                        logger.info(f"   [Spread {lne}] {b['name']:<12} | {t_nm[:10]} vs {opp_nk[:10]} | {b['name']}: {float(f_opp):<5} | Status: {'✅' if hedge.passes_liquidity_filter else '❌ ' + str(hedge.reject_reason)}")
                                        if hedge.passes_liquidity_filter:
                                            roi = round(float((hedge.locked_profit / hedge.total_outlay) * 100), 2) if hedge.total_outlay > 0 else 0.0
                                            if 0 < roi < 15.0:
                                                opportunities.append(_build_opp(x, b["name"], f_opp, hedge, f"Spread {lne}", t_nm, f"{opp_nk} ({inv})", roi))

        # --- FINAL SUMMARY & GLOBAL ALERTS ---
        logger.info("\n" + "="*80)
        
        final_alerts = build_global_alerts(opportunities, fiat_opportunities, limit=3)
        for msg in final_alerts:
            clients.send_telegram_alert(msg)
            
        logger.info(f"✅ SCAN COMPLETE. Evaluated entire slate. Sent {len(final_alerts)} highest-profit alerts.")
        logger.info("="*80)
        
    finally: clients.close()


# --- HELPER FOR TRADITIONAL ARBITRAGE ---
def _build_fiat_opp(x, b1_name, b2_name, odds1, odds2, m_tl, sel1, sel2, imp, roi):
    bankroll = 100.0
    payout = bankroll / float(imp)
    stake1 = payout / float(odds1)
    stake2 = payout / float(odds2)
    
    return FiatArbitrageOpportunity(
        sport_key="nba", home_team=x['home'], away_team=x['away'], commence_time=format_to_local(x['time']),
        market_title=m_tl, 
        bookmaker_1=b1_name, selection_1=sel1, odds_1=float(odds1), stake_1=stake1,
        bookmaker_2=b2_name, selection_2=sel2, odds_2=float(odds2), stake_2=stake2,
        implied_total=float(imp), payout=payout, expected_profit_percent=roi
    )

# --- HELPER FOR POLYMARKET ARBITRAGE ---
def _build_opp(x, b_nm, f_o, hedge: HedgeEstimate, m_tl, p_sd, f_sd, roi):
    return ArbitrageOpportunity(
        sport_key="nba", home_team=x['home'], away_team=x['away'], commence_time=format_to_local(x['time']),
        market_title=m_tl, selection_name=p_sd, fiat_selection=f_sd, bookmaker=b_nm, odds_decimal=float(f_o),
        shares=float(hedge.shares), vwap=float(hedge.vwap or 0), marginal_price=float(hedge.marginal_price or 0), 
        poly_spend=float(hedge.poly_spend), poly_fees=float(hedge.poly_fees), sportsbook_stake=float(hedge.sportsbook_stake),
        total_outlay=float(hedge.total_outlay), locked_profit=float(hedge.locked_profit), expected_profit_percent=roi
    )
