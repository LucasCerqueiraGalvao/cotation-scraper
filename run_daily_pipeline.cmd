@echo off
setlocal

cd /d "%~dp0"

if not exist "artifacts\logs" mkdir "artifacts\logs"

set "LOGFILE=%~dp0artifacts\logs\scheduled_task_runner.log"
echo [%date% %time%] scheduled task start >> "%LOGFILE%"

py -3 "%~dp0daily_pipeline_runner.py" >> "%LOGFILE%" 2>&1
set "RC=%ERRORLEVEL%"

echo [%date% %time%] scheduled task end rc=%RC% >> "%LOGFILE%"

exit /b %RC%
