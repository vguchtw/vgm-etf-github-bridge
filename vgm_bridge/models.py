from __future__ import annotations

from datetime import datetime
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


Mode = Literal["historical", "live_simulation", "live"]


class AppConfig(BaseModel):
    schema_version: str = "1.0"
    simulation_id: str
    base_currency: str = "EUR"
    initial_cash: float = 10000.0
    historical_start: str
    historical_end: Optional[str] = None
    eligible_etfs: list[str]
    initial_weights: Dict[str, float] = {"CASH": 1.0}
    request_ttl_hours: int = 48
    max_decision_age_hours: int = 72
    live_exchange_adapter: Optional[str] = None


class PortfolioState(BaseModel):
    schema_version: str = "1.0"
    simulation_id: str
    mode: Mode
    status: Literal["running", "paused", "completed", "error"] = "running"
    period: str
    cash: float
    positions: Dict[str, float] = Field(default_factory=dict)
    last_prices: Dict[str, float] = Field(default_factory=dict)
    portfolio_value: float
    weights: Dict[str, float]
    state_hash: str
    updated_at_utc: str


class Request(BaseModel):
    schema_version: str = "1.0"
    request_id: str
    simulation_id: str
    mode: Mode
    simulation_only: bool
    status: Literal["running", "paused", "completed", "error"]
    decision_period: str
    created_at_utc: str
    input_state_hash: str
    base_currency: str
    portfolio: dict
    eligible_symbols: list[str]
    policy_path: str
    evidence: dict
    instructions: dict


class Decision(BaseModel):
    schema_version: str
    decision_id: str
    simulation_id: str
    period: str
    input_state_hash: str
    action: Literal["rebalance", "hold"]
    target_weights: Dict[str, float]
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("target_weights")
    @classmethod
    def validate_each_weight(cls, value: Dict[str, float]) -> Dict[str, float]:
        for symbol, weight in value.items():
            if not isinstance(symbol, str) or not symbol:
                raise ValueError("All target weight keys must be non-empty symbols")
            if weight < 0.0 or weight > 1.0:
                raise ValueError(f"Weight for {symbol} is outside [0,1]")
        return value

    @model_validator(mode="after")
    def validate_sum(self):
        total = sum(self.target_weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Target weights sum to {total}, not exactly 1.0")
        return self
