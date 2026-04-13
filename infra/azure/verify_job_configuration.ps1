param(
    [string]$EnvFile = ".\infra\azure\dev.env"
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

Write-Host "Job summary:"
& $azExe containerapp job show `
    --resource-group $resourceGroup `
    --name $jobName `
    --query "{name:name,triggerType:properties.configuration.triggerType,image:properties.template.containers[0].image,cronExpression:properties.configuration.scheduleTriggerConfig.cronExpression,parallelism:properties.configuration.manualTriggerConfig.parallelism}" `
    --only-show-errors -o table

Write-Host ""
Write-Host "Identity:"
& $azExe containerapp job identity show `
    --resource-group $resourceGroup `
    --name $jobName `
    --only-show-errors -o table

Write-Host ""
Write-Host "Configured secrets:"
& $azExe containerapp job secret list `
    --resource-group $resourceGroup `
    --name $jobName `
    --query "[].name" `
    --only-show-errors -o tsv

Write-Host ""
Write-Host "Recent executions:"
& $azExe containerapp job execution list `
    --resource-group $resourceGroup `
    --name $jobName `
    --query "[0:5].{name:name,status:properties.status,start:properties.startTime,end:properties.endTime}" `
    --only-show-errors -o table
