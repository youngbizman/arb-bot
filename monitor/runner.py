from __future__ import annotations

import json
import logging
from decimal import Decimal, getcontext
from typing import Any

from .alerts import build_alert_messages, build_no_opportunities_message
from .api_clients import ApiClients
from .config import ConfigError, load_settings
from .matching import find_arbitrage_opportunities
from .models import HealthSummary
from .parsers import parse_odds_api_games, parse_polymarket_markets


logger = logging.getLogger(__name__)

getcontext().prec = 28


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error(f"Configuration error: {exc}")
        raise

    clients = ApiClients(settings)

    try:
        logger.info("📡 Initializing arbitrage scanner...")

        raw_odds_games = clients.get_fiat_data()
        raw_polymarket_events = clients.get_polymarket_events()

        odds_games = parse_odds_api_games(raw_odds_games)
        polymarket_games = parse_polymarket_markets(raw_polymarket_events)
        clob_price_lookup = _build_clob_price_lookup(clients, raw_polymarket_events)

        opportunities = find_arbitrage_opportunities(
            odds_games=odds_games,
            polymarket_games=polymarket_games,
            clob_price_lookup=clob_price_lookup,
        )

        summary = HealthSummary(
            odds_events_seen=len(raw_odds_games),
            polymarket_events_seen=len(raw_polymarket_events),
            matched_pairs=len(opportunities),
            opportunities_found=len(opportunities),
            parse_errors=0,
            request_errors=0,
        )

        logger.info(
            f"Health summary | odds={summary.odds_events_seen} "
            f"polymarket={summary.polymarket_events_seen} "
            f"matches={summary.matched_pairs} "
            f"opportunities={summary.opportunities_found}"
        )

        if not opportunities:
            logger.info(build_no_opportunities_message())
            return

        alert_messages = build_alert_messages(opportunities, limit=3)

        logger.info(f"🔥 Found {len(opportunities)} opportunities. Sending top {len(alert_messages)}.")

        for message in alert_messages:
            logger.info("-> Sending Telegram alert")
            clients.send_telegram_alert(message)

    finally:
        clients.close()


def _build_clob_price_lookup(
    clients: ApiClients,
    raw_polymarket_events: list[dict[str, Any]],
) -> dict[tuple[str, str, str], Decimal | None]:
    lookup: dict[tuple[str, str, str], Decimal | None] = {}

    for event in raw_polymarket_events:
        if not isinstance(event, dict):
            continue

        event_id = str(event.get("id", "")).strip()
        markets = event.get("markets", [])
        if not event_id or not isinstance(markets, list):
            continue

        for market in markets:
            if not isinstance(market, dict):
                continue

            if not market.get("acceptingOrders"):
                continue

            market_title = str(market.get("sportsMarketType", "")).strip()
            if not market_title:
                market_title = str(market.get("question", "")).strip()

            outcomes = _safe_json_list(market.get("outcomes", []))
            token_ids = _safe_json_list(market.get("clobTokenIds", []))

            if not outcomes or not token_ids:
                continue

            if len(outcomes) != len(token_ids):
                continue

            for index, outcome_name in enumerate(outcomes):
                selection_name = str(outcome_name).strip()
                token_id = str(token_ids[index]).strip()

                if not selection_name or not token_id:
                    continue

                lookup[(event_id, market_title, selection_name)] = clients.get_clob_best_ask(token_id)

    return lookup


def _safe_json_list(value: Any) -> list[Any]:
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
