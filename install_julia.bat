@echo off
title Wflow Julia Setup
color 0B

echo ========================================
echo    Wflow Julia and hydromt Setup Script
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

REM Install Python packages
echo Installing Python packages from requirements.txt...
echo This may take several minutes...
echo.

pip install --upgrade pip
pip install -r requirements.txt

if errorlevel 1 (
    echo [WARNING] Some packages may have installation issues
) else (
    echo [OK] Python packages installed
)
echo.

REM Check if Julia is installed
echo Checking Julia installation...
where julia >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Julia not found!
    echo.
    echo Please install Julia from:
    echo https://julialang.org/downloads/
    echo.
    echo After installation, add Julia to your PATH:
    echo 1. Press Win + X -> System -> Advanced system settings
    echo 2. Click "Environment Variables"
    echo 3. Edit "Path" and add: C:\Users\%USERNAME%\AppData\Local\Programs\Julia\Julia-1.9.X\bin
    echo 4. Click OK and restart this script
    echo.
    pause
    exit /b 1
)

echo [OK] Julia found:
julia --version
echo.

REM Check if setup_julia.jl exists
if not exist "setup_julia.jl" (
    echo [ERROR] setup_julia.jl not found in current directory!
    pause
    exit /b 1
)

REM Install Wflow.jl
echo Installing Wflow.jl package...
echo This may take 5-10 minutes depending on your internet connection...
echo.

julia setup_julia.jl

if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Wflow.jl
    pause
    exit /b 1
)

echo.
echo [OK] Wflow.jl installed successfully!
echo.

REM Install Python-Julia bridge
echo Installing Python-Julia bridge...
pip install julia

if %errorlevel% neq 0 (
    echo [ERROR] Failed to install julia Python package
    pause
    exit /b 1
)

echo.
echo Installing Julia dependencies for Python...
python -c "import julia; julia.install()"

if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Julia dependencies for Python
    pause
    exit /b 1
)

echo.
echo ========================================
echo Testing installations...
echo ========================================
echo.

hydromt --version
if errorlevel 1 (
    echo [ERROR] hydromt not installed correctly
) else (
    echo [OK] hydromt installed
)

echo.
echo Testing Julia/Wflow integration...
python -c "
try:
    from julia import Julia
    j = Julia(sysimage=None, compiled_modules=False)
    j.eval('using Wflow')
    print('[OK] Wflow.jl available in Python')
except Exception as e:
    print(f'[WARNING] {e}')
"

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo You can now run the web app using: run.bat
echo.

pause