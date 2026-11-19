"""Synthetic regression checks for demo retouches. Temporary fixtures do not require the private research datasets."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('DJANGO_SETTINGS_MODULE','platform_app.settings')
import django
django.setup()
import numpy as np
import rasterio
from django.test import RequestFactory, override_settings
from platform_app import africa_demo
from platform_app.result_tools import preview_png
from platform_app.variety_screen import calculation_profile

class DemoRetouchTests(unittest.TestCase):
    def record(self,name='Selected',duration=120):
        """Construct a synthetic variety record for catalogue or interface tests."""
        return dict(id=name,name=name,crop='sweetpotato',is_unspecified=False,
                    temperature_range=[16,34],rainfall_range=[450,1250],ph_range=[5.5,7],
                    cycle_days=[100,duration],notes='High virus resistance (SPVD).',source={'sheet':'Synthetic','range':'A1:P1'})

    def test_matching_uses_actual_cycle_months_and_rejects_incomplete_records(self):
        """Verify that matching uses actual cycle months and rejects incomplete records."""
        selected=self.record()
        self.assertEqual(calculation_profile(selected),calculation_profile(self.record('Same',115)))
        self.assertNotEqual(calculation_profile(selected),calculation_profile(self.record('Longer',125)))
        for field,value in [('is_unspecified',True),('ph_range',[None,7]),('cycle_days',[None,None]),('rainfall_range',[500,450])]:
            other=copy.deepcopy(selected);other[field]=value
            self.assertIsNone(calculation_profile(other))

    def test_variety_card_shows_peer_names_source_and_preserves_spvd_text(self):
        """Verify that variety card shows peer names source and preserves spvd text."""
        selected=self.record()
        peer=self.record('Peer',115)
        other=self.record('Other');other['is_unspecified']=True
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);(base/'data').mkdir();(base/'assets').mkdir()
            catalogue={'source_file':'synthetic.xlsx','records':[selected,peer,self.record('Longer',125),other]}
            path=base/'data/catalogue.json';path.write_text(json.dumps(catalogue))
            before=path.read_bytes()
            for name in ['africa-demo.js','africa-demo.css']:(base/'assets'/name).write_text('/* synthetic */')
            with override_settings(BASE_DIR=base):
                response=africa_demo.home(RequestFactory().get('/demo/',{'variety':selected['id']}))
            html=response.content.decode()
            self.assertIn('Same criteria as: Peer',html)
            self.assertNotIn('Same criteria as: Peer, Longer',html)
            self.assertIn('maps will be identical',html)
            self.assertIn('Source: tolerance catalogue, not independently verified',html)
            self.assertIn('High virus resistance noted',html)
            self.assertEqual(before,path.read_bytes())

    def test_kabode_spvd_override_has_source_and_does_not_change_catalogue(self):
        """Verify that kabode spvd override has source and does not change catalogue."""
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);(base/'data').mkdir();(base/'assets').mkdir()
            records=[self.record('Kabode'),self.record('Other named variety')]
            path=base/'data/catalogue.json'
            path.write_text(json.dumps({'source_file':'synthetic.xlsx','records':records}))
            before=path.read_bytes()
            (base/'data/reference').mkdir()
            (base/'data/reference/rab_sweetpotato_2018_internal.json').write_text(json.dumps({
                'source':{'label':'Synthetic internal source'},'records':[{'name':'Kabode','crop':'sweetpotato',
                'cycle_days':[130,160],'resistances':{'SPVD':'Moderate'}}]}))
            for name in ['africa-demo.js','africa-demo.css']:
                (base/'assets'/name).write_text('/* synthetic */')
            with override_settings(BASE_DIR=base):
                for record in records:
                    response=africa_demo.home(RequestFactory().get('/demo/',{'variety':record['id']}))
                    html=response.content.decode()
                    if record['name']=='Kabode':
                        self.assertIn('<small>SPVD</small>Moderate',html)
                        self.assertIn('Source: Synthetic internal source',html)
                        self.assertNotIn('<small>SPVD</small>High virus resistance noted',html)
                    else:
                        self.assertIn('<small>SPVD</small>High virus resistance noted',html)
                        self.assertNotIn('Source: Synthetic internal source',html)
            self.assertEqual(path.read_bytes(),before)

    def test_missing_temperature_land_is_grey_and_sea_transparent(self):
        """Verify that missing temperature land is grey and sea transparent."""
        values=np.array([[0,1,np.nan,np.nan],[.5,.75,np.nan,np.nan]],dtype='float32')
        land=np.array([[1,1,1,0],[1,1,1,0]],dtype='uint8')
        with rasterio.io.MemoryFile() as mem:
            with mem.open(driver='GTiff',height=2,width=4,count=1,dtype='float32',crs='EPSG:4326',transform=rasterio.Affine(1,0,-2,0,-1,1)) as src:
                png=preview_png(src,values,land_mask=land)
                normal=preview_png(src,values)
        with rasterio.io.MemoryFile(png) as mem,mem.open() as image:
            rgba=np.moveaxis(image.read(),0,-1)
            grey=np.all(rgba==[130,130,130,255],axis=-1)
            self.assertEqual(int(grey.sum()),2)
            self.assertEqual(int((rgba[:,:,3]==0).sum()),2)
            self.assertTrue(np.all(rgba[:,2,:]==[130,130,130,255]))
            self.assertTrue(np.all(rgba[:,3,3]==0))
        with rasterio.io.MemoryFile(normal) as mem,mem.open() as image:
            self.assertEqual(int((image.read(4)==0).sum()),4)

    def test_legend_has_one_column_and_no_forced_no_wrap(self):
        """Verify that legend has one column and no forced no wrap."""
        base=Path(__file__).resolve().parents[1]
        css=(base/'assets/africa-demo.css').read_text(encoding='utf-8')
        rule=css.split('.demo-map-panel .range-classes{',1)[1].split('}',1)[0]
        self.assertIn('grid-template-columns:minmax(0,1fr)',rule)
        row=css.split('.demo-map-panel .range-class{',1)[1].split('}',1)[0]
        self.assertIn('white-space:normal',row)
        script=(base/'assets/africa-demo.js').read_text(encoding='utf-8')
        self.assertIn('Not evaluable',script)
        self.assertIn("backgroundColor='#828282'",script)
