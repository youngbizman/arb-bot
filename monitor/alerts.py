from __future__ import annotations
from .models import ArbitrageOpportunity

def build_alert_messages(
    opportunities: list[ArbitrageOpportunity],
    limit: int = 3,
) -> list[str]:
    if limit <= 0:
        return []

    unique_messages: dict[str, str] = {}

    sorted_opportunities = sorted(
        opportunities,
        key=lambda item: item.expected_profit_percent,
        reverse=True,
    )

    for opportunity in sorted_opportunities:
        message = format_opportunity_alert(opportunity)
        unique_messages[message] = message

    return list(unique_messages.values())[:limit]


def format_opportunity_alert(opportunity: ArbitrageOpportunity) -> str:
    # --- $100 BANKROLL HEDGE CALCULATOR ---
    total_investment = 100.0
    
    # Calculate guaranteed payout
    guaranteed_payout = total_investment / opportunity.implied_total
    
    # Calculate exact dollar amounts to place on each side
    fiat_stake = guaranteed_payout / opportunity.odds_decimal
    poly_stake = guaranteed_payout * opportunity.poly_price

    return (
        f"🚨 ARBITRAGE SNIPER ALERT 🚨\n\n"
        f"🏀 MATCHUP: {opportunity.home_team} vs {opportunity.away_team}\n"
        f"📅 DATE: {opportunity.commence_time[:10]}\n"
        f"🎯 MARKET: {opportunity.market_title}\n"
        f"💵 PROFIT MARGIN: {opportunity.expected_profit_percent:.2f}%\n\n"
        f"🛠️ HEDGE CALCULATOR ($100 Bankroll):\n"
        f"▪️ Bet ${fiat_stake:.2f} on {opportunity.bookmaker} ({opportunity.odds_decimal:.2f} Odds)\n"
        f"▪️ Buy ${poly_stake:.2f} of '{opportunity.selection_name}' on Poly (${opportunity.poly_price:.2f})\n\n"
        f"✅ GUARANTEED RETURN: ${guaranteed_payout:.2f}"
    )


def build_no_opportunities_message() -> str:
    return "⚖️ Markets efficient. No arbitrage gaps found below 100%."
