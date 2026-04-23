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
    # --- REFACTORED: Uses precise, pre-calculated VWAP numbers ---
    return (
        f"🚨 ARBITRAGE SNIPER ALERT 🚨\n\n"
        f"🏀 MATCHUP: {opportunity.home_team} vs {opportunity.away_team}\n"
        f"📅 DATE: {opportunity.commence_time}\n"
        f"🎯 MARKET: {opportunity.market_title}\n"
        f"💵 NET PROFIT MARGIN: {opportunity.expected_profit_percent:.2f}%\n\n"
        f"🛠️ EXECUTION CALCULATOR (${opportunity.total_outlay:.2f} Bankroll):\n"
        f"▪️ Bet ${opportunity.sportsbook_stake:.2f} on '{opportunity.fiat_selection}' at {opportunity.bookmaker} ({opportunity.odds_decimal:.2f})\n"
        f"▪️ Buy ${opportunity.poly_spend:.2f} of '{opportunity.selection_name}' on Poly (Avg Price: ${opportunity.vwap:.4f})\n"
        f"▪️ Polymarket Fees: ${opportunity.poly_fees:.2f}\n\n"
        f"✅ GUARANTEED NET PROFIT: ${opportunity.locked_profit:.2f}"
    )


def build_no_opportunities_message() -> str:
    return "⚖️ Markets efficient. No arbitrage gaps found below 100%."
