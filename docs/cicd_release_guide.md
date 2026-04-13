# CI/CD and Release Guide

Last update: 2026-03-31

## Workflows

- `CI` (`.github/workflows/ci.yml`)
  - Python compile checks
  - orchestrator dry-run smoke
  - docker build sanity
- `CD Dev` (`.github/workflows/cd-dev.yml`)
  - builds/pushes image to ACR (remote build)
  - updates scheduled job in `dev`
  - optional smoke start
- `CD Prod` (`.github/workflows/cd-prod.yml`)
  - deploys an existing image tag to `prod`
  - optional smoke start
  - should run under GitHub `production` environment approvals

## Required GitHub Secrets

- `AZURE_CREDENTIALS` (service principal JSON for `azure/login`)
- `AZ_SUBSCRIPTION_ID`
- `AZ_RESOURCE_GROUP_DEV`
- `AZ_ACR_NAME_DEV`
- `AZ_CONTAINERAPPS_ENV_NAME_DEV`
- `AZ_KEYVAULT_NAME_DEV`
- `AZ_CONTAINERAPP_JOB_NAME_DEV`
- `AZ_RESOURCE_GROUP_PROD`
- `AZ_ACR_NAME_PROD`
- `AZ_CONTAINERAPPS_ENV_NAME_PROD`
- `AZ_KEYVAULT_NAME_PROD`
- `AZ_CONTAINERAPP_JOB_NAME_PROD`

## Optional GitHub Variables

- `AZ_LOCATION` (`brazilsouth` default)
- `AZ_LOG_ANALYTICS_NAME_DEV`
- `AZ_LOG_ANALYTICS_NAME_PROD`
- `AZ_STORAGE_ACCOUNT_NAME_DEV`
- `AZ_STORAGE_ACCOUNT_NAME_PROD`
- `AZ_FILE_SHARE_NAME_DEV`
- `AZ_FILE_SHARE_NAME_PROD`
- `AZ_JOB_CRON_UTC_DEV` (`0 7 * * 1-5` default)
- `AZ_JOB_CRON_UTC_PROD` (`0 7 * * 1-5` default)

## Release Flow

1. Merge code to `main` (CI must pass).
2. Run `CD Dev` with generated tag.
3. Validate smoke and artifacts in `dev`.
4. Promote same tag with `CD Prod`.
5. Record deployed tag and timestamp.

## Rollback Flow

1. Identify last stable tag.
2. Run `rollback_job_image.ps1` (or `CD Prod` with stable tag).
3. Trigger smoke.
4. Confirm logs and SharePoint upload.
