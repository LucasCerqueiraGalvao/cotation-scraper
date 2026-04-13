# When You Return

Minimal input needed to continue with real Azure execution:

1. Microsoft login/session (`az login`)
2. Real values for `infra/azure/dev.env`:
   - subscription/resource names
   - optional alert email

## Fast path command

```powershell
az login
powershell -ExecutionPolicy Bypass -File .\infra\azure\bootstrap_dev_all.ps1 -EnvFile .\infra\azure\dev.env -DotEnvFile .\.env -UseAcrBuild
```

## If you prefer step-by-step

Use:
- `infra/azure/README.md`
- `docs/runbook_cloud_operations.md`
- `docs/execution_status.md`
