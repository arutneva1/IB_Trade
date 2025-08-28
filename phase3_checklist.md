# Phase 3 PR Review Checklist

**Scope:** Account snapshot model (offline). No broker/`ib_async`, no network I/O.

---

## Quick gates
- [ ] Changes limited to account-state layer (e.g., `account_state.py`, related helpers/tests)
- [ ] No edits to order execution, IBKR adapter, or live connectivity
- [ ] No new production deps beyond SRS/plan

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [ ] Diff coverage ≥ **90%** for new/changed code

## Alignment with SRS
- [ ] Computes **current portfolio weights** from positions + prices
- [ ] Separates **cash by currency** (e.g., USD vs CAD) and exposes both
- [ ] Honors `[rebalance]` knobs: `cash_buffer_pct`, `min_order_usd`, `tolerance_bps` (as applicable in this phase)
- [ ] Excludes `CASH` from tradable symbols; retains for net/gross math
- [ ] Outputs both **gross** and **net** exposure figures
- [ ] No FX execution yet—only **read/compute** balances needed by Phase 4

## `account_state.py`
- [ ] Pure, deterministic functions (no I/O)
- [ ] Inputs:
  - [ ] `positions` structure (symbol → quantity; currency for cash)
  - [ ] `prices` (symbol → last/close/mock price)
  - [ ] `cash_balances` (currency → amount), e.g., `{ "USD": 1200.0, "CAD": 5000.0 }`
  - [ ] Config knobs (e.g., `cash_buffer_pct`)
- [ ] Derived outputs:
  - [ ] `market_value` per symbol
  - [ ] `total_equity` (with/without cash buffer)
  - [ ] `weights_current` (symbol → weight in % of **net** or **gross**, per SRS)
  - [ ] `usd_cash`, `cad_cash` (and generic per-currency map)
  - [ ] `gross_exposure`, `net_exposure`
- [ ] Handles zero-price, missing-price, or zero-qty gracefully with clear errors/warnings
- [ ] Rounding/precision rules documented (e.g., 1e-6 tolerance for sums)

## Tests (table‑driven/parameterized)
- [ ] Basic: long-only positions with USD cash → weights sum ~100% (±ε)
- [ ] With **cash buffer**: available cash reduced before sizing; weights reflect buffer
- [ ] With per‑currency cash: USD=0, CAD>0 → weights computed; CAD held for Phase 4 (no conversion here)
- [ ] Mixed positions (overlapping ETFs) compute correct per‑symbol market values and weights
- [ ] Edge cases:
  - [ ] No positions, cash only
  - [ ] Prices missing for a held symbol → descriptive error
  - [ ] Zero price or NaN price rejected with clear message
- [ ] Property tests (optional): weight normalization invariants; non‑negative market values

## Code quality
- [ ] Strong typing (no `Any` leakage); explicit return types
- [ ] Docstrings explain formulas for gross/net, cash handling, and buffer application
- [ ] Small, composable functions (parse → compute market values → compute totals → weights)
- [ ] No time‑of‑day or external state coupling

## Interfaces for next phase (FX)
- [ ] Exposes **USD shortfall** helper or enough fields so FX sizing can derive it
- [ ] Clear contract on currency map (keys are ISO codes; case‑sensitive policy documented)
- [ ] No assumptions about live FX rates (that’s Phase 4)

## Acceptance examples (good to include in tests)
- [ ] Positions: `GLD 10 @ 200`, `GDX 20 @ 30`, USD cash `1000` → weights computed correctly; cash buffer applied if set
- [ ] CAD‑only cash with USD ETFs: weights computed; **no FX trade** produced in Phase 3
- [ ] Sum of weights ≈ 100% (within tolerance) when including cash; equities‑only sum equals 100% when excluding cash by design

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
