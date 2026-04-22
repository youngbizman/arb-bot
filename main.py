import os
import requests
import json
from datetime import datetime
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
                if game.get("bookmakers"):
                    b = game["bookmakers"][0] 
                    for m in b.get("markets", []):
                        if m['key'] == 'h2h':
                            for o in m['outcomes']:
                                key = f"{clean(o['name'])}-win"
                                data[key] = {
                                    "decimal_odds": Decimal(str(o['price'])), 
                                    "team": o['name'], 
                                    "game": f"{h} vs {a}"
                                }
        return data
    except Exception as e:
        print(f"❌ 1xBet Fetch Error: {e}")
        return {}

def get_poly_best_ask(market, team_name):
    """Gets the true executable Ask price using Gamma or CLOB Orderbook."""
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        token_ids = json.loads(market.get("clobTokenIds") or "[]")
        
        if team_name not in outcomes:
            return None
            
        idx = outcomes.index(team_name)
        token_id = token_ids[idx] if idx < len(token_ids) else None
        
        if token_id is None:
            return None

        # Fast path: Gamma already exposes top-of-book on market objects
        if market.get("bestAsk") is not None:
            return Decimal(str(market["bestAsk"]))

        # Fallback: authoritative CLOB order book
        book = requests.get(
            "https://clob.polymarket.com/book",
            params={"token_id": token_id},
            timeout=10,
        ).json()
        
        asks = book.get("asks") or []
        if not asks:
            return None
            
        return Decimal(asks[0]["price"])
    except Exception as e:
        print(f"❌ CLOB Fetch Error: {e}")
        return None

def get_polymarket():
    """Sniper scan using NBA Moneyline JSON parsing and precise Ask prices."""
    url = "https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false&limit=100"
    try:
        res = requests.get(url).json()
        data = {}
        events = res if isinstance(res, list) else res.get('events', [])
        
        for event in events:
            title = event.get('title', '')
            for m in event.get('markets', []):
                if m.get('sportsMarketType') == 'moneyline' and m.get('acceptingOrders') == True:
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
            # Find the opponent on 1xBet
            other_x = next((v for k, v in xbet.items() if v['game'] == game_name and v['team'] != x_val['team']), None)
            
            if other_x:
                opp_d = other_x['decimal_odds']
                inv_opp_d = Decimal("1") / opp_d
                
                # Math from the document: arb_sum = Poly Ask + (1 / Sportsbook Decimal)
                arb_sum = p + inv_opp_d
                
                if arb_sum < Decimal("1"):
                    found_any = True
                    
                    # Calculate Stakes for a $100 Bankroll
                    B = Decimal("100")
                    poly_stake = B * p / arb_sum
                    book_stake = B * inv_opp_d / arb_sum
                    
                    guaranteed_payout = B / arb_sum
                    profit_margin = (guaranteed_payout - B) / B * Decimal("100")
                    
                    alert = (
                        f"💰 ARB FOUND: {game_name}\n"
                        f"Profit: {round(float(profit_margin), 2)}%\n\n"
                        f"🔵 Poly: {round(float(poly_stake), 1)}% on '{poly[key]['label']}'\n"
                        f"🟢 1xBet: {round(float(book_stake), 1)}% on '{other_x['team']}'\n\n"
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
