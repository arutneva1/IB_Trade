# Phase 9 PR Review Checklist

**Scope:** Live connectivity (restricted pilot) via `ib_async` behind the existing provider interface. Strong safety rails; default behavior remains **paper** unless explicitly gated.

---

## Quick gates
- [ ] PR limited to **Live adapter wiring** (`LiveIB` in `ibkr_provider.py` or separate module), ops tooling, and docs
- [ ] **Interface unchanged** for higher layers (executor/pricing do not change logic)
- [ ] No secrets committed; credentials pulled from **ENV/Secrets** (GitHub Actions, `.env` local ignored)
- [ ] Live behavior fully **feature‑flagged**; paper/dry‑run are the default modes
- [ ] PR description references relevant SRS acceptance criteria (AC#)
- [ ] CHANGELOG.md updated under the latest release heading

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Unit/component tests remain **offline**; no network in CI
- [ ] A **manual** workflow (workflow_dispatch) provided for pilot smoke checks (disabled by default)

## Alignment with SRS
- [ ] `price_source` fallback chain: `last` → `midpoint` → `bid/ask` → `snapshot`
- [ ] Optional snapshot mode controlled by config

## Safety & gating
- [ ] Live path requires **both**: CLI `--live --yes` **and** INI `paper_only=false`
- [ ] **KILL_SWITCH** file path checked before any placement; missing → abort with clear error
- [ ] **Account allow‑list**: live adapter verifies account id matches configured allow‑list
- [ ] **Max notional guard** per order & per run; exceeds → abort with detailed message
- [ ] **Market orders** remain disabled unless explicitly enabled in config
- [ ] **Read‑only dry‑run** supported even when connected (no placement)

## Live adapter (`LiveIB`) specifics
- [ ] Uses **`ib_async`** (community‑maintained); **no** `ib_insync`
- [ ] Connection lifecycle: `connect()`/`disconnect()` idempotent; reconnect strategy documented
- [ ] **TWS/Gateway endpoints** configurable; paper vs live endpoints supported
- [ ] Contract resolution matches FakeIB’s normalization (symbols, currency, exchange)
- [ ] Quotes API returns `Quote(bid, ask, ts)` with **UTC timestamps**
- [ ] Order placement: typed DTO → IB order; supports LMT/MKT per config; TIF=DAY; RTH flag
- [ ] Wait‑for‑fills honors timeouts; returns typed fill events with times & prices
- [ ] Pacing/backoff: retry policy, jitter, and max attempts documented & implemented

## Pacing & compliance
- [ ] Respects IBKR pacing: order rate limits, cancel/replace limits; testable via throttle hooks
- [ ] Backoff strategy configurable; default conservative
- [ ] Logs include pacing metrics and decisions (without leaking PII)

## Error handling & resilience
- [ ] Clear exception taxonomy (`ProviderError`, `AuthError`, `ConnectivityError`, `PacingError`, `OrderRejectedError`)
- [ ] Retryable vs non‑retryable errors separated; retries bounded
- [ ] Partial fill/timeout policies honored (cancel/continue) and surfaced to executor
- [ ] Graceful shutdown path cancels open staged orders if configured

## Observability
- [ ] Structured logs (JSON option); events include: connect, resolve, quote, place, fill, cancel, error
- [ ] Optional metrics hooks (counts, durations) behind interface; no vendor lock‑in
- [ ] Redaction of sensitive values (user, account, order ids as needed)

## Config & secrets
- [ ] INI keys documented for live: `[ibkr] host, port, client_id, account, paper, timeouts, pacing, kill_switch`
- [ ] ENV overrides supported (documented precedence: CLI > ENV > INI)
- [ ] Secrets via env/Actions secrets; `.env.example` provided; `.env` git‑ignored

## Tests (what must be covered offline)
- [ ] Contract mapping parity tests FakeIB ↔ LiveIB (shape & normalization)
- [ ] Serialization tests: DTO → IB order fields (no network)
- [ ] Backoff strategy unit tests (deterministic via seeded jitter)
- [ ] Executor integration **against FakeIB** remains green; LiveIB only smoke‑tested manually

## Manual smoke checklist (pilot run, not in CI)
- [ ] Connect to **paper** account; fetch account values and one symbol quote
- [ ] Place tiny LMT BUY/SELL for a test symbol; verify fills and logs; cancel path works
- [ ] FX tiny LMT (e.g., `USD.CAD`) at near‑mid; verify submission & (paper) fill
- [ ] Verify KILL_SWITCH behavior: remove file → placement refused
- [ ] Confirm pacing hook logs when exceeding configured cap

## Docs & runbook
- [ ] `README` Live section: how to set env/INI, start Gateway/TWS, verify connection, run dry‑run vs paper vs live
- [ ] **Runbook**: common errors, pacing rejections, reconnect steps, safe rollback
- [ ] **Incident procedures**: how to hit kill switch, how to cancel outstanding orders

## Acceptance examples
- [ ] With `--live --yes` + `paper_only=false` + kill switch present, a staged plan runs **paper** first; Live only on explicit paper=false and non‑paper endpoint
- [ ] Pacing guard blocks burst placements; backoff invoked; final submission succeeds within retry bounds
- [ ] On network drop mid‑run, reconnect occurs once; on failure, executor aborts with actionable summary

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
