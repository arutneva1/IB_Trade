
# IBKR ETF Rebalancer — Test‑First Implementation Plan (for OpenAI Codex)

This is a concrete, test‑first roadmap for building the **IBKR ETF Portfolio Rebalancer** described in the SRS. It emphasizes *small, verifiable steps* with unit/component/E2E tests and fakes, so bugs surface early.

> Key choices: `ib_async` (not ib_insync), default **spread‑aware limit pricing**, three model portfolios named **SMURF, BADASS, GLTR**, margin via **`CASH` negative row**, optional CAD→USD FX funding.

---

## 0) Prereqs, Tooling, and Definition of Done

**Python:** 3.11  
**Packages:** `ib_async`, `pydantic`, `pandas`, `typer`, `pytest`, `pytest-asyncio`, `hypothesis`, `freezegun`, `loguru`, `ruff`, `mypy`

**CI:** GitHub Actions (or similar) running lint, typecheck, tests on every PR.

**Definition of Done (for each PR):**
1. New/changed code has tests (≥90% coverage on the diff).
2. Lints (`ruff`), formats (`black`), and type‑checks (`mypy`) pass locally and in CI.
3. Clear docstrings + README/SRS section updated if behavior changes.
4. Deterministic tests (use `freezegun` for timestamps).

**Repo layout (target):**
```
ibkr_etf_rebalancer/
  app.py
  config.py
  portfolio_loader.py
  target_blender.py
  account_state.py
  pricing.py
  limit_pricer.py
  rebalance_engine.py
  fx_engine.py
  order_builder.py
  order_executor.py
  ibkr_provider.py         # ib_async adapter + FakeIB
  safety.py
  reporting.py
  util.py
  tests/
```

---

## 1) Phase 0 — Bootstrap & Guardrails

**Tasks**
- Create repo, `requirements.txt`, `pyproject.toml`/`setup.cfg`.
- Add `pre-commit` with `ruff`, `black`.
- Add GitHub Actions workflow for lint/type/test.
- Create `Makefile` or `invoke` tasks wrapping `ruff`, `mypy`, `pytest`, and sample run commands.
  Example:
  ```bash
  make lint test run
  ```
- Add empty modules with docstrings and TODOs.

**No external calls** yet.

**Acceptance**
- CI is green on an empty test suite with a single smoke test.

---

## 2) Phase 1 — Pure Core (No IB, No Network)

### 2.1 `portfolio_loader.py`
**Goal:** Parse `portfolios.csv` (SMURF/BADASS/GLTR). Support margin via **one** `CASH` row with **negative** `target_pct`. Extra columns `note`, `min_lot`, and `exchange` are ignored.
**Tests (pytest):**
- Valid CSV: each portfolio sums to 100% or `assets + CASH = 100%` when margin used.
- Exactly one `CASH` row allowed (if present) and must be negative.
- Error if a `CASH` row exists while `[rebalance].allow_margin` is false.
- Helpful error messages on violations.
- Table‑driven tests with small CSV fixtures.

### 2.2 `config.py`
**Goal:** Parse & validate `settings.ini` sections: `[ibkr] [models] [rebalance] [fx] [limits] [safety] [pricing] [io]` and optional `[symbol_overrides]` (see SRS).
**Tests:**
- Model weights sum to 1.0 (SMURF/BADASS/GLTR).
- Guard `allow_margin`, `max_leverage`, spread‑aware params, FX knobs.
- Validate `[pricing]` options: `price_source` chain and `fallback_to_snapshot` toggle.
- Parse/validate optional `[symbol_overrides]` mapping.
- Defaults and helpful error messages.

### 2.3 `target_blender.py`
**Goal:** Blend SMURF/BADASS/GLTR → final **asset** targets; `CASH` remains a borrow indicator (non‑tradable). Track **gross** vs **net**.  
**Tests:**
- Overlapping symbols combined properly.
- Normalization invariants (Hypothesis property tests).
- Gross exposure (sum of asset weights) and net exposure (after CASH) meet SRS constraints.

### 2.4 `rebalance_engine.py` (math only)
**Goal:** Given targets, current weights (passed in), tolerance bands, leverage, min order USD, fractional flag, and account buffers (`cash_buffer_pct`, `maintenance_buffer_pct`) → **trade plan** (no orders yet).
**Tests:**
- No trades when |drift| ≤ band.
- Overweight/underweight scenarios, min order filtering.
- Margin via `CASH=-50` (gross 150%), leverage cap enforced.
- Simulated scaling of buys after sells due to buying‑power limits, honoring `cash_buffer_pct` and `maintenance_buffer_pct`.
- `trigger_mode=total_drift`: individual drifts inside band (e.g., A=+60 bps, B=-60 bps, band=75 bps) but Σ|drift|=120 bps > `portfolio_total_band_bps`=100 bps ⇒ expect SELL A and BUY B.
- Whole-share rounding when `allow_fractional=false` (SRS §5.7).
- Validate that no symbol results in a negative position (SRS §5.7).

### 2.5 `reporting.py`
**Goal:** Pre‑trade report (CSV/Markdown); post‑trade skeleton.
**Tests:**
- Golden‑file comparisons for stable formatting.

---

## 3) Phase 2 — Spread‑Aware Limit Pricing (Still Offline)

### 3.1 `limit_pricer.py`
**Goal:** Default **LMT** calculator using NBBO (bid/ask), tick rounding, bps caps, and wide/stale escalation.  
**Tests:**
- BUY limit = `min(ask, round_to_tick(mid + buy_offset_frac*spread), mid*(1+max_offset_bps/10000))`.
- SELL symmetric; never beyond NBBO (`use_ask_bid_cap`).
- Spreads from 1–100 bps; different minTicks; stale quotes trigger escalation policy (`cross|market|keep`).

### 3.2 `pricing.py` (interface only)
**Goal:** Define `Quote(bid, ask, ts)` & a provider interface + **FakeQuoteProvider**. Support configurable `price_source` with full fallback chain and optional snapshot mode.
**Tests:**
- Staleness detection (`stale_quote_seconds`).
- Fallback selection if bid/ask missing, respecting `price_source` chain.
- Snapshot option honored.

---

## 4) Phase 3 — Account Snapshot Model (Offline)

### `account_state.py`
**Goal:** Compute current weights from positions + prices; apply `cash_buffer_pct`; read per‑currency cash (USD/CAD).  
**Tests:**
- Correct weight math with/without cash buffer.
- USD and CAD balances kept separate and reported.

---

## 5) Phase 4 — FX Funding (Math + Plan Only)

### Integrate `fx_engine.py`
**Goal:** Just‑in‑time CAD→USD conversion if `[fx].enabled=true` to fund USD ETF BUYs.

**`[fx]` settings:**
- `enabled` — toggle FX funding stage.
- `base_currency` — target currency for the portfolio.
- `funding_currencies` — comma‑separated list of currencies that may be sold to fund `base_currency`.
- `convert_mode` — `just_in_time` vs `always_top_up` behavior.
- `use_mid_for_planning` — size FX orders using mid price instead of snapshot.
- `min_fx_order_usd` — skip conversions below this USD amount.
- `fx_buffer_bps` — extra cushion added to the shortfall.
- `order_type` — `MKT` or `LMT`.
- `limit_slippage_bps` — max slippage when `order_type=LMT`.
- `route` — IBKR venue (e.g., `IDEALPRO`).
- `wait_for_fill_seconds` — pause before placing dependent ETF orders.
- `prefer_market_hours` — when true, gate FX trades outside market hours.

**Tests:**
- FX stage only runs when `enabled=true`; otherwise ETF buys proceed without FX.
- `base_currency`/`funding_currencies` honored: CAD→USD supported, others rejected.
- `convert_mode` paths: `just_in_time` fires only for shortfalls; `always_top_up` replenishes to target cash.
- `use_mid_for_planning` uses mid price sizing vs snapshot ask/bid when false.
- Shortfalls below `min_fx_order_usd` ignored.
- Sized amount includes `fx_buffer_bps` cushion.
- `order_type` switch: `MKT` sent directly; `LMT` obeys `limit_slippage_bps` cap.
- `route` populated on the FX order.
- `wait_for_fill_seconds` delays ETF orders until the FX fill or timeout.
- `prefer_market_hours` blocks orders during off‑hours when true.

---

## 6) Phase 5 — IBKR Provider (ib_async) with Fakes

### 6.1 `ibkr_provider.py`
**Goal:** Define an adapter interface; provide **FakeIB** (deterministic, in‑memory fills) and `LiveIB` stubs.  
**Interface covers:**
- connect/disconnect; contract resolution; quotes; account values (NetLiq, ExcessLiquidity, cash by currency); positions; place/cancel orders; await fills; pacing hooks.
**Tests:**
- FakeIB lifecycle and fill simulation (configurable delays).
- Pacing hook calls (no real sleeps in unit tests).

> Live tests are deferred; unit tests use FakeIB exclusively.

---

## 7) Phase 6 — Order Builder & Executor (Dry‑Run First)

### 7.0 `safety.py`
**Goal:** Centralize kill switch, confirmation prompts, and `prefer_rth` gating.
**Tests:**
- `require_confirm`, `kill_switch_file`, and `prefer_rth` enforcement.

### 7.1 `order_builder.py`
**Goal:** Map plan lines to broker orders using `limit_pricer` (default LMT), TIF=DAY, SMART route, RTH.
**Tests:**
- Mapping correctness for BUY/SELL; FX vs equity orders; tick rounding applied.

### 7.2 `order_executor.py`
**Goal:** Two‑stage sequencing with safety and pacing.
**Flow:**
1. **FX Stage** (if `[fx].enabled=true`): place `BUY USD.CAD`, wait for fill (or configured pause).
2. **Equities Stage**: **SELLS first**, then **BUYS**; cap concurrent open orders; optional confirmation; respect `paper_only` and kill‑switch.
**Tests (with FakeIB):**
- FX before ETF buys; sells before buys.
- Concurrency cap respected.
- `prefer_rth` gating enforced; abort on safety violations with clear messages.

### 7.3 Error Handling
**Goal:** Catch SRS §5.11 failures with actionable messages and non-zero exit codes.
**Failures & tests:**
- Connection failures → FakeIB drop hooks; unit tests verify clear message and exit code.
- Pacing violations → FakeIB pacing hook; tests assert abort with code.
- Contract not found → FakeIB lookup failure; tests show message.
- Stale data → Fake quote provider returns stale quotes; tests assert detection and exit.
- Fractional not allowed → FakeIB rejects fractional orders; tests ensure surfaced and non-zero exit.
- Market closed when `prefer_rth=true` → safety gate trips; tests confirm error path.
- Insufficient buying power → FakeIB account shortfall; tests assert exit.
**Surfacing:** Map each to dedicated non-zero exit codes.

---

## 8) Phase 7 — End‑to‑End Scenarios

**E2E Offline (FakeIB + FakeQuoteProvider):**
- YAML scenarios → plan → pre‑trade report → sim fills → post‑trade report.
**Must cover:**
1. No‑trade within band.
2. Single overweight → SELLS only.
3. Underweights scaled by min order and buying power after sells.
4. Margin via `CASH=-50` (gross 150%), leverage guard.
5. FX funding from CAD to USD first.
6. Spread‑aware limits, wide/stale escalation.
7. Disable `allow_fractional`, verify shares are rounded and residual drift ≤10 bps (SRS scenario test #4).

**Assertions:**
- Acceptance criteria from the SRS (margin, FX funding, spread‑aware limits, safety).

---

## 9) Phase 8 — CLI, Logging, DX polish

**`app.py` with `typer`:**
```
python app.py --csv portfolios.csv --ini settings.ini --report-only
python app.py --csv portfolios.csv --ini settings.ini --dry-run
python app.py --csv portfolios.csv --ini settings.ini --paper
python app.py --csv portfolios_margin.csv --ini settings.ini --paper --yes
python app.py --csv portfolios.csv --ini settings.ini --live --yes
```
**Logging:** Structured logs, run‑id, config echo, environment dump.
**Errors:** Structured error‑handling strategy with defined exit‑code mapping (0 success; non‑zero per failure type).

---

## 10) Test Pyramid & Debugging Tactics

- **Unit (~70%)**: pure functions (loader, blender, pricer, FX sizing).
- **Component (~20%)**: executor with FakeIB; failure injection (stale quotes, pacing, BP limits, FX delay).
- **E2E (~10%)**: YAML scenarios through FakeIB.
- **Property tests**: Hypothesis for sums, rounding monotonicity, spread offset caps.
- **Golden files**: pre/post CSV & Markdown reports (stable IDs/timestamps with `freezegun`).
- **Fault injection**: randomize spreads, drop quotes, simulate IB pacing violations, and ensure graceful backoff/abort.

---

## 11) Codex Prompt Templates (per module)

> Copy one module per PR; paste its spec excerpt + these prompts.

**Example — `limit_pricer.py`:**
- “Implement `price_limit_buy(bid, ask, min_tick, cfg)` and `price_limit_sell(...)` following SRS `[limits]`. Include NBBO caps, spread offsets, tick rounding, `max_offset_bps`, and stale/wide escalation. Generate exhaustive pytest tests covering spreads (1–100 bps), minTick grid, NBBO caps, stale quotes, and each escalation mode.”

**Example — `portfolio_loader.py`:**
- “Implement CSV loader for SMURF/BADASS/GLTR with `CASH` negative row support. Raise clear errors on sums, duplicate/positive CASH, non‑numeric weights. Write table‑driven tests.”

**Example — `fx_engine` integration:**
- “Wire `fx_engine.plan_fx_if_needed(...)` into the planning path. Unit tests: CAD‑only cash → FX order generated; tiny shortfall ignored; parameter validation.”

---

## 12) Roll‑Out Order (usable early)

1. **Report‑only dry‑run** (no IB): drift + proposed trades + **limit prices** visible.
2. **Paper trading with FakeIB** (sim fills) to validate sequencing.
3. **Paper with LiveIB** on 1–2 ETFs; small `min_order_usd`; market closed dry‑runs for safety.
4. Enable **FX** on tiny conversions; observe USD/CAD balances; then larger sizes.
5. Introduce **margin** scenarios gradually (110–120% gross first); monitor Excess Liquidity.

---

## 13) Deliverables Checklist (per phase)

- [ ] Code with docstrings.
- [ ] Tests (unit/component/E2E) + coverage ≥90% on diff.
- [ ] CHANGELOG entry.
- [ ] README update (usage, flags, examples).
- [ ] Demo commands and sample outputs.
- [ ] Known limitations + next steps.

---

## 14) Example Commands

```bash
# Lint + type-check + tests locally
ruff check . && mypy . && pytest -q

# Report-only (no IB order connection)
python app.py --csv portfolios.csv --ini settings.ini --report-only

# Dry-run (reads account, no orders)
python app.py --csv portfolios.csv --ini settings.ini --dry-run

# Paper trading (with confirmation)
python app.py --csv portfolios.csv --ini settings.ini --paper

# Margin + spread-aware limits (default), FX enabled
python app.py --csv portfolios_margin.csv --ini settings.ini --paper --yes
```
