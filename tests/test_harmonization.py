"""Synthetic regression checks for harmonization. Temporary fixtures do not require the private research datasets."""
import tempfile
from pathlib import Path
import unittest
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.enums import Resampling
from harmonize_layers import harmonize


class HarmonizationTests(unittest.TestCase):
    def test_average_scaling_mask_and_exact_grid(self):
        """Verify that average scaling mask and exact grid."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,values,res):
                """Write a synthetic raster fixture with the supplied values and grid."""
                a=np.array(values,dtype='float32')
                with rasterio.open(root/name,'w',driver='GTiff',width=a.shape[1],height=a.shape[0],count=1,dtype='float32',nodata=-9999,crs='EPSG:4326',transform=from_origin(29,-1,res,res)) as d:
                    d.write(a,1)
            write('ref.tif',[[1,-9999],[1,1]],.2)
            write('src.tif',[[40,60,80,80],[40,60,80,80],[0,-9999,50,70],[0,-9999,50,70]],.1)
            stats=harmonize(root/'src.tif',root/'ref.tif',root/'out.tif',Resampling.average,.1,(1,14))
            with rasterio.open(root/'out.tif') as out,rasterio.open(root/'ref.tif') as ref:
                np.testing.assert_allclose(out.read(1),[[5,-9999],[-9999,6]])
                self.assertEqual(out.transform,ref.transform)
                self.assertEqual(out.crs,ref.crs)
            self.assertEqual(stats['valid_cells'],2)
            self.assertEqual(stats['missing_in_climate_domain'],1)

    def test_mode_preserves_class_codes(self):
        """Verify that mode preserves class codes."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,values,res in [('src',[[4,4],[4,12]],.1),('ref',[[1]],.2)]:
                a=np.array(values,dtype='float32')
                with rasterio.open(root/f'{name}.tif','w',driver='GTiff',width=a.shape[1],height=a.shape[0],count=1,dtype='float32',nodata=-9999,crs='EPSG:4326',transform=from_origin(29,-1,res,res)) as dst:
                    dst.write(a,1)
            harmonize(root/'src.tif',root/'ref.tif',root/'out.tif',Resampling.mode,1,(1,12))
            with rasterio.open(root/'out.tif') as out:
                self.assertEqual(out.read(1)[0,0],4)
