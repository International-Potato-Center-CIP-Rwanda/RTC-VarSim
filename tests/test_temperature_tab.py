"""Synthetic regression checks for temperature tab. Temporary fixtures do not require the private research datasets."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_app.settings')
import django
django.setup()
import numpy as np
import rasterio
from django.test import RequestFactory, override_settings
from platform_app import africa_demo

class TemperatureTabTests(unittest.TestCase):
    def test_display_builder_uses_current_input_signature(self):
        """Verify that display builder uses current input signature."""
        import hashlib
        import build_demo_climate
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            data=base/'data'
            data.mkdir()
            plan={'tiles':[{'row':0,'col':0,'height':16,'width':16}]}
            mask='synthetic mask'
            inventory='synthetic inventory'
            (data/'africa-tiles.json').write_text(json.dumps(plan))
            (data/'africa-extraction-mask.geojson').write_text(mask)
            (data/'africa-1991-2020-inventory.json').write_text(inventory)
            signature=hashlib.sha256((json.dumps(plan,sort_keys=True)+mask+inventory).encode()).hexdigest()[:16]
            jobs=data/'africa-jobs'/signature
            jobs.mkdir(parents=True)
            tile=base/'tile'
            tile.mkdir()
            with rasterio.open(tile/'africa-mean.tif','w',driver='GTiff',height=16,width=16,count=1,dtype='float32',crs='EPSG:4326',transform=rasterio.Affine(1,0,-8,0,-1,8),nodata=-9999) as dst:
                dst.write(np.full((16,16),23,dtype='float32'),1)
            for variable in ('tas','pr'):
                for month in range(1,13):
                    (jobs/f'r0-c0-{variable}-{month:02d}.json').write_text(json.dumps({'status':'complete','folder':str(tile)}))
            with patch.object(build_demo_climate,'BASE',base):
                build_demo_climate.build()
            with np.load(data/'demo-climate/monthly.npz') as result:
                np.testing.assert_array_equal(result['values'],np.full((1,1,2,12),23))

    def test_month_class_totals_mask_land_and_missing_cycle_values(self):
        """Verify that month class totals mask land and missing cycle values."""
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            (base/'data').mkdir()
            (base/'data/catalogue.json').write_text(json.dumps({'records':[{
                'id':'synthetic','name':'Synthetic variety','cycle_days':[100,120],
                'temperature_range':[16,34]}]}))
            climate=np.full((2,4,2,12),20,dtype='float32')
            for col in range(4):
                climate[0,col,0,[10,11,0,1][:col]]=40
            climate[1,0,0,[10,11,0,1]]=40
            climate[1,1,0,10]=np.nan
            land=np.array([[1,1,1,1],[1,1,0,0]],dtype=bool)
            with override_settings(BASE_DIR=base), patch.object(africa_demo,'dataset',return_value=(climate,rasterio.Affine(1,0,-4,0,-1,2),None,0,0,1,base)), patch.object(africa_demo,'africa_land_mask',return_value=land):
                request=RequestFactory().post('/api/demo/variety-temperature/',data=json.dumps({'variety_id':'synthetic','planting_month':11}),content_type='application/json')
                response=africa_demo.screen_variety_temperature(request)
            self.assertEqual(response.status_code,200,response.content)
            result=json.loads(response.content)
            meta=result['metadata']
            self.assertEqual(meta['months'],[11,12,1,2])
            self.assertEqual(meta['class_counts'],dict.fromkeys(map(str,range(5)),1))
            self.assertEqual(meta['valid_cells'],5)
            self.assertEqual(meta['not_evaluable_cells'],1)
            with rasterio.open(base/'runs'/result['id']/'temperature-range.tif') as src:
                np.testing.assert_allclose(src.read(1),[[1,.75,.5,.25],[0,-9999,-9999,-9999]])
            self.assertTrue((base/'runs'/result['id']/'temperature-range.png').read_bytes().startswith(b'\x89PNG'))
