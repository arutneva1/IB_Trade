# Changelog

## [Unreleased]
- Placeholder for upcoming changes.
- Document paper and live CLI examples in `workflow.md`.
- Clarified Definition of Done in `plan.md` to include CHANGELOG entries and SRS acceptance-criteria references.
- Expanded Phase 1 checklist with module-specific items, leverage test, and PR gate updates.
- Added Phase 0 review checklist.
- Added integration test covering FX → SELL → BUY order sequencing with `FakeIB`.


## Phase 5
- Export provider and quote provider classes via package API. [SRS AC3][SRS AC9]

## Phase 4
- Added FX planning with `[fx]` configuration for offline CAD→USD conversions and preserved FX bid/ask spreads when sizing funding orders. [SRS AC5][SRS AC12]

## Phase 3
- Support account snapshots via `AccountSnapshot` and `compute_account_state` exports. [SRS AC3]

## Phase 2
- Added spread-aware pricing for more accurate trade evaluation.

## Phase 1
- Implemented core logic and reporting capabilities.

## Phase 0
- Bootstrapped the repository structure.
