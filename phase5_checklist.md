# Phase 5 PR Review Checklist

**Scope:** Broker adapter (ib_async) **with fakes only**. No live orders, no TWS/Gateway connectivity, no network I/O.

---

## Quick gates
- [ ] No API credentials or other secrets committed (see SRS §11)
- [ ] Changes limited to broker-provider layer (e.g., `ibkr_provider.py`, `tests/test_ibkr_provider_*.py`)
- [ ] **Do not** import `ib_insync`; **must** use `ib_async` (or interface-only for this phase)
- [ ] No edits to order executor beyond wiring to the provider interface and fakes
- [ ] No live credentials, tokens, or endpoints; tests run completely offline
- [ ] PR description references relevant SRS acceptance criteria (AC#)
- [ ] CHANGELOG.md updated under the latest release heading

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [ ] Diff coverage ≥ **90%** for new/changed code

## Alignment with SRS
- [ ] Provider interface defines **only** what the app needs (YAGNI):      `connect()`, `disconnect()`, `resolve_contract(symbol, currency, exchange)`, `get_quote(contract)`,      `get_account_values()`, `get_positions()`, `place_order(contract, order)`, `cancel(order_id)`,      `wait_for_fills(order_ids)`, pacing/backoff hooks
- [ ] **FakeIB** (deterministic, in-memory) implements the interface and simulates fills/timestamps/IDs
- [ ] Live adapter `LiveIB` is **stubbed** behind the same interface, not exercised by tests
- [ ] Safety rails present even in fake: paper semantics, max concurrent orders, kill switch plumbing
- [ ] `price_source` fallback chain: `last` → `midpoint` → `bid/ask` → `snapshot`
- [ ] Optional snapshot mode controlled by config

## `ibkr_provider.py` — design
- [ ] Clear `Protocol`/ABC for the provider interface with typed DTOs (contracts, quotes, orders, fills)
- [ ] **Contracts:** equity (symbol/currency/exchange) and FX (e.g., `USD.CAD`, IDEALPRO)      normalization lives here, not in higher layers
- [ ] **Quotes:** integrates with pricing layer types (`Quote(bid, ask, ts)`); timestamps in UTC
- [ ] **Orders:** typed enums for side (`BUY`/`SELL`), type (`LMT`/`MKT`), TIF (`DAY`), route (`SMART`), RTH flag
- [ ] **Pacing:** backoff strategy hooks (callable or strategy object) invoked on simulated pacing limits
- [ ] **Errors:** custom exception types (e.g., `ProviderError`, `PacingError`, `ResolutionError`)

## `FakeIB` behavior
- [ ] Lifecycle: `connect()`/`disconnect()` change state and are idempotent
- [ ] Contract resolution table (dict) with predictable `conId` assignment; unknown symbols raise `ResolutionError`
- [ ] Quotes: seeded map or function; supports staleness simulation and missing bid/ask scenarios
- [ ] Orders: assigns incremental IDs; validates quantity>0, symbol tradability, and order fields
- [ ] Fills: deterministic fill policy (e.g., LMT fills if price crossing/capped; MKT fills immediately)
- [ ] Concurrency cap and pacing hooks are exercised (no real sleeps in tests)
- [ ] Event log (in-memory) for assertions (placed, canceled, filled, timestamps)

## Tests (component-level; no network)
- [ ] `connect()`/`disconnect()` idempotency + state assertions
- [ ] Contract resolution happy path + unknown symbol failure
- [ ] Quote retrieval with fresh, stale, and partial quotes (bid-only / ask-only) paths
- [ ] Order placement:      - LMT BUY that should fill; LMT SELL that should fill      - LMT that **should not** fill due to price; verify remains open/canceled      - MKT path exists but guarded by config (not default)
- [ ] `wait_for_fills` resolves to deterministic fills; times monotonic
- [ ] Pacing: exceeding cap triggers backoff hook; verify hook called with expected args
- [ ] Cancellation: cancel open order → status transitions validated
- [ ] FX contract + order supported (symbolization like `USD.CAD`), no execution wiring yet

## Code quality
- [ ] Interface & DTOs fully typed; no `Any` leakage
- [ ] Clear docstrings: contract normalization, price/size units, timezones, pacing semantics
- [ ] Errors are actionable; include symbol/order_id/context
- [ ] No implicit globals; fake’s state fully encapsulated and resettable between tests

## Safety & non-goals (Phase 5)
- [ ] **No** real TWS/Gateway connections or sockets opened
- [ ] **No** credentials read; environment access feature-flagged for later phases only
- [ ] Default order type remains **LMT**; market orders behind explicit config
- [ ] Paper-only behavior asserted in tests (even though provider is fake)

## Interfaces for later phases
- [ ] Provider plays nicely with executor sequencing (**FX → SELL → BUY**) when integrated
- [ ] `get_account_values()` exposes NetLiq/ExcessLiquidity placeholders for later validation
- [ ] Quote shape matches pricing module to enable spread-aware limits

## Acceptance examples (good to include in tests)
- [ ] Place two LMT SELLs and one BUY; verify `FakeIB` fills SELLs first when executor sequences
- [ ] Pacing cap set to 1; place 3 orders; verify backoff hook called twice with queued orders
- [ ] FX `USD.CAD` LMT at ask crosses → immediate simulated fill

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
