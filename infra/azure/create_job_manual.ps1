param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [string]$ImageTag = "latest",
    [string]$ImageName = "quotation-scrapers"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"

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
$jobContainerName = if ($cfg.ContainsKey("AZ_JOB_CONTAINER_NAME")) { $cfg["AZ_JOB_CONTAINER_NAME"] } else { "quotation-scrapers" }

Write-Host "Setting Azure subscription..."
Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId

Write-Host "Ensuring containerapp extension..."
Invoke-Az -AzExe $azExe -Args @("extension", "add", "--name", "containerapp", "--upgrade")

$acrLoginServer = Invoke-AzTsv -AzExe $azExe -Args @(
    "acr", "show",
    "--resource-group", $resourceGroup,
    "--name", $acrName,
    "--query", "loginServer"
)

$image = "$acrLoginServer/$ImageName`:$ImageTag"
Write-Host "Using image: $image"

Write-Host "Creating or updating manual Container Apps Job..."
Invoke-Az -AzExe $azExe -Args @(
    "containerapp", "job", "create",
    "--resource-group", $resourceGroup,
    "--name", $jobName,
    "--environment", $containerEnv,
    "--trigger-type", "Manual",
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
    "--env-vars", "UPLOAD_MODE=SHAREPOINT", "UPLOAD_ENSURE_ONEDRIVE=FALSE", "LOG_RETENTION_DAYS=14"
)

Write-Host "Triggering manual execution once..."
Invoke-Az -AzExe $azExe -Args @(
    "containerapp", "job", "start",
    "--resource-group", $resourceGroup,
    "--name", $jobName
)

Write-Host "Job created and manual execution triggered successfully."

