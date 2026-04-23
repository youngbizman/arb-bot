from dataclasses import dataclass

@dataclass(frozen=True)
class Game:
    source: str
    event_id: str
    sport_key: str
    home_team: str
    away_team: str
    commence_time: str
    market_title: str
    selection_name: str
    price: float
    bookmaker: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Game.source cannot be empty")
        if not self.event_id.strip():
            raise ValueError("Game.event_id cannot be empty")
        if not self.home_team.strip():
            raise ValueError("Game.home_team cannot be empty")
        if not self.away_team.strip():
            raise ValueError("Game.away_team cannot be empty")
        if not self.market_title.strip():
            raise ValueError("Game.market_title cannot be empty")
        if not self.selection_name.strip():
            raise ValueError("Game.selection_name cannot be empty")
        if self.price <= 0:
            raise ValueError("Game.price must be greater than 0")


@dataclass(frozen=True)
class ArbitrageOpportunity:
    sport_key: str
    home_team: str
    away_team: str
    commence_time: str
    market_title: str
    selection_name: str
    fiat_selection: str  # <--- Added this field
    bookmaker: str
    odds_decimal: float
    poly_price: float
    implied_total: float
    edge_percent: float
    expected_profit_percent: float
    odds_url: str = ""
    polymarket_url: str = ""

    def __post_init__(self) -> None:
        if self.odds_decimal <= 1:
            raise ValueError("ArbitrageOpportunity.odds_decimal must be greater than 1")
        if not 0 < self.poly_price < 1:
            raise ValueError("ArbitrageOpportunity.poly_price must be between 0 and 1")
        if self.implied_total <= 0:
            raise ValueError("ArbitrageOpportunity.implied_total must be greater than 0")


@dataclass(frozen=True)
class HealthSummary:
    odds_events_seen: int = 0
    polymarket_events_seen: int = 0
    matched_pairs: int = 0
    opportunities_found: int = 0
    parse_errors: int = 0
    request_errors: int = 0

    def __post_init__(self) -> None:
        fields_to_check = {
            "odds_events_seen": self.odds_events_seen,
            "polymarket_events_seen": self.polymarket_events_seen,
            "matched_pairs": self.matched_pairs,
            "opportunities_found": self.opportunities_found,
            "parse_errors": self.parse_errors,
            "request_errors": self.request_errors,
        }

        for field_name, value in fields_to_check.items():
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")
