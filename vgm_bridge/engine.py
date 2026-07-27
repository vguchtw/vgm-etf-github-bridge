from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dateutil.relativedelta import relativedelta
from pydantic import ValidationError

from .git_repo import GitRepository
from .market import period_end_price
from .models import AppConfig, Decision, PortfolioState, Request
from .util import append_jsonl, atomic_write_json, read_json, sha256_json, utc_iso


class Bridge:
    def __init__(self, data_dir: Path):
        self.data = data_dir
        self.config = AppConfig.model_validate(read_json(data_dir / "config/config.json"))
        self.mode = os.environ.get("VGM_MODE", "historical")
        self.poll_seconds = int(os.environ.get("POLL_SECONDS", "60"))
        self.repo = GitRepository(
            root=data_dir / "repo",
            repository=os.environ["GITHUB_REPOSITORY"],
            branch=os.environ.get("GITHUB_BRANCH", "main"),
            auth_mode=os.environ.get("GITHUB_AUTH_MODE", "https"),
        )
        self.events = data_dir / "history/events.jsonl"
        self.state_path = data_dir / "state/state.json"

    def event(self, kind: str, **payload) -> None:
        append_jsonl(self.events, {"at_utc": utc_iso(), "kind": kind, **payload})

    def _period_now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _initial_period(self) -> str:
        if self.mode == "historical":
            return self.config.historical_start[:7]
        return self._period_now()

    def _build_state_hash(self, payload: dict) -> str:
        clean = dict(payload)
        clean.pop("state_hash", None)
        clean.pop("updated_at_utc", None)
        return sha256_json(clean)

    def load_or_create_state(self) -> PortfolioState:
        if self.state_path.exists():
            return PortfolioState.model_validate(read_json(self.state_path))
        payload = {
            "schema_version": "1.0",
            "simulation_id": self.config.simulation_id,
            "mode": self.mode,
            "status": "running",
            "period": self._initial_period(),
            "cash": self.config.initial_cash,
            "positions": {},
            "last_prices": {},
            "portfolio_value": self.config.initial_cash,
            "weights": {"CASH": 1.0},
            "updated_at_utc": utc_iso(),
        }
        payload["state_hash"] = self._build_state_hash(payload)
        state = PortfolioState.model_validate(payload)
        atomic_write_json(self.state_path, state.model_dump())
        self.event("state_created", state=state.model_dump())
        return state

    def ensure_repo_contract(self) -> None:
        folders = [
            "policy",
            "requests/pending",
            "requests/processed",
            "decisions/pending",
            "decisions/accepted",
            "decisions/rejected",
            "status",
        ]
        for folder in folders:
            path = self.repo.root / folder / ".gitkeep"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

        policy = self.repo.root / "policy/policy.json"
        if not policy.exists():
            source = Path("/app/policy.example.json")
            shutil.copy2(source, policy)

        self.repo.add_commit_push("Initialize VGM ETF communication contract")

    def _portfolio_payload(self, state: PortfolioState) -> dict:
        return {
            "cash": state.cash,
            "positions": state.positions,
            "last_prices": state.last_prices,
            "portfolio_value": state.portfolio_value,
            "current_weights": state.weights,
        }

    def create_request_if_needed(self, state: PortfolioState) -> Path | None:
        existing = list((self.repo.root / "requests/pending").glob("*.json"))
        for candidate in existing:
            try:
                data = read_json(candidate)
                if (
                    data.get("simulation_id") == state.simulation_id
                    and data.get("decision_period") == state.period
                    and data.get("input_state_hash") == state.state_hash
                ):
                    return None
            except Exception:
                continue

        request_id = f"{state.simulation_id}-{state.period}-{uuid.uuid4().hex[:12]}"
        simulation_only = self.mode != "live"
        request = Request(
            request_id=request_id,
            simulation_id=state.simulation_id,
            mode=self.mode,
            simulation_only=simulation_only,
            status=state.status,
            decision_period=state.period,
            created_at_utc=utc_iso(),
            input_state_hash=state.state_hash,
            base_currency=self.config.base_currency,
            portfolio=self._portfolio_payload(state),
            eligible_symbols=[*self.config.eligible_etfs, "CASH"],
            policy_path="policy/policy.json",
            evidence={
                "as_of_period": state.period,
                "source": "container_state_only",
                "note": "No facts after this simulated period may be used.",
            },
            instructions={
                "one_month_only": True,
                "server_is_authoritative": True,
                "do_not_modify_state": True,
            },
        )
        path = self.repo.root / f"requests/pending/{request_id}.json"
        atomic_write_json(path, request.model_dump())
        local = self.data / f"history/requests/{path.name}"
        atomic_write_json(local, request.model_dump())
        self.repo.add_commit_push(f"Request allocation for {state.period}")
        self.event("request_created", request_id=request_id, period=state.period)
        return path

    def _load_policy(self) -> dict:
        return read_json(self.repo.root / "policy/policy.json")

    def _turnover(self, current: dict[str, float], target: dict[str, float]) -> float:
        symbols = set(current) | set(target)
        return 0.5 * sum(abs(target.get(s, 0.0) - current.get(s, 0.0)) for s in symbols)

    def validate_decision(self, decision: Decision, state: PortfolioState, policy: dict) -> None:
        if decision.simulation_id != state.simulation_id:
            raise ValueError("simulation_id does not match")
        if decision.period != state.period:
            raise ValueError("period does not match current state")
        if decision.input_state_hash != state.state_hash:
            raise ValueError("input_state_hash does not match current state")

        allowed = set(policy["eligible_symbols"])
        unknown = set(decision.target_weights) - allowed
        if unknown:
            raise ValueError(f"ineligible symbols: {sorted(unknown)}")

        constraints = policy["constraints"]
        max_weight = float(constraints.get("max_single_etf_weight", 1.0))
        min_cash = float(constraints.get("min_cash_weight", 0.0))
        for symbol, weight in decision.target_weights.items():
            if symbol != "CASH" and weight > max_weight + 1e-9:
                raise ValueError(f"{symbol} exceeds max_single_etf_weight")
        if decision.target_weights.get("CASH", 0.0) + 1e-9 < min_cash:
            raise ValueError("CASH is below min_cash_weight")

        turnover = self._turnover(state.weights, decision.target_weights)
        max_turnover = float(constraints.get("max_turnover_per_period", 1.0))
        if decision.action == "rebalance" and turnover > max_turnover + 1e-9:
            raise ValueError(f"turnover {turnover:.6f} exceeds {max_turnover:.6f}")

        if self.mode == "live":
            if os.environ.get("ENABLE_LIVE_TRADING", "false").lower() != "true":
                raise ValueError("live trading safety gate is disabled")
            if not self.config.live_exchange_adapter:
                raise ValueError("no live exchange adapter configured")

    def _prices(self, state: PortfolioState, symbols: set[str]) -> dict[str, float]:
        prices = {}
        for symbol in sorted(symbols):
            if symbol == "CASH":
                continue
            prices[symbol] = period_end_price(symbol, state.period)
        return prices

    def execute_simulation(self, decision: Decision, state: PortfolioState) -> PortfolioState:
        symbols = set(decision.target_weights) | set(state.positions)
        prices = self._prices(state, symbols)
        value_before = state.cash + sum(
            quantity * prices.get(symbol, state.last_prices.get(symbol, 0.0))
            for symbol, quantity in state.positions.items()
        )

        target_positions: dict[str, float] = {}
        for symbol, weight in decision.target_weights.items():
            if symbol == "CASH" or weight == 0:
                continue
            target_positions[symbol] = (value_before * weight) / prices[symbol]
        cash = value_before * decision.target_weights.get("CASH", 0.0)

        if self.mode == "historical":
            next_period = (
                datetime.strptime(state.period + "-01", "%Y-%m-%d")
                + relativedelta(months=1)
            ).strftime("%Y-%m")
        else:
            next_period = self._period_now()

        status = "running"
        if self.mode == "historical" and self.config.historical_end:
            if next_period > self.config.historical_end[:7]:
                status = "completed"

        payload = {
            "schema_version": "1.0",
            "simulation_id": state.simulation_id,
            "mode": self.mode,
            "status": status,
            "period": next_period,
            "cash": cash,
            "positions": target_positions,
            "last_prices": prices,
            "portfolio_value": value_before,
            "weights": decision.target_weights,
            "updated_at_utc": utc_iso(),
        }
        payload["state_hash"] = self._build_state_hash(payload)
        return PortfolioState.model_validate(payload)

    def _matching_requests(self, state: PortfolioState) -> list[Path]:
        matches = []
        for path in (self.repo.root / "requests/pending").glob("*.json"):
            try:
                item = read_json(path)
                if (
                    item.get("simulation_id") == state.simulation_id
                    and item.get("decision_period") == state.period
                    and item.get("input_state_hash") == state.state_hash
                ):
                    matches.append(path)
            except Exception:
                pass
        return matches

    def process_decisions(self, state: PortfolioState) -> PortfolioState:
        policy = self._load_policy()
        candidates = sorted((self.repo.root / "decisions/pending").glob("*.json"))
        for path in candidates:
            try:
                decision = Decision.model_validate(read_json(path))
                if decision.simulation_id != state.simulation_id or decision.period != state.period:
                    continue
                self.validate_decision(decision, state, policy)

                if self.mode == "live":
                    raise NotImplementedError(
                        "Live exchange execution is intentionally not implemented in this MVP"
                    )

                new_state = self.execute_simulation(decision, state)
                execution = {
                    "executed_at_utc": utc_iso(),
                    "mode": self.mode,
                    "decision": decision.model_dump(),
                    "state_before": state.model_dump(),
                    "state_after": new_state.model_dump(),
                }
                atomic_write_json(
                    self.data / f"history/decisions/{path.name}",
                    decision.model_dump(),
                )
                atomic_write_json(
                    self.data / f"history/executions/{decision.decision_id}.json",
                    execution,
                )
                atomic_write_json(self.state_path, new_state.model_dump())

                accepted = self.repo.root / "decisions/accepted" / path.name
                path.replace(accepted)
                for request_path in self._matching_requests(state):
                    request_path.replace(
                        self.repo.root / "requests/processed" / request_path.name
                    )
                self.repo.add_commit_push(
                    f"Accept allocation {decision.decision_id} for {decision.period}"
                )
                self.event(
                    "decision_executed",
                    decision_id=decision.decision_id,
                    period=decision.period,
                    portfolio_value=new_state.portfolio_value,
                )
                return new_state

            except (ValidationError, ValueError, NotImplementedError, Exception) as exc:
                # Only reject files that clearly target the current simulation/period.
                try:
                    raw = read_json(path)
                    if (
                        raw.get("simulation_id") != state.simulation_id
                        or raw.get("period") != state.period
                    ):
                        continue
                except Exception:
                    pass
                rejected = self.repo.root / "decisions/rejected" / path.name
                path.replace(rejected)
                reason_path = rejected.with_suffix(".reason.json")
                atomic_write_json(reason_path, {"rejected_at_utc": utc_iso(), "reason": str(exc)})
                self.repo.add_commit_push(f"Reject invalid allocation for {state.period}")
                self.event("decision_rejected", file=path.name, reason=str(exc))
        return state

    def write_status(self, state: PortfolioState) -> None:
        status = {
            "schema_version": "1.0",
            "updated_at_utc": utc_iso(),
            "simulation_id": state.simulation_id,
            "mode": self.mode,
            "status": state.status,
            "period": state.period,
            "state_hash": state.state_hash,
            "portfolio_value": state.portfolio_value,
        }
        atomic_write_json(self.repo.root / "status/bridge-status.json", status)
        self.repo.add_commit_push(f"Update bridge status for {state.period}")

    def setup(self) -> PortfolioState:
        self.repo.ensure_clone()
        self.repo.pull()
        self.ensure_repo_contract()
        state = self.load_or_create_state()
        self.create_request_if_needed(state)
        self.write_status(state)
        return state

    def run_forever(self) -> None:
        state = self.setup()
        while True:
            try:
                self.repo.pull()
                state = PortfolioState.model_validate(read_json(self.state_path))
                if state.status == "running":
                    state = self.process_decisions(state)
                    if state.status == "running":
                        self.create_request_if_needed(state)
                self.write_status(state)
            except Exception as exc:
                self.event("loop_error", reason=str(exc))
            time.sleep(self.poll_seconds)
