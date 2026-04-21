import os
import time
import requests
from datetime import datetime
import pytz

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def send_telegram_alert(message):
    """Sends the formatted text to you and Arash."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram credentials missing!")
        return

    chat_ids = TELEGRAM_CHAT_ID.split(',')
    for chat_id in chat_ids:
        clean_id = chat_id.strip()
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": clean_id, "text": message}
        requests.post(url, json=payload)

def get_eastern_time():
    eastern = pytz.timezone('America/Toronto')
    return datetime.now(eastern).strftime("%B %d %H:%M et").lower()

def get_current_date():
    eastern = pytz.timezone('America/Toronto')
    return datetime.now(eastern).strftime("%B %d")

def normalize_name(name):
    """Simplifies team names so Polymarket and 1xBet match."""
    # Converts "Cleveland Cavaliers" -> "cleveland"
    name = name.lower()
    teams = name.replace("vs.", "vs").split(" vs ")
    clean_teams = []
    for team in teams:
        # Keep just the first word (usually the city) to match easily
        clean_teams.append(team.strip().split()[0]) 
    return " vs ".join(clean_teams)

def get_1xbet_live_odds():
    """Fetches real live NBA data from The Odds API (1xBet)."""
    print("📡 Fetching live 1xBet odds from The Odds API...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "totals", # Over/Under points
        "bookmakers": "1xbet"
    }
    
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print("❌ Error fetching The Odds API.")
        return {}

    games = response.json()
    xbet_data = {}
    
    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        match_name = f"{home} vs {away}"
        simple_name = normalize_name(match_name)
        
        for bookie in game.get("bookmakers", []):
            if bookie["key"] == "1xbet":
                for market in bookie.get("markets", []):
                    if market["key"] == "totals":
                        # Grab the 'Under' outcome as an example
                        for outcome in market.get("outcomes", []):
                            if outcome["name"] == "Under":
                                decimal_odds = outcome["price"]
                                points = outcome["point"]
                                # Convert decimal odds to implied probability
                                prob = round((1 / decimal_odds) * 100, 1)
                                
                                xbet_data[simple_name] = {
                                    "market": f"under {points} points",
                                    "prob": prob,
                                    "points": points # Save this to match exactly with Poly
                                }
    return xbet_data

def get_polymarket_live_odds():
    """Fetches real live NBA data from Polymarket."""
    print("📡 Fetching live Polymarket odds...")
    url = "https://gamma-api.polymarket.com/events?limit=100&active=true&closed=false"
    response = requests.get(url)
    
    if response.status_code != 200:
        print("❌ Error fetching Polymarket API.")
        return {}

    events = response.json()
    poly_data = {}
    
    for event in events:
        title = event.get('title', '')
        if "NBA" in title or "Basketball" in title:
            simple_name = normalize_name(title)
            
            for market in event.get('markets', []):
                if market.get('active') and not market.get('closed'):
                    question = market.get('question', '').lower()
                    outcomes = market.get('outcomes', [])
                    prices = market.get('outcomePrices', [])
                    
                    # Look for total points markets
                    if "over" in question and "points" in question:
                        for outcome, price in zip(outcomes, prices):
                            if outcome.lower() == "yes":
                                try:
                                    prob = round(float(price) * 100, 1)
                                    poly_data[simple_name] = {
                                        "market": question,
                                        "prob": prob
                                    }
                                except ValueError:
                                    pass
    return poly_data

def find_top_3_arbitrages():
    print("🏀 Calculating Live Arbitrages...")
    
    xbet_data = get_1xbet_live_odds()
    poly_data = get_polymarket_live_odds()
    timestamp = get_eastern_time()
    match_date = get_current_date()
    
    found_arbs = []

    # Match the games together
    for simple_name in poly_data:
        if simple_name in xbet_data:
            poly_prob = poly_data[simple_name]["prob"]
            poly_market = poly_data[simple_name]["market"]
            
            xbet_prob = xbet_data[simple_name]["prob"]
            xbet_market = xbet_data[simple_name]["market"]
            
            # The Math Engine
            total_implied = poly_prob + xbet_prob
            if total_implied < 100:
                profit_pct = round((100 / (total_implied / 100)) - 100, 2)
                
                # Split stakes to equal 100% bankroll
                poly_stake = round((poly_prob / total_implied) * 100, 1)
                xbet_stake = round((xbet_prob / total_implied) * 100, 1)

                message = (
                    f"🏀 NBA: {simple_name.upper()}\n"
                    f"📅 Match Date: {match_date}\n\n"
                    f"🔵 Polymarket: Put {poly_stake}% of money on '{poly_market}'\n"
                    f"🟢 1xBet: Put {xbet_stake}% of money on '{xbet_market}'\n\n"
                    f"💰 Total Benefit: {profit_pct}%\n\n"
                    f"⏱ Calc Done: {timestamp}"
                )
                
                found_arbs.append({"profit": profit_pct, "message": message})

    # Sort and alert
    found_arbs.sort(key=lambda x: x["profit"], reverse=True)
    top_3 = found_arbs[:3]
    
    if not top_3:
        print("⚖️ No profitable arbitrages found at this exact moment.")
        
    for rank, arb in enumerate(top_3, 1):
        print(f"\n✅ Found Rank #{rank} (Profit: {arb['profit']}%)")
        send_telegram_alert(arb["message"])
        time.sleep(1) 

if __name__ == "__main__":
    find_top_3_arbitrages()
