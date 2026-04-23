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

@dataclass(frozen=True)
class ArbitrageOpportunity:
    sport_key: str
    home_team: str
    away_team: str
    commence_time: str
    market_title: str
    selection_name: str
    fiat_selection: str
    bookmaker: str
    odds_decimal: float
    
    # --- REFACTORED: Professional Financial Metrics ---
    vwap: float
    marginal_price: float
    poly_spend: float
    poly_fees: float
    sportsbook_stake: float
    total_outlay: float
    locked_profit: float
    expected_profit_percent: float
    
    odds_url: str = ""
    polymarket_url: str = ""

@dataclass(frozen=True)
class HealthSummary:
    odds_events_seen: int = 0
    polymarket_events_seen: int = 0
    matched_pairs: int = 0
    opportunities_found: int = 0
    parse_errors: int = 0
    request_errors: int = 0
