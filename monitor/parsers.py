from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .models import Game


logger = logging.getLogger(__name__)


def clean(text: str | None) -> str:
    if not text:
        return ""
    return text.lower().replace("trail blazers", "blazers").split()[-1]


def parse_iso8601_to_epoch(time_str: str | None) -> int:
    if not time_str:
        return 0

    normalized = time_str.replace(" ", "T")

    if normalized.endswith("+00"):
        normalized += ":00"

    if normalized.endswith("Z"):
        normalized = normalized.replace("Z", "+00:00")

    try:
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        try:
            fallback = datetime.strptime(normalized[:19], "%Y-%m-%dT%H:%M:%S")
            return int(fallback.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return 0


def is_target_single_game(
    fiat_commence_time: str | None,
    poly_start: str | None,
    poly_end: str | None,
) -> bool:
    t_commence = parse_iso8601_to_epoch(fiat_commence_time)
    t_game = parse_iso8601_to_epoch(poly_start)
    t_end = parse_iso8601_to_epoch(poly_end)

    if t_commence == 0:
        return False

    if t_game > 0 and abs(t_game - t_commence) > 14400:
        return False

    if t_end > 0 and abs(t_end - t_commence) > (48 * 3600):
        return False

    return True


def parse_odds_api_games(raw_games: list[dict[str, Any]]) -> list[Game]:
    parsed_games: list[Game] = []

    for raw_game in raw_games:
        if not isinstance(raw_game, dict):
            continue

        home_team = str(raw_game.get("home_team", "")).strip()
        away_team = str(raw_game.get("away_team", "")).strip()
        commence_time = str(raw_game.get("commence_time", "")).strip()
        sport_key = str(raw_game.get("sport_key", "")).strip()
        event_id = str(raw_game.get("id", "")).strip()

        bookmakers = raw_game.get("bookmakers", [])
        if not isinstance(bookmakers, list):
            continue

        for bookmaker in bookmakers:
            if not isinstance(bookmaker, dict):
                continue

            bookmaker_title = str(bookmaker.get("title", "")).strip()
            markets = bookmaker.get("markets", [])
            if not isinstance(markets, list):
                continue

            for market in markets:
                if not isinstance(market, dict):
                    continue

                market_key = str(market.get("key", "")).strip()
                outcomes = market.get("outcomes", [])
                if not isinstance(outcomes, list):
                    continue

                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue

                    selection_name = str(outcome.get("name", "")).strip()
                    raw_price = outcome.get("price")

                    try:
                        price = float(raw_price)
                    except (TypeError, ValueError):
                        continue

                    point = outcome.get("point")
                    description = str(outcome.get("description", "")).strip()

                    market_title = market_key
                    if point is not None:
                        market_title = f"{market_key}:{point}"
                    if description:
                        market_title = f"{market_title}:{description}"

                    try:
                        parsed_games.append(
                            Game(
                                source="odds_api",
                                event_id=event_id,
                                sport_key=sport_key,
                                home_team=home_team,
                                away_team=away_team,
                                commence_time=commence_time,
                                market_title=market_title,
                                selection_name=selection_name,
                                price=price,
                                bookmaker=bookmaker_title,
                                url="",
                            )
                        )
                    except ValueError as exc:
                        logger.warning(f"Skipping invalid Odds API game row: {exc}")

    return parsed_games


def parse_polymarket_markets(raw_events: list[dict[str, Any]]) -> list[Game]:
    parsed_games: list[Game] = []

    for event in raw_events:
        if not isinstance(event, dict):
            continue

        event_id = str(event.get("id", "")).strip()
        sport_key = str(event.get("seriesSlug", "polymarket")).strip() or "polymarket"
        title = str(event.get("title", "")).strip()
        home_team, away_team = _split_event_title(title)

        commence_time = (
            str(event.get("gameStartTime", "")).strip()
            or str(event.get("eventStartTime", "")).strip()
        )

        markets = event.get("markets", [])
        if not isinstance(markets, list):
            continue

        for market in markets:
            if not isinstance(market, dict):
                continue

            if not market.get("acceptingOrders"):
                continue

            market_title = str(market.get("sportsMarketType", "")).strip()
            if not market_title:
                market_title = str(market.get("question", "")).strip()

            raw_outcomes = market.get("outcomes", [])
            raw_token_ids = market.get("clobTokenIds", [])

            outcomes = _coerce_json_list(raw_outcomes)
            token_ids = _coerce_json_list(raw_token_ids)

            if not outcomes or not token_ids:
                continue

            if len(outcomes) != len(token_ids):
                continue

            for index, outcome_name in enumerate(outcomes):
                selection_name = str(outcome_name).strip()
                token_id = str(token_ids[index]).strip()

                if not selection_name or not token_id:
                    continue

                try:
                    parsed_games.append(
                        Game(
                            source="polymarket",
                            event_id=event_id,
                            sport_key=sport_key,
                            home_team=home_team,
                            away_team=away_team,
                            commence_time=commence_time,
                            market_title=market_title,
                            selection_name=selection_name,
                            price=0.01,
                            bookmaker="polymarket",
                            url="",
                        )
                    )
                except ValueError as exc:
                    logger.warning(f"Skipping invalid Polymarket row: {exc}")

    return parsed_games


def _coerce_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return []

    return []


def _split_event_title(title: str) -> tuple[str, str]:
    separators = [" vs ", " v ", " at "]

    lowered = title.lower()
    for separator in separators:
        if separator in lowered:
            parts = title.split(separator, 1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()

    return title.strip(), ""
