import os
import json
import uuid
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class WflowConfig:
    """
    Configuration class for Wflow model building and simulation.
    
    Attributes:
        extent (list): [west, south, east, north]
        subbasin_points (list): [lon, lat] of outlet
        start_date (str): Start date in YYYY-MM-DD format
        end_date (str): End date in YYYY-MM-DD format
        job_id (str): Unique job identifier
        project_id (str): Earth Engine project ID
        base_dir (Path): Base directory for all job files
        artifact_dir (Path): Directory for raw data downloads
        output_dir (Path): Directory for model outputs
    """
    
    def __init__(self, user_inputs):
        """
        Initialize configuration from user inputs.
        
        Args:
            user_inputs (dict): Must contain:
                - extent: [west, south, east, north]
                - subbasin_points: [lon, lat]
                - start_date: 'YYYY-MM-DD'
                - end_date: 'YYYY-MM-DD'
            Optional:
                - job_id: custom job ID
                - project_id: Earth Engine project ID
        """
        # Required inputs
        self.extent = user_inputs['extent']
        self.subbasin_points = user_inputs['subbasin_points']
        self.start_date = user_inputs['start_date']
        self.end_date = user_inputs['end_date']
        
        # Optional inputs with defaults
        self.project_id = user_inputs.get('project_id', 'smart-theory-460821-e3')
        
        # Generate or use provided job ID
        if 'job_id' in user_inputs:
            self.job_id = user_inputs['job_id']
        else:
            self.job_id = str(uuid.uuid4())[:8]
        
        # Set up directory structure
        self.base_dir = Path(f"C:/Users/user/wflow_web_app/tmp/wflow_jobs/{self.job_id}")
        self.artifact_dir = self.base_dir / "artifact_data"
        self.output_dir = self.base_dir / "Output"
        
        # Validate inputs
        self.validate()
        
        logger.info(f"Configuration created for job {self.job_id}")
        
    def validate(self):
        """Validate all input parameters."""
        # Validate extent
        if len(self.extent) != 4:
            raise ValueError(f"Extent must have 4 values, got {len(self.extent)}")
        
        # Validate subbasin points
        if len(self.subbasin_points) != 2:
            raise ValueError(f"Subbasin points must have 2 values, got {len(self.subbasin_points)}")
        
        # Validate dates
        try:
            start = datetime.strptime(self.start_date, '%Y-%m-%d')
            end = datetime.strptime(self.end_date, '%Y-%m-%d')
            if end < start:
                raise ValueError("End date must be after start date")
        except ValueError as e:
            raise ValueError(f"Invalid date format: {e}")
        
        # Validate project ID
        if not self.project_id:
            raise ValueError("Project ID cannot be empty")
    
    def create_directories(self):
        """Create all necessary directories for the job."""
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Directories created for job {self.job_id}")
        logger.debug(f"Base dir: {self.base_dir}")
        logger.debug(f"Artifact dir: {self.artifact_dir}")
        logger.debug(f"Output dir: {self.output_dir}")
        
        return self
    
    def to_dict(self):
        """Convert configuration to dictionary."""
        return {
            'job_id': self.job_id,
            'extent': self.extent,
            'subbasin_points': self.subbasin_points,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'project_id': self.project_id,
            'base_dir': str(self.base_dir),
            'artifact_dir': str(self.artifact_dir),
            'output_dir': str(self.output_dir)
        }
    
    def save_config(self):
        """Save configuration to JSON file."""
        config_path = self.base_dir / 'config.json'
        with open(config_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        
        logger.info(f"Configuration saved to {config_path}")
        return config_path
    
    @classmethod
    def load_config(cls, config_path):
        """Load configuration from JSON file."""
        with open(config_path, 'r') as f:
            data = json.load(f)
        return cls(data)
    
    def __str__(self):
        """String representation."""
        return f"WflowConfig(job_id={self.job_id}, extent={self.extent}, dates={self.start_date} to {self.end_date})"