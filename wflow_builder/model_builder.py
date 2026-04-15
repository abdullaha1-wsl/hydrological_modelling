import subprocess
import logging
import os
import json
import time
import pandas as pd
import numpy as np
from pathlib import Path
import xarray as xr
import configparser
import shutil
import datetime
import calendar
from tqdm import tqdm
import toml

# Patch for Dask progress bar OSError
import sys
import builtins

# Save original print and flush
original_print = builtins.print
original_flush = sys.stdout.flush
original_stderr_flush = sys.stderr.flush

def patched_print(*args, **kwargs):
    """Patched print to handle OSError in progress bars."""
    try:
        # Check if this is from dask progress bar
        if args and isinstance(args[0], str):
            # If it's a progress bar line, try to print without error
            if any(char in args[0] for char in ['[', ']', '#', '%']):
                try:
                    original_print(*args, **kwargs)
                except OSError:
                    pass
            else:
                original_print(*args, **kwargs)
        else:
            original_print(*args, **kwargs)
    except Exception:
        pass

def patched_flush():
    """Patched flush to handle OSError."""
    try:
        original_flush()
    except OSError:
        pass

def patched_stderr_flush():
    """Patched stderr flush to handle OSError."""
    try:
        original_stderr_flush()
    except OSError:
        pass

# Apply patches
builtins.print = patched_print
sys.stdout.flush = patched_flush
sys.stderr.flush = patched_stderr_flush

# Set Dask to use single-threaded scheduler and disable progress bar
try:
    import dask
    dask.config.set(scheduler='single-threaded')
    os.environ['DASK_PROGRESS'] = '0'
    # Disable progress bar logging
    import logging as dask_logging
    dask_logging.getLogger('dask.diagnostics.progress').setLevel(logging.ERROR)
except ImportError:
    pass

logger = logging.getLogger(__name__)

class WflowModelBuilder:
    """
    Builds the wflow model using hydromt and creates the configuration files.
    """
    
    def __init__(self, config):
        """
        Initialize the model builder.
        
        Args:
            config (WflowConfig): Configuration object for the job
        """
        self.config = config
        self.chunksize = 100  # Time chunksize for reading multiple files
        self.lat_chunksize = None  # Latitude chunk size
        self.lon_chunksize = None  # Longitude chunk size
        self.duration_in_months = 3  # Duration for each chunk
        self.ini_output_dir = None
        self.hydromt_output_dir = None
        self.final_output_path = None
        
    def setup_chunk_directories(self):
        """Create necessary directories for chunked processing."""
        base_dir = self.config.base_dir
        
        self.ini_output_dir = base_dir / 'ini_files'
        self.hydromt_output_dir = base_dir / 'hydromt_output'
        self.final_output_path = base_dir / 'final_output'
        
        # Remove existing directories if they exist
        if self.ini_output_dir.exists():
            shutil.rmtree(self.ini_output_dir)
        self.ini_output_dir.mkdir(parents=True, exist_ok=True)
        
        if self.hydromt_output_dir.exists():
            shutil.rmtree(self.hydromt_output_dir)
        self.hydromt_output_dir.mkdir(parents=True, exist_ok=True)
        
        if self.final_output_path.exists():
            shutil.rmtree(self.final_output_path)
        self.final_output_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created directories: {self.ini_output_dir}, {self.hydromt_output_dir}, {self.final_output_path}")
    
    def create_config_file(self, config_path, start_time, end_time):
        """
        Create wflow_build.ini configuration file for hydromt with specific dates.
        
        Args:
            config_path (Path): Path to save the config file
            start_time (datetime.datetime): Start time for this chunk
            end_time (datetime.datetime): End time for this chunk
            
        Returns:
            Path: Path to the created config file
        """
        content = f"""[global]
data_libs = []

[setup_config]
starttime = {start_time.strftime('%Y-%m-%dT%H:%M:%S')}
endtime = {end_time.strftime('%Y-%m-%dT%H:%M:%S')}
timestepsecs = 86400
input.path_forcing = inmaps.nc

[setup_basemaps]
hydrography_fn = merit_hydro_1k
basin_index_fn = merit_hydro_index
upscale_method = ihu

[setup_rivers]
hydrography_fn = merit_hydro_1k
river_geom_fn = rivers_lin2019_v1
river_upa = 30
rivdph_method = powlaw
min_rivdph = 1
min_rivwth = 30
slope_len = 2000
smooth_len = 5000

[setup_reservoirs]
reservoirs_fn = hydro_reservoirs
min_area = 0
priority_jrc = True

[setup_lakes]
lakes_fn = hydro_lakes
min_area = 0

[setup_glaciers]
glaciers_fn = rgi
min_area = 1.0

[setup_lulcmaps]
lulc_fn = globcover

[setup_laimaps]
lai_fn = modis_lai

[setup_soilmaps]
soil_fn = soilgrids
ptf_ksatver = brakensiek

[setup_precip_forcing]
precip_fn = era5

[setup_temp_pet_forcing]
temp_pet_fn = era5
pet_method = debruin
press_correction = True
dem_forcing_fn = era5_orography

[setup_constant_pars]
KsatHorFrac = 25
Cfmax = 3.75653
cf_soil = 0.038
EoverR = 0.05
InfiltCapPath = 5
InfiltCapSoil = 600
MaxLeakage = 0
rootdistpar = -500
TT = 0
TTI = 2
TTM = 0
WHC = 0.1
G_Cfmax = 5.3
G_SIfrac = 0.002
G_TT = 1.3
"""
        with open(config_path, 'w') as f:
            f.write(content)
        
        logger.debug(f"Configuration file created: {config_path}")
        return config_path
    
    def calculate_chunks(self):
        """
        Calculate the number of chunks needed for the time period.
        
        Returns:
            list: List of (start_time, end_time) tuples for each chunk
        """
        start_time = datetime.datetime.strptime(self.config.start_date, '%Y-%m-%d')
        end_time = datetime.datetime.strptime(self.config.end_date, '%Y-%m-%d')
        
        chunks = []
        current_start = start_time
        
        while current_start <= end_time:
            # Calculate end time for this chunk
            # Add months and get the last day of that month
            current_end = current_start.replace(
                month=current_start.month + self.duration_in_months - 1,
                day=calendar.monthrange(
                    current_start.year, 
                    current_start.month + self.duration_in_months - 1
                )[1]
            )
            
            # If this chunk exceeds the overall end date, trim it
            if current_end > end_time:
                current_end = end_time
            
            chunks.append((current_start, current_end))
            
            # Update start for next chunk (add one day to avoid overlap)
            current_start = current_end + datetime.timedelta(days=1)
        
        logger.info(f"Created {len(chunks)} chunks with {self.duration_in_months}-month intervals")
        return chunks
    
    def build_chunk(self, chunk_idx, start_time, end_time):
        """
        Build a single time chunk of the model.
        
        Args:
            chunk_idx (int): Index of this chunk
            start_time (datetime.datetime): Start time for this chunk
            end_time (datetime.datetime): End time for this chunk
            
        Returns:
            Path: Path to the output directory for this chunk
        """
        # Disable Dask progress bar for this process
        try:
            import dask
            dask.config.set(scheduler='single-threaded')
            os.environ['DASK_PROGRESS'] = '0'
        except ImportError:
            pass
        
        # Create INI file for this chunk
        ini_file = self.ini_output_dir / f'wflow_build_{chunk_idx}.ini'
        self.create_config_file(ini_file, start_time, end_time)
        
        # Create output path for this chunk
        chunk_output_name = f"{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}"
        chunk_output_path = self.hydromt_output_dir / chunk_output_name
        chunk_output_path.mkdir(parents=True, exist_ok=True)
        
        # Prepare region string
        subbasin_str = f"{{'subbasin': {self.config.subbasin_points}, 'strord': 7, 'bounds': {self.config.extent}}}"
        
        # Build hydromt command with environment variables to disable progress bars
        cmd = [
            "hydromt", "build", "wflow",
            str(chunk_output_path),
            "-r", subbasin_str,
            "-i", str(ini_file),
            "-d", str(self.config.artifact_dir / "data_catalog.yml"),
            "-vv"
        ]
        
        logger.info(f"Building chunk {chunk_idx + 1}: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}")
        logger.debug(f"Command: {' '.join(cmd)}")
        
        # Run command with environment variables to suppress progress bars
        start_build = time.time()
        env = os.environ.copy()
        env['DASK_PROGRESS'] = '0'
        env['PYTHONWARNINGS'] = 'ignore'
        env['HYDROMT_VERBOSE'] = '0'  # Reduce hydromt verbosity
        
        # Redirect stdout/stderr to avoid progress bar issues
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            env=env,
            timeout=3600  # 1 hour timeout for each chunk
        )
        elapsed = time.time() - start_build
        
        # Save log file
        log_file = chunk_output_path / 'hydromt_build.log'
        with open(log_file, 'w') as f:
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"Elapsed time: {elapsed:.2f} seconds\n")
            f.write("\n--- STDOUT ---\n")
            f.write(result.stdout)
            f.write("\n--- STDERR ---\n")
            f.write(result.stderr)
        
        if result.returncode != 0:
            logger.error(f"Chunk {chunk_idx + 1} build failed: {result.stderr}")
            raise Exception(f"Chunk {chunk_idx + 1} build failed: {result.stderr}")
        
        logger.info(f"Chunk {chunk_idx + 1} built successfully in {elapsed:.2f} seconds")
        
        return chunk_output_path
    
    def build_all_chunks(self):
        """
        Build all time chunks in sequence.
        
        Returns:
            list: List of output paths for each chunk
        """
        chunks = self.calculate_chunks()
        output_paths = []
        
        logger.info(f"Starting to build {len(chunks)} chunks")
        
        for idx, (start_time, end_time) in enumerate(tqdm(chunks, desc="Building chunks")):
            output_path = self.build_chunk(idx, start_time, end_time)
            output_paths.append(output_path)
        
        logger.info(f"All {len(chunks)} chunks built successfully")
        return output_paths
    
    def merge_chunks(self, chunk_paths):
        """
        Merge all chunk outputs into a single final output.
        
        Args:
            chunk_paths (list): List of paths to chunk output directories
            
        Returns:
            dict: Results of the merge process
        """
        logger.info(f"Merging {len(chunk_paths)} chunks into final output")
        
        if not chunk_paths:
            raise Exception("No chunks to merge")
        
        # Copy the first chunk's static files
        first_chunk = chunk_paths[0]
        
        # Copy static files (excluding forcing files)
        for item in first_chunk.iterdir():
            if item.is_file() and item.name not in ['inmaps.nc']:
                dest_path = self.final_output_path / item.name
                shutil.copy2(item, dest_path)
                logger.debug(f"Copied: {item.name}")
        
        # Also copy the TOML file
        toml_files = list(first_chunk.glob("*.toml"))
        if toml_files:
            shutil.copy2(toml_files[0], self.final_output_path / toml_files[0].name)
        
        # Prepare to merge inmaps.nc files
        inmaps_files = []
        for idx, chunk_path in enumerate(chunk_paths):
            inmaps_file = chunk_path / 'inmaps.nc'
            if inmaps_file.exists():
                # Copy to a temporary file with index
                temp_file = self.final_output_path / f'inmaps_{idx}.nc'
                shutil.copy2(inmaps_file, temp_file)
                inmaps_files.append(temp_file)
                logger.debug(f"Copied inmaps file: {temp_file}")
        
        # Merge the inmaps files using xarray
        if inmaps_files:
            logger.info("Merging inmaps files...")
            
            # Set up chunking
            chunks = {'time': self.chunksize}
            if self.lon_chunksize is not None:
                chunks['lon'] = self.lon_chunksize
            if self.lat_chunksize is not None:
                chunks['lat'] = self.lat_chunksize
            
            # Open and concatenate all files
            try:
                # Read the first file to get structure
                first_ds = xr.open_dataset(inmaps_files[0])
                
                # Open all files with chunking
                datasets = [xr.open_dataset(f, chunks=chunks) for f in inmaps_files]
                
                # Concatenate along time dimension
                combined = xr.concat(datasets, dim='time')
                
                # Save merged file
                merged_path = self.final_output_path / 'inmaps.nc'
                combined.to_netcdf(merged_path)
                
                # Close all datasets
                for ds in datasets:
                    ds.close()
                
                logger.info(f"Created merged inmaps.nc file: {merged_path}")
                logger.info(f"Total time steps: {len(combined.time)}")
                
            except Exception as e:
                logger.error(f"Error merging inmaps files: {e}")
                raise
        
        # Update the TOML file with the original start and end times
        self.update_toml_file()
        
        # Find staticmaps file
        staticmaps_files = list(self.final_output_path.glob("*staticmaps*.nc"))
        staticmaps_path = staticmaps_files[0] if staticmaps_files else None
        
        return {
            'success': True,
            'output_dir': str(self.final_output_path),
            'staticmaps_path': str(staticmaps_path) if staticmaps_path else None,
            'forcing_path': str(self.final_output_path / 'inmaps.nc') if (self.final_output_path / 'inmaps.nc').exists() else None,
            'number_of_chunks': len(chunk_paths),
            'total_time_steps': len(combined.time) if 'combined' in locals() else None
        }
    
    def update_toml_file(self):
        """
        Update the TOML file with the original start and end dates.
        """
        toml_files = list(self.final_output_path.glob("*.toml"))
        if not toml_files:
            logger.warning("No TOML file found in final output directory")
            return
        
        toml_path = toml_files[0]
        
        try:
            # Read the TOML file
            with open(toml_path, 'r') as f:
                data = toml.loads(f.read())
            
            # Update start and end times
            start_time = datetime.datetime.strptime(self.config.start_date, '%Y-%m-%d')
            end_time = datetime.datetime.strptime(self.config.end_date, '%Y-%m-%d')
            
            data['starttime'] = start_time.strftime('%Y-%m-%dT%H:%M:%S')
            data['endtime'] = end_time.strftime('%Y-%m-%dT%H:%M:%S')
            
            # Remove cyclic if present
            if 'cyclic' in data:
                del data['cyclic']
            
            # Write updated TOML
            with open(toml_path, 'w') as f:
                f.write(toml.dumps(data))
            
            logger.info(f"Updated TOML file with start time {start_time} and end time {end_time}")
            
        except Exception as e:
            logger.error(f"Error updating TOML file: {e}")
    
    def build_model(self):
        """
        Build the wflow model with chunked time processing.
        
        Returns:
            dict: Results of the build process
        """
        logger.info(f"Building wflow model for job {self.config.job_id} with chunked processing")
        
        # Setup directories
        self.setup_chunk_directories()
        
        # Build all chunks
        chunk_paths = self.build_all_chunks()
        
        # Merge chunks into final output
        merge_results = self.merge_chunks(chunk_paths)
        
        logger.info(f"Model build completed successfully")
        
        return merge_results

# ... (rest of the code remains the same - WflowSimulator class unchanged)

class WflowSimulator:
    """
    Runs the actual Wflow simulation using Julia.
    """
    
    def __init__(self, config):
        """
        Initialize the simulator.
        
        Args:
            config (WflowConfig): Configuration object for the job
        """
        self.config = config
        self.jl = None
        self.setup_julia()
    
    def setup_julia(self):
        """Setup Julia environment for running Wflow."""
        try:
            from julia import Julia
            self.jl = Julia(sysimage=None, compiled_modules=False)
            logger.info("Julia initialized successfully")
            
            # Test if Wflow is available
            try:
                self.jl.eval('using Wflow')
                logger.info("Wflow.jl found and loaded")
            except Exception as e:
                logger.warning(f"Wflow.jl not available in Julia: {e}")
                self.jl = None
                
        except ImportError:
            logger.warning("Julia package not installed. Will use subprocess method.")
            self.jl = None
        except Exception as e:
            logger.warning(f"Julia initialization failed: {e}. Will use subprocess method.")
            self.jl = None
    
    def run_with_julia_package(self, toml_path):
        """
        Run Wflow using Julia's Wflow package (direct method).
        
        Args:
            toml_path (str): Path to the TOML configuration file
            
        Returns:
            dict: Simulation results
        """
        logger.info(f"Running Wflow simulation with Julia package for {self.config.job_id}")
        
        if self.jl is None:
            logger.info("Julia package not available, falling back to subprocess")
            return self.run_with_subprocess(toml_path)
        
        try:
            start_time = time.time()
            
            # Import Wflow in Julia
            self.jl.eval('using Wflow')
            
            # Run the model
            logger.info(f"Executing: Wflow.run('{toml_path}')")
            result = self.jl.eval(f'Wflow.run("{toml_path}")')
            
            elapsed_time = time.time() - start_time
            logger.info(f"Wflow simulation completed in {elapsed_time:.2f} seconds")
            
            # Check for output files
            output_files = self.find_output_files()
            
            return {
                'success': True,
                'method': 'julia_package',
                'elapsed_time': elapsed_time,
                'output_files': output_files,
                'result': str(result) if result else None
            }
            
        except Exception as e:
            logger.error(f"Julia Wflow execution failed: {e}")
            logger.info("Falling back to subprocess method")
            return self.run_with_subprocess(toml_path)
    
    def run_with_subprocess(self, toml_path):
        """
        Run Wflow using Julia subprocess (fallback method).
        
        Args:
            toml_path (str): Path to the TOML configuration file
            
        Returns:
            dict: Simulation results
        """
        logger.info(f"Running Wflow simulation with subprocess for {self.config.job_id}")
        
        # Create a Julia script
        script_path = Path(toml_path).parent / 'run_wflow.jl'
        script_content = f"""
using Wflow
println("Starting Wflow simulation...")
@time Wflow.run("{toml_path}")
println("Simulation complete!")
"""
        with open(script_path, 'w') as f:
            f.write(script_content)
        
        # Run Julia script
        cmd = ["julia", str(script_path)]
        
        try:
            start_time = time.time()
            
            # Run with timeout (2 hours default)
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=7200  # 2 hours
            )
            
            elapsed_time = time.time() - start_time
            
            # Save output to log file
            log_file = Path(toml_path).parent / 'wflow_simulation.log'
            with open(log_file, 'w') as f:
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Elapsed time: {elapsed_time:.2f} seconds\n")
                f.write("\n--- STDOUT ---\n")
                f.write(result.stdout)
                f.write("\n--- STDERR ---\n")
                f.write(result.stderr)
            
            if result.returncode != 0:
                logger.error(f"Wflow simulation failed: {result.stderr}")
                raise Exception(f"Wflow simulation failed: {result.stderr}")
            
            logger.info(f"Wflow simulation completed in {elapsed_time:.2f} seconds")
            
            # Check for output files
            output_files = self.find_output_files()
            
            return {
                'success': True,
                'method': 'subprocess',
                'elapsed_time': elapsed_time,
                'output_files': output_files,
                'log_file': str(log_file),
                'stdout': result.stdout,
                'stderr': result.stderr
            }
            
        except subprocess.TimeoutExpired:
            logger.error("Wflow simulation timed out after 2 hours")
            raise Exception("Simulation timed out after 2 hours")
        except Exception as e:
            logger.error(f"Wflow simulation failed: {e}")
            raise
    
    def find_output_files(self):
        """
        Find all output files from the simulation.
        
        Returns:
            dict: Dictionary of output files by type
        """
        output_dir = self.config.model_dir / 'Output' if hasattr(self.config, 'model_dir') else self.config.base_dir / 'Output'
        
        output_files = {
            'netcdf': [],
            'csv': [],
            'toml': [],
            'log': [],
            'others': []
        }
        
        # Define search patterns
        patterns = {
            'netcdf': ['*.nc', '*output*.nc', '*results*.nc', '*discharge*.nc'],
            'csv': ['*.csv', '*timeseries*.csv', '*discharge*.csv', '*Q*.csv'],
            'toml': ['*.toml'],
            'log': ['*.log']
        }
        
        # Search in output directory
        if output_dir.exists():
            for file_type, patterns_list in patterns.items():
                for pattern in patterns_list:
                    files = list(output_dir.glob(pattern))
                    output_files[file_type].extend([str(f) for f in files])
            
            # Search in subdirectories
            for subdir in ['results', 'output', 'run_default', 'static']:
                subdir_path = output_dir / subdir
                if subdir_path.exists():
                    for file_type, patterns_list in patterns.items():
                        for pattern in patterns_list:
                            files = list(subdir_path.glob(pattern))
                            output_files[file_type].extend([str(f) for f in files])
        
        # Log summary
        for file_type, files in output_files.items():
            if files:
                logger.debug(f"Found {len(files)} {file_type} files")
        
        return output_files
    
    def extract_discharge_at_outlet(self):
        """
        Extract discharge time series at the specified outlet point.
        
        Returns:
            str: Path to the saved CSV file, or None if not found
        """
        try:
            outlet_lon, outlet_lat = self.config.subbasin_points
            logger.info(f"Extracting discharge at outlet ({outlet_lon}, {outlet_lat})")
            
            output_dir = self.config.model_dir / 'Output' if hasattr(self.config, 'model_dir') else self.config.base_dir / 'Output'
            
            # Look for netCDF output files
            nc_files = list(output_dir.glob("**/*.nc"))
            
            # Filter for likely discharge files
            discharge_files = []
            for f in nc_files:
                fname = f.name.lower()
                if any(x in fname for x in ['discharge', 'q_', 'output', 'results']):
                    discharge_files.append(f)
            
            if not discharge_files:
                logger.warning("No discharge netCDF files found")
                return None
            
            # Try each file
            for nc_file in discharge_files:
                try:
                    logger.debug(f"Trying file: {nc_file}")
                    ds = xr.open_dataset(nc_file)
                    
                    # Look for discharge variables
                    discharge_vars = ['Q', 'q', 'discharge', 'q_river', 'river_discharge', 'runoff']
                    discharge_data = None
                    var_name = None
                    
                    for var in discharge_vars:
                        if var in ds.variables:
                            discharge_data = ds[var]
                            var_name = var
                            break
                    
                    if discharge_data is not None:
                        # Find the nearest grid cell to outlet
                        if 'lon' in ds.coords and 'lat' in ds.coords:
                            lon_coords = ds.lon.values
                            lat_coords = ds.lat.values
                            
                            # Find indices of nearest cell
                            lon_idx = np.abs(lon_coords - outlet_lon).argmin()
                            lat_idx = np.abs(lat_coords - outlet_lat).argmin()
                            
                            logger.info(f"Nearest grid cell: lon={lon_coords[lon_idx]:.4f}, lat={lat_coords[lat_idx]:.4f}")
                            
                            # Extract time series
                            if 'time' in ds.dims:
                                ts = discharge_data.isel(lat=lat_idx, lon=lon_idx).values
                                times = ds.time.values
                                
                                # Create DataFrame
                                df = pd.DataFrame({
                                    'time': times,
                                    'discharge': ts,
                                    'longitude': lon_coords[lon_idx],
                                    'latitude': lat_coords[lat_idx]
                                })
                                
                                # Save to CSV
                                csv_path = output_dir / 'discharge_at_outlet.csv'
                                df.to_csv(csv_path, index=False)
                                
                                logger.info(f"Discharge time series saved to {csv_path}")
                                
                                # Calculate statistics
                                mean_q = np.nanmean(ts)
                                max_q = np.nanmax(ts)
                                min_q = np.nanmin(ts)
                                logger.info(f"Discharge statistics - Mean: {mean_q:.2f}, Max: {max_q:.2f}, Min: {min_q:.2f}")
                                
                                ds.close()
                                return str(csv_path)
                    
                    ds.close()
                    
                except Exception as e:
                    logger.debug(f"Error processing {nc_file}: {e}")
                    continue
            
            logger.warning("Could not extract discharge from any file")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting discharge: {e}")
            return None
    
    def create_simulation_summary(self, sim_result):
        """
        Create a summary of the simulation results.
        
        Args:
            sim_result (dict): Results from the simulation
            
        Returns:
            str: Path to the saved summary file
        """
        output_dir = self.config.model_dir / 'Output' if hasattr(self.config, 'model_dir') else self.config.base_dir / 'Output'
        summary_path = output_dir / 'simulation_summary.json'
        
        # Get file sizes
        output_files = sim_result.get('output_files', {})
        file_sizes = {}
        
        for file_type, files in output_files.items():
            file_sizes[file_type] = []
            for file_path in files:
                if os.path.exists(file_path):
                    size = os.path.getsize(file_path)
                    file_sizes[file_type].append({
                        'path': file_path,
                        'size_bytes': size,
                        'size_mb': size / (1024 * 1024)
                    })
        
        summary = {
            'job_id': self.config.job_id,
            'simulation_date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'extent': self.config.extent,
            'outlet': self.config.subbasin_points,
            'simulation_method': sim_result.get('method'),
            'elapsed_time_seconds': sim_result.get('elapsed_time'),
            'elapsed_time_minutes': sim_result.get('elapsed_time', 0) / 60,
            'output_files': file_sizes,
            'discharge_csv': sim_result.get('discharge_csv'),
            'success': sim_result.get('success', False)
        }
        
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Simulation summary saved to {summary_path}")
        return str(summary_path)
    
    def run_simulation(self, toml_path):
        """
        Run the complete Wflow simulation.
        
        Args:
            toml_path (str): Path to the TOML configuration file
            
        Returns:
            dict: Complete simulation results
        """
        logger.info(f"Starting Wflow simulation for job {self.config.job_id}")
        logger.info(f"TOML file: {toml_path}")
        
        # Run the simulation
        sim_result = self.run_with_julia_package(toml_path)
        
        if sim_result['success']:
            # Extract discharge at outlet
            discharge_file = self.extract_discharge_at_outlet()
            if discharge_file:
                sim_result['discharge_csv'] = discharge_file
            
            # Create summary
            summary_file = self.create_simulation_summary(sim_result)
            sim_result['summary_file'] = summary_file
            
            logger.info("Wflow simulation completed successfully")
        else:
            logger.error("Wflow simulation failed")
        
        return sim_result
    
    def test_julia_installation(self):
        """
        Test if Julia and Wflow are properly installed.
        
        Returns:
            dict: Test results
        """
        logger.info("Testing Julia installation")
        
        result = {
            'julia_available': False,
            'wflow_available': False,
            'julia_version': None,
            'wflow_version': None,
            'error': None
        }
        
        try:
            # Check if Julia is in PATH
            julia_check = subprocess.run(['julia', '--version'], 
                                        capture_output=True, text=True)
            if julia_check.returncode == 0:
                result['julia_available'] = True
                result['julia_version'] = julia_check.stdout.strip()
                
                # Test Wflow
                test_script = """
                using Pkg
                try
                    using Wflow
                    version = pkgversion(Wflow)
                    println("Wflow version: ", version)
                catch e
                    println("Wflow not installed: ", e)
                end
                """
                
                test_cmd = ['julia', '-e', test_script]
                wflow_check = subprocess.run(test_cmd, capture_output=True, text=True)
                
                if 'Wflow version' in wflow_check.stdout:
                    result['wflow_available'] = True
                    result['wflow_version'] = wflow_check.stdout.strip()
                else:
                    result['error'] = wflow_check.stderr
            else:
                result['error'] = 'Julia not found in PATH'
                
        except Exception as e:
            result['error'] = str(e)
        
        return result