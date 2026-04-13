# ADR 0001 - Scope and Operational Baseline

Status: Accepted  
Date: 2026-03-31

## Context
The project needs to migrate from local execution to cloud execution with operational stability and clear fallback criteria.

## Decision
1. Primary platform: `Azure Container Apps Jobs`.
2. Official fallback: `Azure VM + Task Scheduler`.
3. Fallback trigger:
   - two consecutive production failures, or
   - one critical upload-blocking failure for more than 4 hours.
4. Official schedule:
   - timezone: `America/Sao_Paulo`
   - time: `04:00`
   - weekdays only (Monday to Friday).
5. SLA/KPI baseline:
   - 30-day success rate >= `95%`
   - hard timeout per run: `5h`
   - operational target p95: `<= 4h30`.
6. Secrets policy:
   - secrets only in `Azure Key Vault`
   - no hardcoded secrets in repo/scripts/image
   - quarterly rotation (or immediate in incident).
7. Manual files strategy (`cma/one/zim`) in cloud:
   - preferred: Graph download at each run
   - fallback: mounted persistent copy.
8. Cloud persistence strategy:
   - `Azure Files` for browser profiles and troubleshooting artifacts.
9. Environment matrix:
   - `dev` for technical validation and stability tuning
   - `prod` for official daily operation.

## Consequences
- We can start Subplan 01 without open decision blockers.
- We reduce migration risk with an explicit fallback path.
- Runtime objectives are now measurable and auditable.
