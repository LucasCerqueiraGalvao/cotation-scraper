param(
    [string]$EnvFile = ".\infra\azure\dev.env",
    [string]$ImageName = "",
    [string]$ImageTag = "",
    [switch]$UseAcrBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. "$PSScriptRoot\common.ps1"

$azExe = Resolve-AzExecutable
$cfg = Load-EnvFile -Path $EnvFile

$subscriptionId = Require-Setting -Config $cfg -Key "AZ_SUBSCRIPTION_ID"
$resourceGroup = Require-Setting -Config $cfg -Key "AZ_RESOURCE_GROUP"
$acrName = Require-Setting -Config $cfg -Key "AZ_ACR_NAME"
$defaultImageName = if ($cfg.ContainsKey("AZ_IMAGE_NAME")) { ($cfg["AZ_IMAGE_NAME"] | Out-String).Trim() } else { "quotation-scrapers" }

if (-not $ImageName) {
    $ImageName = $defaultImageName
}
if (-not $ImageTag) {
    $ImageTag = Get-Date -Format "yyyyMMdd-HHmm"
}

Set-AzureSubscription -AzExe $azExe -SubscriptionId $subscriptionId
$acrLoginServer = Invoke-AzTsv -AzExe $azExe -Args @(
    "acr", "show",
    "--resource-group", $resourceGroup,
    "--name", $acrName,
    "--query", "loginServer"
)

$image = "$acrLoginServer/$ImageName`:$ImageTag"

if ($UseAcrBuild) {
    Write-Host "Building image in ACR..."
    Invoke-Az -AzExe $azExe -Args @(
        "acr", "build",
        "--registry", $acrName,
        "--resource-group", $resourceGroup,
        "--image", "$ImageName`:$ImageTag",
        "."
    )
} else {
    Write-Host "Logging in to ACR..."
    Invoke-Az -AzExe $azExe -Args @(
        "acr", "login",
        "--name", $acrName
    )

    Write-Host "Building local Docker image..."
    & docker build -t $image .
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed."
    }

    Write-Host "Pushing Docker image to ACR..."
    & docker push $image
    if ($LASTEXITCODE -ne 0) {
        throw "Docker push failed."
    }
}

Write-Host ""
Write-Host "Image ready: $image"

