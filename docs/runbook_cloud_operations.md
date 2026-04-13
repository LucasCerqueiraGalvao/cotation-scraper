# Runbook - Cloud Operations

Status: active  
Last update: 2026-03-31

## Scope

Operational procedures for Azure Container Apps Job execution of Cotation Scrapers.

## Components

- Container Apps Job: daily runner
- Azure Container Registry: image repository
- Key Vault: secrets source
- Log Analytics: log storage and diagnostics
- SharePoint (Graph): final file upload target

## Daily Operation Checklist

1. Confirm last run status:
   - `powershell -ExecutionPolicy Bypass -File .\infra\azure\verify_job_configuration.ps1 -EnvFile .\infra\azure\dev.env`
2. Confirm expected outputs in SharePoint:
   - `comparacao_carriers_cliente.xlsx`
   - `comparacao_carriers_cliente_special.xlsx`
   - `comparacao_carriers_cliente_granito.xlsx`
3. Confirm no consecutive failure trend in recent executions.

## Standard Commands

### Start smoke run

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\start_job_smoke.ps1 -EnvFile .\infra\azure\dev.env -NoWait
```

### Build and deploy new image tag

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\build_and_push_image.ps1 -EnvFile .\infra\azure\dev.env
powershell -ExecutionPolicy Bypass -File .\infra\azure\configure_job_schedule.ps1 -EnvFile .\infra\azure\dev.env -ImageTag <TAG>
```

### Rollback image

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\rollback_job_image.ps1 -EnvFile .\infra\azure\dev.env -RollbackTag <LAST_STABLE_TAG> -StartAfterRollback
```

## Incident Triage

1. Identify failing stage in logs (`hapag`, `maersk`, `comparison`, `upload`).
2. Capture evidence:
   - run id
   - error excerpt
   - execution name and timestamp
3. Classify severity:
   - transient: single retry permitted
   - persistent: open incident and escalate

## Failure Policy

- Retry once for transient errors.
- Trigger incident when:
  - 2 consecutive failed runs, or
  - SharePoint upload failure blocks delivery for over 4 hours.

## Escalation Matrix

- L1 Operator: Data Analytics operations owner
- L2 Engineering: scraping/runtime maintainer
- L3 Business owner: freight operations stakeholder

Note: replace with named people/on-call rota in production handoff document.

## Alerts and Dashboard

- Baseline alert creation:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\observability\create_alerts_baseline.ps1 -EnvFile .\infra\azure\dev.env -AlertEmail "<ops@company.com>"
```

- KQL query pack:
  - `infra/azure/observability/kql_queries.md`

## Secret Management

- Seed/update secrets from local `.env`:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\seed_keyvault_secrets_from_dotenv.ps1 -EnvFile .\infra\azure\dev.env -DotEnvFile .\.env
```

- Apply to job as Key Vault references:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\configure_job_identity_and_secrets.ps1 -EnvFile .\infra\azure\dev.env
```

## Known Behaviors

- Some routes naturally return "sem cotacao" and this is not a hard failure by itself.
- Full job can take hours; smoke runs should be used for fast operational checks.
- Anonymous share links can be blocked by tenant policy; upload can still succeed.
