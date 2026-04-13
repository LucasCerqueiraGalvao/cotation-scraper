param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [string]$ImageName = "",
    [string]$ImageTag = "latest",
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"
. "$PSScriptRoot\secret_catalog.ps1"

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$acrName = Require-Setting -Config $cfg -Key "AZ_ACR_NAME"
$containerEnv = Require-Setting -Config $cfg -Key "AZ_CONTAINERAPPS_ENV_NAME"
$jobName = Require-Setting -Config $cfg -Key "AZ_CONTAINERAPP_JOB_NAME"

$jobCpu = if ($cfg.ContainsKey("AZ_JOB_CPU")) { $cfg["AZ_JOB_CPU"] } else { "2.0" }
$jobMemory = if ($cfg.ContainsKey("AZ_JOB_MEMORY")) { $cfg["AZ_JOB_MEMORY"] } else { "4Gi" }
$jobReplicaTimeout = if ($cfg.ContainsKey("AZ_JOB_REPLICA_TIMEOUT_SEC")) { $cfg["AZ_JOB_REPLICA_TIMEOUT_SEC"] } else { "18000" }
$jobReplicaRetry = if ($cfg.ContainsKey("AZ_JOB_REPLICA_RETRY_LIMIT")) { $cfg["AZ_JOB_REPLICA_RETRY_LIMIT"] } else { "0" }
$jobReplicaCompletion = if ($cfg.ContainsKey("AZ_JOB_REPLICA_COMPLETION_COUNT")) { $cfg["AZ_JOB_REPLICA_COMPLETION_COUNT"] } else { "1" }
$jobParallelism = if ($cfg.ContainsKey("AZ_JOB_PARALLELISM")) { $cfg["AZ_JOB_PARALLELISM"] } else { "1" }
$jobCronUtc = if ($cfg.ContainsKey("AZ_JOB_CRON_UTC")) { $cfg["AZ_JOB_CRON_UTC"] } else { "0 7 * * 1-5" }
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
$image = "$acrLoginServer/$ImageName`:$ImageTag"

$jobExists = $true
try {
    Invoke-Az -AzExe $azExe -Args @(
        "containerapp", "job", "show",
        "--resource-group", $resourceGroup,
        "--name", $jobName
    )
} catch {
    $jobExists = $false
}

if (-not $jobExists) {
    Write-Host "Creating scheduled job..."

    $envPairs = @()
    foreach ($d in (Get-NonSecretEnvDefaults)) {
        $k = $d.Key
        $v = $d.Value
        if ($cfg.ContainsKey($k) -and ($cfg[$k] | Out-String).Trim()) {
            $v = ($cfg[$k] | Out-String).Trim()
        }
        $envPairs += "$k=$v"
    }

    Invoke-Az -AzExe $azExe -Args (
        @(
            "containerapp", "job", "create",
            "--resource-group", $resourceGroup,
            "--name", $jobName,
            "--environment", $containerEnv,
            "--trigger-type", "Schedule",
            "--cron-expression", $jobCronUtc,
            "--replica-timeout", $jobReplicaTimeout,
            "--replica-retry-limit", $jobReplicaRetry,
            "--replica-completion-count", $jobReplicaCompletion,
            "--parallelism", $jobParallelism,
            "--image", $image,
            "--container-name", $jobContainerName,
            "--cpu", $jobCpu,
            "--memory", $jobMemory,
            "--command", "python",
            "--args", "src/orchestration/daily_pipeline_runner.py",
            "--env-vars"
        ) + $envPairs
    )

    Write-Host "Scheduled job created."
} else {
    $currentTrigger = Invoke-AzTsv -AzExe $azExe -Args @(
        "containerapp", "job", "show",
        "--resource-group", $resourceGroup,
        "--name", $jobName,
        "--query", "properties.configuration.triggerType"
    )

    if (($currentTrigger -ieq "Manual") -and -not $ForceRecreate) {
        throw "Job '$jobName' esta em trigger Manual. Rode novamente com -ForceRecreate para recriar como Schedule."
    }

    if (($currentTrigger -ieq "Manual") -and $ForceRecreate) {
        Write-Host "Recreating manual job as scheduled job..."
        Invoke-Az -AzExe $azExe -Args @(
            "containerapp", "job", "delete",
            "--resource-group", $resourceGroup,
            "--name", $jobName,
            "--yes"
        )
        Invoke-Az -AzExe $azExe -Args @(
            "containerapp", "job", "create",
            "--resource-group", $resourceGroup,
            "--name", $jobName,
            "--environment", $containerEnv,
            "--trigger-type", "Schedule",
            "--cron-expression", $jobCronUtc,
            "--replica-timeout", $jobReplicaTimeout,
            "--replica-retry-limit", $jobReplicaRetry,
            "--replica-completion-count", $jobReplicaCompletion,
            "--parallelism", $jobParallelism,
            "--image", $image,
            "--container-name", $jobContainerName,
            "--cpu", $jobCpu,
            "--memory", $jobMemory,
            "--command", "python",
            "--args", "src/orchestration/daily_pipeline_runner.py"
        )
    } else {
        Write-Host "Updating scheduled job settings..."
        Invoke-Az -AzExe $azExe -Args @(
            "containerapp", "job", "update",
            "--resource-group", $resourceGroup,
            "--name", $jobName,
            "--cron-expression", $jobCronUtc,
            "--image", $image,
            "--container-name", $jobContainerName,
            "--cpu", $jobCpu,
            "--memory", $jobMemory,
            "--replica-timeout", $jobReplicaTimeout,
            "--replica-retry-limit", $jobReplicaRetry,
            "--replica-completion-count", $jobReplicaCompletion,
            "--parallelism", $jobParallelism
        )
    }
}

Write-Host ""
Write-Host "Schedule configured."
Write-Host "- job: $jobName"
Write-Host "- image: $image"
Write-Host "- cron(UTC): $jobCronUtc"

