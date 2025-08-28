# Phase 6 PR Review Checklist

**Scope:** Order building & execution (dry‑run first) using fakes only. No live orders, no TWS/Gateway connectivity, no network I/O.

---

## Quick gates
- [ ] No API credentials or other secrets committed (see SRS §11)
- [ ] Changes limited to order layer (e.g., `order_builder.py`, `order_executor.py`, `safety.py`, tests)
- [ ] Uses provider **interface** + `FakeIB` only; *no* live `ib_async` calls
- [ ] No edits to pricing math except calling `limit_pricer`
- [ ] No credentials or endpoints touched
- [ ] PR description references relevant SRS acceptance criteria (AC#)
- [ ] CHANGELOG.md updated under the latest release heading

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [ ] Diff coverage ≥ **90%** for new/changed code

## Alignment with SRS
- [ ] Default **spread‑aware LMT** for equities via `limit_pricer` (NBBO caps enforced)
- [ ] TIF=**DAY**, Route=**SMART**, **RTH** respected by default
- [ ] `[rebalance]` knobs applied: tolerance bands, `min_order_usd`, `fractional_shares`, `allow_margin`/`max_leverage`
- [ ] `[limits]` knobs honored: `buy_offset_frac`, `sell_offset_frac`, `max_offset_bps`, `wide_spread_bps`, `stale_quote_seconds`, `escalate_action`, `use_ask_bid_cap`
- [ ] Sequencing: **FX → SELLS → BUYS**; buys may be scaled by realized sell proceeds/buying power
- [ ] Safety rails: `paper_only` default; `--live --yes` required for live (not in this phase), KILL_SWITCH, concurrency cap
- [ ] Dry‑run prints pre‑trade report + order plan; paper mode places orders only on `FakeIB`
- [ ] `price_source` fallback chain: `last` → `midpoint` → `bid/ask` → `snapshot`
- [ ] Optional snapshot mode controlled by config
- [ ] Applies `cash_buffer_pct` and `maintenance_buffer_pct` when sizing and sequencing orders

## `order_builder.py`
- [ ] Pure mapping of plan → broker orders (no side effects)
- [ ] Applies `limit_pricer` for all equity LMT prices; tick rounding using minTick
- [ ] FX orders built from `FxPlan` (pair, side `BUY USD.CAD`, LMT/MKT per config); pip rounding
- [ ] Fractional shares handling follows config; else round to nearest lot/share
- [ ] Validates symbol tradability and positive quantities before emitting
- [ ] DTOs typed (enums for side/type/TIF/route); no `Any` leakage

## `order_executor.py`
- [ ] **Dry‑run**: no orders placed; returns a summary (used in CLI/reporting)
- [ ] **Paper**: place orders through `FakeIB` via provider interface
- [ ] Sequencing enforced:
  1. **FX stage** (if plan exists): place; wait for fills (or configured pause)
  2. **Equity SELLS**
  3. **Equity BUYS** (scaled if needed; never exceed buying power/leverage)
- [ ] Concurrency cap for open orders; backoff/pacing hooks invoked (no real sleeps in tests)
- [ ] Waits for fills with timeouts; clear status transitions (submitted/open/filled/canceled)
- [ ] Error handling: aborts on safety violations with actionable messages
- [ ] Idempotency: safe to re‑run after failures (does not duplicate already‑filled work)
- [ ] Logging: structured, includes order ids, prices, quantities, and outcomes

## Tests (component level; offline with fakes)
- [ ] **Dry‑run** path returns plan + limit prices; no provider calls
- [ ] **FX first**: CAD‑only cash + USD buys ⇒ FX plan executed before any equity orders
- [ ] **Sells before buys**: verify event log order; buys scaled by sell proceeds if configured
- [ ] **NBBO cap** respected in placed LMT prices (BUY ≤ ask; SELL ≥ bid) with FakeQuoteProvider
- [ ] **Concurrency**: cap=1 with 3 orders ⇒ pacing hook called twice; no race conditions
- [ ] **Min order** filtering: tiny trades skipped with reason recorded
- [ ] **Tolerance bands**: no orders when drift ≤ band
- [ ] **Fractional vs whole** share behavior covered
- [ ] **Timeout/partial fill** scenarios handled (cancel or continue per policy)
- [ ] **Safety**: paper_only enforced; live flags ignored in this phase; kill switch honored
- [ ] **Deterministic**: tests use fixed quotes/timestamps (e.g., `freezegun`)

## Code quality
- [ ] Strong typing on public functions; explicit return types
- [ ] Clear docstrings: sequencing, scaling, and safety rules
- [ ] Small composable helpers (build → validate → execute → wait → summarize)
- [ ] No global mutable state; fakes reset between tests

## Interfaces for later phases
- [ ] Executor emits a post‑trade summary usable by reporting
- [ ] Hooks exist to integrate LiveIB in Phase 7/8 behind the same interface
- [ ] Error types align with provider exceptions for consistent handling

## Acceptance examples (good to include in tests)
- [ ] Plan: FX $10k USD, then SELL `GLD` 5 sh, BUY `GDX` 100 sh → event log shows FX→SELL→BUY with expected limit prices and fills
- [ ] Wide spread triggers escalation policy in `limit_pricer`; verify resulting order prices
- [ ] Concurrency=1 with three BUYS: order ids issued sequentially; fills recorded; pacing hook counts match

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
