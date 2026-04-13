Set-StrictMode -Version Latest

function Load-EnvFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Env file not found: $Path"
    }

    $values = @{}
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            return
        }

        $key = $parts[0].Trim()
        $val = $parts[1].Trim()
        $values[$key] = $val
    }

    return $values
}

function Load-DotEnvFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Dotenv file not found: $Path"
    }

    $values = @{}
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            return
        }

        $key = $parts[0].Trim()
        $val = $parts[1].Trim()

        if ($val.StartsWith('"') -and $val.EndsWith('"') -and $val.Length -ge 2) {
            $val = $val.Substring(1, $val.Length - 2)
        } elseif ($val.StartsWith("'") -and $val.EndsWith("'") -and $val.Length -ge 2) {
            $val = $val.Substring(1, $val.Length - 2)
        }

        $values[$key] = $val
    }

    return $values
}

function Require-Setting {
    param(
        [hashtable]$Config,
        [string]$Key
    )

    $value = ($Config[$Key] | Out-String).Trim()
    if (-not $value) {
        throw "Missing required setting: $Key"
    }
    return $value
}

function Resolve-AzExecutable {
    $azCmd = Get-Command az -ErrorAction SilentlyContinue
    if ($azCmd) {
        return $azCmd.Source
    }

    $candidates = @(
        "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        "C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Azure CLI (az) not found. Install Azure CLI before running this script."
}

function Invoke-Az {
    param(
        [string]$AzExe,
        [string[]]$Args
    )

    & $AzExe @Args --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Args -join ' ')"
    }
}

function Invoke-AzJson {
    param(
        [string]$AzExe,
        [string[]]$Args
    )

    $output = & $AzExe @Args --only-show-errors -o json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Args -join ' ')"
    }

    if (-not $output) {
        return $null
    }
    return ($output | ConvertFrom-Json)
}

function Invoke-AzTsv {
    param(
        [string]$AzExe,
        [string[]]$Args
    )

    $output = & $AzExe @Args --only-show-errors -o tsv
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Args -join ' ')"
    }
    return ($output | Out-String).Trim()
}

function Set-AzureSubscription {
    param(
        [string]$AzExe,
        [string]$SubscriptionId
    )

    Invoke-Az -AzExe $AzExe -Args @("account", "set", "--subscription", $SubscriptionId)
}

