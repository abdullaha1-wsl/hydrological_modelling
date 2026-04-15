@echo off
title Wflow Web Application
color 0A

echo ========================================
echo    Wflow Web Application Launcher
echo ========================================
echo.

REM Check if we're in the right conda environment
echo Checking Python environment...
python -c "import sys; exit(0 if sys.version_info >= (3,11) and sys.version_info < (3,12) else 1)"
if errorlevel 1 (
    echo [ERROR] You are not using Python 3.11!
    echo.
    echo Please activate the wflow_env environment first:
    echo   conda activate wflow_env
    echo.
    pause
    exit /b 1
)

python --version
echo [OK] Python 3.11 found
echo.

REM Check if hydromt is installed
echo Checking hydromt installation...
hydromt --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] hydromt not found!
    echo Please run install_julia.bat first
    pause
    exit /b 1
) else (
    echo [OK] hydromt found
)
echo.

REM Check if Julia is available
echo Checking Julia installation...
where julia >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Julia not found. Wflow simulation will use subprocess mode.
    echo To enable Julia integration, install Julia from: https://julialang.org/downloads/
) else (
    julia --version
    echo [OK] Julia found
)
echo.

REM Create necessary directories
if not exist "tmp" mkdir tmp
if not exist "tmp\wflow_jobs" mkdir tmp\wflow_jobs
echo [OK] Directories created
echo.

REM Check Earth Engine authentication
echo Checking Earth Engine authentication...
python -c "import ee; ee.Initialize()" 2>nul
if errorlevel 1 (
    echo [WARNING] Earth Engine not authenticated.
    echo You will need to authenticate when the app runs.
) else (
    echo [OK] Earth Engine authenticated
)
echo.

REM Start the Flask application
echo ========================================
echo Starting Wflow Web Application...
echo ========================================
echo.
echo The application will be available at:
echo   http://localhost:5000
echo.
echo Press Ctrl+C to stop the server
echo.

python app.py

pause