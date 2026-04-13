param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [string]$DotEnvFile = ".\.env",
    [switch]$AllowEmpty
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"
. "$PSScriptRoot\secret_catalog.ps1"

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile
$dot = Load-DotEnvFile -Path $DotEnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$keyVaultName = Require-Setting -Config $cfg -Key "AZ_KEYVAULT_NAME"

Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId

$catalog = Get-SecretCatalog
$updated = 0
$skipped = 0

foreach ($entry in $catalog) {
    $envVar = $entry.EnvVar
    $kvName = $entry.KeyVaultName
    $value = ""

    if ($dot.ContainsKey($envVar)) {
        $value = ($dot[$envVar] | Out-String).Trim()
    }

    if (-not $value -and $cfg.ContainsKey($envVar)) {
        $value = ($cfg[$envVar] | Out-String).Trim()
    }

    if (-not $value -and -not $AllowEmpty) {
        Write-Host "[skip] $envVar -> $kvName (sem valor)"
        $skipped++
        continue
    }

    Write-Host "[set] $envVar -> $kvName"
    Invoke-Az -AzExe $azExe -Args @(
        "keyvault", "secret", "set",
        "--vault-name", $keyVaultName,
        "--name", $kvName,
        "--value", $value
    )
    $updated++
}

Write-Host ""
Write-Host "Key Vault sync concluido."
Write-Host "- vault: $keyVaultName"
Write-Host "- updated: $updated"
Write-Host "- skipped: $skipped"
