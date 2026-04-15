from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import threading
import uuid
import json
import logging
from datetime import datetime
from pathlib import Path
import shutil
import os
import zipfile
from io import BytesIO

# Import our wflow builder modules
from wflow_builder.config import WflowConfig
from wflow_builder.data_fetcher import DataFetcher
from wflow_builder.model_builder import WflowModelBuilder
from wflow_builder.julia_runner import JuliaRunner  # Add this import

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Store job status
jobs = {}

class WflowJob:
    def __init__(self, job_id, config):
        self.job_id = job_id
        self.config = config
        self.status = 'pending'  # pending, running, completed, failed
        self.progress = 0
        self.message = ''
        self.result = None
        self.error = None
        self.created_at = datetime.now()
        
    def to_dict(self):
        return {
            'job_id': self.job_id,
            'status': self.status,
            'progress': self.progress,
            'message': self.message,
            'created_at': self.created_at.isoformat(),
            'extent': self.config.extent if self.config else None,
            'start_date': self.config.start_date if self.config else None,
            'end_date': self.config.end_date if self.config else None
        }

def run_wflow_job(job_id, user_inputs):
    """Background task to run wflow building and simulation"""
    try:
        job = jobs[job_id]
        job.status = 'running'
        job.message = 'Initializing...'
        job.progress = 5
        
        # Create configuration
        logger.info(f"Creating config for job {job_id}")
        config = WflowConfig(user_inputs)
        config.create_directories()
        job.config = config
        
        # Copy GRDC CSV file to artifact directory if it exists
        job.message = 'Copying GRDC data...'
        job.progress = 8
        grdc_source = Path(__file__).parent / "wflow_builder" / "grdc.csv"
        if grdc_source.exists():
            grdc_dest = config.artifact_dir / "grdc.csv"
            shutil.copy2(grdc_source, grdc_dest)
            logger.info(f"Copied GRDC file to {grdc_dest}")
        else:
            logger.warning(f"GRDC file not found at {grdc_source}")
            # Create empty GRDC file as placeholder
            grdc_dest = config.artifact_dir / "grdc.csv"
            with open(grdc_dest, 'w') as f:
                f.write("grdc_no,river,station,country,lat,lon,area,altitude\n")
            logger.info(f"Created empty GRDC placeholder at {grdc_dest}")
        
        # Fetch data from Earth Engine
        job.message = 'Initializing data fetching...'
        job.progress = 0
        fetcher = DataFetcher(config)
        
        # Step 1: Fetch basin data
        job.message = 'Fetching basin data...'
        job.progress = 5
        fetcher.fetch_basin_data()
        
        # Step 2: Fetch DEM data
        job.message = 'Fetching DEM data...'
        job.progress = 15
        fetcher.fetch_dem_data()
        
        job.message = 'Fetching Reservoir Data...'
        job.progress = 20
        fetcher.fetch_reservoir_data()

        job.message = 'Fetching Glacier Data...'
        job.progress = 25
        fetcher.fetch_glacier_data()

        job.message = 'Fetching Lake Data...'
        job.progress = 30
        fetcher.fetch_lake_data()

        # Step 3: Fetch landuse data
        job.message = 'Fetching landuse and climate data...'
        job.progress = 35
        fetcher.fetch_landuse_data()
        
        # Step 4: Fetch soil data
        job.message = 'Fetching soil data...'
        job.progress = 45
        fetcher.fetch_soil_data()
        
        # Step 5: Fetch river data
        job.message = 'Fetching river data...'
        job.progress = 55
        fetcher.fetch_river_data()
        
        # Step 6: Fetch MODIS LAI
        job.message = 'Fetching Leaf Area Index...'
        job.progress = 60
        fetcher.fetch_modis_lai(config.start_date, config.end_date)
        
        # Step 7: Fetch ERA5 data
        job.message = 'Fetching Daily Climate Data...'
        job.progress = 65
        fetcher.fetch_era5_data(config.start_date, config.end_date)
        
        # Step 8: Create data catalog
        job.message = 'Creating data catalog...'
        job.progress = 70
        fetcher.create_data_catalog()
        
        # Step 9: Build wflow model with hydromt
        job.message = 'Building wflow model with hydromt...'
        job.progress = 75
        builder = WflowModelBuilder(config)
        build_result = builder.build_model()
        
        # Step 10: Run Julia simulation
        job.message = 'Running wflow simulation in Julia...'
        job.progress = 85
        julia_runner = JuliaRunner(config)
        simulation_result = julia_runner.run_simulation()
        
        # Finalize
        job.message = 'Model built and simulation completed successfully!'
        job.progress = 100
        job.result = {
            'build_result': build_result,
            'simulation_result': simulation_result
        }
        job.status = 'completed'
        
        logger.info(f"Job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}", exc_info=True)
        job.status = 'failed'
        job.error = str(e)
        job.message = f'Failed: {str(e)}'

@app.route('/')
def index():
    """Serve the web interface"""
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit_job():
    """Submit a new wflow building job"""
    try:
        data = request.json
        
        # Validate inputs
        required = ['extent', 'subbasin_points', 'start_date', 'end_date']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Validate extent format
        if len(data['extent']) != 4:
            return jsonify({'error': 'Extent must be [west, south, east, north]'}), 400
        
        # Validate subbasin points
        if len(data['subbasin_points']) != 2:
            return jsonify({'error': 'Subbasin points must be [lon, lat]'}), 400
        
        # Create job
        job_id = str(uuid.uuid4())[:8]
        config_data = {
            'extent': data['extent'],
            'subbasin_points': data['subbasin_points'],
            'start_date': data['start_date'],
            'end_date': data['end_date'],
            'job_id': job_id,
            'project_id': data.get('project_id', 'smart-theory-460821-e3')
        }
        
        # Create job object
        job = WflowJob(job_id, None)  # Config will be set in background thread
        jobs[job_id] = job
        
        # Start background thread
        thread = threading.Thread(target=run_wflow_job, args=(job_id, config_data))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'job_id': job_id,
            'status': 'pending',
            'message': 'Job submitted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error submitting job: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<job_id>')
def job_status(job_id):
    """Get job status"""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify(job.to_dict())

@app.route('/api/download/<job_id>')
def download_results(job_id):
    """Download model results as zip file"""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if job.status != 'completed':
        return jsonify({'error': 'Job not completed yet'}), 400
    
    try:
        # Create zip file in memory
        memory_file = BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            base_path = Path(job.config.base_dir)
            if base_path.exists():
                for root, dirs, files in os.walk(base_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, base_path)
                        zf.write(file_path, arcname)
        
        memory_file.seek(0)
        
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'wflow_model_{job_id}.zip'
        )
        
    except Exception as e:
        logger.error(f"Error creating download: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/jobs', methods=['GET'])
def list_jobs():
    """List all jobs"""
    job_list = [job.to_dict() for job in jobs.values()]
    return jsonify(job_list)

@app.route('/api/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    """Cancel a running job"""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if job.status == 'running':
        job.status = 'cancelled'
        job.message = 'Job cancelled by user'
        
    return jsonify({'status': 'cancelled'})

@app.route('/api/cleanup/<job_id>', methods=['POST'])
def cleanup_job(job_id):
    """Clean up job files"""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    try:
        if job.config and job.config.base_dir.exists():
            shutil.rmtree(job.config.base_dir)
        
        # Remove from jobs dict if completed/failed
        if job.status in ['completed', 'failed', 'cancelled']:
            del jobs[job_id]
        
        return jsonify({'status': 'cleaned'})
        
    except Exception as e:
        logger.error(f"Error cleaning up job {job_id}: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('/tmp/wflow_jobs', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    
    app.run(debug=False, host='0.0.0.0', port=5000)