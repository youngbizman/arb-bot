import logging
import json
import unicodedata
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from zoneinfo import ZoneInfo

from .api_clients import ApiClients
from .config import ConfigError, load_settings
from .models import ArbitrageOpportunity, FiatArbitrageOpportunity
from .alerts import format_mma_opportunity_alert, format_mma_fiat_opportunity_alert

logger = logging.getLogger(__name__)
getcontext().prec = 28

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
            p, s = Decimal(str(row.get("price", "0"))), Decimal(str(row.get("size", "0")))
            if s > 0: levels.append(BookLevel(price=p, size=s))
        except: pass
    return sorted(levels, key=lambda lvl: lvl.price)

def fee_per_share(p: Decimal, r: Decimal) -> Decimal:
    return r * p * (Decimal("1") - p)

def evaluate_buy_hedge_from_asks(asks, decimal_odds, bankroll="100", fee_rate="0.03", max_avg_impact_rel="0.02"):
    levels = normalize_asks(asks)
    odds, bankroll_d, fee_r = Decimal(str(decimal_odds)), Decimal(bankroll), Decimal(fee_rate)
    inv_odds = Decimal("1") / odds
    eps = Decimal("0.0000000001")

    if not levels: return HedgeEstimate(None, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), None, None, Decimal("0"), False, "Empty Orderbook")

    best = levels[0]
    q, cost, fees = Decimal("0"), Decimal("0"), Decimal("0")
    marginal, full_bankroll_supported = None, False

    for lvl in levels:
        lvl_fee_ps = fee_per_share(lvl.price, fee_r)
        lvl_all_in_ps = lvl.price + lvl_fee_ps + inv_odds
        if lvl_all_in_ps >= Decimal("1"): break
        rem = bankroll_d - ((q * inv_odds) + cost + fees)
        if rem <= eps: 
            full_bankroll_supported = True
            break
        affordable = rem / lvl_all_in_ps
        take = min(lvl.size, affordable)
        if take <= 0: break
        q += take
        cost += take * lvl.price
        fees += take * lvl_fee_ps
        marginal = lvl.price
        if take < lvl.size:
            full_bankroll_supported = True
            break

    total = cost + fees + (q * inv_odds)
    if total >= bankroll_d - eps: full_bankroll_supported = True
    if q <= Decimal("0"): return HedgeEstimate(best.price, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), None, None, Decimal("0"), False, "No profitable depth")

    vwap = cost / q
    profit = q - total
    impact = (vwap / best.price) - Decimal("1")
    reason = None
    if not full_bankroll_supported: reason = "Insufficient depth for $100 bankroll"
    elif impact > Decimal(max_avg_impact_rel): reason = "Slippage exceeds 2% buffer"
    elif profit <= 0: reason = "Negative profit after fees"

    return HedgeEstimate(best.price, q, (q/odds), cost, fees, total, vwap, marginal, profit, (reason is None), reason)

def clean_fighter_name(text: str) -> str:
    if not text: return ""
    # Strip accents (Jiří Procházka -> Jiri Prochazka) natively
    text = unicodedata.normalize('NFKD', str(text)).encode('ASCII', 'ignore').decode('utf-8')
    # Remove punctuation, lowercase it, and grab the last name
    text = re.sub(r'[^a-zA-Z\s]', '', text.lower())
    parts = text.split()
    return parts[-1] if parts else ""

def format_to_local(iso: str) -> str:
    try: return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %I:%M %p")
    except: return iso[:10]

def parse_iso8601_to_epoch(t):
    try: return int(datetime.fromisoformat(str(t).replace(" ", "T").replace("Z", "+00:00")).timestamp())
    except: return 0

def validate_market_state(book: dict, fiat_last_update: str) -> tuple[bool, float, float]:
    poly_ts = float(book.get("timestamp") or 0)
    if poly_ts > 1e11: poly_ts /= 1000.0  
    fiat_ts = parse_iso8601_to_epoch(fiat_last_update)
    delta_t = abs(fiat_ts - poly_ts) if fiat_ts > 0 else 999.0
    asks = sorted([Decimal(str(r.get("price", "0"))) for r in book.get("asks", []) if Decimal(str(r.get("size", "0"))) > 0])
    bids = sorted([Decimal(str(r.get("price", "0"))) for r in book.get("bids", []) if Decimal(str(r.get("size", "0"))) > 0], reverse=True)
    best_ask = float(asks[0]) if asks else 1.0
    best_bid = float(bids[0]) if bids else 0.0
    spread = ((best_ask - best_bid) / best_ask) * 100 if best_ask > 0 else 100.0
    return (delta_t <= 2.5 and spread <= 5.0), delta_t, spread

def run_ufc() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try: settings = load_settings()
    except ConfigError as exc: logger.error(f"Config error: {exc}"); return
    clients = ApiClients(settings)
    
    try:
        logger.info("📡 Initializing UFC/MMA Sync-Validated Sniper...")
        raw_odds, raw_poly = clients.get_mma_fiat_data(), clients.get_mma_polymarket_events()
        
        fiat_games = {}
        for game in raw_odds:
            h, a = game.get('home_team'), game.get('away_team')
            if not h or not a: continue
            k = f"{clean_fighter_name(h)}_{clean_fighter_name(a)}"
            if k not in fiat_games: fiat_games[k] = {"home": h, "away": a, "time": game.get('commence_time'), "bookies": []}
            for b in game.get("bookmakers", []):
                b_data = {"name": b.get("title"), "last_update": b.get("last_update"), "h2h": {}}
                for m in b.get("markets", []):
                    if m.get('key') == 'h2h':
                        for o in m.get('outcomes', []):
                            nm, pr = clean_fighter_name(o.get('name')), o.get('price')
                            if pr is not None: b_data["h2h"][nm] = Decimal(str(pr))
                fiat_games[k]["bookies"].append(b_data)

        opportunities, fiat_opportunities = [], []
        for gk, x in fiat_games.items():
            h_nk, a_nk = clean_fighter_name(x["home"]), clean_fighter_name(x["away"])
            logger.info(f"\n🥊 MATCHED: {x['home']} vs {x['away']} | Local Time: {format_to_local(x['time'])}")
            logger.info("-" * 80)

            # 1. Fiat Scanner (UFC)
            for i in range(len(x["bookies"])):
                for j in range(i + 1, len(x["bookies"])):
                    b1, b2 = x["bookies"][i], x["bookies"][j]
                    for t_nm, o1 in b1["h2h"].items():
                        opp_nk = h_nk if t_nm == a_nk else a_nk
                        o2 = b2["h2h"].get(opp_nk)
                        if o1 and o2:
                            imp = (Decimal("1")/o1) + (Decimal("1")/o2)
                            if imp < 1:
                                roi = round(((1/float(imp))-1)*100, 2)
                                if 0 < roi < 25.0: # MMA Sanity Filter bump
                                    fiat_opportunities.append(_build_fiat_opp(x, b1["name"], b2["name"], o1, o2, "Moneyline", t_nm, opp_nk, imp, roi))

            # 2. Poly Scanner (UFC)
            target = next((e for e in raw_poly if h_nk in e.get('title','').lower() and a_nk in e.get('title','').lower()), None)
            if not target: continue
            
            for b in x["bookies"]:
                for m in target.get('markets', []):
                    if not m.get('acceptingOrders'): continue
                    mt = str(m.get('sportsMarketType', '')).lower()
                    try:
                        outs, toks = json.loads(m.get('outcomes')), json.loads(m.get('clobTokenIds'))
                    except: continue
                    
                    if mt == 'moneyline' or mt == 'winner':
                        for idx, t_nm in enumerate(outs):
                            p_nk, f_odds = clean_fighter_name(t_nm), b["h2h"].get(clean_fighter_name(t_nm))
                            if f_odds:
                                book = clients.get_clob_book(toks[idx])
                                opp_nk = h_nk if p_nk == a_nk else a_nk
                                f_opp = b["h2h"].get(opp_nk)
                                if f_opp:
                                    hedge = evaluate_buy_hedge_from_asks(book.get("asks", []), f_opp)
                                    is_v, dt, sp = validate_market_state(book, b.get("last_update"))
                                    if hedge.passes_liquidity_filter and not is_v:
                                        hedge.passes_liquidity_filter = False
                                        hedge.reject_reason = f"Async Data (Delta {dt:.1f}s, Spread {sp:.1f}%)"
                                    logger.info(f"   [ML] {b['name']:<12} | {t_nm[:10]:<10} | {b['name']}: {float(f_opp):<5} | Status: {'✅' if hedge.passes_liquidity_filter else '❌ ' + str(hedge.reject_reason)}")
                                    if hedge.passes_liquidity_filter:
                                        roi = round(float((hedge.locked_profit/hedge.total_outlay)*100), 2)
                                        if 0 < roi < 25.0:  # MMA Sanity Filter bump
                                            opportunities.append(_build_opp(x, b["name"], f_opp, hedge, "Moneyline", t_nm, opp_nk, roi, dt, sp))

        logger.info("\n" + "="*80)
        
        # Sort and send MMA alerts
        all_opps = []
        for o in opportunities: all_opps.append({'profit': o.expected_profit_percent, 'msg': format_mma_opportunity_alert(o)})
        for o in fiat_opportunities: all_opps.append({'profit': o.expected_profit_percent, 'msg': format_mma_fiat_opportunity_alert(o)})
        
        sorted_opps = sorted(all_opps, key=lambda x: x['profit'], reverse=True)[:3]
        
        for item in sorted_opps: 
            clients.send_telegram_alert(item['msg'])
            
        logger.info(f"✅ UFC SCAN COMPLETE. Sent {len(sorted_opps)} alerts.")
        logger.info("="*80)
        
    finally: clients.close()

def _build_fiat_opp(x, b1, b2, o1, o2, m, s1, s2, imp, roi):
    payout = 100.0 / float(imp)
    return FiatArbitrageOpportunity("mma", x['home'], x['away'], format_to_local(x['time']), m, b1, s1, float(o1), (payout/float(o1)), b2, s2, float(o2), (payout/float(o2)), float(imp), payout, roi)

def _build_opp(x, b, f_o, hedge, m, p_s, f_s, roi, dt, sp):
    return ArbitrageOpportunity("mma", x['home'], x['away'], format_to_local(x['time']), m, p_s, f_s, b, float(f_o), float(hedge.shares), float(hedge.vwap or 0), float(hedge.marginal_price or 0), float(hedge.poly_spend), float(hedge.poly_fees), float(hedge.sportsbook_stake), float(hedge.total_outlay), float(hedge.locked_profit), roi, dt, sp)
