# Phase 4 PR Review Checklist

**Scope:** FX funding logic (math/plan only). No broker/`ib_async`, no live orders or network I/O.

---

## Quick gates
- [ ] Changes limited to FX planning layer (e.g., `fx_engine.py`, minor wiring in planner + tests)
- [ ] No edits to order execution or broker adapter beyond **adding an FX intent type**
- [ ] No live connectivity; quotes are **fakes/mocks** only
- [ ] No new production deps beyond SRS/plan

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Local: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [ ] Diff coverage ≥ **90%** for new/changed code

## Alignment with SRS `[fx]`
- [ ] Respects config switches: `enabled`, `pair="USD.CAD"`, `fx_buffer_bps`, `min_fx_order_usd`, `max_fx_order_usd` (optional), `allow_market`, `limit_offset_pips` (or reuse spread-aware knobs)
- [ ] Treats **CAD cash as available** to fund **USD ETF buys**
- [ ] Computes **USD shortfall** from planned USD‑denominated BUYs and current cash (after any sell proceeds if planner models that)
- [ ] Applies **buffer**: shortfall × (1 + buffer_bps/10_000)
- [ ] Enforces **minimum FX order** in USD notionals; ignores tiny shortfalls below threshold
- [ ] Produces an **FX plan/intent** object (no placement): side=`BUY USD.CAD`, qty notionals, indicative price, reasoning
- [ ] No position side effects; returns data used later by executor in Phase 6

## `fx_engine.py` (core API)
- [ ] Pure function(s), e.g.:
  ```py
  def plan_fx_if_needed(
      usd_needed: float,
      usd_cash: float,
      cad_cash: float,
      fx_quote: Quote | None,
      cfg: FxConfig,
  ) -> FxPlan
  ```
- [ ] `FxPlan` typed dataclass includes:
  - [ ] `need_fx: bool`
  - [ ] `pair: str` (e.g., "USD.CAD")
  - [ ] `side: Literal["BUY","SELL"]` (BUY USD.CAD to raise USD)
  - [ ] `usd_notional: float`, `est_rate: float`, `qty: float` (units of base or quote clearly documented)
  - [ ] `order_type: Literal["LMT","MKT"]`, `limit_price: float | None`
  - [ ] `reason: str` (human‑readable: “fund USD shortfall of X with buffer Ybps”)
- [ ] Accepts **no** network calls; `Quote` comes from `FakeQuoteProvider`

## Pricing behavior (still offline)
- [ ] If `order_type="LMT"`: derive indicative limit from FX mid + `limit_offset_pips` (or spread‑aware if you reuse `limit_pricer` with FX tick)
- [ ] If quotes **stale/missing**: either use conservative fallback (documented) or return `need_fx=False` with reason
- [ ] Tick rounding: price rounded to **pip** (`0.0001`) unless configuration specifies different min tick
- [ ] Quantity rounding (if applicable) documented (e.g., 0.01 units)

## Tests (table‑driven/parameterized)
- [ ] **CAD‑only cash** + planned USD ETF buys → FX plan created (`BUY USD.CAD`) before equities
- [ ] **Tiny shortfall** below `min_fx_order_usd` → **no FX plan**
- [ ] **Buffer applied**: plan notional equals `max(0, (usd_needed - usd_cash)) * (1 + buffer_bps/10_000)` within rounding tolerance
- [ ] **Stale/missing quote** path covered (fallback or skip with reason)
- [ ] **Limit vs Market** branches: both paths tested per config
- [ ] **Tick rounding** for price and (if applicable) quantity respected
- [ ] Interaction with planner: when FX plan exists, equities BUY notional after FX is feasible in the math (no negative residual USD)
- [ ] Edge cases:
  - [ ] `usd_needed <= usd_cash` → no FX
  - [ ] `cad_cash == 0` → either skip with reason or return plan with quantity 0
  - [ ] Very large shortfalls respect optional `max_fx_order_usd` (if configured)

## Code quality
- [ ] Strong typing (`FxPlan`, `FxConfig`, `Quote`); explicit return types; no `Any` leakage
- [ ] Clear docstrings: base/quote conventions, rate definition (USD/CAD), units for `qty`
- [ ] Deterministic & side‑effect‑free; no time‑of‑day coupling
- [ ] Errors/warnings are actionable; include the computed shortfall and thresholds

## Interfaces for next phases
- [ ] Plan structure is easy for Phase 6 executor to consume (FX **before** ETF buys)
- [ ] Exposes updated **post‑FX cash forecast** fields or enough info for executor to compute them
- [ ] No hard dependency on `ib_async`; contracts/routes (e.g., IDEALPRO) remain **constants** in a shared schema, not used yet

## Acceptance examples (good to include in tests)
- [ ] Inputs: `usd_needed=10_000`, `usd_cash=1_000`, `cad_cash=20_000`, `fx_buffer_bps=25`, mid `1.3500` → plan `BUY USD.CAD` for **$11,250 USD** at limit `~1.3500 + offset` (pip‑rounded), or MKT if configured
- [ ] Inputs: `usd_needed=500`, `min_fx_order_usd=1_000` → **no FX plan** (reason mentions threshold)
- [ ] Stale quote (> `stale_quote_seconds`) → documented fallback path taken

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
