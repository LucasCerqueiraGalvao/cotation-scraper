Set-StrictMode -Version Latest

function Get-SecretCatalog {
    return @(
        @{ EnvVar = "HL_USER";                 KeyVaultName = "hl-user";                  JobSecretName = "hluser" }
        @{ EnvVar = "HL_PASS";                 KeyVaultName = "hl-pass";                  JobSecretName = "hlpass" }
        @{ EnvVar = "MAERSK_USER";             KeyVaultName = "maersk-user";              JobSecretName = "mkuser" }
        @{ EnvVar = "MAERSK_PASS";             KeyVaultName = "maersk-pass";              JobSecretName = "mkpass" }
        @{ EnvVar = "CMA_USER";                KeyVaultName = "cma-user";                 JobSecretName = "cmauser" }
        @{ EnvVar = "CMA_PASS";                KeyVaultName = "cma-pass";                 JobSecretName = "cmapass" }
        @{ EnvVar = "SHAREPOINT_TENANT_ID";    KeyVaultName = "sharepoint-tenant-id";     JobSecretName = "sptenant" }
        @{ EnvVar = "SHAREPOINT_CLIENT_ID";    KeyVaultName = "sharepoint-client-id";     JobSecretName = "spclient" }
        @{ EnvVar = "SHAREPOINT_CLIENT_SECRET";KeyVaultName = "sharepoint-client-secret"; JobSecretName = "spsecret" }
        @{ EnvVar = "SHAREPOINT_SITE_ID";      KeyVaultName = "sharepoint-site-id";       JobSecretName = "spsiteid" }
        @{ EnvVar = "SHAREPOINT_HOSTNAME";     KeyVaultName = "sharepoint-hostname";      JobSecretName = "sphost" }
        @{ EnvVar = "SHAREPOINT_SITE_PATH";    KeyVaultName = "sharepoint-site-path";     JobSecretName = "spsitepath" }
        @{ EnvVar = "SHAREPOINT_DRIVE_ID";     KeyVaultName = "sharepoint-drive-id";      JobSecretName = "spdriveid" }
        @{ EnvVar = "SHAREPOINT_FOLDER_PATH";  KeyVaultName = "sharepoint-folder-path";   JobSecretName = "spfolder" }
    )
}

function Get-NonSecretEnvDefaults {
    return @(
        @{ Key = "UPLOAD_MODE"; Value = "SHAREPOINT" }
        @{ Key = "UPLOAD_ENSURE_ONEDRIVE"; Value = "FALSE" }
        @{ Key = "SHAREPOINT_GRAPH_TIMEOUT_SEC"; Value = "30" }
        @{ Key = "LOG_RETENTION_DAYS"; Value = "14" }
        @{ Key = "SYNC_BEFORE_CMA_READ"; Value = "0" }
    )
}

