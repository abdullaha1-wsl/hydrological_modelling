import os
import ee
import logging
import geopandas as gpd
import json
from pathlib import Path
import requests
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import xarray as xr
import rasterio
import rioxarray
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import yaml
from io import BytesIO
import zipfile
import shutil
from threading import Lock

logger = logging.getLogger(__name__)

class DataFetcher:
    def __init__(self, config):
        self.config = config
        self.project_id = 'smart-theory-460821-e3'  # Your GEE project ID
        
        # Initialize Earth Engine
        try:
            ee.Initialize(project=self.project_id)
            logger.info("Earth Engine initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Earth Engine: {e}")
            raise
    
    def fetch_basin_data(self):
        """
        Fetch basin data from HydroSHEDS using Earth Engine.
        
        Returns:
            Path: Path to the saved basin GeoPackage file
        """
        logger.info(f"Fetching basin data for {self.config.job_id}")
        
        try:
            extent = self.config.extent
            logger.info(f"Using extent: {extent}")
            
            # Create AOI from extent
            aoi = ee.Geometry.Rectangle(extent)
            
            # Load HydroSHEDS basins (level 5 for watershed-level basins)
            level = 5
            basins = ee.FeatureCollection(f'WWF/HydroSHEDS/v1/Basins/hybas_{level}')
            basins_in_area = basins.filterBounds(aoi)
            
            count = basins_in_area.size().getInfo()
            logger.info(f"Found {count} basins in the extent")
            
            if count == 0:
                logger.warning("No basins found in extent")
                return None
            
            # Clip basins to AOI
            clipped = basins_in_area.map(lambda f: f.intersection(aoi, ee.ErrorMargin(1)))
            
            # Export to temporary file
            temp_file = self.config.artifact_dir / 'temp_basins.geojson'
            
            logger.debug(f"Exporting to temporary file: {temp_file}")
            
            # Get download URL for FeatureCollection
            url = clipped.getDownloadURL('geojson')
            
            logger.debug(f"Download URL: {url}")
            
            # Download the file
            response = requests.get(url, timeout=300)
            response.raise_for_status()
            
            # Save the content
            with open(temp_file, 'wb') as f:
                f.write(response.content)
            
            # Read the GeoJSON file using json and create GeoDataFrame manually
            # This avoids the fiona.path issue
            logger.debug("Reading GeoJSON file")
            with open(temp_file, 'r', encoding='utf-8') as f:
                geojson_data = json.load(f)
            
            # Convert to GeoDataFrame
            gdf = gpd.GeoDataFrame.from_features(geojson_data["features"])
            gdf.crs = "EPSG:4326"  # Set CRS to WGS84
            
            output_file = self.config.artifact_dir / 'merit_hydro_index.gpkg'
            
            # Standardize column names
            if 'MAIN_BAS' in gdf.columns:
                final_gdf = gdf[['MAIN_BAS', 'geometry']].copy()
                final_gdf = final_gdf.rename(columns={'MAIN_BAS': 'basid'})
            else:
                final_gdf = gdf[['geometry']].copy()
                final_gdf['basid'] = range(1, len(final_gdf) + 1)
            
            # Save to GeoPackage
            final_gdf.to_file(output_file, driver='GPKG')
            
            # Clean up temporary file
            if temp_file.exists():
                temp_file.unlink()
                logger.debug("Temporary file cleaned up")
            
            logger.info(f"Basin data saved to {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Error fetching basin data: {e}")
            logger.exception("Detailed traceback:")
            raise
    
    def fetch_river_data(self):
        """
        Fetch river data from custom assets.
        
        Returns:
            Path: Path to the saved river GeoPackage file
        """
        logger.info("Fetching river data")
        
        try:
            extent = self.config.extent
            aoi = ee.Geometry.Rectangle(extent)
            
            # River asset path from your notebook
            asset_path = 'projects/smart-theory-460821-e3/assets/rivers_lin2019v1'
            output_name = 'rivers_lin2019_v1'
            
            output_file = self._export_vector_asset(asset_path, output_name, aoi)
            
            if output_file and output_file.exists():
                logger.info(f"River data saved to {output_file}")
                return output_file
            else:
                logger.warning("No river data found")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching river data: {e}")
            return None
    
    def fetch_reservoir_data(self):
        """
        Fetch reservoir data from custom assets.
        
        Returns:
            Path: Path to the saved reservoir GeoPackage file
        """
        logger.info("Fetching reservoir data")
        
        try:
            extent = self.config.extent
            aoi = ee.Geometry.Rectangle(extent)
            
            # Reservoir asset path from your notebook
            asset_path = 'projects/smart-theory-460821-e3/assets/hydro_reserviors_renamed'
            output_name = 'hydro_reservoirs'
            
            output_file = self._export_vector_asset(
                asset_path, output_name, aoi, 
                create_empty=True, 
                rename_field='hylak_id', 
                use_fid=True,
                add_dam_height=True  # Enable dam height calculation
            )
            
            if output_file:
                logger.info(f"Reservoir data saved to {output_file}")
                return output_file
            else:
                logger.warning("No reservoir data found")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching reservoir data: {e}")
            return None
    
    def fetch_lake_data(self):
        """
        Fetch lake data (using same reservoirs asset as placeholder).
        
        Returns:
            Path: Path to the saved lake GeoPackage file
        """
        logger.info("Fetching lake data")
        
        try:
            extent = self.config.extent
            aoi = ee.Geometry.Rectangle(extent)
            
            # Using same reservoirs asset as placeholder for lakes
            asset_path = 'projects/smart-theory-460821-e3/assets/hydro_reserviors_renamed'
            output_name = 'hydro_lakes'
            
            output_file = self._export_vector_asset(
                asset_path, output_name, aoi, 
                create_empty=True, 
                rename_field='hylak_id', 
                use_fid=True,
                add_dam_height=True  # Enable dam height calculation
            )
            
            if output_file:
                logger.info(f"Lake data saved to {output_file}")
                return output_file
            else:
                logger.warning("No lake data found")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching lake data: {e}")
            return None
    
    def fetch_glacier_data(self):
        """
        Fetch glacier data from RGI asset.
        
        Returns:
            Path: Path to the saved glacier GeoPackage file
        """
        logger.info("Fetching glacier data")
        
        try:
            extent = self.config.extent
            aoi = ee.Geometry.Rectangle(extent)
            
            # RGI asset path from your notebook
            asset_path = 'projects/smart-theory-460821-e3/assets/rgi'
            output_name = 'rgi'
            
            output_file = self._export_vector_asset(asset_path, output_name, aoi, create_empty=True)
            
            if output_file:
                logger.info(f"Glacier data saved to {output_file}")
                return output_file
            else:
                logger.warning("No glacier data found")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching glacier data: {e}")
            return None
    
    def _export_vector_asset(self, asset_path, output_name, aoi, create_empty=False, rename_field=None, use_fid=False, add_dam_height=False):
        """
        Generic function to export vector assets following notebook pattern.
        
        Args:
            asset_path: Earth Engine asset path
            output_name: Output filename without extension
            aoi: Earth Engine geometry for clipping
            create_empty: Whether to create empty GeoPackage if no features found
            rename_field: Field name to rename to 'waterbody_id' (if provided)
            use_fid: Whether to set waterbody_id equal to fid (feature index)
            add_dam_height: Whether to calculate and add Dam_height field
        
        Returns:
            Path to saved GeoPackage or None
        """
        try:
            logger.info(f"=== Starting export for {output_name} ===")
            logger.info(f"Asset path: {asset_path}")
            logger.info(f"Output name: {output_name}")
            logger.info(f"Create empty: {create_empty}")
            logger.info(f"Rename field: {rename_field}")
            logger.info(f"Use FID: {use_fid}")
            logger.info(f"Add dam height: {add_dam_height}")
            logger.info(f"Output directory: {self.config.artifact_dir}")
            logger.info(f"Directory exists: {self.config.artifact_dir.exists()}")
            
            # Load and filter
            fc = ee.FeatureCollection(asset_path)
            filtered = fc.filterBounds(aoi)
            count = filtered.size().getInfo()
            
            logger.info(f"Found {count} features in {output_name} within bounds")
            
            output_file = self.config.artifact_dir / f"{output_name}.gpkg"
            logger.info(f"Output file will be: {output_file}")
            
            # Check if we should create empty GeoPackage
            if count == 0:
                logger.info(f"No features found for {output_name} - count is 0")
                if create_empty:
                    logger.info(f"Creating empty GeoPackage for {output_name}...")
                    try:
                        # Create empty GeoPackage
                        gdf = gpd.GeoDataFrame(columns=['geometry'], crs='EPSG:4326')
                        gdf = gdf.set_geometry('geometry')
                        if rename_field or use_fid:
                            # Add empty waterbody_id column
                            gdf['waterbody_id'] = pd.Series(dtype='int64')
                        if add_dam_height:
                            gdf['Dam_height'] = pd.Series(dtype='float64')
                        gdf.to_file(output_file, driver='GPKG')
                        logger.info(f"✅ Created empty GeoPackage: {output_file}")
                        logger.info(f"File exists: {output_file.exists()}")
                        logger.info(f"File size: {output_file.stat().st_size if output_file.exists() else 0} bytes")
                        return output_file
                    except Exception as e:
                        logger.error(f"❌ Failed to create empty GeoPackage: {e}")
                        return None
                else:
                    logger.info(f"create_empty=False, returning None for {output_name}")
                    return None
            
            # Clip features to AOI
            logger.info(f"Clipping {count} features to AOI...")
            clipped = filtered.map(lambda f: f.intersection(aoi, ee.ErrorMargin(1)))
            
            # Check if any features remain after clipping
            clipped_count = clipped.size().getInfo()
            logger.info(f"Features after clipping: {clipped_count}")
            
            if clipped_count == 0:
                logger.info(f"No features remain after clipping for {output_name}")
                if create_empty:
                    logger.info(f"Creating empty GeoPackage after clipping for {output_name}...")
                    try:
                        # Create empty GeoPackage
                        gdf = gpd.GeoDataFrame(columns=['geometry'], crs='EPSG:4326')
                        gdf = gdf.set_geometry('geometry')
                        if rename_field or use_fid:
                            # Add empty waterbody_id column
                            gdf['waterbody_id'] = pd.Series(dtype='int64')
                        if add_dam_height:
                            gdf['Dam_height'] = pd.Series(dtype='float64')
                        gdf.to_file(output_file, driver='GPKG')
                        logger.info(f"✅ Created empty GeoPackage after clipping: {output_file}")
                        logger.info(f"File exists: {output_file.exists()}")
                        logger.info(f"File size: {output_file.stat().st_size if output_file.exists() else 0} bytes")
                        return output_file
                    except Exception as e:
                        logger.error(f"❌ Failed to create empty GeoPackage after clipping: {e}")
                        return None
                else:
                    logger.info(f"create_empty=False after clipping, returning None for {output_name}")
                    return None
            
            # Export to temp file
            temp_file = self.config.artifact_dir / f"temp_{output_name}.geojson"
            logger.info(f"Temp file will be: {temp_file}")
            
            # Get download URL for FeatureCollection
            logger.info(f"Getting download URL for {clipped_count} features...")
            url = clipped.getDownloadURL('geojson')
            
            logger.debug(f"Download URL: {url}")
            
            logger.info(f"Downloading data...")
            response = requests.get(url, timeout=300)
            response.raise_for_status()
            logger.info(f"Download complete. Response size: {len(response.content)} bytes")
            
            # Save the content
            with open(temp_file, 'wb') as f:
                f.write(response.content)
            logger.info(f"Temp file saved: {temp_file}")
            
            # Read GeoJSON using json and convert to GeoDataFrame manually
            logger.info(f"Reading GeoJSON from temp file...")
            with open(temp_file, 'r', encoding='utf-8') as f:
                geojson_data = json.load(f)
            
            feature_count = len(geojson_data.get("features", []))
            logger.info(f"GeoJSON has {feature_count} features")
            
            # Log the first feature's properties to see available fields
            if feature_count > 0:
                first_feature = geojson_data["features"][0]
                logger.info(f"First feature properties: {list(first_feature.get('properties', {}).keys())}")
                if rename_field:
                    logger.info(f"Looking for field '{rename_field}' in properties")
                    if rename_field in first_feature.get('properties', {}):
                        logger.info(f"✓ Found field '{rename_field}' with value: {first_feature['properties'][rename_field]}")
                    else:
                        logger.warning(f"✗ Field '{rename_field}' not found in properties")
            
            gdf = gpd.GeoDataFrame.from_features(geojson_data["features"])
            gdf.crs = "EPSG:4326"
            logger.info(f"Created GeoDataFrame with {len(gdf)} rows")
            logger.info(f"Initial columns: {list(gdf.columns)}")
            
            # Handle waterbody_id field
            if use_fid:
                # Set waterbody_id equal to the row index (fid)
                logger.info(f"Setting waterbody_id equal to fid (feature index)")
                gdf['waterbody_id'] = range(len(gdf))
                logger.info(f"Set waterbody_id values from 0 to {len(gdf)-1}")
                
                # If rename_field is also specified, we can drop that field if it exists
                if rename_field and rename_field in gdf.columns:
                    logger.info(f"Dropping original field '{rename_field}' as we're using fid")
                    gdf = gdf.drop(columns=[rename_field])
            elif rename_field and rename_field in gdf.columns:
                # Rename the field to waterbody_id
                logger.info(f"Renaming field '{rename_field}' to 'waterbody_id'")
                gdf = gdf.rename(columns={rename_field: 'waterbody_id'})
                logger.info(f"Field renamed successfully")
                logger.info(f"Columns after rename: {list(gdf.columns)}")
            elif rename_field:
                logger.warning(f"Field '{rename_field}' not found in DataFrame. Available columns: {list(gdf.columns)}")
                # Add waterbody_id column with fid values
                if create_empty:
                    logger.info(f"Adding waterbody_id column using fid (row index)")
                    gdf['waterbody_id'] = range(len(gdf))
            
            # Add Dam_height field if requested
            if add_dam_height:
                logger.info("Adding Dam_height field for multiple reservoirs...")
                dam_height = self._calculate_dam_height(gdf)
                gdf['Dam_height'] = dam_height
                logger.info(f"Added Dam_height field with values from {dam_height.min():.2f} to {dam_height.max():.2f} m")
                logger.info(f"Mean dam height: {dam_height.mean():.2f} m")
                logger.info(f"Median dam height: {dam_height.median():.2f} m")
                logger.info(f"Number of reservoirs with dam height > 0: {(dam_height > 0).sum()} out of {len(dam_height)}")
            
            # Save to GeoPackage
            logger.info(f"Saving to GeoPackage: {output_file}")
            gdf.to_file(output_file, driver='GPKG')
            logger.info(f"✅ Saved {output_file} with {len(gdf)} features")
            logger.info(f"File exists: {output_file.exists()}")
            logger.info(f"File size: {output_file.stat().st_size} bytes")
            
            # Verify the saved file has the correct column
            if output_file.exists():
                verify_gdf = gpd.read_file(output_file)
                logger.info(f"Verification - Saved columns: {list(verify_gdf.columns)}")
                if 'waterbody_id' in verify_gdf.columns:
                    logger.info(f"✓ waterbody_id column exists in saved file")
                    logger.info(f"  waterbody_id range: {verify_gdf['waterbody_id'].min()} to {verify_gdf['waterbody_id'].max()}")
                else:
                    logger.warning(f"✗ waterbody_id column NOT found in saved file")
                if 'Dam_height' in verify_gdf.columns:
                    logger.info(f"✓ Dam_height column exists in saved file")
                    logger.info(f"  Dam_height range: {verify_gdf['Dam_height'].min():.2f} to {verify_gdf['Dam_height'].max():.2f} m")
            
            # Clean up
            if temp_file.exists():
                temp_file.unlink()
                logger.info(f"Temp file cleaned up: {temp_file}")
            
            logger.info(f"=== Completed export for {output_name} ===")
            return output_file
            
        except Exception as e:
            logger.error(f"❌ Error exporting {asset_path}: {e}")
            logger.exception("Detailed traceback:")
            
            # Try to create empty GeoPackage as fallback
            if create_empty:
                logger.info(f"Attempting to create empty GeoPackage as fallback for {output_name}...")
                try:
                    output_file = self.config.artifact_dir / f"{output_name}.gpkg"
                    gdf = gpd.GeoDataFrame(columns=['geometry'], crs='EPSG:4326')
                    gdf = gdf.set_geometry('geometry')
                    if rename_field or use_fid:
                        gdf['waterbody_id'] = pd.Series(dtype='int64')
                    if add_dam_height:
                        gdf['Dam_height'] = pd.Series(dtype='float64')
                    gdf.to_file(output_file, driver='GPKG')
                    logger.info(f"✅ Created empty GeoPackage (error recovery): {output_file}")
                    logger.info(f"File exists: {output_file.exists()}")
                    logger.info(f"File size: {output_file.stat().st_size if output_file.exists() else 0} bytes")
                    return output_file
                except Exception as e2:
                    logger.error(f"❌ Failed to create empty GeoPackage as fallback: {e2}")
            else:
                logger.info(f"create_empty=False, not creating fallback GeoPackage for {output_name}")
            
            return None
    
    def _calculate_dam_height(self, gdf):
        """
        Calculate dam height for multiple reservoirs based on reservoir characteristics.
        Uses empirical relationships from existing literature.
        
        Common empirical formulas:
        1. h = a * V^b * A^c (power law relationship)
        2. Simplified: h = 10 * (V / A)^0.5 (based on reservoir geometry)
        3. Using volume and area: h ≈ 2 * V / A (for simple prism shape)
        
        Args:
            gdf: GeoDataFrame with reservoir attributes for multiple reservoirs
            
        Returns:
            Series: Dam height in meters for each reservoir
        """
        # Initialize with NaN
        dam_height = pd.Series(np.nan, index=gdf.index)
        
        # Check if we have the required fields
        volume_columns = ['Vol_total', 'Vol_res', 'Volume', 'vol_total', 'vol_res']
        area_columns = ['Lake_area', 'Area', 'lake_area', 'area']
        
        # Find which volume column exists
        volume_col = None
        for col in volume_columns:
            if col in gdf.columns:
                volume_col = col
                break
        
        # Find which area column exists
        area_col = None
        for col in area_columns:
            if col in gdf.columns:
                area_col = col
                break
        
        if not volume_col or not area_col:
            logger.warning(f"Required fields for dam height calculation not found. Available columns: {list(gdf.columns)}")
            logger.info("Using default dam height of 20m for all reservoirs")
            dam_height = pd.Series(20.0, index=gdf.index)
            return dam_height
        
        # Get volume and area
        volume = gdf[volume_col]
        area = gdf[area_col]
        
        # Check for valid data
        valid_mask = volume.notna() & area.notna() & (volume > 0) & (area > 0)
        valid_count = valid_mask.sum()
        
        logger.info(f"Calculating dam height for {valid_count} out of {len(gdf)} reservoirs")
        logger.info(f"Using {volume_col} and {area_col}")
        
        if valid_count == 0:
            logger.warning("No valid volume and area data found for any reservoir")
            logger.info("Using default dam height of 20m for all reservoirs")
            dam_height = pd.Series(20.0, index=gdf.index)
            return dam_height
        
        # Log statistics of input data
        logger.info(f"Volume statistics for valid reservoirs:")
        logger.info(f"  Range: {volume[valid_mask].min():.2e} to {volume[valid_mask].max():.2e} m³")
        logger.info(f"  Mean: {volume[valid_mask].mean():.2e} m³")
        logger.info(f"  Median: {volume[valid_mask].median():.2e} m³")
        
        logger.info(f"Area statistics for valid reservoirs:")
        logger.info(f"  Range: {area[valid_mask].min():.2f} to {area[valid_mask].max():.2f} km²")
        logger.info(f"  Mean: {area[valid_mask].mean():.2f} km²")
        logger.info(f"  Median: {area[valid_mask].median():.2f} km²")
        
        # Convert area from km² to m² for calculations
        area_m2 = area * 1e6
        
        # Method 1: Simplified prism shape approximation
        # Dam height = 2 * Volume / Area (for a triangular prism approximation)
        dam_height_prism = 2 * volume / area_m2
        
        # Method 2: Using empirical relationship from literature
        # h = 10 * (Volume / Area)^0.5
        # Based on typical reservoir geometries
        dam_height_empirical = 10 * np.sqrt(volume / area_m2)
        
        # Method 3: Alternative formula based on reservoir shape factor
        # h = 5 * (Volume)^(1/3) (assuming cubic shape)
        dam_height_cubic = 5 * np.power(volume, 1/3)
        
        # Method 4: Based on surface area scaling
        # h = 15 * np.log10(area + 1) (logarithmic scaling)
        dam_height_log = 15 * np.log10(area + 1)
        
        # Calculate weighted average based on reservoir size categories
        # Small reservoirs: more weight to empirical method
        # Medium reservoirs: balanced approach
        # Large reservoirs: more weight to prism method
        
        # Classify reservoirs by volume
        # Small: < 1e6 m³, Medium: 1e6 - 1e8 m³, Large: > 1e8 m³
        is_small = volume < 1e6
        is_medium = (volume >= 1e6) & (volume <= 1e8)
        is_large = volume > 1e8
        
        # Initialize dam height with zeros
        dam_height = pd.Series(0.0, index=gdf.index)
        
        # Calculate for small reservoirs
        if is_small.any():
            # Small reservoirs: 70% empirical, 20% prism, 10% cubic
            dam_height_small = (0.7 * dam_height_empirical + 
                               0.2 * dam_height_prism + 
                               0.1 * dam_height_cubic)
            dam_height[is_small] = dam_height_small[is_small]
            logger.info(f"Processed {is_small.sum()} small reservoirs (< 1e6 m³)")
        
        # Calculate for medium reservoirs
        if is_medium.any():
            # Medium reservoirs: 40% empirical, 40% prism, 20% cubic
            dam_height_medium = (0.4 * dam_height_empirical + 
                                0.4 * dam_height_prism + 
                                0.2 * dam_height_cubic)
            dam_height[is_medium] = dam_height_medium[is_medium]
            logger.info(f"Processed {is_medium.sum()} medium reservoirs (1e6 - 1e8 m³)")
        
        # Calculate for large reservoirs
        if is_large.any():
            # Large reservoirs: 30% empirical, 60% prism, 10% cubic
            dam_height_large = (0.3 * dam_height_empirical + 
                               0.6 * dam_height_prism + 
                               0.1 * dam_height_cubic)
            dam_height[is_large] = dam_height_large[is_large]
            logger.info(f"Processed {is_large.sum()} large reservoirs (> 1e8 m³)")
        
        # Apply constraints based on typical dam heights
        # Minimum dam height: 5 meters
        # Maximum dam height: 300 meters (very large dams)
        dam_height = np.clip(dam_height, 5.0, 300.0)
        
        # Handle any NaN or infinite values
        dam_height = dam_height.fillna(20.0)
        dam_height = dam_height.replace([np.inf, -np.inf], 20.0)
        
        # For invalid data points, use default
        dam_height[~valid_mask] = 20.0
        
        # Log calculation details for first few reservoirs
        sample_size = min(5, len(gdf))
        for i in range(sample_size):
            if valid_mask.iloc[i]:
                vol = volume.iloc[i]
                ar = area.iloc[i]
                logger.debug(f"Reservoir {i}: Volume={vol:.2e} m³, Area={ar:.2f} km², "
                           f"Prism={dam_height_prism.iloc[i]:.1f}m, "
                           f"Empirical={dam_height_empirical.iloc[i]:.1f}m, "
                           f"Cubic={dam_height_cubic.iloc[i]:.1f}m, "
                           f"Final={dam_height.iloc[i]:.1f}m")
        
        # Log summary statistics
        logger.info(f"Dam height summary statistics for all {len(dam_height)} reservoirs:")
        logger.info(f"  Range: {dam_height.min():.2f} to {dam_height.max():.2f} m")
        logger.info(f"  Mean: {dam_height.mean():.2f} m")
        logger.info(f"  Median: {dam_height.median():.2f} m")
        logger.info(f"  Std: {dam_height.std():.2f} m")
        
        # Log distribution by size categories
        logger.info(f"Dam height distribution by reservoir size:")
        if is_small.any():
            logger.info(f"  Small reservoirs (< 1e6 m³): {dam_height[is_small].mean():.2f} m (n={is_small.sum()})")
        if is_medium.any():
            logger.info(f"  Medium reservoirs (1e6-1e8 m³): {dam_height[is_medium].mean():.2f} m (n={is_medium.sum()})")
        if is_large.any():
            logger.info(f"  Large reservoirs (> 1e8 m³): {dam_height[is_large].mean():.2f} m (n={is_large.sum()})")
        
        return dam_height
    
    def fetch_dem_data(self):
        """
        Fetch DEM data (elevation, upstream area, stream order, flow direction).
        
        Returns:
            Path: Path to the directory containing DEM rasters
        """
        logger.info("Fetching DEM data")
        
        try:
            extent = self.config.extent
            region_geom = ee.Geometry.Rectangle(extent)
            region = region_geom.getInfo()
            
            # Create output directory
            output_dir = self.config.artifact_dir / "merit_hydro_1k"
            output_dir.mkdir(exist_ok=True)
            
            logger.info(f"Files will be saved to: {output_dir}")
            
            # Asset configuration from your notebook
            datasets = {
                "elevtn": {
                    "asset": "projects/smart-theory-460821-e3/assets/30sec_elevtn",
                    "outfile": "elevtn.tif",
                    "nodata": -9999
                },
                "uparea": {
                    "asset": "projects/smart-theory-460821-e3/assets/30sec_uparea",
                    "outfile": "uparea.tif",
                    "nodata": -9999
                },
                "strord": {
                    "asset": "projects/smart-theory-460821-e3/assets/30sec_strord",
                    "outfile": "strord.tif",
                    "nodata": 255
                },
                "flwdir": {
                    "asset": "projects/smart-theory-460821-e3/assets/30sec_flwdir",
                    "outfile": "flwdir.tif",
                    "nodata": 247
                }
            }
            
            for name, config in datasets.items():
                self._download_raster_asset(
                    config["asset"],
                    output_dir / config["outfile"],
                    region_geom,
                    region,
                    config["nodata"]
                )
            
            logger.info(f"All rasters downloaded to {output_dir}")
            return output_dir
            
        except Exception as e:
            logger.error(f"Error fetching DEM properties: {e}")
            raise
    
    def fetch_landuse_data(self):
        """
        Fetch climate classification and landuse data.
        
        Returns:
            dict: Dictionary with paths to downloaded rasters
        """
        logger.info("Fetching climate and landuse data")
        
        try:
            extent = self.config.extent
            region_geom = ee.Geometry.Rectangle(extent)
            region = region_geom.getInfo()
            
            output_dir = self.config.artifact_dir
            
            # Asset configuration from your notebook
            datasets = {
                "globcover": {
                    "asset": "projects/smart-theory-460821-e3/assets/globcover",
                    "outfile": "globcover.tif",
                    "nodata": 0
                },
                "chelsa": {
                    "asset": "projects/smart-theory-460821-e3/assets/chelsa",
                    "outfile": "chelsa.tif",
                    "nodata": -32767
                },
                "koppen_geiger": {
                    "asset": "projects/smart-theory-460821-e3/assets/koppen_geiger",
                    "outfile": "koppen_geiger.tif",
                    "nodata": 32
                }
            }
            
            downloaded_files = {}
            for name, config in datasets.items():
                output_path = output_dir / config["outfile"]
                self._download_raster_asset(
                    config["asset"],
                    output_path,
                    region_geom,
                    region,
                    config["nodata"]
                )
                downloaded_files[name] = output_path
            
            logger.info(f"All rasters downloaded to {output_dir}")
            return downloaded_files
            
        except Exception as e:
            logger.error(f"Error fetching climate/landuse data: {e}")
            raise
    
    def fetch_soil_data(self):
        """
        Fetch soil data from SoilGrids assets with parallel downloads.
        
        Returns:
            Path: Path to the directory containing soil rasters
        """
        logger.info("Fetching soil data")
        
        try:
            extent = self.config.extent
            region_geom = ee.Geometry.Rectangle(extent)
            
            # Create output directory
            output_dir = self.config.artifact_dir / "soilgrids"
            output_dir.mkdir(exist_ok=True)
            
            logger.info(f"Files will be saved to: {output_dir}")
            
            # Depth layers to process
            depth_layers = [1, 2, 3, 4, 5, 6, 7]
            
            # Base dataset configuration
            base_datasets = {
                "tax_usda": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/tax_usda",
                    "outfile_base": "tax_usda",
                    "nodata": -32768,
                    "has_depth": False
                },
                "soilthickness": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/soilthickness",
                    "outfile_base": "soilthickness",
                    "nodata": -32768,
                    "has_depth": False
                },
                "sndppt": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/sndppt",
                    "outfile_base": "sndppt",
                    "nodata": -32768,
                    "has_depth": True
                },
                "sltppt": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/sltppt",
                    "outfile_base": "sltppt",
                    "nodata": -32768,
                    "has_depth": True
                },
                "oc": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/oc",
                    "outfile_base": "oc",
                    "nodata": -32768,
                    "has_depth": True
                },
                "ph": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/ph",
                    "outfile_base": "ph",
                    "nodata": -32768,
                    "has_depth": True
                },
                "bd": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/bd",
                    "outfile_base": "bd",
                    "nodata": -32768,
                    "has_depth": True
                },
                "clyppt": {
                    "asset_base": "projects/smart-theory-460821-e3/assets/soilgrids/clyppt",
                    "outfile_base": "clyppt",
                    "nodata": -32768,
                    "has_depth": True
                }
            }
            
            # Create download tasks
            tasks = self._create_soil_tasks(base_datasets, depth_layers)
            
            # Download in parallel
            self._download_soil_parallel(tasks, output_dir, region_geom, max_workers=5)
            
            logger.info(f"All soil rasters downloaded to {output_dir}")
            return output_dir
            
        except Exception as e:
            logger.error(f"Error fetching soil data: {e}")
            raise
    
    def _create_soil_tasks(self, base_datasets, depth_layers):
        """Create list of download tasks for soil data"""
        tasks = []
        
        # Add tasks for datasets without depth
        for name, d in base_datasets.items():
            if not d["has_depth"]:
                tasks.append((
                    d["asset_base"],
                    f"{d['outfile_base']}.tif",
                    d["nodata"]
                ))
        
        # Add tasks for depth-specific datasets
        for depth in depth_layers:
            for name, d in base_datasets.items():
                if d["has_depth"]:
                    tasks.append((
                        f"{d['asset_base']}_sl{depth}",
                        f"{d['outfile_base']}_sl{depth}.tif",
                        d["nodata"]
                    ))
        
        return tasks
    
    def _download_soil_parallel(self, tasks, output_dir, region_geom, max_workers=5, max_retries=3):
        """Download soil files in parallel"""
        total_tasks = len(tasks)
        logger.info(f"Starting parallel download of {total_tasks} files with {max_workers} workers...")
        
        successful = 0
        failed = 0
        start_time = time.time()
        
        def download_single(asset, outfile, nodata):
            path = output_dir / outfile
            
            if path.exists():
                logger.debug(f"File already exists: {outfile}, skipping...")
                return True
            
            for attempt in range(max_retries):
                try:
                    image = ee.Image(asset)
                    
                    url = image.getDownloadURL({
                        "region": region_geom,
                        "scale": 250,
                        "format": "GEO_TIFF"
                    })
                    
                    logger.debug(f"Downloading {outfile} (attempt {attempt + 1}/{max_retries})...")
                    
                    r = requests.get(url, stream=True, timeout=60)
                    r.raise_for_status()
                    
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(8192):
                            if chunk:
                                f.write(chunk)
                    
                    # Set nodata value
                    with rasterio.open(path, "r+") as src:
                        src.nodata = nodata
                    
                    logger.debug(f"✓ Saved: {outfile}")
                    return True
                    
                except Exception as e:
                    logger.debug(f"Failed for {outfile} (attempt {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Failed completely for {outfile}")
                        return False
            return False
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(download_single, asset, outfile, nodata): (asset, outfile)
                for asset, outfile, nodata in tasks
            }
            
            for future in as_completed(future_to_task):
                asset, outfile = future_to_task[future]
                try:
                    if future.result():
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.error(f"Exception for {outfile}: {e}")
                    failed += 1
                
                # Log progress
                completed = successful + failed
                if completed % 10 == 0 or completed == total_tasks:
                    elapsed = time.time() - start_time
                    logger.info(f"Progress: {completed}/{total_tasks} "
                              f"(Success: {successful}, Failed: {failed}) - "
                              f"Elapsed: {elapsed:.1f}s")
        
        elapsed = time.time() - start_time
        logger.info(f"Parallel download completed in {elapsed:.1f} seconds")
        logger.info(f"Successful: {successful}, Failed: {failed}")
    
    def _download_raster_asset(self, asset_path, output_path, region_geom, region, nodata):
        """Download a raster asset and set nodata value"""
        image = ee.Image(asset_path)
        proj = image.projection().getInfo()
        
        url = image.getDownloadURL({
            "region": region,
            "crs": proj["crs"],
            "crs_transform": proj["transform"],
            "format": "GEO_TIFF"
        })
        
        logger.debug(f"Downloading {output_path.name}...")
        
        r = requests.get(url, stream=True)
        r.raise_for_status()
        
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        
        logger.debug("Setting NoData...")
        
        with rasterio.open(output_path, "r+") as src:
            src.nodata = nodata
        
        logger.debug(f"Saved -> {output_path}")
    
    def fetch_era5_data(self, start_date, end_date):
        """
        Fetch ERA5 climate and orography data with optimized parallel processing.
        Uses hourly data for all variables.
        
        Args:
            start_date: Start date string (YYYY-MM-DD)
            end_date: End date string (YYYY-MM-DD)
        
        Returns:
            dict: Dictionary with paths to downloaded NetCDF files
        """
        logger.info(f"Fetching ERA5 data from {start_date} to {end_date} with parallel processing")
        
        try:
            extent = self.config.extent
            region_geom = ee.Geometry.Rectangle(extent)
            
            output_dir = self.config.artifact_dir
            era5_scale = 27830  # ERA5 native resolution
            
            # Download climate data in parallel
            logger.info("Downloading ERA5 climate data (hourly) in parallel...")
            climate_data, climate_coords, climate_dates = self._download_era5_climate_parallel(
                region_geom, start_date, end_date, era5_scale, max_workers=10
            )
            
            climate_file = None
            if climate_data and climate_coords is not None and len(climate_dates) > 0:
                climate_file = self._create_era5_climate_dataset(
                    climate_data, climate_coords, climate_dates, output_dir
                )
            
            # Download orography data for the entire period
            logger.info("Downloading ERA5 orography data for entire period...")
            orography_data, orography_coords, orography_dates = self._download_era5_orography_parallel(
                region_geom, start_date, end_date, era5_scale, max_workers=10
            )
            
            orography_file = None
            if orography_data and orography_coords is not None and len(orography_dates) > 0:
                orography_file = self._create_era5_orography_dataset(
                    orography_data, orography_coords, orography_dates, output_dir
                )
            
            result = {
                'climate': climate_file,
                'orography': orography_file
            }
            
            logger.info(f"ERA5 data saved: climate={climate_file}, orography={orography_file}")
            return result
            
        except Exception as e:
            logger.error(f"Error fetching ERA5 data: {e}")
            raise
    
    def _download_era5_climate_parallel(self, region, start_date, end_date, scale, max_workers=10):
        """
        Download ERA5 climate data in parallel using ThreadPoolExecutor.
        Uses hourly data with correct band names.
        """
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        days = pd.date_range(start, end, freq='D')
        
        logger.info(f"Processing {len(days)} days in parallel with {max_workers} workers...")
        
        data_lock = Lock()
        
        all_data = {
            "precip": [],
            "temp": [],
            "kin": [],
            "kout": [],
            "press_msl": []
        }
        coord_data_list = []
        all_hourly_dates = set()
        
        def process_day(day_idx, day):
            """Process a single day and return results"""
            day_str = day.strftime('%Y-%m-%d')
            next_day = day + pd.Timedelta(days=1)
            next_day_str = next_day.strftime('%Y-%m-%d')
            
            day_data = {k: [] for k in all_data.keys()}
            day_coords = []
            day_dates = set()
            
            try:
                # Get hourly data for the day
                hourly_coll = ee.ImageCollection("ECMWF/ERA5/HOURLY") \
                    .filterDate(day_str, next_day_str) \
                    .filterBounds(region)
                
                # Select all required bands with correct names
                hourly_coll = hourly_coll.select([
                    'total_precipitation',
                    'temperature_2m',
                    'toa_incident_solar_radiation',
                    'mean_surface_direct_short_wave_radiation_flux',
                    'mean_sea_level_pressure'
                ])
                
                hourly_data = hourly_coll.getRegion(region, scale).getInfo()
                
                if len(hourly_data) > 1:
                    df_hourly = pd.DataFrame(hourly_data[1:], columns=hourly_data[0])
                    df_hourly['datetime'] = pd.to_datetime(df_hourly['time'], unit='ms')
                    
                    df_hourly["latitude"] = pd.to_numeric(df_hourly["latitude"], errors='coerce')
                    df_hourly["longitude"] = pd.to_numeric(df_hourly["longitude"], errors='coerce')
                    df_hourly = df_hourly.dropna(subset=['latitude', 'longitude'])
                    df_hourly["latitude"] = df_hourly["latitude"].round(5)
                    df_hourly["longitude"] = df_hourly["longitude"].round(5)
                    
                    day_coords = df_hourly[["latitude", "longitude"]].to_dict('records')
                    
                    for dt in df_hourly['datetime']:
                        day_dates.add(dt)
                    
                    # Map variables
                    var_mapping = {
                        'total_precipitation': 'precip',
                        'temperature_2m': 'temp',
                        'toa_incident_solar_radiation': 'kin',
                        'mean_surface_direct_short_wave_radiation_flux': 'kout',
                        'mean_sea_level_pressure': 'press_msl'
                    }
                    
                    for ee_var, our_var in var_mapping.items():
                        if ee_var in df_hourly.columns:
                            for _, row in df_hourly.iterrows():
                                value = row[ee_var]
                                if pd.notna(value):
                                    day_data[our_var].append({
                                        "datetime": row["datetime"],
                                        "latitude": row["latitude"],
                                        "longitude": row["longitude"],
                                        "value": float(value)
                                    })
                
                return {
                    'success': True,
                    'day_idx': day_idx,
                    'day_data': day_data,
                    'day_coords': day_coords,
                    'day_dates': day_dates,
                    'day_str': day_str
                }
                
            except Exception as e:
                logger.warning(f"Error processing {day_str}: {str(e)[:100]}")
                return {
                    'success': False,
                    'day_idx': day_idx,
                    'day_str': day_str,
                    'error': str(e)
                }
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_day = {
                executor.submit(process_day, idx, day): (idx, day)
                for idx, day in enumerate(days)
            }
            
            completed = 0
            for future in as_completed(future_to_day):
                idx, day = future_to_day[future]
                try:
                    result = future.result()
                    completed += 1
                    
                    if result['success']:
                        with data_lock:
                            for var_name, var_data in result['day_data'].items():
                                all_data[var_name].extend(var_data)
                            
                            if result['day_coords']:
                                coord_data_list.extend(result['day_coords'])
                            
                            for dt in result['day_dates']:
                                all_hourly_dates.add(dt)
                        
                        if completed % 10 == 0 or completed == len(days):
                            logger.info(f"Progress: {completed}/{len(days)} days processed")
                    else:
                        logger.warning(f"Day {result['day_str']} failed: {result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.error(f"Error processing day {day}: {e}")
        
        if coord_data_list:
            coord_data = pd.DataFrame(coord_data_list).drop_duplicates()
            logger.info(f"Total: {len(all_hourly_dates)} hourly timesteps across {len(days)} days")
            return all_data, coord_data, sorted(all_hourly_dates)
        else:
            logger.error("No data could be retrieved for any day")
            return None, None, None
    
    def _download_era5_orography_parallel(self, region, start_date, end_date, scale, max_workers=10):
        """
        Download ERA5 orography data (geopotential) for entire period in parallel.
        Geopotential varies daily with atmospheric conditions.
        """
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        days = pd.date_range(start, end, freq='D')
        
        logger.info(f"Processing {len(days)} days of orography data in parallel with {max_workers} workers...")
        
        data_lock = Lock()
        
        all_data = {"elevtn": []}
        coord_data_list = []
        all_hourly_dates = set()
        
        def process_day(day_idx, day):
            """Process orography for a single day"""
            day_str = day.strftime('%Y-%m-%d')
            next_day = day + pd.Timedelta(days=1)
            next_day_str = next_day.strftime('%Y-%m-%d')
            
            day_data = []
            day_coords = []
            day_dates = set()
            
            try:
                # Get hourly geopotential data for the day
                hourly_coll = ee.ImageCollection("ECMWF/ERA5/HOURLY") \
                    .filterDate(day_str, next_day_str) \
                    .filterBounds(region) \
                    .select(['geopotential'])
                
                hourly_data = hourly_coll.getRegion(region, scale).getInfo()
                
                if len(hourly_data) > 1:
                    df_hourly = pd.DataFrame(hourly_data[1:], columns=hourly_data[0])
                    df_hourly['datetime'] = pd.to_datetime(df_hourly['time'], unit='ms')
                    
                    df_hourly["latitude"] = pd.to_numeric(df_hourly["latitude"], errors='coerce')
                    df_hourly["longitude"] = pd.to_numeric(df_hourly["longitude"], errors='coerce')
                    df_hourly = df_hourly.dropna(subset=['latitude', 'longitude'])
                    df_hourly["latitude"] = df_hourly["latitude"].round(5)
                    df_hourly["longitude"] = df_hourly["longitude"].round(5)
                    
                    # Store coordinates (unique for this day)
                    day_coords = df_hourly[["latitude", "longitude"]].to_dict('records')
                    
                    # Convert geopotential to elevation (m)
                    for _, row in df_hourly.iterrows():
                        if pd.notna(row['geopotential']):
                            day_data.append({
                                "datetime": row["datetime"],
                                "latitude": row["latitude"],
                                "longitude": row["longitude"],
                                "value": float(row['geopotential']) / 9.80665
                            })
                            day_dates.add(row["datetime"])
                
                return {
                    'success': True,
                    'day_idx': day_idx,
                    'day_data': day_data,
                    'day_coords': day_coords,
                    'day_dates': day_dates,
                    'day_str': day_str
                }
                
            except Exception as e:
                logger.warning(f"Error processing orography for {day_str}: {str(e)[:100]}")
                return {
                    'success': False,
                    'day_idx': day_idx,
                    'day_str': day_str,
                    'error': str(e)
                }
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_day = {
                executor.submit(process_day, idx, day): (idx, day)
                for idx, day in enumerate(days)
            }
            
            completed = 0
            for future in as_completed(future_to_day):
                idx, day = future_to_day[future]
                try:
                    result = future.result()
                    completed += 1
                    
                    if result['success']:
                        with data_lock:
                            all_data["elevtn"].extend(result['day_data'])
                            
                            if result['day_coords']:
                                coord_data_list.extend(result['day_coords'])
                            
                            for dt in result['day_dates']:
                                all_hourly_dates.add(dt)
                        
                        if completed % 10 == 0 or completed == len(days):
                            logger.info(f"Orography progress: {completed}/{len(days)} days processed")
                    else:
                        logger.warning(f"Day {result['day_str']} orography failed: {result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.error(f"Error processing orography for day {day}: {e}")
        
        if coord_data_list:
            coord_data = pd.DataFrame(coord_data_list).drop_duplicates()
            logger.info(f"Total: {len(all_hourly_dates)} hourly timesteps for orography")
            return all_data, coord_data, sorted(all_hourly_dates)
        else:
            logger.error("No orography data could be retrieved for any day")
            return None, None, None
    
    def _create_era5_climate_dataset(self, data_dict, coords, hourly_dates, output_dir):
        """Create xarray dataset for ERA5 climate data (hourly)"""
        if coords is None or len(data_dict) == 0:
            return None
        
        all_coords = pd.concat([coords], ignore_index=True).drop_duplicates()
        lats = np.sort(all_coords["latitude"].unique())
        lons = np.sort(all_coords["longitude"].unique())
        
        ds = xr.Dataset()
        
        lat_idx = {lat: i for i, lat in enumerate(lats)}
        lon_idx = {lon: i for i, lon in enumerate(lons)}
        time_idx = {t: i for i, t in enumerate(hourly_dates)}
        
        # Variable metadata
        var_info = {
            "precip": {"conversion": lambda x: x, "unit": "m", "desc": "Total precipitation"},
            "temp": {"conversion": lambda x: x, "unit": "K", "desc": "Temperature at 2m"},
            "kin": {"conversion": lambda x: x, "unit": "W/m²", "desc": "TOA incident solar radiation"},
            "kout": {"conversion": lambda x: x, "unit": "W/m²", "desc": "Mean surface direct short wave radiation flux"},
            "press_msl": {"conversion": lambda x: x, "unit": "Pa", "desc": "Mean sea level pressure"}
        }
        
        for var_name, var_data_list in data_dict.items():
            if not var_data_list:
                continue
            
            arr = np.full((len(hourly_dates), len(lats), len(lons)), np.nan, dtype=np.float32)
            
            for entry in var_data_list:
                dt = entry.get("datetime")
                lat = entry.get("latitude")
                lon = entry.get("longitude")
                value = entry.get("value")
                
                if (dt in time_idx and lat in lat_idx and lon in lon_idx and
                    value is not None and not np.isnan(value)):
                    i = time_idx[dt]
                    j = lat_idx[lat]
                    k = lon_idx[lon]
                    arr[i, j, k] = value
            
            if var_name in var_info:
                arr = var_info[var_name]["conversion"](arr)
                units = var_info[var_name]["unit"]
                description = var_info[var_name]["desc"]
            else:
                units = "unknown"
                description = var_name
            
            ds[var_name] = xr.DataArray(
                arr,
                dims=["time", "lat", "lon"],
                coords={"time": hourly_dates, "lat": lats, "lon": lons},
                attrs={"units": units, "long_name": description}
            )
        
        # Add global attributes
        ds.attrs = {
            "title": "ERA5 Hourly Climate Data",
            "creation_date": pd.Timestamp.now().isoformat(),
            "source": "ECMWF/ERA5/HOURLY",
            "start_date": self.config.start_date,
            "end_date": self.config.end_date
        }
        
        # Save to NetCDF
        era5_filename = output_dir / "era5.nc"
        ds.to_netcdf(era5_filename)
        
        logger.info(f"ERA5 climate data saved: {era5_filename}")
        return era5_filename
    
    def _create_era5_orography_dataset(self, data_dict, coords, hourly_dates, output_dir):
        """Create xarray dataset for ERA5 orography data (dynamic geopotential)"""
        if coords is None or len(data_dict) == 0:
            return None
        
        all_coords = pd.concat([coords], ignore_index=True).drop_duplicates()
        lats = np.sort(all_coords["latitude"].unique())
        lons = np.sort(all_coords["longitude"].unique())
        
        ds = xr.Dataset()
        
        lat_idx = {lat: i for i, lat in enumerate(lats)}
        lon_idx = {lon: i for i, lon in enumerate(lons)}
        time_idx = {t: i for i, t in enumerate(hourly_dates)}
        
        # Create array for elevation (geopotential converted to meters)
        elevtn_data = data_dict.get("elevtn", [])
        if not elevtn_data:
            return None
        
        # Initialize 3D array (time, lat, lon)
        arr = np.full((len(hourly_dates), len(lats), len(lons)), np.nan, dtype=np.float32)
        
        for entry in elevtn_data:
            dt = entry.get("datetime")
            lat = entry.get("latitude")
            lon = entry.get("longitude")
            value = entry.get("value")
            
            if (dt in time_idx and lat in lat_idx and lon in lon_idx and
                value is not None and not np.isnan(value)):
                i = time_idx[dt]
                j = lat_idx[lat]
                k = lon_idx[lon]
                arr[i, j, k] = value
        
        # Add to dataset
        ds["elevtn"] = xr.DataArray(
            arr,
            dims=["time", "lat", "lon"],
            coords={"time": hourly_dates, "lat": lats, "lon": lons},
            attrs={"units": "m", "long_name": "Elevation from geopotential (Z = Φ/g)"}
        )
        
        # Add global attributes
        ds.attrs = {
            "title": "ERA5 Orography (Dynamic Geopotential)",
            "creation_date": pd.Timestamp.now().isoformat(),
            "source": "ECMWF/ERA5/HOURLY",
            "description": "Elevation derived from geopotential (Φ/g). Varies with atmospheric conditions.",
            "variable_description": "Geopotential is the gravitational potential energy per unit mass. Dividing by g gives elevation.",
            "units": "meters",
            "start_date": self.config.start_date,
            "end_date": self.config.end_date
        }
        
        # Save to NetCDF
        orography_filename = output_dir / "era5_orography.nc"
        
        # Use compression for large files
        encoding = {
            'elevtn': {
                'zlib': True,
                'complevel': 4,
                'dtype': 'float32'
            }
        }
        
        ds.to_netcdf(orography_filename, encoding=encoding)
        
        logger.info(f"ERA5 orography data saved to {orography_filename} with shape {arr.shape}")
        logger.info(f"  - {len(hourly_dates)} timesteps")
        logger.info(f"  - {len(lats)} latitude points")
        logger.info(f"  - {len(lons)} longitude points")
        
        return orography_filename
    
    def fetch_modis_lai(self, start_date, end_date):
        """
        Fetch MODIS LAI data and ensure exactly 12 timestamps.
        Uses proper data download method.
        
        Args:
            start_date: Start date string (YYYY-MM-DD)
            end_date: End date string (YYYY-MM-DD)
        
        Returns:
            Path: Path to the saved NetCDF file
        """
        logger.info(f"Fetching MODIS LAI data from {start_date} to {end_date}")
        
        try:
            extent = self.config.extent
            min_lon, min_lat, max_lon, max_lat = extent
            
            output_dir = self.config.artifact_dir
            output_path = output_dir / "modis_lai.nc"
            
            # MODIS MCD15A3H availability start date
            modis_start_date = '2002-07-04'
            
            # Create bounding box geometry
            roi = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
            
            # Get all available images
            modis = ee.ImageCollection('MODIS/061/MCD15A3H') \
                .filterDate(start_date, end_date) \
                .filterBounds(roi) \
                .select(['Lai'])
            
            # Get count and dates
            count = modis.size().getInfo()
            logger.info(f"Found {count} images in the collection")
            
            target_timestamps = 12
            
            if count == 0:
                logger.warning("No MODIS images found, returning None")
                return None
            
            # Get all dates
            dates = modis.aggregate_array('system:time_start').getInfo()
            dates = [pd.to_datetime(d, unit='ms') for d in dates]
            
            # Select evenly spaced timestamps
            if count >= target_timestamps:
                indices = np.linspace(0, count - 1, target_timestamps, dtype=int)
                selected_dates = [dates[i] for i in indices]
            else:
                # If fewer than 12, keep all and pad later
                selected_dates = dates
                logger.info(f"Only {count} images available, will pad to {target_timestamps}")
            
            # Download images using proper download method
            lai_arrays = []
            successful_dates = []
            
            image_list = modis.toList(count)
            
            for i, sel_date in enumerate(selected_dates):
                logger.info(f"Processing image {i+1}/{len(selected_dates)} for {sel_date.strftime('%Y-%m-%d')}")
                
                # Find the exact image for this date (or closest)
                date_str = sel_date.strftime('%Y-%m-%d')
                next_date = (sel_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                
                date_filtered = ee.ImageCollection('MODIS/061/MCD15A3H') \
                    .filterDate(date_str, next_date) \
                    .filterBounds(roi) \
                    .select(['Lai'])
                
                date_count = date_filtered.size().getInfo()
                
                if date_count > 0:
                    image = ee.Image(date_filtered.first())
                    arr = self._download_single_modis_image(image, sel_date.strftime('%Y%m%d'), 
                                                           roi, min_lon, min_lat, max_lon, max_lat)
                else:
                    # Try to find closest image within 2 days
                    nearby = ee.ImageCollection('MODIS/061/MCD15A3H') \
                        .filterDate(
                            (sel_date - pd.Timedelta(days=2)).strftime('%Y-%m-%d'),
                            (sel_date + pd.Timedelta(days=3)).strftime('%Y-%m-%d')
                        ) \
                        .filterBounds(roi) \
                        .select(['Lai']) \
                        .sort('system:time_start')
                    
                    nearby_count = nearby.size().getInfo()
                    if nearby_count > 0:
                        image = ee.Image(nearby.first())
                        actual_date_ms = image.get('system:time_start').getInfo()
                        actual_date = pd.to_datetime(actual_date_ms, unit='ms')
                        logger.info(f"Using nearby image from {actual_date.strftime('%Y-%m-%d')}")
                        arr = self._download_single_modis_image(image, actual_date.strftime('%Y%m%d'),
                                                               roi, min_lon, min_lat, max_lon, max_lat)
                    else:
                        logger.warning(f"No image found for {sel_date.strftime('%Y-%m-%d')}")
                        arr = None
                
                if arr is not None:
                    lai_arrays.append(arr)
                    successful_dates.append(sel_date)
                else:
                    # Create placeholder
                    width = int((max_lon - min_lon) / (500/111000))
                    height = int((max_lat - min_lat) / (500/111000))
                    placeholder = np.full((height, width), np.nan, dtype=np.float32)
                    lai_arrays.append(placeholder)
                    successful_dates.append(sel_date)
            
            # Pad to exactly 12 if needed
            if len(lai_arrays) < target_timestamps:
                logger.info(f"Padding from {len(lai_arrays)} to {target_timestamps} timestamps")
                ref_shape = lai_arrays[0].shape
                while len(lai_arrays) < target_timestamps:
                    lai_arrays.append(np.full(ref_shape, np.nan, dtype=np.float32))
                    if successful_dates:
                        successful_dates.append(successful_dates[-1] + pd.Timedelta(days=30))
                    else:
                        successful_dates.append(pd.to_datetime(start_date))
            
            # Stack arrays
            lai_3d = np.stack(lai_arrays[:target_timestamps], axis=0)
            logger.info(f"Final array shape: {lai_3d.shape}")
            
            # Create dataset
            lats = np.linspace(max_lat, min_lat, lai_3d.shape[1])
            lons = np.linspace(min_lon, max_lon, lai_3d.shape[2])
            
            ds = xr.Dataset(
                {
                    'Lai': (['time', 'lat', 'lon'], lai_3d.astype(np.float32)),
                },
                coords={
                    'time': successful_dates[:target_timestamps],
                    'lat': lats.astype(np.float32),
                    'lon': lons.astype(np.float32),
                },
                attrs={
                    'title': 'MODIS LAI 4-day Composite',
                    'product': 'MCD15A3H',
                    'version': '061',
                    'extent': str(extent),
                    'source': 'Google Earth Engine',
                    'image_dates': str([d.strftime('%Y-%m-%d') for d in successful_dates[:target_timestamps]])
                }
            )
            
            ds.Lai.attrs['units'] = 'm²/m²'
            ds.Lai.attrs['long_name'] = 'Leaf Area Index'
            ds.Lai.attrs['_FillValue'] = np.nan
            
            # Save to NetCDF
            ds.to_netcdf(output_path, mode='w', format='NETCDF4', engine='netcdf4')
            
            logger.info(f"MODIS LAI data saved to {output_path} with {len(ds.time)} timestamps")
            return output_path
            
        except Exception as e:
            logger.error(f"Error fetching MODIS LAI data: {e}")
            raise
    
    def _download_single_modis_image(self, image, date_str, roi, min_lon, min_lat, max_lon, max_lat):
        """Download a single MODIS image using proper data download"""
        try:
            # Apply scale factor (0.1) to get actual LAI values
            image = image.multiply(0.1).rename('Lai')
            
            # MODIS native resolution is 500m
            scale = 500  # meters
            
            # Use getDownloadURL - this preserves actual data values
            url = image.getDownloadURL({
                'name': f'MODIS_LAI_{date_str}',
                'scale': scale,
                'region': roi,
                'format': 'GEO_TIFF',
                'crs': 'EPSG:4326'
            })
            
            logger.debug(f"Downloading {date_str}...")
            response = requests.get(url, timeout=120)
            
            if response.status_code == 200:
                # Handle both zip and direct GeoTIFF
                if response.content[:2] == b'PK':
                    # It's a zip file (multiple bands)
                    with zipfile.ZipFile(BytesIO(response.content)) as zip_ref:
                        # Find the .tif file
                        tif_files = [f for f in zip_ref.namelist() if f.endswith('.tif')]
                        if tif_files:
                            with zip_ref.open(tif_files[0]) as f:
                                ds = rioxarray.open_rasterio(f)
                                arr = ds.values[0] if len(ds.values.shape) > 2 else ds.values
                else:
                    # Direct GeoTIFF
                    ds = rioxarray.open_rasterio(BytesIO(response.content))
                    arr = ds.values[0] if len(ds.values.shape) > 2 else ds.values
                
                arr = arr.astype(np.float32)
                # Set invalid values to NaN
                arr[arr < 0] = np.nan
                arr[arr > 10] = np.nan
                
                logger.debug(f"✅ Downloaded {date_str}: shape={arr.shape}, range=[{np.nanmin(arr):.2f}, {np.nanmax(arr):.2f}]")
                return arr
            else:
                logger.debug(f"Download failed with status {response.status_code}")
                return None
                
        except Exception as e:
            logger.debug(f"Error downloading single image: {e}")
            return None
    
    def create_data_catalog(self):
        """
        Copy the sample data catalog from wflow_builder folder to artifact directory.
        
        Returns:
            Path: Path to the copied data catalog
        """
        logger.info("Copying data catalog from sample")
        
        try:
            # Path to sample catalog in wflow_builder folder
            sample_catalog_path = Path(__file__).parent / "data_catalog.yml"
            
            if not sample_catalog_path.exists():
                logger.error(f"Sample catalog not found at {sample_catalog_path}")
                # Try alternative path
                sample_catalog_path = Path(__file__).parent.parent / "wflow_builder" / "data_catalog.yml"
                
            if not sample_catalog_path.exists():
                logger.error(f"Sample catalog also not found at {sample_catalog_path}")
                raise FileNotFoundError(f"Sample data catalog not found")
            
            # Destination path in artifact directory
            dest_path = self.config.artifact_dir / "data_catalog.yml"
            
            # Copy the file
            shutil.copy2(sample_catalog_path, dest_path)
            
            logger.info(f"✅ Data catalog copied from {sample_catalog_path} to {dest_path}")
            logger.info(f"File exists: {dest_path.exists()}")
            logger.info(f"File size: {dest_path.stat().st_size} bytes")
            
            return dest_path
            
        except Exception as e:
            logger.error(f"Error copying data catalog: {e}")
            raise