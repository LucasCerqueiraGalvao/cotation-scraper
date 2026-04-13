param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [string]$ImageName = "",
    [string]$RollbackTag,
    [switch]$StartAfterRollback
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"

if (-not $RollbackTag) {
    throw "Informe -RollbackTag para rollback da imagem."
}

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$acrName = Require-Setting -Config $cfg -Key "AZ_ACR_NAME"
$jobName = Require-Setting -Config $cfg -Key "AZ_CONTAINERAPP_JOB_NAME"
$jobContainerName = if ($cfg.ContainsKey("AZ_JOB_CONTAINER_NAME")) { $cfg["AZ_JOB_CONTAINER_NAME"] } else { "quotation-scrapers" }
$defaultImageName = if ($cfg.ContainsKey("AZ_IMAGE_NAME")) { $cfg["AZ_IMAGE_NAME"] } else { "quotation-scrapers" }

if (-not $ImageName) {
    $ImageName = $defaultImageName
}

Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId
$acrLoginServer = Invoke-AzTsv -AzExe $azExe -Args @(
    "acr", "show",
    "--resource-group", $resourceGroup,
    "--name", $acrName,
    "--query", "loginServer"
)

$image = "$acrLoginServer/$ImageName`:$RollbackTag"

Write-Host "Applying rollback image: $image"
Invoke-Az -AzExe $azExe -Args @(
    "containerapp", "job", "update",
    "--resource-group", $resourceGroup,
    "--name", $jobName,
    "--container-name", $jobContainerName,
    "--image", $image
)

if ($StartAfterRollback) {
    Write-Host "Triggering manual run after rollback..."
    Invoke-Az -AzExe $azExe -Args @(
        "containerapp", "job", "start",
        "--resource-group", $resourceGroup,
        "--name", $jobName
    )
}

Write-Host "Rollback applied successfully."

