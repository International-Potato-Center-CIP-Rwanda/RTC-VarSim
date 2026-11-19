"""Synthetic regression checks for result tools. Temporary fixtures do not require the private research datasets."""
import hashlib
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from django.test import Client, override_settings
from platform_app.result_tools import filter_cells


class ResultTests(unittest.TestCase):
    def test_thresholds_ties_and_nodata(self):
        """Verify that thresholds ties and nodata."""
        values=np.array([[.2,.8],[.8,np.nan]])
        self.assertEqual(filter_cells(values,'none',100).sum(),3)
        self.assertEqual(filter_cells(values,'absolute',80).sum(),2)
        top=filter_cells(values,'top',33)
        self.assertEqual(top.sum(),1)
        self.assertTrue(top[1,0])
        self.assertEqual(filter_cells(values,'top',0).sum(),0)
        self.assertEqual(filter_cells(values,'top',100).sum(),3)
        self.assertEqual(filter_cells(values,'absolute',100).sum(),0)
        for mode,percent in [('bad',1),('top',-1),('absolute',101),('top',float('nan'))]:
            with self.assertRaises(ValueError):filter_cells(values,mode,percent)

    def test_inspection_filter_and_immutable_raster(self):
        """Verify that inspection filter and immutable raster."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run='11111111-1111-4111-8111-111111111111'
            directory=root/'runs'/run;directory.mkdir(parents=True)
            path=directory/'similarity.tif'
            with rasterio.open(path,'w',driver='GTiff',width=2,height=2,count=1,dtype='float32',crs='EPSG:4326',transform=from_origin(29,-1,.1,.1),nodata=-9999) as dst:
                dst.write(np.array([[.2,1],[-9999,.8]],dtype='float32'),1)
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            with override_settings(BASE_DIR=root):
                client=Client();url=f'/api/results/{run}/'
                preview=client.get(url,{'mode':'top','percent':0})
                self.assertEqual(preview.status_code,200)
                self.assertEqual(preview.json()['visible_cells'],0)
                self.assertTrue(preview.json()['image'].startswith('data:image/png;base64,'))
                query={'mode':'absolute','percent':80,'longitude':29.05,'latitude':-1.05}
                sample=client.get(url,query).json()
                self.assertEqual(sample['status'],'filtered_out')
                self.assertAlmostEqual(sample['score'],.2)
                query.update(longitude=29.15)
                self.assertEqual(client.get(url,query).json()['status'],'visible')
                query.update(longitude=29.05,latitude=-1.15)
                self.assertEqual(client.get(url,query).json()['status'],'no_data')
                query.update(latitude=0)
                self.assertEqual(client.get(url,query).json()['status'],'outside_extent')
                self.assertEqual(client.get(url,{'percent':'nan'}).status_code,400)
                self.assertEqual(client.get('/api/results/22222222-2222-4222-8222-222222222222/').status_code,404)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
