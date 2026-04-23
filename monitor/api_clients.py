from __future__ import annotations

import logging
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
            total=3, connect=3, read=3, backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": "arb-bot/2.0"})
        return session

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(url, params=params, timeout=self.settings.request_timeout_seconds)
        response.raise_for_status()
        return response.json()

    def get_fiat_data(self) -> list[dict[str, Any]]:
        url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
        params = {
            "apiKey": self.settings.odds_api_key,
            "regions": "eu,us",
            "markets": "h2h,totals,spreads",
            "bookmakers": "pinnacle,onexbet,draftkings",
        }
        try:
            data = self._get_json(url, params=params)
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error(f"Odds API request failed: {exc}")
            return []

    def get_polymarket_events(self) -> list[dict[str, Any]]:
        url = "https://gamma-api.polymarket.com/events"
        params = {"series_id": 10345, "active": "true", "closed": "false", "limit": 100}
        try:
            data = self._get_json(url, params=params)
            if isinstance(data, list): return data
            if isinstance(data, dict): return data.get("events", [])
            return []
        except Exception as exc:
            logger.error(f"Polymarket request failed: {exc}")
            return []

    # --- REFACTORED: Now returns the entire Ask Ladder ---
    def get_clob_asks(self, token_id: str) -> list[dict[str, Any]]:
        if not str(token_id).strip(): return []
        url = "https://clob.polymarket.com/book"
        params = {"token_id": token_id}
        try:
            data = self._get_json(url, params=params)
            if not isinstance(data, dict): return []
            return data.get("asks", [])
        except Exception as exc:
            logger.warning(f"CLOB request failed for token {token_id}: {exc}")
            return []

    def send_telegram_alert(self, message: str) -> bool:
        if not message.strip(): return False
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": self.settings.telegram_chat_id, "text": message}
        try:
            response = self.session.post(url, json=payload, timeout=self.settings.request_timeout_seconds)
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.error(f"Telegram send failed: {exc}")
            return False

    def close(self) -> None:
        self.session.close()
