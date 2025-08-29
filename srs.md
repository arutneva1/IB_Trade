# SRS — IBKR ETF Portfolio Rebalancer (for OpenAI Codex)

**Author:** You (Julian)  
**Intended implementer:** OpenAI Codex (Python)  
**Target broker:** Interactive Brokers (IBKR) via `ib_async`  
**Trading scope:** Long-only ETFs, cash, rebalancing only  
**Runtime modes:** Dry‑run (default), Paper, Live (guard‑railed)

---

## 1) Problem Statement & Goals
You maintain **three model ETF portfolios** (e.g., Core, Factor, Thematic). Each model lists **ETF tickers and target %.** A config file (`settings.ini`) provides **global weights** for each model (e.g., 60/30/10). The app must:

1. **Load** the three model portfolios (from a single CSV).  
2. **Combine** them using the configured weights to produce a **final target allocation** by ETF.  
3. **Read** current account holdings from IBKR.  
4. **Compute drift** vs. targets.  
5. **Generate and place orders** to rebalance within user‑defined **tolerance bands** and constraints.  
6. **Report** the plan (before and after), log everything, and respect IBKR pacing/limits.  
7. **FX funding (optional):** If portfolio assets are USD‑denominated and the account holds CAD cash, optionally convert **CAD→USD** just‑in‑time to fund USD ETF buys.

**Non‑Goals (out of scope v1):** tax‑lot selection, shorting, options/futures, advanced multi‑currency optimization (beyond CAD→USD funding), margin optimization.

---

## 2) Definitions
- Model portfolio: Named set of (ETF symbol, target %) that sum to 100% within the model.  
- Model mix: Global weights across the three models (e.g., SMURF=0.5, BADASS=0.3, GLTR=0.2).  
- Final target weight for ETF i: ( w_i = sum over k of (m_k × p_{k,i}) ), where p_{k,i} is ETF i’s weight in model k (0 if absent).  
- Drift: Current weight – final target weight.  
- Tolerance band: Threshold(s) determining when to trade (e.g., ±50 bps per holding, or portfolio‑level trigger).  
- CASH pseudo‑symbol (margin): A special CSV row with symbol CASH and a negative target_pct indicating borrowed cash (margin). Only valid when allow_margin=true. The sum of asset weights plus CASH must equal 100% (±0.01).  

---

## 3) Inputs & File Formats

### 3.1 `portfolios.csv` (single file, long format)
Required columns (comma‑separated):

```
portfolio,symbol,target_pct
SMURF,VTI,40
SMURF,VEA,30
SMURF,BND,30
BADASS,USMV,60
BADASS,QUAL,40
GLTR,IGV,50
GLTR,XLV,50
```

**Rules:**
- `portfolio` must be one of `SMURF`, `BADASS`, `GLTR` (case‑insensitive).  
- For each portfolio, either:  
  (A) No `CASH` row → target_pct for assets must sum to **100%** (±0.01); or  
  (B) Exactly one `CASH` row with **negative** `target_pct` → **sum(assets) + CASH = 100%** (±0.01).  
- `CASH` encoding is permitted only when `allow_margin=true` in `settings.ini`.  
- Symbols are IBKR symbols (US ETFs assumed; SMART routing default).  
- Optional extra columns (ignored if present): `note`, `min_lot`, `exchange`.

**Margin encoding (canonical Option 2):**
- Add a single `CASH` row with a **negative** percentage equal to the intended borrow.
- Example (keep GLD at 100% and add 50% GDX using margin):

```
portfolio,symbol,target_pct
SMURF,VTI,40
SMURF,VEA,30
SMURF,BND,30
BADASS,USMV,60
BADASS,QUAL,40
GLTR,GLD,100
GLTR,GDX,50
GLTR,CASH,-50
```

- Here, assets sum to 150%, `CASH=-50%`, net = 100%. The engine computes gross exposure and validates against leverage safety rails.

### 3.2 `settings.ini`
```
[ibkr]
host = 127.0.0.1
port = 4002           ; 4001/4002 as needed
client_id = 42
account_id = UXXXXXX  ; or DUXXXXXX for paper
read_only = true      ; force read‑only API until explicitly disabled

[models]
smurf = 0.50
badass = 0.30
gltr  = 0.20
; must sum to 1.00 (±0.001 tolerance)

[rebalance]
trigger_mode = per_holding        ; per_holding | total_drift
per_holding_band_bps = 50         ; trade if |drift| > 0.50%
portfolio_total_band_bps = 100    ; used when trigger_mode=total_drift
min_order_usd = 500               ; ignore smaller trades
cash_buffer_pct = 1.0             ; hold back 1% of NetLiq as cash
allow_fractional = false          ; set true only if account supports it
allow_margin = false              ; set true to permit CSV with CASH<0
max_leverage = 1.50               ; hard cap on gross (e.g., 150%)
maintenance_buffer_pct = 10       ; keep headroom vs. margin call
prefer_rth = true                 ; place orders only during RTH by default
order_type = LMT                  ; default to smarter spread‑aware limits

[pricing]
price_source = last               ; last | midpoint | bidask
fallback_to_snapshot = true

[fx]
enabled = false                 ; when true, CAD cash may fund USD buys
base_currency = USD             ; portfolio/target currency
funding_currencies = CAD       ; comma‑sep list; v1 supports CAD only
convert_mode = just_in_time    ; just_in_time | always_top_up
use_mid_for_planning = true    ; plan FX size using mid price
min_fx_order_usd = 1000        ; skip tiny conversions
max_fx_order_usd = 5000        ; cap single conversion size (optional)
fx_buffer_bps = 20             ; buy a small extra cushion (0.20%)
order_type = MKT               ; MKT | LMT
limit_slippage_bps = 5         ; when order_type=LMT
route = IDEALPRO               ; IBKR FX venue
wait_for_fill_seconds = 5      ; pause before placing dependent ETF buys
prefer_market_hours = false    ; FX is 24x5; allow off‑hours by default

[limits]
smart_limit = true
style = spread_aware             ; spread_aware | static_bps | off
buy_offset_frac = 0.25           ; BUY at mid + 0.25*spread (capped)
sell_offset_frac = 0.25          ; SELL at mid - 0.25*spread (capped)
max_offset_bps = 10              ; never cross >10 bps past mid
wide_spread_bps = 50             ; when wider, escalate
escalate_action = cross          ; cross | market | keep
stale_quote_seconds = 10         ; if quotes stale, treat as wide
use_ask_bid_cap = true           ; never set BUY limit > ask or SELL < bid

[symbol_overrides]
; Optional explicit contract overrides (symbol=conId or symbol=exchange)
; VTI = SMART

[safety]
paper_only = true                 ; hard‑gate: override requires explicit flag
require_confirm = true            ; prompt for Y/N before sending non‑dry orders
kill_switch_file = KILL_SWITCH    ; if this file exists, abort immediately

[io]
report_dir = reports
log_level = INFO

```
### 3.3 `[pricing]` & `[fx]` configuration
- `[pricing]` selects the quote source (`last`, `midpoint`, or `bidask`) and whether to fall back to snapshot data.
- `[fx]` enables optional CAD→USD conversions, defining base/funding currencies, conversion timing, and order controls such as `max_fx_order_usd` and `limit_slippage_bps`.

### 3.4 `[limits]` — Spread‑aware limit pricing (default)
- Default order type is **LMT** with a **spread‑aware** strategy.
- For each symbol, fetch **bid/ask**, compute **mid** and **spread**.
- BUY limit = `min(ask, round_to_tick(mid + buy_offset_frac*spread), mid*(1+max_offset_bps/10000))`.
- SELL limit = `max(bid, round_to_tick(mid - sell_offset_frac*spread), mid*(1-max_offset_bps/10000))`.
- If `spread_bps > wide_spread_bps` or quotes are stale: apply `escalate_action` (`cross`: set BUY=ask/SELL=bid; `market`: send MKT; `keep`: place conservative limit at mid ± max_offset).
- Limits are **never** set beyond the NBBO (respect `use_ask_bid_cap`).
- Tick rounding uses contract minTick; fallback to $0.01 if unavailable.

## 4) High‑Level Architecture
```
ibkr_etf_rebalancer/
├─ app.py                 # CLI entrypoint
├─ ibkr_provider.py       # connection, contract resolution, prices, account (ib_async)
├─ portfolio_loader.py    # CSV -> models dict; validate 100% / CASH rules
├─ target_blender.py      # combine models with [models] weights
├─ account_state.py       # holdings snapshot, valuation, current weights
├─ rebalance_engine.py    # drift calc, trade list, rounding, constraints
├─ fx_engine.py           # handles CAD→USD funding calculations and FX order sizing
├─ limit_pricer.py        # spread‑aware limit price calculator (default)
├─ order_builder.py       # build Order objects using calculated limits
├─ order_executor.py      # dry-run, paper, live; batching & pacing
├─ pricing.py             # quote adapter (bid/ask/mid), staleness
├─ reporting.py           # before/after tables, CSV/JSON/markdown
├─ config.py              # settings.ini loader & schema validation
├─ safety.py              # kill switch, confirmations, paper-only guard
├─ util.py                # common helpers
└─ tests/                 # unit & scenario tests
```

Key snapshot helpers are re-exported for convenience; import
``AccountSnapshot`` and ``compute_account_state`` directly from
``ibkr_etf_rebalancer`` when performing offline analysis.

**Primary library:** `ib_async`.
**Python:** 3.10+ recommended.  
**OS:** Windows 10+, macOS, or Linux (TWS/Gateway installed & running).

---

## 5) Detailed Requirements

### 5.1 Config Loading & Validation
- Parse `settings.ini` with strict schema.
- Validate: `p1+p2+p3 ≈ 1.0`; bands ≥ 0; `min_order_usd ≥ 0`; booleans; `order_type` in allowed set.
- On invalid config: fail fast with actionable error messages.

### 5.2 Portfolio Loading & Validation
- Read `portfolios.csv` into a data structure: `{ 'P1': {sym: pct}, 'P2': {...}, 'P3': {...} }`.
- Normalize to fractions (0–1) internally (keep signs for `CASH`).
- Validation per portfolio:
  1. Count `CASH` rows. If more than one → fail.
  2. If a `CASH` row exists:
     - Require `allow_margin=true` in config; otherwise fail with: "CSV contains CASH but margin is disabled".
     - Enforce `CASH < 0`. If `CASH ≥ 0` → fail (positive cash should be modeled by reducing asset weights).
     - Compute `sum_assets = sum(target_pct of non‑CASH)` and verify `sum_assets + CASH ≈ 100%` (±0.01).
     - Compute gross = `sum_assets`. Verify `gross ≤ [rebalance].max_leverage × 100%` (with a small epsilon); else fail with a leverage error.
  3. If no `CASH` row: verify `sum_assets ≈ 100%` (±0.01).

*Implementation note:* The loader enforces the weight and `CASH` rules above and checks that gross exposure respects `[rebalance].max_leverage`.

### 5.3 Model Blending
- Compute final targets per symbol using model mix.
- If the same symbol appears in multiple models, sum its contributions.
- CASH handling: `CASH` rows do not become tradable targets; they only imply borrowing for the portfolio that contains them. The blended gross exposure is the sum of blended asset weights; the net exposure is adjusted by the blended `CASH` (negative) such that net ≈ 100%.
- Ensure final asset target vector (excluding CASH) sums to the intended gross (e.g., 150%), while net remains 100% after applying `CASH`. Exclude `cash_buffer_pct` which is handled later.
- Compute **final targets** per symbol using model mix.
- If the same symbol appears in multiple models, **sum** its contributions.
- Ensure final target vector sums to 1.0 (±1e‑6), excluding `cash_buffer_pct` which is handled later.

### 5.4 Account State Snapshot
- Connect to IBKR (respect `read_only` and `paper_only`).
- Fetch: NetLiquidation (base currency), **per‑currency cash balances** (at least USD, CAD), positions (symbol, quantity, average cost, market price), and market values.
- Restrict to **ETFs in target set** plus existing ETF positions.  
- Compute current weights per ETF = market_value / (NetLiq − cash_buffer_amount).
- **Cash buffer:** `cash_buffer_amount = NetLiq * cash_buffer_pct/100` (retain as cash).

### 5.5 Pricing
- For each target ETF: obtain bid/ask and compute mid = (bid+ask)/2; if unavailable, use configured `price_source` with robust fallback order: `last` → `midpoint` → `bid/ask` → `snapshot` if allowed.  
- For FX (USD/CAD): request a real‑time quote for USD.CAD and compute **mid**.  
- Detect stale prices (e.g., older than `stale_quote_seconds`) and warn; treat as wide for limit escalation.

### 5.6 Drift & Trade Decision Rules
- Compute drift per holding: `drift_i = current_w_i − target_w_i`.
- **Triggering:**
  - If `trigger_mode=per_holding`: include symbol _i_ if `|drift_i| > per_holding_band_bps/10000`.
  - If `trigger_mode=total_drift`: include when `sum(|drift|) > portfolio_total_band_bps/10000` and optimize set of trades to minimize slippage subject to constraints.
- **Dollar trades:** translate required weight change into **dollar** orders using NetLiq minus cash buffer.
- **Min order filter:** drop any line where `abs(dollar_amt) < min_order_usd`.

### 5.7 Share Rounding & Constraints
- If `allow_fractional=false`: round shares to nearest whole share, re‑compute dollars, and ensure total buy ≤ available buying power (respect `allow_margin`).
- If insufficient buying power for buys: execute sells first (if any) then size buys to respect `max_leverage` and `maintenance_buffer_pct`.  
- Margin guardrails: When CSV implies gross >100 via `CASH<0`, ensure resulting gross ≤ `max_leverage × NetLiq` and that post‑trade excess liquidity stays above a threshold implied by `maintenance_buffer_pct` (query from IBKR account values; abort if not satisfied).  
- Ensure no symbol goes negative (no shorting).  
- Optional per‑symbol lot minimums (future extension).

### 5.8 Order Construction
- **Stage 0 (FX funding, if `[fx].enabled=true`):**
  - Compute **USD required** for planned BUYs: `usd_buys_needed = sum(max(0, buy_notional_usd))` minus available **USD cash** and expected same‑cycle USD proceeds from sells (configurable: conservative assumes sells available).
  - If `usd_buys_needed > min_fx_order_usd`, size FX BUY for **USD.CAD** as: `amount = usd_buys_needed × (1 + fx_buffer_bps/10000)` and submit via `IDEALPRO` using `order_type` (MKT or LMT).  
  - Wait `wait_for_fill_seconds` (or confirm fill) before placing dependent USD ETF BUYs.
- **Stage 1 (Equities, default LMT with spread‑aware pricing):**
  - Retrieve bid/ask; compute mid, spread, spread_bps.
  - BUY limit price = `min(ask, round_to_tick(mid + buy_offset_frac*spread), mid*(1+max_offset_bps/10000))`.
  - SELL limit price = `max(bid, round_to_tick(mid - sell_offset_frac*spread), mid*(1-max_offset_bps/10000))`.
  - If `spread_bps > wide_spread_bps` or quotes stale, apply `escalate_action` (`cross` | `market` | `keep`).
  - TIF: `DAY`.  
  - Route: `SMART`.  
- **Batching:** place **sells first**, then **buys**; cap concurrent open orders (default 5).

### 5.9 Execution Modes & Safety
- Modes: `--dry-run` (no orders), `--paper`, `--live`.  
- **Default to dry‑run** unless `--paper` or `--live` explicitly passed.  
- If `[safety].paper_only=true` and user passes `--live`, **hard refuse** with a clear message.  
- If `[safety].require_confirm=true`, prompt Y/N with a summary before sending any real orders.  
- **Kill switch:** if `KILL_SWITCH` file detected at start or before order placement → abort.

### 5.10 Reporting & Logging
- Produce a human‑readable pre‑trade report (markdown & CSV):
  - Account summary (NetLiq, cash, buffer).
  - Final targets table (symbol, target %, current %, drift bps, price, dollar delta, shares).
  - Proposed orders (side, qty, est $).  
- Post‑trade report: actual fills, residual drift.  
- Write structured logs (`.log`) with DEBUG option for troubleshooting.

### 5.11 Error Handling
- Gracefully handle: connection failures, pacing violations, contract not found, stale data, fractional not allowed, market closed if `prefer_rth=true`, insufficient buying power.  
- Provide actionable messages and exit codes (0 success; non‑zero with reason).

---

## 6) CLI & Program Flow

### 6.1 CLI Examples
```
# Dry-run (reads account, computes plan, writes reports; no orders)
python app.py --csv portfolios.csv --ini settings.ini --dry-run

# Paper trading with confirmation
python app.py --csv portfolios.csv --ini settings.ini --paper

# Live (only if safety allows)
python app.py --csv portfolios.csv --ini settings.ini --live --yes

# Override bands and minimums temporarily
python app.py --csv portfolios.csv --ini settings.ini --paper \
  --per-holding-band-bps 75 --min-order-usd 300

# Report-only (don’t even connect for orders)
python app.py --csv portfolios.csv --ini settings.ini --report-only
```

### 6.2 Flow (pseudocode)
```python
main():
  cfg = load_config("settings.ini")
  models = load_models_csv("portfolios.csv")
  validate_models(models)
  targets = blend_targets(models, cfg.models)

  ib = IBKRProvider(cfg.ibkr)
  acct = AccountState.from_ibkr(ib, targets.keys())

  prices = Pricing(ib, cfg.pricing).get_prices(list(targets.keys()))
  drift = compute_drift(acct, targets, prices, cfg.rebalance.cash_buffer_pct)

  plan = RebalanceEngine(cfg.rebalance).build_plan(
            targets, acct, prices)

  report_pre(plan, acct, targets, prices, cfg.io)

  if args.dry_run or cfg.safety.read_only: exit(0)
  Safety.check(cfg.safety)
  if cfg.safety.require_confirm: prompt_user_confirm(plan)

  fills = OrderExecutor(ib, cfg).execute(plan)
  report_post(fills, acct, targets, prices, cfg.io)
```

---

## 7) Data Structures (suggested)

```python
@dataclass
class IBKRConfig:
    host: str; port: int; client_id: int; account_id: str; read_only: bool

@dataclass
class RebalanceConfig:
    trigger_mode: str; per_holding_band_bps: int; portfolio_total_band_bps: int
    min_order_usd: float; cash_buffer_pct: float
    allow_fractional: bool; allow_margin: bool
    prefer_rth: bool; order_type: str; limit_price_slippage_bps: int

@dataclass
class Targets:  # final blended targets
    weights: dict[str, float]  # symbol -> 0..1

@dataclass
class Holding:
    symbol: str; qty: float; mkt_price: float; mkt_value: float

@dataclass
class AccountSnapshot:
    net_liq: float; cash: float; holdings: dict[str, Holding]

@dataclass
class TradeLine:
    symbol: str; side: Literal["BUY","SELL"]
    shares: float; est_px: float; est_notional: float

@dataclass
class Plan:
    to_sell: list[TradeLine]
    to_buy: list[TradeLine]
    summary: dict
```

---

## 8) Acceptance Criteria
1. [AC1] (Validation) App refuses to run with invalid `settings.ini` or portfolios that don’t sum to 100% per model (clear error).  
2. [AC2] (Blending) Given the sample CSV and `smurf=0.5,badass=0.3,gltr=0.2`, the final targets equal the weighted sum across models to within 1e‑6 and total 100%.  
3. [AC3] (Snapshot) App retrieves NetLiq, cash (USD & CAD), and all ETF positions for the configured account.  
4. [AC4] (Triggering) With `per_holding_band_bps=50`, only holdings with |drift|>0.50% appear in the plan.  
5. [AC5] (Sizing) Orders respect `min_order_usd`, `allow_fractional`, `allow_margin`, `cash_buffer_pct`, and FX guardrails.  
6. [AC6] (Execution) In `--paper` mode, orders are actually submitted to the paper account; in `--dry-run`, no orders are sent.  
7. [AC7] (Safety) If `paper_only=true`, `--live` is blocked with a clear message.  
8. [AC8] (Reporting) Pre‑ and post‑trade CSVs are written to `reports/` and include target vs. current vs. residual drift.  
9. [AC9] (Pacing) The app spaces requests to avoid IBKR pacing violations (no error 10197).  
10. [AC10] (Exit codes) 0 on success; non‑zero plus message on handled failures.  
11. [AC11] (Margin via CASH) A CSV containing `CASH=-50` alongside assets totaling 150 (e.g., SMURF: GLD=100, GDX=50, CASH=-50) validates only when `allow_margin=true` and `max_leverage ≥ 1.5`; resulting plan targets ~150% gross and 100% net, otherwise the app fails with a clear leverage/validator error.  
12. [AC12] (FX funding) With `[fx].enabled=true`, account with CAD cash and zero USD cash can fund USD ETF BUYs by placing a `BUY USD.CAD` FX trade sized to cover the shortfall plus `fx_buffer_bps`; ETFs are only placed after FX funding confirms (or the configurable wait).  
13. [AC13] (Spread‑aware limits) For liquid ETFs (spread_bps ≤ `wide_spread_bps`), BUY/SELL limits are placed at mid ± `offset_frac*spread` (rounded to tick) and never beyond NBBO; for wide or stale quotes, `escalate_action` policy is applied.  

---

## 9) Test Plan (minimal)

### Unit tests
- `test_blend_targets.py`: verify weights sum and overlap logic.  
- `test_bands_and_min_order.py`: triggering and min‑notional filters.  
- `test_rounding.py`: whole vs fractional share rounding.  
- `test_config_schema.py`: ini parsing and defaulting.

### Scenario tests (with mocked IBKR)
1. **Small drift ignored:** All |drift| < 50 bps → no trades.  
2. **One large overweight:** Generates SELLs only, respects min order.  
3. **Underweight multiple symbols:** Generates SELLs (if needed) then scaled BUYs due to cash limits.  
4. **Fractional disallowed:** Rounds shares, residual drift ≤ 10 bps.  
5. **Margin via CASH:** `SMURF: GLD 100, GDX 50, CASH -50` with `allow_margin=true` and `max_leverage≥1.5` → BUY GDX sized to ~50% of NetLiq; validator blocks the same CSV when `allow_margin=false` or `max_leverage<1.5`.  
6. **Spread‑aware limits:** With `buy_offset_frac=0.25`, `max_offset_bps=10`, a symbol quoted 100×100.10 (spread 10 bps) must produce BUY limit ≤ 100.10 and ≥ 100.025 (rounded to tick).

Run these scenarios with the CLI `--scenario` option and a YAML fixture, e.g.:

```bash
python -m ibkr_etf_rebalancer.app --scenario tests/e2e/fixtures/no_trade_within_band.yml
```

Fixtures live under `tests/e2e/fixtures/` and together exercise acceptance
criteria AC1–AC13.

---

## 10) Performance & Reliability
- Single rebalance run should complete in < 30s under normal conditions (snapshot + pricing + plan).  
- Parallelize market data queries up to a safe concurrency (e.g., 4–6) to avoid pacing.  
- Retries with backoff on transient IBKR errors.

---

## 11) Security & Safety
- Never store API credentials in repo.  
- Default mode is **dry‑run**; **paper_only=true** in config by default.  
- Enforce explicit `--live --yes` to place real orders and require config flip.

---

## 12) Future Enhancements (post‑v1)
- Multi‑account support and household views.  
- Tax‑aware rebalancing (wash sale, lot selection).  
- Currency handling & FX orders.  
- Smarter limit order pricing (spread‑aware).  
- Web dashboard.

---

## 13) Developer Notes for Codex
- Preferred stack: `ib_async`, `pydantic` (for config validation), `pandas` for tabular reporting, `typer` or `argparse` for CLI, `loguru` or stdlib `logging`.  
- Keep pure functions in the planning layer; isolate IO/side‑effects (IBKR) for testability.  
- Provide `requirements.txt` and `Makefile`/`invoke` tasks for lint/test/run:

```
pip install -r requirements.txt
pytest -q
python app.py --csv portfolios.csv --ini settings.ini --dry-run
```

---

## 14) Example Outputs (pre‑trade report columns)
- `symbol, target_pct, current_pct, drift_bps, price, dollar_delta, share_delta, side, est_notional`
- Sorted by largest |drift_bps| first; totals at bottom.
- Pre‑trade reports are emitted as both CSV and Markdown files.
- Post‑trade reports will summarise fills with columns: `symbol, side, filled_shares, avg_price, notional`.

---

## 15) Example Files (ready to tweak)

**`portfolios.csv`**
```
portfolio,symbol,target_pct
SMURF,VTI,40
SMURF,VEA,30
SMURF,BND,30
BADASS,USMV,60
BADASS,QUAL,40
GLTR,IGV,50
GLTR,XLV,50
```

**`portfolios_margin.csv` (using CASH)**
```
portfolio,symbol,target_pct
SMURF,GLD,100
SMURF,GDX,50
SMURF,CASH,-50
```


**`settings.ini`**
```
[ibkr]
host=127.0.0.1
port=4002
client_id=7
account_id=DU1234567
read_only=true

[models]
smurf=0.50
badass=0.30
gltr=0.20

[rebalance]
trigger_mode=per_holding
per_holding_band_bps=50
portfolio_total_band_bps=100
min_order_usd=500
cash_buffer_pct=1.0
allow_fractional=false
allow_margin=true
max_leverage=1.50
maintenance_buffer_pct=10
prefer_rth=true
order_type=LMT

[pricing]
price_source=last
fallback_to_snapshot=true

[fx]
enabled=true
base_currency=USD
funding_currencies=CAD
convert_mode=just_in_time
use_mid_for_planning=true
min_fx_order_usd=1000
max_fx_order_usd=5000
fx_buffer_bps=20
order_type=MKT
limit_slippage_bps=5
route=IDEALPRO
wait_for_fill_seconds=5
prefer_market_hours=false

[limits]
smart_limit=true
style=spread_aware
buy_offset_frac=0.25
sell_offset_frac=0.25
max_offset_bps=10
wide_spread_bps=50
escalate_action=cross
stale_quote_seconds=10
use_ask_bid_cap=true

[safety]
paper_only=true
require_confirm=true
kill_switch_file=KILL_SWITCH

[io]
report_dir=reports
log_level=INFO
```
