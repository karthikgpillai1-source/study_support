@echo off
REM ===========================================================================
REM  Study Intelligence Platform - Management Script
REM
REM  Usage:  manage.bat [command]
REM
REM  Commands:
REM    local   - Start both backend and frontend for local testing (default)
REM    api     - Start ONLY the backend API
REM    ui      - Start ONLY the frontend UI
REM    check   - Run the full quality gate (lint, types, tests)
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

set "COMMAND=%~1"
if /i "%COMMAND%"=="" set "COMMAND=local"

if /i "%COMMAND%"=="local" goto :local
if /i "%COMMAND%"=="api" goto :api
if /i "%COMMAND%"=="ui" goto :ui
if /i "%COMMAND%"=="check" goto :check
if /i "%COMMAND%"=="help" goto :help

echo [ERROR] Unknown command: %COMMAND%
goto :help

:help
echo Usage: manage.bat [command]
echo.
echo Commands:
echo   local   Start both backend and frontend for local testing (default)
echo   api     Start ONLY the backend API
echo   ui      Start ONLY the frontend UI
echo   check   Run the full quality gate (lint, types, tests)
echo.
exit /b 0

REM ===========================================================================
REM   LOCAL (Start Both)
REM ===========================================================================
:local
echo.
echo  ============================================================
echo   Study Intelligence Platform - local testing
echo  ============================================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] 'uv' was not found on your PATH.
    echo          Install it with:  pip install uv
    echo          Docs: https://docs.astral.sh/uv/
    echo.
    pause
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Node.js was not found on your PATH.
    echo          Install the LTS build from https://nodejs.org/
    echo.
    pause
    exit /b 1
)

call :SetupBackend
if errorlevel 1 exit /b 1

call :SetupFrontend
if errorlevel 1 exit /b 1

call :FreePort 8000 "backend API"
call :FreePort 5173 "frontend dev server"

echo  Starting backend API on http://127.0.0.1:8000 ...
start "Study Intelligence - API" /D "%BACKEND%" cmd /k uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

timeout /t 5 /nobreak >nul

echo  Starting frontend on http://localhost:5173 ...
start "Study Intelligence - UI" /D "%FRONTEND%" cmd /k npm run dev

echo.
echo  ============================================================
echo   Web app ......... http://localhost:5173
echo   API docs ........ http://127.0.0.1:8000/docs
echo   Health check .... http://127.0.0.1:8000/api/health
echo.
echo   Both servers run in their own windows.
echo   Close those windows to stop them.
echo  ============================================================
echo.

start "" http://localhost:5173
timeout /t 3 /nobreak >nul
endlocal
exit /b 0

REM ===========================================================================
REM   API ONLY
REM ===========================================================================
:api
where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 'uv' not found. Install with:  pip install uv
    pause
    exit /b 1
)

call :SetupBackend
if errorlevel 1 exit /b 1

echo.
echo  ============================================================
echo   API .............. http://127.0.0.1:8000
echo   OpenAPI docs ...... http://127.0.0.1:8000/docs
echo   Health check ..... http://127.0.0.1:8000/api/health
echo.
echo   Press Ctrl+C to stop.
echo  ============================================================
echo.

cd /d "%BACKEND%"
call uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
endlocal
exit /b 0

REM ===========================================================================
REM   UI ONLY
REM ===========================================================================
:ui
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install the LTS build from https://nodejs.org/
    pause
    exit /b 1
)

call :SetupFrontend
if errorlevel 1 exit /b 1

echo.
echo  ============================================================
echo   Web app .......... http://localhost:5173
echo   API proxy ........ http://127.0.0.1:8000/api
echo                     ^(needs API running in another window^)
echo.
echo   Press Ctrl+C to stop.
echo  ============================================================
echo.

cd /d "%FRONTEND%"
start "" http://localhost:5173
call npm run dev
endlocal
exit /b 0

REM ===========================================================================
REM   CHECK (Quality Gate)
REM ===========================================================================
:check
set FAILED=0

echo.
echo  ============================================================
echo   Quality gate
echo  ============================================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] 'uv' not found. Install with: pip install uv
    pause
    exit /b 1
)

echo  --- Backend: ruff format check ------------------------------------
pushd "%BACKEND%"
call uv run ruff format --check .
if errorlevel 1 ( set FAILED=1 )
echo.

echo  --- Backend: ruff lint -------------------------------------------
call uv run ruff check .
if errorlevel 1 ( set FAILED=1 )
echo.

echo  --- Backend: mypy -------------------------------------------------
call uv run mypy app
if errorlevel 1 ( set FAILED=1 )
echo.

echo  --- Backend: pytest ------------------------------------------------
call uv run pytest -q
if errorlevel 1 ( set FAILED=1 )
popd
echo.

where npm >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Node.js not found - skipping frontend checks.
    set FAILED=1
    goto :check_summary
)

echo  --- Frontend: typecheck -------------------------------------------
pushd "%FRONTEND%"
call npm run typecheck
if errorlevel 1 ( set FAILED=1 )
echo.

echo  --- Frontend: lint ------------------------------------------------
call npm run lint
if errorlevel 1 ( set FAILED=1 )
echo.

echo  --- Frontend: production build ------------------------------------
call npm run build
if errorlevel 1 ( set FAILED=1 )
popd
echo.

:check_summary
echo  ============================================================
if "%FAILED%"=="0" (
    echo   ALL CHECKS PASSED
) else (
    echo   SOME CHECKS FAILED - see the output above
)
echo  ============================================================
echo.

if "%FAILED%"=="0" exit /b 0
pause
exit /b 1

REM ===========================================================================
REM   Helper Functions
REM ===========================================================================

:SetupBackend
if not exist "%BACKEND%\.env" (
    echo Creating backend\.env from .env.example ...
    copy /y "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
    set "NEWKEY="
    for /f "usebackq delims=" %%K in (`uv run python -c "import secrets; print(secrets.token_urlsafe(48))" 2^>nul`) do set "NEWKEY=%%K"
    if defined NEWKEY (
        powershell -NoProfile -Command ^
            "$p='%BACKEND%\.env'; (Get-Content $p -Raw) -replace '(?m)^SECRET_KEY=.*$', 'SECRET_KEY=%NEWKEY%' | Set-Content $p -NoNewline" >nul 2>&1
        echo Generated a strong random SECRET_KEY.
    ) else (
        echo  [WARN] Could not generate a secret key. Set SECRET_KEY manually to a
        echo         random 48+ character value before deploying.
    )
)
if not exist "%BACKEND%\.venv" (
    echo Installing backend dependencies ^(first run^) ...
    pushd "%BACKEND%"
    call uv sync --extra dev
    set "RC=!errorlevel!"
    popd
    if not "!RC!"=="0" (
        echo [ERROR] Backend dependency install failed.
        exit /b 1
    )
)
exit /b 0

:SetupFrontend
if not exist "%FRONTEND%\node_modules" (
    echo Installing frontend dependencies ^(first run^) ...
    pushd "%FRONTEND%"
    call npm install
    set "RC=!errorlevel!"
    popd
    if not "!RC!"=="0" (
        echo [ERROR] npm install failed.
        exit /b 1
    )
)
exit /b 0

:FreePort
set "PORT=%~1"
set "LABEL=%~2"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:"LISTENING" ^| findstr /R /C:":%PORT% .*$"') do (
    echo  Port %PORT% is still in use by a previous %LABEL% ^(pid %%P^).
    echo  Stopping it ...
    taskkill /F /PID %%P >nul 2>&1
    if errorlevel 1 (
        echo  [WARN] Could not stop pid %%P. Close it manually or use a different port.
    ) else (
        echo  Stopped.
    )
    timeout /t 1 /nobreak >nul
)
exit /b 0
