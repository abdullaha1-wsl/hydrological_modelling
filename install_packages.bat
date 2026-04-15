@echo off
title Install Wflow Python Packages
color 0A

echo ========================================
echo    Installing Python Packages
echo ========================================
echo.

REM Check if we're in wflow_env
echo Checking environment...
python -c "import sys; print(f'Python {sys.version}')"
echo.

echo Installing packages from requirements.txt...
echo This may take several minutes...
echo.

pip install --upgrade pip
pip install flask==2.3.3
pip install flask-cors==4.0.0
pip install earthengine-api==1.5.0
pip install numpy==1.24.3
pip install pandas==2.0.3
pip install xarray==2024.3.0
pip install rasterio==1.3.9
pip install geopandas==0.14.1
pip install rioxarray==0.15.0
pip install netcdf4==1.6.5
pip install scipy==1.11.4
pip install pyyaml==6.0.1
pip install requests==2.31.0
pip install matplotlib==3.7.5
pip install hydromt==0.10.1
pip install hydromt_wflow==0.8.0
pip install geemap==0.31.0
pip install julia==0.6.1

echo.
echo ========================================
echo Verifying installations...
echo ========================================
echo.

python -c "import flask; print('✓ flask', flask.__version__)"
python -c "import numpy; print('✓ numpy', numpy.__version__)"
python -c "import pandas; print('✓ pandas', pandas.__version__)"
python -c "import rasterio; print('✓ rasterio', rasterio.__version__)"
python -c "import geopandas; print('✓ geopandas', geopandas.__version__)"
python -c "import hydromt; print('✓ hydromt', hydromt.__version__)"

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo You can now run: python app.py
echo.

pause