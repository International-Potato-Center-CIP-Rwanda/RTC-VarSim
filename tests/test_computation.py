"""Synthetic regression checks for computation. Temporary fixtures do not require the private research datasets."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin
from django.test import Client, override_settings
from platform_app.computation import compute


class ComputationTests(unittest.TestCase):
    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        raster = self.base / 'test.tif'
        with rasterio.open(raster, 'w', driver='GTiff', width=2, height=2, count=1,
                           dtype='float32', crs='EPSG:4326', transform=from_origin(29,-1,.1,.1), nodata=-9999) as dst:
            dst.write(np.array([[10,20],[-9999,30]],dtype='float32'),1)
        self.cfg = {'layers':[{'id':'temperature','path':str(raster),'unit':'°C'}]}
        self.cat = {'records':[{'id':'test','name':'Test','crop':'potato','source':{}}]}
        self.payload = {'variety':'test','rationale':'Synthetic software test only.', 'reference_site':{'longitude':29.05,'latitude':-1.05},
                        'parameters':[{'id':'temperature','weight':1,'normalization':10}]}

    def test_numeric_result_mask_and_record(self):
        """Verify that numeric result mask and record."""
        directory = self.base/'result'
        result = compute(self.payload,self.cfg,self.cat,directory)
        self.assertEqual(result['statistics']['valid_cells'],3)
        with rasterio.open(directory/'similarity.tif') as src:
            a=src.read(1,masked=True)
            self.assertAlmostEqual(float(a[0,0]),1)
            self.assertAlmostEqual(float(a[0,1]),.5)
            self.assertTrue(a.mask[1,0])
        self.assertTrue((directory/'similarity.png').read_bytes().startswith(b'\x89PNG'))
        record=json.loads((directory/'metadata.json').read_text())
        self.assertEqual(record['setup']['reference_site']['longitude'],29.05)

    def test_http_run_download_and_invalid_site(self):
        """Verify that http run download and invalid site."""
        with override_settings(BASE_DIR=self.base), patch('platform_app.views.configuration',return_value=self.cfg), patch('platform_app.views.catalogue',return_value=self.cat):
            client=Client()
            response=client.post('/api/compute/',self.payload,content_type='application/json')
            self.assertEqual(response.status_code,200)
            for url in response.json()['files'].values():
                download=client.get(url)
                self.assertEqual(download.status_code,200)
                download.close()
            self.payload['reference_site']['latitude']=-1.15
            self.assertEqual(client.post('/api/compute/',self.payload,content_type='application/json').status_code,400)
            self.payload['reference_site']=None
            self.assertEqual(client.post('/api/compute/',self.payload,content_type='application/json').status_code,400)
