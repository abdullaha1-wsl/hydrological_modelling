@echo off
title Wflow Conda Environment Setup
color 0A

echo ========================================
echo    Creating Wflow Conda Environment
echo ========================================
echo.

REM Check if conda is available
where conda >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Conda not found! Please install Anaconda or Miniconda first.
    pause
    exit /b 1
)

echo [OK] Conda found
echo.

REM Create new conda environment with Python 3.11
echo Creating conda environment 'wflow_env' with Python 3.11...
echo This may take a few minutes...
echo.

conda create -n wflow_env python=3.11 -y

if errorlevel 1 (
    echo [ERROR] Failed to create conda environment
    pause
    exit /b 1
)

echo.
echo [OK] Environment created successfully
echo.

echo Activating environment...
call conda activate wflow_env

if errorlevel 1 (
    echo [ERROR] Failed to activate environment
    pause
    exit /b 1
)

echo [OK] Environment activated
echo.

echo Installing pip packages from requirements.txt...
echo This may take several minutes...
echo.

pip install --upgrade pip
pip install -r requirements.txt

if errorlevel 1 (
    echo [WARNING] Some packages may have installation issues
) else (
    echo [OK] All packages installed successfully
)

echo.
echo ========================================
echo Environment Setup Complete!
echo ========================================
echo.
echo To use this environment:
echo   1. conda activate wflow_env
echo   2. install_julia.bat
echo   3. python app.py
echo.
echo Current environment: wflow_env
echo.

pause