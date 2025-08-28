# Phase 1 PR Review Checklist

Copy/paste into your PR or keep this file in `.github/` to guide reviews for **Phase 1** (pure core; no broker I/O).

---

## Quick gates
- [ ] **Scope is Phase 1 only** (pure core; no broker/`ib_async`, no network I/O)
- [ ] Only expected files changed (e.g., `portfolio_loader.py`, `tests/test_portfolio_loader.py`)
- [ ] No new dependencies added to `requirements.txt`
- [ ] PR references relevant SRS acceptance criteria in description
- [ ] CHANGELOG.md updated under latest release
- [ ] PR description references relevant SRS acceptance criteria

## CI & local checks
- [ ] CI is green (ruff, black, mypy, pytest)
- [ ] Local sanity: `ruff check .` / `black --check .` / `mypy .` / `pytest -q` all pass
- [ ] Coverage on diff ≥ **90%** for new/changed code

## Alignment with SRS
- [ ] Uses model names **SMURF**, **BADASS**, **GLTR**
- [ ] Margin encoding uses **`CASH` negative row** pattern only
- [ ] Spread-aware pricing, FX, broker calls **not** implemented in Phase 1
- [ ] `price_source` fallback chain: `last` → `midpoint` → `bid/ask` → `snapshot`
- [ ] Optional snapshot mode controlled by config

## Tests (table-driven & edge cases)
- [ ] Valid CSVs load: per-portfolio sums = **100%** or **assets + CASH = 100%** (±0.01)
- [ ] Exactly **one** optional `CASH` row per portfolio; **must be negative**
- [ ] Descriptive errors for:
  - [ ] Missing/unknown portfolio name
  - [ ] Multiple `CASH` rows
  - [ ] Non-numeric or out-of-range `target_pct`
  - [ ] Sums not meeting the rule above
- [ ] Fixtures cover **SMURF/BADASS/GLTR** with overlapping ETFs
- [ ] Golden sample(s) included for a valid file and a few invalid files
- [ ] Portfolios exceeding `[rebalance].max_leverage` are rejected

## Code quality
- [ ] Clear dataclasses/types; no magic constants
- [ ] Pure functions for parsing/validation (no side effects)
- [ ] Helpful error messages (actionable, not generic)
- [ ] Docstrings explaining CSV schema & rules; SRS references added if behavior differs

## Nice-to-have (optional)
- [ ] Property test for sum invariants (weights normalize as expected)
- [ ] Performance sanity (parsing runs in <100ms for typical CSVs)

---

### Module-specific add-on: `portfolio_loader.py`
- [ ] `PortfolioRow` dataclass and a loader function returning a structured map like `{ "SMURF": {sym: pct}, ... }`
- [ ] Normalization preserves signs (keep `CASH` negative internally)
- [ ] Clear separation: parsing → validation → normalization
- [ ] Unit tests assert **exact** error messages (or stable substrings) for bad inputs

### Module-specific add-on: `config.py`
- [ ] INI validation
- [ ] Model weights sum to 100%
- [ ] Margin knobs (e.g., `[rebalance].max_leverage`)

### Module-specific add-on: `target_blender.py`
- [ ] Overlap handling
- [ ] Gross vs. net exposure

### Module-specific add-on: `rebalance_engine.py`
- [ ] Drift filtering
- [ ] Min order
- [ ] Leverage guard
- [ ] Rounding rules

### Module-specific add-on: `reporting.py`
- [ ] Pre-trade report columns
- [ ] Skeleton post-trade

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
