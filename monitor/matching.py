from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from .models import ArbitrageOpportunity, Game
from .parsers import clean, is_target_single_game


logger = logging.getLogger(__name__)


def find_arbitrage_opportunities(
    odds_games: list[Game],
    polymarket_games: list[Game],
    clob_price_lookup: dict[tuple[str, str, str], Decimal | None],
) -> list[ArbitrageOpportunity]:
    opportunities: list[ArbitrageOpportunity] = []

    grouped_odds = _group_by_event(odds_games)
    grouped_poly = _group_by_event(polymarket_games)

    for odds_event_key, odds_event_games in grouped_odds.items():
        if not odds_event_games:
            continue

        sample_odds_game = odds_event_games[0]
        matching_poly_groups = _find_matching_polymarket_groups(
            sample_odds_game,
            grouped_poly.values(),
        )

        for poly_event_games in matching_poly_groups:
            event_opportunities = _match_event_markets(
                odds_event_games,
                poly_event_games,
                clob_price_lookup,
            )
            opportunities.extend(event_opportunities)

    unique: dict[tuple[str, str, str, str, str], ArbitrageOpportunity] = {}

    for item in opportunities:
        key = (
            item.home_team,
            item.away_team,
            item.commence_time,
            item.market_title,
            item.selection_name,
        )
        existing = unique.get(key)
        if existing is None or item.expected_profit_percent > existing.expected_profit_percent:
            unique[key] = item

    return sorted(
        unique.values(),
        key=lambda x: x.expected_profit_percent,
        reverse=True,
    )


def _group_by_event(games: Iterable[Game]) -> dict[tuple[str, str, str], list[Game]]:
    grouped: dict[tuple[str, str, str], list[Game]] = {}

    for game in games:
        key = (
            clean(game.home_team),
            clean(game.away_team),
            game.commence_time,
        )
        grouped.setdefault(key, []).append(game)

    return grouped


def _find_matching_polymarket_groups(
    odds_game: Game,
    polymarket_groups: Iterable[list[Game]],
) -> list[list[Game]]:
    matches: list[list[Game]] = []

    odds_home = clean(odds_game.home_team)
    odds_away = clean(odds_game.away_team)

    for poly_games in polymarket_groups:
        if not poly_games:
            continue

        poly_sample = poly_games[0]
        poly_home = clean(poly_sample.home_team)
        poly_away = clean(poly_sample.away_team)

        names_match = (
            odds_home == poly_home and odds_away == poly_away
        ) or (
            odds_home == poly_away and odds_away == poly_home
        )

        if not names_match:
            continue

        poly_start = poly_sample.commence_time
        poly_end = poly_sample.commence_time

        if not is_target_single_game(odds_game.commence_time, poly_start, poly_end):
            continue

        matches.append(poly_games)

    return matches


def _match_event_markets(
    odds_games: list[Game],
    poly_games: list[Game],
    clob_price_lookup: dict[tuple[str, str, str], Decimal | None],
) -> list[ArbitrageOpportunity]:
    opportunities: list[ArbitrageOpportunity] = []

    odds_by_market: dict[str, list[Game]] = {}
    poly_by_market: dict[str, list[Game]] = {}

    for game in odds_games:
        odds_by_market.setdefault(game.market_title, []).append(game)

    for game in poly_games:
        poly_by_market.setdefault(_normalize_poly_market_title(game.market_title), []).append(game)

    for odds_market_title, odds_market_games in odds_by_market.items():
        poly_market_title = _map_odds_market_to_poly_market(odds_market_title)
        if not poly_market_title:
            continue

        poly_market_games = poly_by_market.get(poly_market_title, [])
        if not poly_market_games:
            continue

        for poly_game in poly_market_games:
            clob_key = (poly_game.event_id, poly_game.market_title, poly_game.selection_name)
            poly_price = clob_price_lookup.get(clob_key)

            if poly_price is None:
                continue

            hedge_odds_game = _find_opposite_odds_leg(odds_market_games, poly_game)
            if hedge_odds_game is None:
                continue

            try:
                implied_total = poly_price + (Decimal("1") / Decimal(str(hedge_odds_game.price)))
            except Exception as exc:
                logger.warning(f"Could not calculate implied total: {exc}")
                continue

            if implied_total >= Decimal("1"):
                continue

            expected_profit_percent = ((Decimal("1") / implied_total) - Decimal("1")) * Decimal("100")
            edge_percent = (Decimal("1") - implied_total) * Decimal("100")

            try:
                opportunities.append(
                    ArbitrageOpportunity(
                        sport_key=hedge_odds_game.sport_key,
                        home_team=hedge_odds_game.home_team,
                        away_team=hedge_odds_game.away_team,
                        commence_time=hedge_odds_game.commence_time,
                        market_title=odds_market_title,
                        selection_name=poly_game.selection_name,
                        bookmaker=hedge_odds_game.bookmaker,
                        odds_decimal=float(hedge_odds_game.price),
                        poly_price=float(poly_price),
                        implied_total=float(implied_total),
                        edge_percent=float(edge_percent),
                        expected_profit_percent=float(expected_profit_percent),
                        odds_url=hedge_odds_game.url,
                        polymarket_url=poly_game.url,
                    )
                )
            except ValueError as exc:
                logger.warning(f"Skipping invalid arbitrage opportunity: {exc}")

    return opportunities


def _normalize_poly_market_title(market_title: str) -> str:
    value = market_title.strip().lower()

    mapping = {
        "moneyline": "h2h",
        "first_half_moneyline": "h2h_h1",
        "total": "totals",
        "totals": "totals",
        "spread": "spreads",
        "spreads": "spreads",
        "team_totals": "team_totals",
    }

    return mapping.get(value, value)


def _map_odds_market_to_poly_market(odds_market_title: str) -> str | None:
    lower_value = odds_market_title.lower()

    if lower_value.startswith("h2h_h1"):
        return "h2h_h1"
    if lower_value.startswith("h2h"):
        return "h2h"
    if lower_value.startswith("totals"):
        return "totals"
    if lower_value.startswith("spreads"):
        return "spreads"
    if lower_value.startswith("team_totals"):
        return "team_totals"

    return None


def _find_opposite_odds_leg(odds_market_games: list[Game], poly_game: Game) -> Game | None:
    poly_pick = clean(poly_game.selection_name)

    if poly_pick in {"over", "under"}:
        target = "under" if poly_pick == "over" else "over"
        for game in odds_market_games:
            if clean(game.selection_name) == target:
                return game
        return None

    poly_home = clean(poly_game.home_team)
    poly_away = clean(poly_game.away_team)

    for game in odds_market_games:
        odds_pick = clean(game.selection_name)

        if odds_pick == poly_home and poly_pick == poly_away:
            return game
        if odds_pick == poly_away and poly_pick == poly_home:
            return game

    return None
