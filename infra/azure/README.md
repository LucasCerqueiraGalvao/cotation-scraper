# Azure Scripts

Infrastructure and operations scripts for the Azure migration plan.

## Files

- `common.ps1`: shared helpers (env parsing, az execution, subscription setup)
- `secret_catalog.ps1`: secret mapping (`ENV VAR` -> `Key Vault` -> `Job secret`)
- `dev.env.example`: template for `dev`
- `prod.env.example`: template for `prod`
- `provision_foundation.ps1`: provision baseline infra
- `create_job_manual.ps1`: create manual Container Apps Job and trigger one execution
- `seed_keyvault_secrets_from_dotenv.ps1`: push local `.env` values to Key Vault
- `configure_job_identity_and_secrets.ps1`: assign job identity, RBAC, registry auth, keyvault-backed secrets and env vars
- `build_and_push_image.ps1`: build and push image to ACR
- `configure_job_schedule.ps1`: create/update scheduled job and runtime settings
- `start_job_smoke.ps1`: trigger smoke execution and optionally poll status
- `verify_job_configuration.ps1`: print current job config/secrets/executions
- `rollback_job_image.ps1`: rollback job image to stable tag
- `bootstrap_dev_all.ps1`: one-shot orchestration of dev bootstrap flow
- `observability/create_alerts_baseline.ps1`: create action group + baseline activity-log alert
- `observability/kql_queries.md`: query snippets for dashboard/troubleshooting

## Setup

1. Copy environment file:

```powershell
Copy-Item .\infra\azure\dev.env.example .\infra\azure\dev.env
```

2. Authenticate Azure:

```powershell
az login
```

3. Select subscription (if needed):

```powershell
az account set --subscription <SUBSCRIPTION_ID>
```

## End-to-End (Dev)

1. Provision base infra:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\provision_foundation.ps1 -EnvFile .\infra\azure\dev.env
```

2. Build and push image:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\build_and_push_image.ps1 -EnvFile .\infra\azure\dev.env
```

3. Create manual job + initial run:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\create_job_manual.ps1 -EnvFile .\infra\azure\dev.env -ImageTag latest
```

4. Seed secrets from local `.env`:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\seed_keyvault_secrets_from_dotenv.ps1 -EnvFile .\infra\azure\dev.env -DotEnvFile .\.env
```

5. Configure identity + keyvault-backed job secrets/env vars:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\configure_job_identity_and_secrets.ps1 -EnvFile .\infra\azure\dev.env
```

6. Convert/update to scheduled execution:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\configure_job_schedule.ps1 -EnvFile .\infra\azure\dev.env -ImageTag latest -ForceRecreate
```

7. Smoke execution:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\start_job_smoke.ps1 -EnvFile .\infra\azure\dev.env -NoWait
```

8. Configure baseline alerts:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\observability\create_alerts_baseline.ps1 -EnvFile .\infra\azure\dev.env -AlertEmail "<ops@company.com>"
```

9. Verify configuration:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\verify_job_configuration.ps1 -EnvFile .\infra\azure\dev.env
```

## One-shot Bootstrap (Dev)

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\bootstrap_dev_all.ps1 -EnvFile .\infra\azure\dev.env -DotEnvFile .\.env -UseAcrBuild
```

## Notes

- `AZ_JOB_CRON_UTC=0 7 * * 1-5` means `04:00` in `America/Sao_Paulo` (UTC-3 baseline).
- `configure_job_schedule.ps1` does not destroy a manual job unless `-ForceRecreate` is used.
- `seed_keyvault_secrets_from_dotenv.ps1` only updates values present in `.env` (unless `-AllowEmpty`).
- Keep `dev.env`/`prod.env` out of git if they contain sensitive values.
