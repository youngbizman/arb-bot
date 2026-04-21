import os
import time
import requests
import json
import re
from datetime import datetime

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def clean_team(name):
    """Simplifies: 'Philadelphia 76ers' -> 'philadelphia'"""
    name = name.lower()
    # Remove nicknames so we only compare the city/base name
    for n in ["cavaliers", "rockets", "nuggets", "lakers", "heat", "celtics", "mavericks", "spurs", "76ers", "blazers", "warriors", "bucks", "suns", "pistons"]:
        name = name.replace(n, "")
    return re.sub(r'[^a-z]', '', name).strip()

def get_1xbet_data():
    """Fetches Moneyline and Totals from 1xBet."""
    print("📡 Requesting 1xBet data...")
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    # We fetch h2h (Moneyline) and totals
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "1xbet"}
    
    try:
        res = requests.get(url, params=params).json()
        if isinstance(res, dict): return {} # API Error
        
        data = {}
        for game in res:
            home = clean_team(game['home_team'])
            away = clean_team(game['away_team'])
            game_key = f"{home}-{away}"
            
            for bookie in game.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    # --- Handle Moneyline ---
                    if market["key"] == "h2h":
                        for outcome in market["outcomes"]:
                            team_key = clean_team(outcome["name"])
                            prob = (1 / outcome["price"]) * 100
                            data[f"{game_key}-win-{team_key}"] = {"prob": prob, "label": f"{outcome['name']} Win"}
                    
                    # --- Handle Totals ---
                    if market["key"] == "totals":
                        for outcome in market["outcomes"]:
                            if outcome["name"] == "Under":
                                line = outcome["point"]
                                prob = (1 / outcome["price"]) * 100
                                data[f"{game_key}-under-{line}"] = {"prob": prob, "label": f"Under {line} pts"}
        return data
    except: return {}

def get_polymarket_data():
    """Fetches corresponding NBA markets from Polymarket."""
    print("📡 Requesting Polymarket data...")
    url = "https://gamma-api.polymarket.com/events?limit=200&active=true&closed=false"
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            title = event.get("title", "")
            if not any(x in title for x in ["NBA", "Lakers", "Celtics", "Rockets", "76ers", "Spurs"]): continue
            
            # Identify teams in the title
            teams = title.replace(" at ", " vs ").split(" vs ")
            if len(teams) < 2: continue
            home, away = clean_team(teams[0]), clean_team(teams[1])
            game_key = f"{home}-{away}"
            
            for m in event.get("markets", []):
                q = m.get("question", "").lower()
                prices = m.get("outcomePrices")
                if isinstance(prices, str): prices = json.loads(prices)
                if not prices or len(prices) < 1: continue
                
                # --- Match Winner ---
                if "will" in q and "win" in q:
                    for i, outcome in enumerate(m.get("outcomes", [])):
                        team_key = clean_team(outcome)
                        if team_key in [home, away]:
                            data[f"{game_key}-win-{team_key}"] = {"prob": float(prices[i]) * 100, "label": f"{outcome} Win"}
                
                # --- Point Totals ---
                if "over" in q and "points" in q:
                    line_match = re.search(r"(\d+\.?\d*)", q)
                    if line_match:
                        line = float(line_match.group(1))
                        data[f"{game_key}-under-{line}"] = {"prob": float(prices[0]) * 100, "label": f"Over {line} pts"}
        return data
    except: return {}

def run_scanner():
    xbet = get_1xbet_data()
    poly = get_polymarket_data()
    
    print("\n--- 📊 LIVE MARKET SNAPSHOT ---")
    print(f"{'GAME/MARKET':<40} | {'1xBET %':<10} | {'POLY %':<10}")
    print("-" * 65)
    
    found_any = False
    for key in xbet:
        if key in poly:
            x_prob, p_prob = xbet[key]["prob"], poly[key]["prob"]
            print(f"{xbet[key]['label']:<40} | {round(x_prob, 1):<10} | {round(p_prob, 1):<10}")
            
            total = x_prob + p_prob
            if total < 100:
                found_any = True
                profit = (100 / (total / 100)) - 100
                send_telegram_alert(f"💰 ARB FOUND: {xbet[key]['label']}\nBenefit: {round(profit, 2)}%\nDivide money: {round(p_prob/total*100, 1)}% Poly / {round(x_prob/total*100, 1)}% 1xBet")

    if not found_any:
        print("\n⚖️ Results: All matched markets are balanced (No profit).")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    run_scanner()
