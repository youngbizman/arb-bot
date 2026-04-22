import os
import requests
import json
import re
from datetime import datetime
import pytz
from decimal import Decimal, getcontext

# Set high precision for decimal arbitrage math
getcontext().prec = 28

# Secure keys
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Strict Playoff Filters based on API Schema diagnostics
SERIES_SLUG_HINTS = ["who-will-win-series", "total-games", "series-outcome", "champion", "to-win-series", "advance"]
DATE_SLUG_RE = re.compile(r".*-\d{4}-\d{2}-\d{2}$")

def clean(text):
    """Extracts the team nickname for perfect matching."""
    text = text.lower().replace("trail blazers", "blazers")
    return text.split()[-1]

def get_1xbet():
    """Fetches real NBA Winner odds from The Odds API."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h"}
    try:
        res = requests.get(url, params=params).json()
        data = {}
        if isinstance(res, list):
            for game in res:
                h, a = game['home_team'], game['away_team']
                
                raw_time = game.get('commence_time', '')
                match_date = "Unknown Date"
                if raw_time:
                    try:
                        dt = datetime.strptime(raw_time, "%Y-%m-%dT%H:%M:%SZ")
                        match_date = dt.strftime("%B %d")
                    except:
                        pass

                if game.get("bookmakers"):
                    b = game["bookmakers"][0] 
                    for m in b.get("markets", []):
                        if m['key'] == 'h2h':
                            for o in m['outcomes']:
                                key = f"{clean(o['name'])}-win"
                                data[key] = {
                                    "decimal_odds": Decimal(str(o['price'])), 
                                    "team": o['name'], 
                                    "game": f"{h} vs {a}",
                                    "date": match_date
                                }
        return data
    except Exception as e:
        print(f"❌ 1xBet Fetch Error: {e}")
        return {}

def get_poly_best_ask(market, team_name):
    """Gets the true executable Ask price by manually finding the minimum price in the orderbook."""
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        token_ids = json.loads(market.get("clobTokenIds") or "[]")
        
        if team_name not in outcomes:
            return None
            
        idx = outcomes.index(team_name)
        token_id = token_ids[idx] if idx < len(token_ids) else None
        
        if token_id is None:
            return None

        book = requests.get(
            "https://clob.polymarket.com/book",
            params={"token_id": token_id},
            timeout=10,
        ).json()
        
        asks = book.get("asks") or []
        if not asks:
            return None
            
        # Parse all prices and find the mathematical minimum to avoid the 0.99 sorting bug.
        prices = []
        for ask in asks:
            if "price" in ask:
                prices.append(Decimal(str(ask["price"])))
                
        if not prices:
            return None
            
        return min(prices)
        
    except Exception as e:
        return None

def get_polymarket():
    """Sniper scan using NBA Moneyline JSON parsing, Playoff filtering, and precise Ask prices."""
    url = "https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100"
    try:
        res = requests.get(url).json()
        data = {}
        events = res if isinstance(res, list) else res.get('events', [])
        
        for event in events:
            # Skip games that are already finished
            if event.get("ended") == True:
                continue
                
            for m in event.get('markets', []):
                if m.get('sportsMarketType') != 'moneyline' or not m.get('acceptingOrders'):
                    continue
                
                # --- START OF PLAYOFF SERIES FILTERING ---
                game_id = m.get("gameId")
                game_start = m.get("gameStartTime")
                
                # 1. Reject if no specific game properties exist
                if not game_id or not game_start:
                    continue
                
                market_slug = (m.get("slug") or "").lower()
                event_slug = (event.get("slug") or "").lower()
                slug_blob = f"{event_slug} {market_slug}"
                
                # 2. Reject if slug contains macroscopic series keywords
                if any(hint in slug_blob for hint in SERIES_SLUG_HINTS):
                    continue
                
                # 3. Reject if the slug is not strictly date-stamped for a single match
                if not (DATE_SLUG_RE.match(market_slug) or DATE_SLUG_RE.match(event_slug)):
                    continue
                # --- END OF PLAYOFF SERIES FILTERING ---

                outcomes_str = m.get('outcomes', "[]")
                outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                
                if outcomes:
                    for team_name in outcomes:
                        team_id = clean(team_name)
                        best_ask = get_poly_best_ask(m, team_name)
                        
                        if best_ask is not None:
                            data[f"{team_id}-win"] = {"best_ask": best_ask, "label": team_name}
        return data
    except Exception as e:
        print(f"❌ Poly Events Error: {e}")
        return {}

def run_scan():
    print("📡 Fetching Market Data...")
    xbet = get_1xbet()
    poly = get_polymarket()
    
    print("\n--- 📊 INTERNAL DATA TABLE (REAL ASK PRICES) ---")
    print(f"{'TEAM':<20} | {'1XBET (DECIMAL)':<15} | {'POLY ASK %':<10}")
    print("-" * 52)
    
    found_any = False
    
    for key, x_val in xbet.items():
        if key in poly:
            d = x_val['decimal_odds']
            p = poly[key]['best_ask']
            
            print(f"{x_val['team']:<20} | {float(d):<15} | {round(float(p)*100, 1)}%")
            
            game_name = x_val['game']
            other_x = next((v for k, v in xbet.items() if v['game'] == game_name and v['team'] != x_val['team']), None)
            
            if other_x:
                opp_d = other_x['decimal_odds']
                inv_opp_d = Decimal("1") / opp_d
                
                arb_sum = p + inv_opp_d
                
                if arb_sum < Decimal("1"):
                    found_any = True
                    
                    B = Decimal("100")
                    poly_stake = B * p / arb_sum
                    book_stake = B * inv_opp_d / arb_sum
                    
                    guaranteed_payout = B / arb_sum
                    profit_margin = (guaranteed_payout - B) / B * Decimal("100")
                    
                    match_date = x_val.get('date', 'Unknown Date')
                    
                    alert = (
                        f"🏀 NBA: {game_name}\n"
                        f"📅 Match Date: {match_date}\n\n"
                        f"🔵 Polymarket: Put {round(float(poly_stake), 1)}% of money on '{poly[key]['label']}'\n"
                        f"🟢 1xBet: Put {round(float(book_stake), 1)}% of money on '{other_x['team']}'\n\n"
                        f"💰 Total Benefit: {round(float(profit_margin), 2)}%\n\n"
                        f"⏱ Calc Done: {datetime.now(pytz.timezone('America/Toronto')).strftime('%B %d %H:%M et').lower()}"
                    )
                    send_telegram_alert(alert)

    print("\n--- 🔍 ARBITRAGE VERDICT ---")
    if not found_any:
        print("⚖️ All markets are efficient. No gaps below 100% found.")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scan()
