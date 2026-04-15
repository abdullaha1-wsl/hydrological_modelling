# wflow_builder/julia_runner.py
import subprocess
import logging
from pathlib import Path
import time
import sys

logger = logging.getLogger(__name__)

class JuliaRunner:
    def __init__(self, config):
        self.config = config
        # Use base_dir instead of model_dir
        self.base_dir = Path(config.base_dir)
        # The TOML file is in the Output subdirectory
        self.toml_path = self.base_dir / "final_output" / "wflow_sbm.toml"
        self.output_dir = self.base_dir / "final_output"  # This is where simulation should run
        
    def check_julia_installation(self):
        """Check if Julia is installed and return version"""
        try:
            result = subprocess.run(["julia", "--version"], capture_output=True, text=True, check=True)
            logger.info(f"Julia is installed: {result.stdout.strip()}")
            return True, result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"Julia is not installed or not in PATH: {e}")
            return False, str(e)
    
    def check_wflow_installation(self):
        """Check if Wflow package is installed in Julia using Pkg.installed()"""
        try:
            # Method 1: Check using Pkg.installed() dictionary
            check_cmd = [
                "julia", "-e",
                """
                import Pkg
                installed = Pkg.installed()
                if haskey(installed, "Wflow")
                    println("INSTALLED")
                    println(installed["Wflow"])
                else
                    println("NOT_INSTALLED")
                end
                """
            ]
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                output_lines = result.stdout.strip().split('\n')
                if output_lines and output_lines[0] == "INSTALLED":
                    version = output_lines[1] if len(output_lines) > 1 else "unknown"
                    logger.info(f"Wflow package is installed (version: {version})")
                    return True, version
                else:
                    logger.info("Wflow package not found in installed packages")
                    
                    # Method 2: Try to check if it can be loaded (fallback)
                    load_cmd = [
                        "julia", "-e",
                        "try; using Wflow; println('CAN_LOAD'); catch; println('CANNOT_LOAD'); end"
                    ]
                    load_result = subprocess.run(load_cmd, capture_output=True, text=True, timeout=30)
                    if load_result.returncode == 0 and "CAN_LOAD" in load_result.stdout:
                        logger.info("Wflow package can be loaded but not in Pkg.installed()")
                        return True, "unknown"
                    
                    return False, "Not installed"
            else:
                logger.warning(f"Error checking Wflow installation: {result.stderr}")
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            logger.error("Timeout checking Wflow installation")
            return False, "Timeout"
        except Exception as e:
            logger.error(f"Error checking Wflow installation: {e}")
            return False, str(e)
    
    def install_wflow_package(self):
        """Install Wflow package in Julia"""
        logger.info("Attempting to install Wflow package...")
        
        # Method 1: Try with Pkg.add
        try:
            install_cmd = ["julia", "-e", "using Pkg; Pkg.add('Wflow')"]
            result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info("Wflow package installed successfully via Pkg.add")
                return True, None
            else:
                logger.warning(f"Pkg.add failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"Pkg.add exception: {e}")
        
        # Method 2: Try with Pkg.add and specific version
        try:
            install_cmd = ["julia", "-e", "using Pkg; Pkg.add(PackageSpec(name='Wflow', version='0.8.1'))"]
            result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info("Wflow package installed successfully with version 0.8.1")
                return True, None
            else:
                logger.warning(f"Pkg.add with version failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"Pkg.add with version exception: {e}")
        
        # Method 3: Try with Pkg.activate and add
        try:
            install_cmd = ["julia", "-e", "using Pkg; Pkg.activate(); Pkg.add('Wflow')"]
            result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info("Wflow package installed successfully with Pkg.activate")
                return True, None
            else:
                logger.warning(f"Pkg.activate add failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"Pkg.activate exception: {e}")
        
        return False, "All installation methods failed"
    
    def run_simulation(self):
        """
        Run the wflow simulation using Julia
        The TOML file is in the Output folder
        """
        logger.info("Starting wflow simulation with Julia...")
        logger.info(f"Base directory: {self.base_dir}")
        logger.info(f"Looking for TOML file at: {self.toml_path}")
        
        try:
            # Check if toml file exists
            if not self.toml_path.exists():
                logger.error(f"TOML file not found at: {self.toml_path}")
                # Try alternative path - maybe it's in the base_dir directly
                alt_path = self.base_dir / "wflow_sbm.toml"
                if alt_path.exists():
                    logger.info(f"Found TOML at alternative path: {alt_path}")
                    self.toml_path = alt_path
                    self.output_dir = self.base_dir
                else:
                    # List contents to help debug
                    logger.error(f"Contents of {self.base_dir}: {list(self.base_dir.glob('*'))}")
                    if (self.base_dir / "Output").exists():
                        logger.error(f"Contents of Output folder: {list((self.base_dir / 'Output').glob('*'))}")
                    raise FileNotFoundError(f"TOML file not found at {self.toml_path} or {alt_path}")
            
            # Check if Julia is installed
            julia_installed, julia_msg = self.check_julia_installation()
            if not julia_installed:
                error_msg = (
                    "Julia is not installed. Please install Julia first:\n"
                    "1. Go to https://julialang.org/downloads/\n"
                    "2. Download and install Julia for Windows\n"
                    "3. Make sure Julia is added to your PATH\n"
                    "4. Restart this application"
                )
                logger.error(error_msg)
                raise Exception(error_msg)
            
            # Check if Wflow package is installed
            wflow_installed, wflow_version = self.check_wflow_installation()
            if not wflow_installed:
                logger.info("Wflow package not found. Attempting to install...")
                install_success, install_msg = self.install_wflow_package()
                
                if not install_success:
                    error_msg = (
                        "Failed to install Wflow package automatically. Please install manually:\n\n"
                        "1. Open a new Command Prompt\n"
                        "2. Run: julia\n"
                        "3. In the Julia REPL, type: using Pkg\n"
                        "4. Then type: Pkg.add(\"Wflow\")\n"
                        "5. Wait for installation to complete\n"
                        "6. Exit Julia with: exit()\n"
                        "7. Restart this application\n\n"
                        "If you still have issues, try:\n"
                        "julia -e 'using Pkg; Pkg.add(PackageSpec(name=\"Wflow\", version=\"0.8.1\"))'"
                    )
                    logger.error(error_msg)
                    raise Exception(error_msg)
            else:
                logger.info(f"Wflow package is already installed (version: {wflow_version}), proceeding with simulation...")
            
            # FIX: Escape backslashes in Windows paths for Julia strings
            toml_path_str = str(self.toml_path).replace('\\', '\\\\')
            output_dir_str = str(self.output_dir).replace('\\', '\\\\')
            
            # Run Julia with commands via subprocess - using a temporary file to avoid escaping issues
            script_content = f"""
            using Wflow
            using Dates
            println("="^60)
            println("WFLOW SIMULATION STARTED")
            println("="^60)
            println("TOML file: {toml_path_str}")
            println("Working directory: {output_dir_str}")
            println("Start time: $(Dates.now())")
            println("="^60)
            
            try
                @time Wflow.run("{toml_path_str}")
                println("\\n" * "="^60)
                println("SIMULATION COMPLETED SUCCESSFULLY")
                println("End time: $(Dates.now())")
                println("="^60)
                exit(0)
            catch e
                println("ERROR: ", e)
                exit(1)
            end
            """
            
            # Write script to temporary file to avoid command-line escaping issues
            script_path = self.output_dir / "run_wflow_simulation.jl"
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            logger.info(f"Created Julia script at: {script_path}")
            
            # Run Julia with the script file
            cmd = ["julia", str(script_path)]
            logger.info(f"Running: {' '.join(cmd)}")
            
            # Start Julia process
            logger.debug("Launching Julia process...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.output_dir),
                timeout=7200  # 2 hour timeout
            )
            
            # Log output for debugging
            if result.stdout:
                logger.info(f"Julia output: {result.stdout}")
            if result.stderr:
                logger.warning(f"Julia stderr: {result.stderr}")
            
            # Check results
            if result.returncode != 0:
                logger.error(f"Julia simulation failed with return code {result.returncode}")
                logger.error(f"STDERR: {result.stderr}")
                raise Exception(f"Simulation failed: {result.stderr}")
            
            # Check for output files - these should be the actual simulation outputs
            output_files = list(self.output_dir.glob("output*.nc")) + list(self.output_dir.glob("*_output.nc")) + list(self.output_dir.glob("results*.nc"))
            
            if output_files:
                logger.info(f"Simulation output files created: {[f.name for f in output_files]}")
            else:
                # Also check for any netcdf files that might be outputs
                all_nc = list(self.output_dir.glob("*.nc"))
                # Filter out the input files
                input_files = ['inmaps.nc', 'staticmaps.nc', 'wflow_sbm.nc']
                simulation_outputs = [f for f in all_nc if f.name not in input_files]
                
                if simulation_outputs:
                    logger.info(f"Simulation output files created: {[f.name for f in simulation_outputs]}")
                    output_files = simulation_outputs
                else:
                    logger.warning("No simulation output files found in Output directory")
            
            logger.info("✅ Simulation completed successfully")
            
            # Clean up temporary script
            if script_path.exists():
                script_path.unlink()
            
            return {
                'success': True,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'output_dir': str(self.output_dir),
                'toml_path': str(self.toml_path),
                'output_files': [str(f) for f in output_files]
            }
            
        except subprocess.TimeoutExpired:
            logger.error("Simulation timed out after 2 hours")
            raise Exception("Simulation timed out")
            
        except Exception as e:
            logger.error(f"Error running simulation: {e}")
            raise
    
    def run_simulation_with_script(self):
        """
        Alternative method: Run simulation using a Julia script file
        """
        try:
            # FIX: Escape backslashes in Windows paths for Julia strings
            toml_path_str = str(self.toml_path).replace('\\', '\\\\')
            
            # Create a temporary Julia script
            script_content = f"""
using Wflow
using Dates

println("="^60)
println("WFLOW SIMULATION STARTED")
println("="^60)
println("TOML file: {toml_path_str}")
println("Start time: $(Dates.now())")
println("="^60)

try
    @time Wflow.run("{toml_path_str}")
    println("\\n" * "="^60)
    println("SIMULATION COMPLETED SUCCESSFULLY")
    println("End time: $(Dates.now())")
    println("="^60)
    exit(0)
catch e
    println("ERROR: ", e)
    exit(1)
end
"""
            
            script_path = self.output_dir / "run_wflow.jl"
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            logger.info(f"Created Julia script at: {script_path}")
            
            cmd = ["julia", str(script_path)]
            logger.info(f"Running: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.output_dir),
                timeout=7200
            )
            
            if result.returncode == 0:
                logger.info("✅ Simulation completed successfully")
                
                # Check for output files
                output_files = list(self.output_dir.glob("output*.nc")) + list(self.output_dir.glob("*_output.nc"))
                if not output_files:
                    # Filter out input files
                    all_nc = list(self.output_dir.glob("*.nc"))
                    input_files = ['inmaps.nc', 'staticmaps.nc', 'wflow_sbm.nc']
                    output_files = [f for f in all_nc if f.name not in input_files]
                
                return {
                    'success': True,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'output_dir': str(self.output_dir),
                    'output_files': [str(f) for f in output_files]
                }
            else:
                logger.error(f"❌ Simulation failed: {result.stderr}")
                raise Exception(f"Simulation failed: {result.stderr}")
                
        except Exception as e:
            logger.error(f"Error in script method: {e}")
            raise