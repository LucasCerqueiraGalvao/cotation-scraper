param(
    [string]$EnvFile = ".\infra\azure\dev.env"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$location = Require-Setting -Config $cfg -Key "AZ_LOCATION"
$envName = Require-Setting -Config $cfg -Key "AZ_ENV"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$acrName = Require-Setting -Config $cfg -Key "AZ_ACR_NAME"
$logWorkspace = Require-Setting -Config $cfg -Key "AZ_LOG_ANALYTICS_NAME"
$containerEnv = Require-Setting -Config $cfg -Key "AZ_CONTAINERAPPS_ENV_NAME"
$keyVaultName = Require-Setting -Config $cfg -Key "AZ_KEYVAULT_NAME"
$storageAccount = Require-Setting -Config $cfg -Key "AZ_STORAGE_ACCOUNT_NAME"
$fileShare = Require-Setting -Config $cfg -Key "AZ_FILE_SHARE_NAME"
$tagProject = Require-Setting -Config $cfg -Key "AZ_TAG_PROJECT"
$tagOwner = Require-Setting -Config $cfg -Key "AZ_TAG_OWNER"
$tagCostCenter = Require-Setting -Config $cfg -Key "AZ_TAG_COST_CENTER"

$tags = @(
    "project=$tagProject"
    "env=$envName"
    "owner=$tagOwner"
    "costCenter=$tagCostCenter"
    "managedBy=codex"
)

Write-Host "Setting Azure subscription..."
Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId
$accountName = Invoke-AzTsv -AzExe $azExe -Args @("account", "show", "--query", "name")
Write-Host "Using subscription: $accountName ($subscriptionId)"

Write-Host "Registering resource providers..."
Invoke-Az -AzExe $azExe -Args @("provider", "register", "--namespace", "Microsoft.App")
Invoke-Az -AzExe $azExe -Args @("provider", "register", "--namespace", "Microsoft.OperationalInsights")
Invoke-Az -AzExe $azExe -Args @("provider", "register", "--namespace", "Microsoft.KeyVault")
Invoke-Az -AzExe $azExe -Args @("provider", "register", "--namespace", "Microsoft.Storage")

Write-Host "Ensuring containerapp extension..."
Invoke-Az -AzExe $azExe -Args @("extension", "add", "--name", "containerapp", "--upgrade")

Write-Host "Creating/Updating Resource Group..."
Invoke-AzJson -AzExe $azExe -Args (
    @(
        "group", "create",
        "--name", $resourceGroup,
        "--location", $location,
        "--tags"
    ) + $tags
) | Out-Null

Write-Host "Creating/Updating Log Analytics workspace..."
Invoke-AzJson -AzExe $azExe -Args (
    @(
        "monitor", "log-analytics", "workspace", "create",
        "--resource-group", $resourceGroup,
        "--workspace-name", $logWorkspace,
        "--location", $location,
        "--sku", "PerGB2018",
        "--tags"
    ) + $tags
) | Out-Null

$workspaceId = Invoke-AzTsv -AzExe $azExe -Args @(
    "monitor", "log-analytics", "workspace", "show",
    "--resource-group", $resourceGroup,
    "--workspace-name", $logWorkspace,
    "--query", "customerId"
)
$workspaceKey = Invoke-AzTsv -AzExe $azExe -Args @(
    "monitor", "log-analytics", "workspace", "get-shared-keys",
    "--resource-group", $resourceGroup,
    "--workspace-name", $logWorkspace,
    "--query", "primarySharedKey"
)

Write-Host "Creating/Updating ACR..."
Invoke-AzJson -AzExe $azExe -Args (
    @(
        "acr", "create",
        "--resource-group", $resourceGroup,
        "--name", $acrName,
        "--sku", "Basic",
        "--admin-enabled", "false",
        "--location", $location,
        "--tags"
    ) + $tags
) | Out-Null

Write-Host "Creating/Updating Key Vault..."
Invoke-AzJson -AzExe $azExe -Args (
    @(
        "keyvault", "create",
        "--resource-group", $resourceGroup,
        "--name", $keyVaultName,
        "--location", $location,
        "--sku", "standard",
        "--enable-rbac-authorization", "true",
        "--tags"
    ) + $tags
) | Out-Null

Write-Host "Creating/Updating Storage Account..."
Invoke-AzJson -AzExe $azExe -Args (
    @(
        "storage", "account", "create",
        "--resource-group", $resourceGroup,
        "--name", $storageAccount,
        "--location", $location,
        "--sku", "Standard_LRS",
        "--kind", "StorageV2",
        "--min-tls-version", "TLS1_2",
        "--allow-blob-public-access", "false",
        "--tags"
    ) + $tags
) | Out-Null

Write-Host "Ensuring Azure File Share..."
Invoke-AzJson -AzExe $azExe -Args @(
    "storage", "share-rm", "create",
    "--resource-group", $resourceGroup,
    "--storage-account", $storageAccount,
    "--name", $fileShare,
    "--quota", "100"
) | Out-Null

Write-Host "Creating/Updating Container Apps Environment..."
Invoke-AzJson -AzExe $azExe -Args (
    @(
        "containerapp", "env", "create",
        "--resource-group", $resourceGroup,
        "--name", $containerEnv,
        "--location", $location,
        "--logs-workspace-id", $workspaceId,
        "--logs-workspace-key", $workspaceKey,
        "--tags"
    ) + $tags
) | Out-Null

$acrLoginServer = Invoke-AzTsv -AzExe $azExe -Args @(
    "acr", "show",
    "--resource-group", $resourceGroup,
    "--name", $acrName,
    "--query", "loginServer"
)

$summary = [ordered]@{
    subscription_id = $subscriptionId
    resource_group = $resourceGroup
    location = $location
    acr_name = $acrName
    acr_login_server = $acrLoginServer
    log_analytics_workspace = $logWorkspace
    containerapps_environment = $containerEnv
    key_vault = $keyVaultName
    storage_account = $storageAccount
    file_share = $fileShare
}

Write-Host ""
Write-Host "Provisioning completed successfully."
$summary.GetEnumerator() | ForEach-Object {
    Write-Host ("- {0}: {1}" -f $_.Key, $_.Value)
}
