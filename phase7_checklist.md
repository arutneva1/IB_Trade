# Phase 7 PR Review Checklist

**Scope:** End‑to‑end (E2E) **offline** runs using fakes only (FakeIB + FakeQuoteProvider). No live orders, no TWS/Gateway connectivity, no network I/O.

---

## Quick gates
- [ ] Changes limited to **E2E harness & scenarios** (e.g., `tests/e2e/`, scenario loader, reporting glue)
- [ ] No functional changes to pricing math or provider beyond **wiring**
- [ ] No new production deps; dev/test deps only (e.g., `pyyaml`, `freezegun`)
- [ ] All runs deterministic (fixed timestamps, seeded randomness)

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [ ] Diff coverage ≥ **90%** for added harness logic (scenario loader, reporters)

## Alignment with SRS/plan
- [ ] E2E runner executes the **full flow**: account snapshot → target blend → rebalance plan → FX plan → order build → executor (FakeIB) → post‑trade report
- [ ] Pre‑trade artifacts generated (CSV/Markdown) match tables expected in SRS
- [ ] Post‑trade artifacts summarize fills, slippage vs limit, remaining drift
- [ ] Safety rails enforced even offline (paper default, kill‑switch honored)
- [ ] Spread‑aware pricing used by default; NBBO caps respected in prices placed

## Scenario format (example YAML)
```yaml
name: "fx_then_rebalance_cad_only"
as_of: "2025-01-15T14:30:00Z"
prices:
  GLD: 200.00
  GDX: 30.00
quotes:
  GLD: { bid: 199.98, ask: 200.02 }
  GDX: { bid: 29.99, ask: 30.01 }
  USD.CAD: { bid: 1.3499, ask: 1.3501 }
positions:
  GLD: 10
  GDX: 0
cash:
  USD: 0.0
  CAD: 20000.0
config_overrides:
  rebalance: { tolerance_bps: 25, min_order_usd: 50 }
  fx: { enabled: true, pair: "USD.CAD", fx_buffer_bps: 25 }
```

**Loader expectations**
- [ ] Validates schema; descriptive errors on missing fields/types
- [ ] Supports `config_overrides` to tweak `.ini` for a scenario
- [ ] Freezes time to `as_of` during run (`freezegun` or equivalent)

## E2E scenarios to include
- [ ] **No‑trade within band**: drift under tolerance → zero orders, clear rationale
- [ ] **Overweight → SELLS only**: verify sells placed/filled; buys skipped
- [ ] **Underweights scaled**: buys sized after sells; obey `min_order_usd`
- [ ] **Margin via CASH=-50**: gross 150%; leverage guard enforced
- [ ] **FX funding from CAD**: CAD‑only cash funds USD ETF buys via `BUY USD.CAD` first
- [ ] **Spread‑aware pricing**: limits at `mid ± offset*spread`, tick rounding, NBBO caps
- [ ] **Wide/stale escalation**: trigger `escalate_action` branches (`keep`/`cross`/`market`)
- [ ] **Fractional vs whole**: both code paths covered per config
- [ ] **Concurrency/pacing**: cap=1 with multiple orders invokes pacing hook; deterministic
- [ ] **Timeout/partial fills**: executor handles per policy (cancel/continue) with logs
- [ ] **Safety rails**: paper‑only; kill‑switch prevents placement; clear messages

## Artifacts (per scenario)
- [ ] `pre_trade_report_<stamp>.csv` and `.md`
- [ ] `event_log_<stamp>.json` (orders placed/canceled/filled with timestamps)
- [ ] `post_trade_report_<stamp>.csv` and `.md`
- [ ] Stable filenames (use `as_of` stamp) for golden comparisons

## Tests
- [ ] Table‑driven pytest that iterates scenarios in `tests/e2e/fixtures/*.yml`
- [ ] Golden‑file tests for pre/post reports (allow minor numeric tolerance)
- [ ] Assertions on event log ordering: **FX → SELLS → BUYS**
- [ ] Assertions on price caps: BUY ≤ ask; SELL ≥ bid
- [ ] Determinism: running twice yields identical artifacts/event sequences

## Code quality
- [ ] Scenario loader & runner are **pure orchestrators** (no hidden state)
- [ ] Strong typing on scenario schema & outputs; explicit return types
- [ ] Docstrings describe scenario fields, units, and assumptions
- [ ] Clear failure messages when a scenario cannot execute (what, where, why)

## Interfaces for next phase
- [ ] E2E runner callable from CLI (`app.py --scenario path.yml --paper`)
- [ ] Reports reusable by README/examples; easy to embed in CI artifacts
- [ ] Hooks ready for swapping `FakeIB` → `LiveIB` behind the same interface later

## Acceptance examples
- [ ] **CAD‑only cash**: FX notional = `(usd_needed - usd_cash) * (1 + buffer_bps/10k)`; equities buys proceed after FX fills
- [ ] **Tolerance band**: pre‑trade report shows max drift < band; no orders, exit code 0
- [ ] **Wide spread**: `spread_bps > wide_spread_bps` triggers configured escalation; placed prices match expectation

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
