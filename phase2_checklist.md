# Phase 2 PR Review Checklist

**Scope:** Spread‑aware pricing & quotes only (offline). No broker/`ib_async`, no network I/O.

---

## Quick gates
- [ ] Changes limited to pricing layer (e.g., `limit_pricer.py`, `pricing.py`, related tests)
- [ ] No edits to order execution or IBKR adapter
- [ ] No new production deps beyond SRS/plan
- [ ] PR description references relevant SRS acceptance criteria (AC#)
- [ ] CHANGELOG.md updated under the latest release heading

## CI & local checks
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [ ] Diff coverage ≥ **90%** for new/changed code

## Alignment with SRS
- [ ] Default **spread‑aware LMT** strategy implemented (SRS `[limits]`)
- [ ] Config keys honored: `smart_limit`, `style=spread_aware`, `buy_offset_frac`, `sell_offset_frac`, `max_offset_bps`, `wide_spread_bps`, `escalate_action`, `stale_quote_seconds`, `use_ask_bid_cap`
- [ ] NBBO rule enforced: **BUY ≤ ask**, **SELL ≥ bid**
- [ ] `price_source` fallback chain: `last` → `midpoint` → `bid/ask` → `snapshot`
- [ ] Optional snapshot mode controlled by config

## `limit_pricer.py`
- [ ] Pure functions only (no I/O): `price_limit_buy(...)`, `price_limit_sell(...)`
- [ ] Mid/Spread: `mid=(bid+ask)/2`, `spread=ask-bid`; guard `spread>0`
- [ ] Offsets: `mid ± offset_frac*spread`; cap by `max_offset_bps` vs mid
- [ ] **Tick rounding** uses contract `minTick` (fallback `0.01` if unknown)
- [ ] **NBBO cap** respected when `use_ask_bid_cap=true`
- [ ] **Wide/stale escalation** per config:      `spread_bps > wide_spread_bps` or quote stale ⇒ `escalate_action` (`cross` | `keep` | `market`)
- [ ] Deterministic outputs; no hidden state

## `pricing.py`
- [ ] `Quote(bid: float, ask: float, ts: datetime)` dataclass (or TypedDict)
- [ ] Staleness detection uses `stale_quote_seconds`
- [ ] **FakeQuoteProvider** for tests (no network)
- [ ] Robust when only one side present (bid **or** ask): fallback or clear error
- [ ] No imports of broker libs; no TWS/Gateway calls

## Tests (table‑driven/parameterized)
- [ ] **NBBO cap**: BUY never > ask; SELL never < bid
- [ ] **Ticks**: rounding correct for `0.01`, `0.005`, etc.
- [ ] **Offsets**: with `buy_offset_frac=0.25` & `sell_offset_frac=0.25`, limits land at `mid ± 0.25*spread` (then rounded & capped)
- [ ] **max_offset_bps** respected
- [ ] **Wide** spread triggers escalation exactly as configured
- [ ] **Stale** quote triggers escalation
- [ ] **Edge cases**: zero/negative spread → defensive behavior with clear message
- [ ] Optional property tests:      monotonicity vs spread; rounding never violates NBBO cap
- [ ] Tests use **FakeQuoteProvider** only (no network)

## Code quality
- [ ] Docstrings reference SRS `[limits]`; examples included
- [ ] Typed interfaces & returns (no `Any` leakage)
- [ ] Actionable error messages (what input was wrong and how to fix)
- [ ] No time‑of‑day coupling; tests control timestamps

## Acceptance examples (good to include in tests)
- [ ] bid=100.00, ask=100.10 (spread 10 bps), `buy_offset_frac=0.25`, `max_offset_bps=10` ⇒ BUY limit ≥ tick‑rounded `mid+0.25*spread` and ≤ `ask` and ≤ `mid*(1+10bps)`
- [ ] `spread_bps=60`, `escalate_action=cross` ⇒ BUY=ask, SELL=bid (tick‑rounded)
- [ ] Stale `ts` beyond `stale_quote_seconds` ⇒ escalation path taken

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
