@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"
cd /d "%PROJECT_DIR%"

if not exist "artifacts\logs" mkdir "artifacts\logs"

set "LOGFILE=%PROJECT_DIR%\artifacts\logs\scheduled_task_runner.log"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "PYTHON_ARGS="
set "PYTHON_DESC="

if exist "%PYTHON_EXE%" (
    set "PYTHON_DESC=%PYTHON_EXE%"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
        set "PYTHON_DESC=py -3"
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=python"
            set "PYTHON_DESC=python"
        )
    )
)

if not defined PYTHON_DESC (
    echo [%date% %time%] ERRO: interpretador Python nao encontrado - venv/py/python. >> "%LOGFILE%"
    exit /b 1
)

echo [%date% %time%] scheduled task start >> "%LOGFILE%"
echo [%date% %time%] python exe: %PYTHON_DESC% >> "%LOGFILE%"

if defined PYTHON_ARGS (
    "%PYTHON_EXE%" %PYTHON_ARGS% "%PROJECT_DIR%\src\orchestration\daily_pipeline_runner.py" %* >> "%LOGFILE%" 2>&1
) else (
    "%PYTHON_EXE%" "%PROJECT_DIR%\src\orchestration\daily_pipeline_runner.py" %* >> "%LOGFILE%" 2>&1
)
set "RC=%ERRORLEVEL%"

echo [%date% %time%] scheduled task end rc=%RC% >> "%LOGFILE%"

exit /b %RC%
