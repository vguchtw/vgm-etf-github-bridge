# VGM ETF GitHub Bridge

A simulation-first Docker service for coordinating monthly ETF decisions through a GitHub repository.

## Responsibilities

The container is authoritative for:

- portfolio state;
- simulation date;
- execution;
- market-price lookup;
- validation;
- request creation;
- append-only local audit history.

ChatGPT is only an allocation committee. It may write a proposed decision to GitHub, but it never executes an order or advances the clock.

## Modes

### `historical`

Starts from the configured historical date and €10,000 cash by default. One accepted decision advances the simulation by exactly one calendar month.

### `live_simulation`

Uses the current UTC month and a paper portfolio. It never sends a broker or exchange order.

### `live`

Uses the current UTC month and requires all of the following:

1. `VGM_MODE=live`;
2. `ENABLE_LIVE_TRADING=true`;
3. a configured exchange adapter;
4. a valid decision;
5. local validation.

No live exchange adapter is included in this MVP. Therefore the supplied project cannot place live orders.

## GitHub repository layout

```text
policy/policy.json
requests/pending/<request_id>.json
requests/processed/<request_id>.json
decisions/pending/<simulation_id>-<period>-<timestamp>.json
decisions/accepted/<decision filename>
decisions/rejected/<decision filename>
status/bridge-status.json
README.md
```

The container creates missing communication folders using `.gitkeep` files.

## Local persistent history

Under `/opt/vgm-etf-bridge`:

```text
config/config.json
repo/
state/state.json
history/events.jsonl
history/requests/
history/decisions/
history/executions/
reports/monthly/
logs/
```

`events.jsonl` is append-only. Every request, decision validation, execution, price lookup, state change, and failure is recorded with UTC timestamps.

## Installation

```bash
sudo mkdir -p /opt/vgm-etf-bridge/config
sudo chown -R "$USER":"$USER" /opt/vgm-etf-bridge

cp .env.example .env
cp config.example.json /opt/vgm-etf-bridge/config/config.json

# Edit .env and config.json.
docker compose build
docker compose up -d
docker compose logs -f
```

## GitHub authentication

HTTPS mode:

- create a fine-grained GitHub token scoped only to the communication repository;
- grant Contents read/write;
- place it in `.env` as `GITHUB_TOKEN`;
- never commit `.env`.

SSH mode is also supported using `GITHUB_AUTH_MODE=ssh` and the read-only host SSH mount.

## Bootstrap

On first start the service:

1. clones the repository;
2. creates the repository contract folders if absent;
3. installs `policy.example.json` as `policy/policy.json` if no policy exists;
4. creates an initial state with €10,000 cash;
5. creates the first request.

## Request lifecycle

1. The container creates one request for the current simulated period.
2. It commits and pushes the request.
3. The ChatGPT Scheduled Task creates one matching decision.
4. The container pulls, validates, and executes it.
5. The request and decision are archived in GitHub.
6. Local state and history are updated.
7. In historical mode, the date advances by one month and a new request is committed.

## Important limitation

Whether a ChatGPT Scheduled Task can write to GitHub unattended depends on the connector permissions and the Scheduled Task runtime. The container safely remains idle when no valid decision appears. It never guesses a decision and never advances the month without a valid decision.
