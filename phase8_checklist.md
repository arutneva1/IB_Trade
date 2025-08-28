# Phase 8 PR Review Checklist

**Scope:** CLI, docs, packaging, and polish. Default remains **offline/paper**. No live orders by default.

---

## Quick gates
- [ ] No API credentials or other secrets committed (see SRS §11)
- [ ] Changes limited to CLI & polish (e.g., `app.py`, `__main__.py`, `README.md`, docs/examples, packaging metadata)
- [ ] No behavior changes to pricing/math or provider beyond wiring CLI options
- [ ] Live trading remains fully gated (paper default; explicit `--live --yes` required, and KILL_SWITCH checked)
- [ ] PR description references relevant SRS acceptance criteria (AC#)
- [ ] CHANGELOG.md updated under the latest release heading

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [ ] Diff coverage ≥ **90%** for new/changed code (CLI & helpers covered via CliRunner tests)
- [ ] Build & packaging sanity: `pip install -e .` works; console entry-point launches

## Alignment with SRS/plan
- [ ] CLI supports **dry‑run**, **paper**, (gated) **live** modes
- [ ] Sequencing & safety rules unchanged (FX → SELLS → BUYS; LMT default; NBBO caps; tolerance bands)
- [ ] Spread‑aware pricing is still the default for equities
- [ ] FX handling per SRS `[fx]` is surfaced via CLI flags/env/config; no new execution behavior added
- [ ] `price_source` fallback chain: `last` → `midpoint` → `bid/ask` → `snapshot`
- [ ] Optional snapshot mode controlled by config

## CLI (`app.py` with Typer)
- [ ] Commands/subcommands (example):
  - [ ] `rebalance` (main path): reads CSV + INI, runs pre‑trade, (optionally) executes with fakes/paper
  - [ ] `scenario` (optional): runs E2E fixture (`--file tests/e2e/fixtures/*.yml`)
  - [ ] `report` (optional): render/inspect existing plans into Markdown/CSV
- [ ] Common options:
  - [ ] `--csv PATH`, `--ini PATH`, `--output-dir PATH`, `--as-of DATETIME`
  - [ ] `--dry-run / --paper / --live` (mutually exclusive), `--yes` (confirmations), `--kill-switch PATH`
  - [ ] Logging: `--log-level`, `--log-json/--log-text`
  - [ ] Pricing: `--use-ask-bid-cap/--no-use-ask-bid-cap` (respects config overrides)
- [ ] Help text is clear and references safety defaults; `--help` prints examples
- [ ] Non‑zero exit codes for failures (config/IO 2, safety 3, runtime 4, unknown 5)

## Config & safety (wiring, not new behavior)
- [ ] Config precedence documented & implemented: **CLI > ENV > INI defaults**
- [ ] `paper_only=true` by default unless `--live --yes` and `paper_only=false` in INI
- [ ] `KILL_SWITCH` file path required & existence checked for live mode (even though not used in Phase 8)
- [ ] Secrets never printed; config values with sensitive data are redacted in logs
- [ ] Guardrails: refuse `MKT` orders unless explicitly enabled in limits/fx config

## Logging & observability
- [ ] Structured logs (timestamp, level, event, details); JSON mode option
- [ ] Key events logged: config loaded, plan built, FX plan, orders built, (paper) execution, summaries
- [ ] Pre‑ and post‑trade artifacts written under `--output-dir` with stamped filenames
- [ ] Error messages are actionable and reference SRS sections where useful

## Docs & examples
- [ ] `README.md` updated with:
  - [ ] Install (dev + minimal runtime)
  - [ ] Safety disclaimer (paper default, live gating, kill switch)
  - [ ] Quick start (dry‑run) and paper example commands
  - [ ] CSV schema (CASH negative pattern), INI keys (including `[fx]`, `[limits]`, `[rebalance]`)
  - [ ] Spread‑aware pricing overview and NBBO caps
  - [ ] Example outputs (snippets of pre‑/post‑trade reports)
- [ ] Examples directory contains sample `portfolios.csv`, `settings.ini`, and a small scenario YAML
- [ ] Changelog or release notes for Phase 8

## Packaging
- [ ] `pyproject.toml` includes `project.scripts` entry point, e.g.: `ib-rebalance = ibkr_etf_rebalancer.app:main`
- [ ] Version bumped (`0.1.x` → next) and tagged in changelog
- [ ] Optional: `--version` command prints version from package metadata

## Tests (CLI & glue; offline with fakes)
- [ ] Typer `CliRunner` tests for:
  - [ ] `--help` output contains key options
  - [ ] `--dry-run` generates reports and **does not** call provider
  - [ ] `--paper` path calls `FakeIB` and produces expected event log order
  - [ ] `--live` without `--yes` or missing kill‑switch → exits with safety error code
  - [ ] Bad inputs (missing CSV/INI) → non‑zero exit with clear message
- [ ] Logging tests (JSON mode emits keys, not free‑form text)
- [ ] Exit code tests for success/failure categories
- [ ] Golden‑file checks for CLI‑produced reports

## Code quality
- [ ] Strong typing on CLI entry points & helpers; explicit return types
- [ ] Small composable helpers; side effects isolated to CLI adapter layer
- [ ] Docstrings & inline examples for commands/options
- [ ] No global mutable state; configuration passed explicitly

## Acceptance examples (good to include in docs/tests)
- [ ] Dry‑run: `ib-rebalance --csv portfolios.csv --ini settings.ini --dry-run --output-dir out/` → creates pre‑trade report; exit 0
- [ ] Paper: `ib-rebalance --csv portfolios.csv --ini settings.ini --paper --output-dir out/` → uses `FakeIB`; logs FX→SELLS→BUYS; exit 0
- [ ] Live gated: `ib-rebalance --csv portfolios.csv --ini settings.ini --live` → exits with message “use --yes and provide KILL_SWITCH”; exit 3

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
