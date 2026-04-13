# Execution Status - Azure Migration

Last update: 2026-03-31

## Objective
Track, in one place, what is already done and what is still pending for the Azure migration plan.

## Current Phase
- In progress: `Fase 3-8 automation pack (ready to execute with credentials)`
- Next: `Execucao real em Azure (dev/prod) apos login e envs`

## Done
- Planning structure created and organized:
  - `plan_master.md`
  - `azure_deploy_plan.md`
  - `docs/subplans/subplan_00` ... `subplan_08`
- Baseline ADR published:
  - `docs/adr/adr_0001_scope_and_ops_baseline.md`
- SharePoint upload mode already available in code (`UPLOAD_MODE=SHAREPOINT`).
- New granite output flow implemented and published:
  - `comparacao_carriers_cliente_granito.xlsx`
- Route matrix for granite scenario added in local inputs and manual sheets:
  - new indexes `256..268`
  - destination flags `GRANITO JOBS` and `GRANITO MARKUP USD`
- Initial cloud-readiness scan executed (paths/env/sync points mapped).
- Cloud preflight script implemented:
  - `scripts/preflight_cloud_env.py`
- README updated with cloud preflight and cloud-like execution flow.
- Operational runbook finalized:
  - `docs/runbook_cloud_operations.md`
- Cloud-like dry-run completed:
  - evidence: `artifacts/logs/20260331_112844_pipeline.log`
- Cloud-like fast validation completed (without full scraping):
  - preflight SharePoint OK (`failures=0`, `warnings=0`)
  - evidence log: `artifacts/logs/20260331_120743_cloudlike_fast_validation.log`
  - 3 outputs generated and uploaded to SharePoint:
    - `comparacao_carriers_cliente.xlsx`
    - `comparacao_carriers_cliente_special.xlsx`
    - `comparacao_carriers_cliente_granito.xlsx`
- Legacy launcher hardened for cloud/runtime portability:
  - `scripts/run_daily_pipeline.cmd` now resolves Python as `.venv -> py -3 -> python`
- Docker predeploy foundation started:
  - `Dockerfile` + `.dockerignore` created
  - runtime dependencies completed in `requirements.txt`
  - Maersk browser channel made configurable (`MAERSK_BROWSER_CHANNEL`)
- Docker local build validated:
  - command: `docker build -t quotation-scrapers:local .`
  - result: image generated successfully.
- Docker runtime sanity validated:
  - command: `docker run --rm quotation-scrapers:local python src/orchestration/daily_pipeline_runner.py --dry-run`
  - result: exit code `0`.
  - evidence: `artifacts/logs/20260331_122001_docker_dryrun.log`
- Docker cloud-like fast validation with real outputs completed:
  - evidence: `artifacts/logs/20260331_121852_docker_cloudlike_fast_validation.log`
  - outputs generated and uploaded from container:
    - `comparacao_carriers_cliente.xlsx`
    - `comparacao_carriers_cliente_special.xlsx`
    - `comparacao_carriers_cliente_granito.xlsx`
- Azure foundation automation scaffold prepared:
  - `infra/azure/common.ps1`
  - `infra/azure/dev.env.example`
  - `infra/azure/prod.env.example`
  - `infra/azure/provision_foundation.ps1`
  - `infra/azure/create_job_manual.ps1`
  - `infra/azure/seed_keyvault_secrets_from_dotenv.ps1`
  - `infra/azure/configure_job_identity_and_secrets.ps1`
  - `infra/azure/build_and_push_image.ps1`
  - `infra/azure/configure_job_schedule.ps1`
  - `infra/azure/start_job_smoke.ps1`
  - `infra/azure/verify_job_configuration.ps1`
  - `infra/azure/rollback_job_image.ps1`
  - `infra/azure/observability/create_alerts_baseline.ps1`
  - `infra/azure/observability/kql_queries.md`
  - `infra/azure/README.md`
  - local scaffold files created (ignored in git): `infra/azure/dev.env`, `infra/azure/prod.env`
- Azure CLI installed on host:
  - `Microsoft.AzureCLI 2.84.0`
  - scripts updated to resolve `az.cmd` even when PATH is not refreshed.
- Runtime observability improved:
  - runner propagates `RUN_ID` and `PIPELINE_STAGE` for child stages
  - comparison/upload now log runtime metadata
  - evidence: `artifacts/logs/20260331_124233_runner_dryrun_after_runid.log`
  - evidence: `artifacts/logs/20260331_124243_runid_component_smoke.log`
  - evidence: `artifacts/logs/20260331_124907_docker_dryrun_after_rebuild.log`
- CI/CD baseline created:
  - `.github/workflows/ci.yml`
  - `.github/workflows/cd-dev.yml`
  - `.github/workflows/cd-prod.yml`
  - `docs/cicd_release_guide.md`
- Go-live/hypercare artifacts created:
  - `docs/go_live_checklist.md`
  - `docs/hypercare_daily_log_template.md`
  - `docs/when_you_return.md`

## Pending (high priority)
- Run real Azure provisioning in `dev` using `infra/azure/provision_foundation.ps1`.
- Seed secrets and apply identity/RBAC in Azure `dev`.
- Run manual/smoke executions in Azure and validate Log Analytics + SharePoint upload.
- Configure GitHub secrets/vars and execute first `CD Dev` pipeline run.
- Configure alert email target and create baseline action group/alerts.
- (Optional) Run full scraper benchmark inside container for anti-bot behavior and duration profile.

## Info Needed From User
- Need Azure authenticated session (`az login`) and tenant/subscription context to execute provisioning.
- Need `infra/azure/dev.env` (already scaffolded locally) filled with real resource names/IDs.
- Need final Microsoft credentials and target email for alerts/action group.
- User input will be requested only when execution needs tenant-specific access that cannot be inferred from repo/local context.

## Subplan Progress
- `subplan_00_scope_and_decisions`: `done`
- `subplan_01_code_cloud_readiness`: `done`
- `subplan_02_local_docker_predeploy`: `done`
- `subplan_03_azure_infra_foundation`: `in_progress`
- `subplan_04_identity_secrets_sharepoint_graph`: `in_progress`
- `subplan_05_container_apps_job_schedule`: `in_progress`
- `subplan_06_cicd_and_release_management`: `in_progress`
- `subplan_07_observability_and_runbook`: `in_progress`
- `subplan_08_go_live_hypercare_rollback`: `in_progress`

## Update Rule
- Every execution block must update:
  - this file (`docs/execution_status.md`)
  - the active subplan file (`docs/subplans/subplan_xx_*.md`)
- Use explicit sections:
  - `Done in this cycle`
  - `Still pending`
  - `Blockers / info needed`

