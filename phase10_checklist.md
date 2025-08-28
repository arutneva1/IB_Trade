# Phase 10 PR Review Checklist

**Scope:** Production hardening & readiness for limited rollout. No major feature work—focus on safety, observability, release process, and resilience. Default remains **paper** unless explicitly gated.

---

## Quick gates
- [ ] PR contents match Phase 10 scope (ops/safety/observability/rollout); no new trading features
- [ ] Feature flags guard any behavior that could affect live runs
- [ ] No secrets in code or logs; `.env` remains git‑ignored; secrets pulled from env/secret store

## CI, QA & quality bars
- [ ] CI green: `ruff`, `black --check`, `mypy`, `pytest`
- [ ] Diff coverage ≥ **90%** (including new safety/ops helpers)
- [ ] Static analysis for supply chain basics (dependabot/py-upgrade optional)
- [ ] Reproducible builds: `pip install -e .` and `python -m ibkr_etf_rebalancer --version` succeed

## Safety rails (final)
- [ ] Hard caps enforced & configurable:
  - [ ] **Per-order** notional cap
  - [ ] **Per-instrument** daily notional cap
  - [ ] **Per-run** and **per-day** aggregate caps
- [ ] **Kill switch** verified in code path used by executor (checked before any placement)
- [ ] **Paper default** preserved; live requires `--live --yes` + INI `paper_only=false` + kill switch present
- [ ] Guard against accidental **MKT** orders unless explicitly enabled
- [ ] Idempotency & replay protection: reruns do not duplicate already‑filled work

## Observability & telemetry
- [ ] **Structured logs** (JSON option) with correlation ids; PII redacted
- [ ] **Metrics emitted** (via lightweight hooks): order counts, placements, cancels, fills, pacing retries, error counts, latencies
- [ ] **Dashboards** (sample Grafana/Markdown screenshots or JSON configs) included in `ops/`
- [ ] **Log levels** configurable; noisy paths downgraded; errors actionable

## Alerting & SLOs
- [ ] Documented **SLOs** (examples): time to place N orders, fill wait latency, error rate, pacing rejections
- [ ] **Alert thresholds** and routing documented (even if not wired to a service yet)
- [ ] Exit codes mapped for automation: config/IO=2, safety=3, runtime=4, unknown=5

## Resilience & recovery
- [ ] **Backoff/jitter** strategy applied to pacing/temporary errors; bounded retries
- [ ] **Circuit breaker** or run‑abort triggers on cascading failures (e.g., repeated rejections)
- [ ] **Checkpointing** or clear resume plan: re‑running after crash is safe; partial progress is detected
- [ ] **Time control** in tests (e.g., `freezegun`) to make retries deterministic

## Configuration & rollout
- [ ] Clear **config precedence**: CLI > ENV > INI (documented & tested)
- [ ] **Read‑only dry‑run in prod** mode documented (`--dry-run` with live quotes optional later)
- [ ] **Canary plan**: small universe, tiny notionals, paper first, then live
- [ ] **Feature flags** for risky toggles (e.g., market orders, fractional shares)
- [ ] **Release notes** and CHANGELOG updated; semantic version bump

## Security & compliance
- [ ] Least‑privilege principle documented for IB account / client id
- [ ] No secrets in logs or artifacts; secrets usage documented
- [ ] Audit trail: event log includes who/when/what; artifacts stamped & immutable outputs in `--output-dir`
- [ ] License checks for dependencies (notice files if needed)

## Documentation & runbooks
- [ ] **README** updated with production checklist & safety summary
- [ ] **Runbook** (`ops/runbook.md`): start/stop, kill switch, rollback, common errors, pacing incidents
- [ ] **On‑call** notes: what alerts mean, initial triage steps, commands to gather context
- [ ] **Examples**: full end‑to‑end dry‑run & paper commands with expected outputs

## Tests (non‑network, deterministic)
- [ ] Safety cap violations raise clear exceptions with suggested fixes
- [ ] Kill switch removal blocks placement (unit + component test)
- [ ] Retry/backoff unit tests (seeded jitter); bounded attempts verified
- [ ] Idempotency: repeat execution over same plan yields no duplicate orders
- [ ] Event log schema is stable; golden tests for key fields

## Acceptance examples
- [ ] **Cap exceeded**: building orders beyond cap aborts with message listing offending symbols/notionals
- [ ] **Kill switch missing**: live mode exits with code 3 and actionable text
- [ ] **Retryable errors**: two transient quote/provider errors recover via backoff; third aborts with summary
- [ ] **Replay**: rerunning after partial fills continues gracefully without duplicating filled orders

### Reviewer quick commands
```bash
ruff check . && black --check . && mypy . && pytest -q
```
