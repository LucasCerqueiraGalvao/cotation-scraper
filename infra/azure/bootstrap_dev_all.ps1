param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [string]$DotEnvFile = ".\.env",
    [string]$ImageTag = "",
    [string]$AlertEmail = "",
    [switch]$UseAcrBuild,
    [switch]$SkipAlerts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $ImageTag) {
    $ImageTag = Get-Date -Format "yyyyMMdd-HHmm"
}

Write-Host "=== Step 1/8: Provision foundation ==="
powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\provision_foundation.ps1" -EnvFile $EnvFile

Write-Host "=== Step 2/8: Seed Key Vault secrets ==="
powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\seed_keyvault_secrets_from_dotenv.ps1" -EnvFile $EnvFile -DotEnvFile $DotEnvFile

Write-Host "=== Step 3/8: Build and push image ==="
$buildArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", "$PSScriptRoot\build_and_push_image.ps1",
    "-EnvFile", $EnvFile,
    "-ImageTag", $ImageTag
)
if ($UseAcrBuild) {
    $buildArgs += "-UseAcrBuild"
}
powershell @buildArgs

Write-Host "=== Step 4/8: Create manual job ==="
powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\create_job_manual.ps1" -EnvFile $EnvFile -ImageTag $ImageTag

Write-Host "=== Step 5/8: Configure identity and secrets ==="
powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\configure_job_identity_and_secrets.ps1" -EnvFile $EnvFile

Write-Host "=== Step 6/8: Configure schedule ==="
powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\configure_job_schedule.ps1" -EnvFile $EnvFile -ImageTag $ImageTag -ForceRecreate

if (-not $SkipAlerts) {
    Write-Host "=== Step 7/8: Create alerts baseline ==="
    $alertArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", "$PSScriptRoot\observability\create_alerts_baseline.ps1",
        "-EnvFile", $EnvFile
    )
    if ($AlertEmail) {
        $alertArgs += @("-AlertEmail", $AlertEmail)
    }
    powershell @alertArgs
} else {
    Write-Host "=== Step 7/8: Alerts skipped ==="
}

Write-Host "=== Step 8/8: Verify job configuration ==="
powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\verify_job_configuration.ps1" -EnvFile $EnvFile

Write-Host ""
Write-Host "Bootstrap completed successfully."
Write-Host "- image_tag: $ImageTag"
