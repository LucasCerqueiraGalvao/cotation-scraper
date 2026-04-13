param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [int]$PollSeconds = 15,
    [int]$TimeoutSeconds = 600,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$jobName = Require-Setting -Config $cfg -Key "AZ_CONTAINERAPP_JOB_NAME"

Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId

Write-Host "Starting manual job execution..."
Invoke-Az -AzExe $azExe -Args @(
    "containerapp", "job", "start",
    "--resource-group", $resourceGroup,
    "--name", $jobName
)

Write-Host "Latest executions snapshot:"
& $azExe containerapp job execution list `
    --resource-group $resourceGroup `
    --name $jobName `
    --query "[0:3].{name:name,status:properties.status,startTime:properties.startTime,endTime:properties.endTime}" `
    --only-show-errors -o table

if ($NoWait) {
    return
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    $status = Invoke-AzTsv -AzExe $azExe -Args @(
        "containerapp", "job", "execution", "list",
        "--resource-group", $resourceGroup,
        "--name", $jobName,
        "--query", "[0].properties.status"
    )
    if (-not $status) {
        Start-Sleep -Seconds $PollSeconds
        continue
    }

    Write-Host "[poll] status=$status"
    $normalized = $status.ToLowerInvariant()
    if ($normalized -in @("succeeded", "failed", "stopped", "completed", "cancelled")) {
        Write-Host "Execution reached terminal state: $status"
        return
    }

    Start-Sleep -Seconds $PollSeconds
}

Write-Host "Timeout reached while waiting execution status."
