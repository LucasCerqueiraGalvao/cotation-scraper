param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [string]$AlertEmail = "",
    [string]$ActionGroupName = "",
    [string]$ActionGroupShortName = "COTOPS"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\..\common.ps1"

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$jobName = Require-Setting -Config $cfg -Key "AZ_CONTAINERAPP_JOB_NAME"
$envName = if ($cfg.ContainsKey("AZ_ENV")) { ($cfg["AZ_ENV"] | Out-String).Trim() } else { "dev" }

if (-not $ActionGroupName) {
    $ActionGroupName = "ag-cotation-scrapers-$envName"
}
if (-not $AlertEmail -and $cfg.ContainsKey("AZ_ALERT_EMAIL")) {
    $AlertEmail = ($cfg["AZ_ALERT_EMAIL"] | Out-String).Trim()
}

Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId

$jobId = Invoke-AzTsv -AzExe $azExe -Args @(
    "containerapp", "job", "show",
    "--resource-group", $resourceGroup,
    "--name", $jobName,
    "--query", "id"
)

if (-not $AlertEmail) {
    throw "Informe -AlertEmail ou AZ_ALERT_EMAIL no env file para criar action group."
}

Write-Host "Creating/updating action group..."
Invoke-Az -AzExe $azExe -Args @(
    "monitor", "action-group", "create",
    "--resource-group", $resourceGroup,
    "--name", $ActionGroupName,
    "--short-name", $ActionGroupShortName,
    "--action", "email", "opsmail", $AlertEmail
)

$actionGroupId = Invoke-AzTsv -AzExe $azExe -Args @(
    "monitor", "action-group", "show",
    "--resource-group", $resourceGroup,
    "--name", $ActionGroupName,
    "--query", "id"
)

$alertName = "alert-$jobName-activity-failure"
Write-Host "Creating/updating activity log alert: $alertName"

try {
    Invoke-Az -AzExe $azExe -Args @(
        "monitor", "activity-log", "alert", "delete",
        "--resource-group", $resourceGroup,
        "--name", $alertName
    )
} catch {
    # ignore if not found
}

Invoke-Az -AzExe $azExe -Args @(
    "monitor", "activity-log", "alert", "create",
    "--resource-group", $resourceGroup,
    "--name", $alertName,
    "--scope", $jobId,
    "--condition", "resourceId=$jobId and status=Failed",
    "--action-group", $actionGroupId,
    "--description", "Alerta para falha de operacoes administrativas no Container Apps Job."
)

Write-Host ""
Write-Host "Alerts baseline configured."
Write-Host "- action_group: $ActionGroupName"
Write-Host "- action_email: $AlertEmail"
Write-Host "- alert_name: $alertName"
