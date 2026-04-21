import requests

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
        print("-" * 40)
        
        for market in event.get('markets', []):
            if market.get('active') and not market.get('closed'):
                question = market.get('question', 'Unknown Market')
                outcomes = market.get('outcomes', [])
                prices = market.get('outcomePrices', [])
                
                print(f"\n📈 {question}")
                for outcome, price in zip(outcomes, prices):
                    cents = round(float(price) * 100, 1)
                    print(f"   ➤ {outcome}: {cents}¢")
    else:
        print("❌ Error fetching data.")

if __name__ == "__main__":
    # Scanning the Brighton vs Chelsea game we looked at earlier
    get_polymarket_prices("epl-bri-che-2026-04-21")
