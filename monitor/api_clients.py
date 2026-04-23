from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings


logger = logging.getLogger(__name__)


class ApiClients:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
        )

        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": "arb-bot/1.0"})

        return session

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            url,
            params=params,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_fiat_data(self) -> list[dict[str, Any]]:
        url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
        params = {
            "apiKey": self.settings.odds_api_key,
            "regions": "eu,us",
            "markets": "h2h,totals,spreads",
            "bookmakers": "pinnacle,onexbet",
        }

        try:
            data = self._get_json(url, params=params)
            if isinstance(data, list):
                return data

            logger.warning("Odds API returned unexpected data format")
            return []

        except requests.RequestException as exc:
            logger.error(f"Odds API request failed: {exc}")
            return []
        except ValueError as exc:
            logger.error(f"Odds API returned invalid JSON: {exc}")
            return []

    def get_polymarket_events(self) -> list[dict[str, Any]]:
        url = "https://gamma-api.polymarket.com/events"
        params = {
            "series_id": 10345,
            "active": "true",
            "closed": "false",
            "limit": 100,
        }

        try:
            data = self._get_json(url, params=params)

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                events = data.get("events", [])
                if isinstance(events, list):
                    return events

            logger.warning("Polymarket returned unexpected data format")
            return []

        except requests.RequestException as exc:
            logger.error(f"Polymarket request failed: {exc}")
            return []
        except ValueError as exc:
            logger.error(f"Polymarket returned invalid JSON: {exc}")
            return []

    def get_clob_best_ask(self, token_id: str) -> Decimal | None:
        if not str(token_id).strip():
            return None

        url = "https://clob.polymarket.com/book"
        params = {"token_id": token_id}

        try:
            data = self._get_json(url, params=params)

            if not isinstance(data, dict):
                return None

            asks = data.get("asks", [])
            if not isinstance(asks, list):
                return None

            prices: list[Decimal] = []

            for ask in asks:
                if not isinstance(ask, dict):
                    continue

                raw_price = ask.get("price")
                if raw_price is None:
                    continue

                try:
                    prices.append(Decimal(str(raw_price)))
                except (InvalidOperation, ValueError, TypeError):
                    continue

            return min(prices) if prices else None

        except requests.RequestException as exc:
            logger.warning(f"CLOB request failed for token {token_id}: {exc}")
            return None
        except ValueError as exc:
            logger.warning(f"CLOB returned invalid JSON for token {token_id}: {exc}")
            return None

    def send_telegram_alert(self, message: str) -> bool:
        if not message.strip():
            return False

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": message,
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            return True

        except requests.RequestException as exc:
            logger.error(f"Telegram send failed: {exc}")
            return False

    def close(self) -> None:
        self.session.close()
