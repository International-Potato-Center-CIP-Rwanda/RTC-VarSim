"""Synthetic regression checks for africa jobs. Temporary fixtures do not require the private research datasets."""
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from africa_climate_jobs import mask_output

class MaskTests(unittest.TestCase):
    def test_land_mask_preserves_missing_and_excludes_outside(self):
        """Verify that land mask preserves missing and excludes outside."""
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with rasterio.open(folder/'mean.tif','w',driver='GTiff',height=2,width=3,count=1,dtype='float32',nodata=-9999,crs='EPSG:4326',transform=from_origin(0,2,1,1)) as dest:
                dest.write(np.array([[10,-9999,30],[40,50,60]],dtype='float32'),1)
            mask=folder/'mask.json'
            mask.write_text(json.dumps({'features':[{'geometry':{'type':'Polygon','coordinates':[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}}]}))
            result=mask_output(folder,mask)
            with rasterio.open(folder/'africa-mean.tif') as src:
                np.testing.assert_array_equal(src.read(1),[[10,-9999,-9999],[40,50,-9999]])
            self.assertEqual(result['land_cells'],4)
            self.assertEqual(result['valid_land_cells'],3)
