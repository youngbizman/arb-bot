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
    return (
        f"MATCHUP: {opportunity.home_team} vs {opportunity.away_team}\n"
        f"DATE: {opportunity.commence_time[:10]}\n"
        f"MARKET: {opportunity.market_title}\n"
        f"POLY SIDE: {opportunity.selection_name} @ {opportunity.poly_price:.4f}\n"
        f"HEDGE SIDE: {opportunity.bookmaker} @ {opportunity.odds_decimal:.2f}\n"
        f"IMPLIED TOTAL: {opportunity.implied_total:.4f}\n"
        f"EDGE: {opportunity.edge_percent:.2f}%\n"
        f"EXPECTED PROFIT: {opportunity.expected_profit_percent:.2f}%"
    )


def build_no_opportunities_message() -> str:
    return "⚖️ Markets efficient. No arbitrage gaps found below 100%."
