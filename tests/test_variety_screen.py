"""Synthetic regression checks for variety screen. Temporary fixtures do not require the private research datasets."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import rasterio
from django.test import RequestFactory, override_settings
from platform_app import africa_demo
from platform_app.africa_demo import screen_variety_temperature
from platform_app.variety_screen import (
    annual_rainfall_range_screen, combine_criteria, cycle_days_upper_bound, cycle_months, temperature_range_screen,
)
from platform_app.soil_ph import thickness_weighted_ph


class VarietyTemperatureScreenTests(unittest.TestCase):
    def test_annual_rainfall_sums_all_twelve_months_and_keeps_limits_inclusive(self):
        """Verify that annual rainfall sums all twelve months and keeps limits inclusive."""
        values=np.zeros((1,2,2,12),dtype='float32')
        values[0,0,1,:]=np.arange(1,13,dtype='float32')
        values[0,1,1,:]=1
        result=annual_rainfall_range_screen(values,12,78)
        np.testing.assert_array_equal(result,[[1,1]])
        values[0,1,1,0]=np.nan
        self.assertTrue(np.isnan(annual_rainfall_range_screen(values,12,78)[0,1]))

    def test_soil_ph_0_30_is_thickness_weighted_and_requires_all_depths(self):
        """Verify that soil ph 0 30 is thickness weighted and requires all depths."""
        result=thickness_weighted_ph(
            np.array([[5.0, 5.0]],dtype='float32'),
            np.array([[6.0, np.nan]],dtype='float32'),
            np.array([[7.0, 7.0]],dtype='float32'),
        )
        np.testing.assert_allclose(result[0,0],(5*5+10*6+15*7)/30)
        self.assertTrue(np.isnan(result[0,1]))

    def test_share_uses_selected_month_means_and_inclusive_limits(self):
        """Verify that share uses selected month means and inclusive limits."""
        values=np.zeros((1,2,2,12),dtype='float32')
        values[0,0,0,:3]=[16,25,34]
        values[0,1,0,:3]=[15.9,25,34.1]
        result=temperature_range_screen(values,[1,2,3],16,34)
        np.testing.assert_allclose(result,[[1,1/3]])

    def test_months_wrap_and_missing_month_masks_cell(self):
        """Verify that months wrap and missing month masks cell."""
        values=np.zeros((1,2,2,12),dtype='float32')
        values[0,0,0,[11,0]]=[20,30]
        values[0,1,0,0]=np.nan
        result=temperature_range_screen(values,[12,1],16,34)
        np.testing.assert_allclose(result[0,0],1)
        self.assertTrue(np.isnan(result[0,1]))

    def test_november_planting_cycle_wraps_across_december_and_january(self):
        """Verify that november planting cycle wraps across december and january."""
        self.assertEqual(cycle_months(11,100),[11,12,1,2])

    def test_variety_without_cycle_duration_is_not_evaluable(self):
        """Verify that variety without cycle duration is not evaluable."""
        self.assertIsNone(cycle_days_upper_bound({'cycle_days':[100,None]}))
        self.assertIsNone(cycle_days_upper_bound({'cycle_days':None}))

    def test_temperature_endpoint_returns_not_evaluable_for_missing_cycle(self):
        """Verify that temperature endpoint returns not evaluable for missing cycle."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            data=Path(directory)/'data';data.mkdir()
            (data/'catalogue.json').write_text(json.dumps({'records':[{'id':'v1','name':'No cycle','cycle_days':[None,None]}]}),encoding='utf-8')
            with override_settings(BASE_DIR=Path(directory)):
                request=RequestFactory().post('/api/demo/variety-temperature/',data=json.dumps({'variety_id':'v1','planting_month':11}),content_type='application/json')
                response=screen_variety_temperature(request)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(json.loads(response.content)['status'],'not_evaluable')

    def test_rainfall_and_ph_criterion_maps_have_three_classes_and_land_only_counts(self):
        """Verify that rainfall and ph criterion maps have three classes and land only counts."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            base=Path(directory);(base/'data').mkdir();(base/'runs').mkdir()
            (base/'data'/'catalogue.json').write_text(json.dumps({'records':[{
                'id':'v1','name':'Test variety','rainfall_range':[100,150],'ph_range':[5.5,7.0]
            }]}),encoding='utf-8')
            climate=np.zeros((2,3,2,12),dtype='float32')
            climate[:,:,1,:]=10
            climate[0,0,1,:]=5       # annual 60: below range
            climate[1,0,1,:]=20      # annual 240: above range
            climate[1,1,1,0]=np.nan  # missing annual total: not evaluable
            land=np.array([[True,True,False],[True,True,False]])
            ph=np.array([[4.5,6.0,np.nan],[8.0,np.nan,np.nan]],dtype='float32')
            affine=rasterio.Affine(1,0,-3,0,-1,2)
            request_factory=RequestFactory()
            with override_settings(BASE_DIR=base), \
                 patch.object(africa_demo,'dataset',return_value=(climate,affine,None,0,0,1,base)), \
                 patch.object(africa_demo,'africa_land_mask',return_value=land), \
                 patch.object(africa_demo,'africa_ph_display',return_value=ph):
                for criterion in ('annual_rainfall','soil_ph'):
                    request=request_factory.post('/api/demo/variety-criterion/',data=json.dumps({'variety_id':'v1','criterion':criterion,'planting_month':11}),content_type='application/json')
                    response=africa_demo.screen_variety_criterion(request)
                    self.assertEqual(response.status_code,200,response.content)
                    result=json.loads(response.content)
                    metadata=result['metadata']
                    self.assertEqual(metadata['valid_cells'],3)
                    self.assertEqual(metadata['cells_below_range'],1)
                    self.assertEqual(metadata['cells_in_range'],1)
                    self.assertEqual(metadata['cells_above_range'],1)
                    self.assertAlmostEqual(metadata['share_in_range_pct'],100/3)
                    self.assertIn('Evaluable African land cells only',metadata['coverage'])
                    with rasterio.open(base/'runs'/result['id']/'criterion-range.tif') as raster:
                        np.testing.assert_array_equal(raster.read(1),[[0,1,255],[2,255,255]])
                    png=(base/'runs'/result['id']/'criterion-range.png').read_bytes()
                    self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_combined_count_keeps_not_evaluable_separate(self):
        """Verify that combined count keeps not evaluable separate."""
        result=combine_criteria([np.array([[1,1,np.nan]]),np.array([[1,0,1]]),np.array([[0,1,1]])])
        np.testing.assert_array_equal(result,[[2,2,4]])

    def test_summary_click_returns_annual_rainfall_range_ph_and_coordinates(self):
        """Verify that summary click returns annual rainfall range ph and coordinates."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            base=Path(directory);run=base/'runs'/'run1';run.mkdir(parents=True)
            (base/'data').mkdir()
            (base/'data'/'catalogue.json').write_text(json.dumps({'records':[{
                'id':'v1','name':'Test variety','temperature_range':[16,34],
                'rainfall_range':[100,500],'ph_range':[5.5,7.0]
            }]}),encoding='utf-8')
            with rasterio.open(run/'summary.tif','w',driver='GTiff',height=1,width=1,count=1,dtype='uint8',crs='EPSG:4326',transform=rasterio.Affine(1,0,0,0,-1,1),nodata=255) as dst:
                dst.write(np.array([[3]],dtype='uint8'),1)
                dst.update_tags(variety_id='v1',variety_name='Test variety',planting_month=11,cycle_days=120,months='[11,12,1,2]')
            climate=np.zeros((1,1,2,12),dtype='float32')
            climate[0,0,0,[10,11,0,1]]=[20,15,30,35]
            climate[0,0,1,[10,11,0,1]]=[20,30,40,50]
            climate[0,0,1,2]=60  # Outside the November–February crop cycle.
            affine=rasterio.Affine(1,0,0.5,0,-1,0.5)
            request=RequestFactory().get('/summary/',{'longitude':0.5,'latitude':0.5})
            with override_settings(BASE_DIR=base),patch.object(africa_demo,'dataset',return_value=(climate,affine,None,0,0,1,base)),patch.object(africa_demo,'africa_ph_display',return_value=np.array([[6.2]],dtype='float32')):
                response=africa_demo.sample_variety_summary(request,'run1')
        self.assertEqual(response.status_code,200,response.content)
        result=json.loads(response.content)
        self.assertEqual(result['criteria']['temperature']['monthly_values'][0]['value_c'],20)
        self.assertEqual(result['criteria']['temperature']['months_in_range'],2)
        self.assertEqual(result['criteria']['temperature']['within_range'],False)
        self.assertEqual(result['criteria']['rainfall']['annual_total_mm'],200)
        self.assertTrue(result['criteria']['rainfall']['within_range'])
        self.assertEqual(result['criteria']['rainfall']['cycle_total_mm'],140)
        self.assertEqual([x['month'] for x in result['criteria']['rainfall']['cycle_monthly_values']],[11,12,1,2])
        self.assertIn('dry-season gaps',result['criteria']['rainfall']['cycle_note'])
        self.assertAlmostEqual(result['criteria']['soil_ph']['value'],6.2,places=5)
        self.assertIn('0–30 cm',result['criteria']['soil_ph']['source'])
        self.assertEqual(result['longitude'],0.5)
        self.assertEqual(result['latitude'],0.5)

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'data/catalogue.json').is_file(), 'Local integration check requires the private catalogue and data; never distributed')
    def test_sweetpotato_variety_card_uses_crop_specific_disease_labels(self):
        """Verify that sweetpotato variety card uses crop specific disease labels."""
        request=RequestFactory().get('/demo/')
        with override_settings(BASE_DIR=Path(__file__).resolve().parents[1]):
            response=africa_demo.home(request)
        html=response.content.decode('utf-8')
        self.assertIn('SPVD',html)
        self.assertIn('Alternaria',html)
        self.assertIn('Sweetpotato weevils',html)
        self.assertNotIn('<small>Late blight</small>',html)

    def test_invalid_interval_months_or_shape_are_rejected(self):
        """Verify that invalid interval months or shape are rejected."""
        values=np.zeros((1,1,2,12))
        for args in [([1,1],16,34),([0],16,34),([1],34,16),([True],16,34)]:
            with self.subTest(args=args),self.assertRaises(ValueError):
                temperature_range_screen(values,*args)
        with self.assertRaises(ValueError):
            temperature_range_screen(np.zeros((1,12)),[1],16,34)


if __name__=='__main__': unittest.main()
