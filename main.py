import requests
import os

# Grab the secure keys from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    """Sends a message directly to your Telegram app."""
    # Safety check: Did GitHub load the secrets properly?
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram credentials not found! Check your GitHub Secrets.")
        print("Message that WOULD have been sent:\n", message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("✅ Telegram alert sent successfully!")
    else:
        print(f"❌ Failed to send Telegram alert. Error: {response.text}")

def get_polymarket_prices(event_slug):
    url = f"https://gamma-api.polymarket.com/events?slug={event_slug}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if not data:
            print("Event not found.")
            return

        event = data[0]
        print(f"✅ Scanning: {event['title']}")
        
        # Build a message to send to your phone
        alert_message = f"🤖 *Arb-Bot Live Update*\nScanning: {event['title']}\n"
        found_data = False
        
        for market in event.get('markets', []):
            if market.get('active') and not market.get('closed'):
                question = market.get('question', 'Unknown Market')
                outcomes = market.get('outcomes', [])
                prices = market.get('outcomePrices', [])
                
                # For this test, let's just grab the Over/Under 2.5 prices
                if "2.5" in question:
                    alert_message += f"\n📈 {question}\n"
                    found_data = True
                    
                    for outcome, price in zip(outcomes, prices):
                        # BULLETPROOF CHECK: Is there actually a price?
                        try:
                            if price and price.strip():
                                cents = round(float(price) * 100, 1)
                                alert_message += f"➤ {outcome}: {cents}¢\n"
                            else:
                                alert_message += f"➤ {outcome}: N/A (No Volume)\n"
                        except ValueError:
                            alert_message += f"➤ {outcome}: Data Error\n"
        
        # Only send a text if we actually found 2.5 markets
        if found_data:
            send_telegram_alert(alert_message)
        else:
            print("⚠️ No active 2.5 goals markets found in this event right now.")
            
    else:
        print("❌ Error fetching data from Polymarket API.")

if __name__ == "__main__":
    get_polymarket_prices("epl-bri-che-2026-04-21")
