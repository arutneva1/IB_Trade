# Phase 2 PR Review Checklist

**Scope:** Spread‑aware pricing & quotes only (offline). No broker/`ib_async`, no network I/O.

---

## Quick gates
- [x] Changes limited to pricing layer (e.g., `limit_pricer.py`, `pricing.py`, related tests)
- [x] No edits to order execution or IBKR adapter
- [x] No new production deps beyond SRS/plan

## CI & local checks
- [x] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [x] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass
- [x] Diff coverage ≥ **90%** for new/changed code

## Alignment with SRS
- [x] Default **spread‑aware LMT** strategy implemented (SRS `[limits]`)
- [x] Config keys honored: `smart_limit`, `style=spread_aware`, `buy_offset_frac`, `sell_offset_frac`, `max_offset_bps`, `wide_spread_bps`, `escalate_action`, `stale_quote_seconds`, `use_ask_bid_cap`
- [x] NBBO rule enforced: **BUY ≤ ask**, **SELL ≥ bid**

## `limit_pricer.py`
- [x] Pure functions only (no I/O): `price_limit_buy(...)`, `price_limit_sell(...)`
- [x] Mid/Spread: `mid=(bid+ask)/2`, `spread=ask-bid`; guard `spread>0`
- [x] Offsets: `mid ± offset_frac*spread`; cap by `max_offset_bps` vs mid
- [x] **Tick rounding** uses contract `minTick` (fallback `0.01` if unknown)
- [x] **NBBO cap** respected when `use_ask_bid_cap=true`
- [x] **Wide/stale escalation** per config:      `spread_bps > wide_spread_bps` or quote stale ⇒ `escalate_action` (`cross` | `keep` | `market`)
- [x] Deterministic outputs; no hidden state

## `pricing.py`
- [x] `Quote(bid: float, ask: float, ts: datetime)` dataclass (or TypedDict)
- [x] Staleness detection uses `stale_quote_seconds`
- [x] **FakeQuoteProvider** for tests (no network)
- [x] Robust when only one side present (bid **or** ask): fallback or clear error
- [x] No imports of broker libs; no TWS/Gateway calls

## Tests (table‑driven/parameterized)
- [x] **NBBO cap**: BUY never > ask; SELL never < bid
- [x] **Ticks**: rounding correct for `0.01`, `0.005`, etc.
- [x] **Offsets**: with `buy_offset_frac=0.25` & `sell_offset_frac=0.25`, limits land at `mid ± 0.25*spread` (then rounded & capped)
- [x] **max_offset_bps** respected
- [x] **Wide** spread triggers escalation exactly as configured
- [x] **Stale** quote triggers escalation
- [x] **Edge cases**: zero/negative spread → defensive behavior with clear message
- [x] Optional property tests:      monotonicity vs spread; rounding never violates NBBO cap
- [x] Tests use **FakeQuoteProvider** only (no network)

## Code quality
- [x] Docstrings reference SRS `[limits]`; examples included
- [x] Typed interfaces & returns (no `Any` leakage)
- [x] Actionable error messages (what input was wrong and how to fix)
- [x] No time‑of‑day coupling; tests control timestamps

## Acceptance examples (good to include in tests)
- [x] bid=100.00, ask=100.10 (spread 10 bps), `buy_offset_frac=0.25`, `max_offset_bps=10` ⇒ BUY limit ≥ tick‑rounded `mid+0.25*spread` and ≤ `ask` and ≤ `mid*(1+10bps)`
- [x] `spread_bps=60`, `escalate_action=cross` ⇒ BUY=ask, SELL=bid (tick‑rounded)
- [x] Stale `ts` beyond `stale_quote_seconds` ⇒ escalation path taken

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
