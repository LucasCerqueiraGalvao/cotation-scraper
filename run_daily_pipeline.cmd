@echo off
setlocal

cd /d "%~dp0"

if not exist "artifacts\logs" mkdir "artifacts\logs"

set "LOGFILE=%~dp0artifacts\logs\scheduled_task_runner.log"
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python310\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo [%date% %time%] scheduled task start >> "%LOGFILE%"

"%PYTHON_EXE%" "%~dp0daily_pipeline_runner.py" >> "%LOGFILE%" 2>&1
set "RC=%ERRORLEVEL%"

echo [%date% %time%] scheduled task end rc=%RC% >> "%LOGFILE%"

exit /b %RC%
