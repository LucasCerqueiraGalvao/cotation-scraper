param(
    [string]$EnvFile = ".\infra\azure\dev.env"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"
. "$PSScriptRoot\secret_catalog.ps1"

function Ensure-RoleAssignment {
    param(
        [string]$AzExe,
        [string]$AssigneeObjectId,
        [string]$Scope,
        [string]$Role
    )

    $existingCount = Invoke-AzTsv -AzExe $AzExe -Args @(
        "role", "assignment", "list",
        "--assignee-object-id", $AssigneeObjectId,
        "--scope", $Scope,
        "--role", $Role,
        "--query", "length(@)"
    )

    if ([int]$existingCount -gt 0) {
        Write-Host "[role] ja existe: $Role @ $Scope"
        return
    }

    Write-Host "[role] criando: $Role @ $Scope"
    Invoke-Az -AzExe $AzExe -Args @(
        "role", "assignment", "create",
        "--assignee-object-id", $AssigneeObjectId,
        "--assignee-principal-type", "ServicePrincipal",
        "--role", $Role,
        "--scope", $Scope
    )
}

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$acrName = Require-Setting -Config $cfg -Key "AZ_ACR_NAME"
$keyVaultName = Require-Setting -Config $cfg -Key "AZ_KEYVAULT_NAME"
$jobName = Require-Setting -Config $cfg -Key "AZ_CONTAINERAPP_JOB_NAME"
$jobContainerName = if ($cfg.ContainsKey("AZ_JOB_CONTAINER_NAME")) { $cfg["AZ_JOB_CONTAINER_NAME"] } else { "cotation-scrapers" }

Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId

Write-Host "Ensuring system-assigned identity on job..."
Invoke-Az -AzExe $azExe -Args @(
    "containerapp", "job", "identity", "assign",
    "--resource-group", $resourceGroup,
    "--name", $jobName,
    "--system-assigned"
)

$principalId = Invoke-AzTsv -AzExe $azExe -Args @(
    "containerapp", "job", "identity", "show",
    "--resource-group", $resourceGroup,
    "--name", $jobName,
    "--query", "principalId"
)
if (-not $principalId) {
    throw "Nao foi possivel resolver principalId da identidade do job '$jobName'."
}

$kvId = Invoke-AzTsv -AzExe $azExe -Args @(
    "keyvault", "show",
    "--resource-group", $resourceGroup,
    "--name", $keyVaultName,
    "--query", "id"
)
$acrId = Invoke-AzTsv -AzExe $azExe -Args @(
    "acr", "show",
    "--resource-group", $resourceGroup,
    "--name", $acrName,
    "--query", "id"
)
$acrLoginServer = Invoke-AzTsv -AzExe $azExe -Args @(
    "acr", "show",
    "--resource-group", $resourceGroup,
    "--name", $acrName,
    "--query", "loginServer"
)

Ensure-RoleAssignment -AzExe $azExe -AssigneeObjectId $principalId -Scope $kvId -Role "Key Vault Secrets User"
Ensure-RoleAssignment -AzExe $azExe -AssigneeObjectId $principalId -Scope $acrId -Role "AcrPull"

Write-Host "Configuring job registry auth with system identity..."
Invoke-Az -AzExe $azExe -Args @(
    "containerapp", "job", "registry", "set",
    "--resource-group", $resourceGroup,
    "--name", $jobName,
    "--server", $acrLoginServer,
    "--identity", "system"
)

$catalog = Get-SecretCatalog
$secretSpecs = @()
$secretEnvPairs = @()

foreach ($entry in $catalog) {
    $envVar = $entry.EnvVar
    $kvName = $entry.KeyVaultName
    $jobSecret = $entry.JobSecretName

    try {
        $secretId = Invoke-AzTsv -AzExe $azExe -Args @(
            "keyvault", "secret", "show",
            "--vault-name", $keyVaultName,
            "--name", $kvName,
            "--query", "id"
        )
        if (-not $secretId) {
            throw "secret id vazio"
        }
    } catch {
        Write-Host "[warn] segredo ausente no Key Vault, ignorando: $kvName"
        continue
    }

    $secretRef = "keyvaultref:https://$keyVaultName.vault.azure.net/secrets/$kvName,identityref:system"
    $secretSpecs += "$jobSecret=$secretRef"
    $secretEnvPairs += "$envVar=secretref:$jobSecret"
}

if ($secretSpecs.Count -gt 0) {
    Write-Host "Configuring job secrets (keyvaultref)..."
    Invoke-Az -AzExe $azExe -Args (
        @(
            "containerapp", "job", "secret", "set",
            "--resource-group", $resourceGroup,
            "--name", $jobName,
            "--secrets"
        ) + $secretSpecs
    )
} else {
    Write-Host "[warn] nenhum segredo encontrado para configurar no job."
}

$envPairs = @()
$envPairs += $secretEnvPairs

$defaults = Get-NonSecretEnvDefaults
foreach ($d in $defaults) {
    $k = $d.Key
    $v = $d.Value
    if ($cfg.ContainsKey($k) -and ($cfg[$k] | Out-String).Trim()) {
        $v = ($cfg[$k] | Out-String).Trim()
    }
    $envPairs += "$k=$v"
}

$optionalEnvKeys = @(
    "SHAREPOINT_TRY_CREATE_LINK",
    "SHAREPOINT_LINK_SCOPE",
    "SHAREPOINT_LINK_TYPE",
    "CMA_COTATIONS_FILE",
    "ONE_COTATIONS_FILE",
    "ZIM_COTATIONS_FILE",
    "MANUAL_QUOTES_SOURCE"
)
foreach ($key in $optionalEnvKeys) {
    if ($cfg.ContainsKey($key)) {
        $value = ($cfg[$key] | Out-String).Trim()
        if ($value) {
            $envPairs += "$key=$value"
        }
    }
}

Write-Host "Updating job env vars..."
Invoke-Az -AzExe $azExe -Args (
    @(
        "containerapp", "job", "update",
        "--resource-group", $resourceGroup,
        "--name", $jobName,
        "--container-name", $jobContainerName,
        "--set-env-vars"
    ) + $envPairs
)

Write-Host ""
Write-Host "Job identity + secrets + env vars configured successfully."
Write-Host "- principal_id: $principalId"
Write-Host "- secrets_set: $($secretSpecs.Count)"
Write-Host "- env_vars_set: $($envPairs.Count)"
