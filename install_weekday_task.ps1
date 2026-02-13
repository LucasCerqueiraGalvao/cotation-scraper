param(
    [string]$TaskName = "CotationScrapers_Daily_2AM",
    [string]$StartTime = "02:00"
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cmdPath = Join-Path $projectDir "run_daily_pipeline.cmd"

if (-not (Test-Path $cmdPath)) {
    throw "Nao encontrei $cmdPath"
}

# Cria wrapper em caminho sem espacos para evitar erro 0x80070002 no Task Scheduler.
$wrapperPath = Join-Path $env:USERPROFILE "run_daily_pipeline_task.cmd"
$wrapperContent = @"
@echo off
call "$cmdPath"
exit /b %ERRORLEVEL%
"@
Set-Content -Path $wrapperPath -Value $wrapperContent -Encoding ascii

$taskCmd = $wrapperPath

Write-Host "Criando/atualizando tarefa: $TaskName"
Write-Host "Comando: $taskCmd"

# Sem /RL HIGHEST para evitar necessidade de admin.
schtasks /Create /TN $TaskName /TR $taskCmd /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $StartTime /F | Out-Host

if ($LASTEXITCODE -ne 0) {
    throw "Falha ao criar/atualizar tarefa no Agendador."
}

Write-Host "Tarefa criada/atualizada com sucesso."
Write-Host "Resumo da tarefa:"
schtasks /Query /TN $TaskName /V /FO LIST | Out-Host
