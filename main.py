import os
import time
import requests
import re
from datetime import datetime
import pytz

# Secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def normalize_name(name):
    """Strips names down to the city/core name to ensure a match."""
    name = name.lower()
    # Remove common filler words
    for word in ["cavaliers", "rockets", "nuggets", "lakers", "heat", "celtics", "mavericks", "spurs"]:
        name = name.replace(word, "")
    # Keep only alphanumeric and spaces
    return "".join(e for e in name if e.isalnum() or e.isspace()).strip()

def extract_line(text):
    """Finds the point total (e.g. 216.5) inside a Polymarket question."""
    match = re.search(r"(\d+\.?\d*)", text)
    return float(match.group(1)) if match else None

def get_1xbet_live_odds():
    """Fetches real Totals from 1xBet via The Odds API."""
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "totals", "bookmakers": "1xbet"}
    
    try:
        res = requests.get(url, params=params).json()
        data = {}
        for game in res:
            simple_name = f"{normalize_name(game['home_team'])} vs {normalize_name(game['away_team'])}"
            for bookie in game.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == "Under":
                            line = outcome["point"]
                            # Convert Decimal Odds to Implied Probability
                            prob = (1 / outcome["price"]) * 100
                            data[f"{simple_name}_{line}"] = {"prob": prob, "market": f"under {line}"}
        return data
    except:
        return {}

def get_polymarket_live_odds():
    """Fetches real 'Over' markets from Polymarket Gamma API."""
    url = "https://gamma-api.polymarket.com/events?limit=100&active=true&closed=false"
    try:
        res = requests.get(url).json()
        data = {}
        for event in res:
            if "NBA" in event.get("title", ""):
                teams = event["title"].split(" at ") if " at " in event["title"] else event["title"].split(" vs ")
                if len(teams) < 2: continue
                simple_name = f"{normalize_name(teams[0])} vs {normalize_name(teams[1])}"
                
                for m in event.get("markets", []):
                    q = m.get("question", "").lower()
                    if "over" in q and "points" in q:
                        line = extract_line(q)
                        price = float(m.get("outcomePrices", ["0", "0"])[0]) # Price of "Yes"
                        if line:
                            data[f"{simple_name}_{line}"] = {"prob": price * 100, "market": q}
        return data
    except:
        return {}

def find_top_3_arbitrages():
    print("🔄 Scanning for Live Arbitrage...")
    poly = get_polymarket_live_odds()
    xbet = get_1xbet_live_odds()
    
    found = []
    for key in poly:
        if key in xbet:
            p_prob, x_prob = poly[key]["prob"], xbet[key]["prob"]
            total = p_prob + x_prob
            if total < 100:
                profit = (100 / (total / 100)) - 100
                p_stake = round((p_prob / total) * 100, 1)
                x_stake = round((x_prob / total) * 100, 1)
                
                msg = (
                    f"🏀 NBA: {key.split('_')[0].upper()}\n"
                    f"📅 Match Date: {datetime.now().strftime('%B %d')}\n\n"
                    f"🔵 Polymarket: Put {p_stake}% on '{poly[key]['market']}'\n"
                    f"🟢 1xBet: Put {x_stake}% on '{xbet[key]['market']}'\n\n"
                    f"💰 Total Benefit: {round(profit, 2)}%\n\n"
                    f"⏱ Calc Done: {datetime.now().strftime('%B %d %H:%M et').lower()}"
                )
                found.append({"profit": profit, "msg": msg})

    found.sort(key=lambda x: x["profit"], reverse=True)
    for arb in found[:3]:
        send_telegram_alert(arb["msg"])

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in TELEGRAM_CHAT_ID.split(','):
        requests.post(url, json={"chat_id": cid.strip(), "text": message})

if __name__ == "__main__":
    find_top_3_arbitrages()
