# Hydrological Modelling Builder

A Python web application for gridded hydrological modelling, powered by Julia and driven by geospatial data from Google Earth Engine (GEE).

## Overview

`wflow_builder` is a Flask-based web application that automates the construction and execution of gridded hydrological models. It fetches remote sensing and climate datasets from Google Earth Engine, processes them into model-ready inputs, and runs high-performance hydrological simulations via Julia. Results are served through a web interface for easy interaction and visualization.

The app is built around the [Wflow.jl](https://github.com/Deltares/Wflow.jl) hydrological modelling framework (Deltares), which supports distributed models such as wflow_sbm for rainfall-runoff simulation across gridded catchments.

## Project Structure
```
├── app.py # Flask application entry point
├── wflow_builder/ # Core application module
│ ├── init.py
│ ├── config.py # App configuration (GEE credentials, model paths, etc.)
│ ├── data_catalog.yml # Catalogue of GEE datasets and spatial layers
│ ├── data_fetcher.py # GEE data fetching and export pipeline
│ ├── data_fetcher2.py # Secondary GEE / auxiliary data fetcher
│ ├── julia_runner.py # Python-Julia bridge for running Wflow.jl
│ └── model_builder.py # Assembles model inputs and config from fetched data
├── static/css/ # Stylesheets
├── templates/ # Jinja2 HTML templates
├── requirements.txt # Python dependencies
├── runtime.txt # Python runtime version
├── Procfile # Heroku/deployment process config
├── setup_julia.jl # Installs Wflow.jl and Julia dependencies
├── install_julia.bat # Julia installation (Windows)
├── install_packages.bat # Package installation (Windows)
├── setup_conda_env.bat # Conda environment setup (Windows)
└── run.bat # Local run script (Windows)
```

## Requirements

- Python (see `runtime.txt` for version)
- Julia with [Wflow.jl](https://github.com/Deltares/Wflow.jl)
- Conda (recommended for environment management)
- A Google Earth Engine account with an authenticated project

## Setup

### 1. Set Up the Python Environment

```
conda env create -f environment.yml
conda activate wflow_builder
```
#### Or using pip:
```
pip install -r requirements.txt
```
### 2. Authenticate Google Earth Engine
```
earthengine authenticate
Then set your GEE project in wflow_builder/config.py:
EE_PROJECT = "your-gee-project-id"
```
### 3. Install Julia
#### Windows:
```
install_julia.bat
```
#### macOS/Linux:
```
Download and install Julia from julialang.org.
```
### 4. Set Up Julia Packages (Wflow.jl)
```
julia setup_julia.jl
```
### 5. Configure Data Sources
wflow_builder/data_catalog.yml defines the GEE datasets used as model inputs (DEM, land use, soil properties, precipitation). Update this file to point to your datasets or GEE assets, and configure catchment parameters and output paths in wflow_builder/config.py.

Running the App
Windows:
```
run.bat
```
macOS/Linux:
```
python app.py
```
The app will be available at http://localhost:5000.

## Workflow
A typical modelling run follows these steps:

Define a catchment — specify the area of interest via the web interface

Fetch GEE data — data_fetcher.py pulls datasets (DEM, land cover, soil, climate forcing) from Google Earth Engine and exports them as gridded rasters

Build the model — model_builder.py assembles the Wflow.jl input configuration (.toml) and static maps from the fetched data

Run the simulation — julia_runner.py executes Wflow.jl for the configured catchment and time period

View results — outputs are displayed through the Flask web interface

## GEE Datasets
The data catalog (data_catalog.yml) typically includes:

Layer	Example GEE Source
Digital Elevation Model	MERIT DEM / SRTM
Land use / Land cover	ESA WorldCover / GlobCover
Soil properties	SoilGrids
Precipitation forcing	ERA5 / CHIRPS / IMERG
Evapotranspiration	MODIS MOD16
Deployment
This project includes a Procfile for deployment on platforms like Heroku:


web: gunicorn app:app
Ensure all environment variables defined in config.py are set in your deployment environment. GEE authentication in a server environment requires a service account key.

Module Reference
Module	Description
data_fetcher.py	Fetches and exports primary GEE datasets (DEM, land cover, soil)
data_fetcher2.py	Fetches supplementary or climate forcing data from GEE
julia_runner.py	Manages Wflow.jl execution as a Julia subprocess
model_builder.py	Assembles Wflow.jl model configuration and static input maps
