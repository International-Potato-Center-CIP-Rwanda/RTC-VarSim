"""Reference-loader regression tests using deliberately fabricated source records.

Names exercise approved aliases; cycles, resistance labels and page numbers below
are synthetic test values, not an extraction of any variety catalogue or guide.
No runtime dataset or PDF is distributed with these tests.
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_app.settings')
import django
django.setup()
from django.test import RequestFactory, override_settings
from platform_app import africa_demo
from platform_app.reference_catalogue import load_catalogue, UNAVAILABLE_RANGES
from platform_app.variety_screen import cycle_months, cycle_days_upper_bound

SOURCE = Path(__file__).resolve().parents[1]


class ReferenceCatalogueTests(unittest.TestCase):
    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base/'data/reference').mkdir(parents=True)
        (self.base/'assets').mkdir()
        synthetic = []
        for name, alias, cycle, page in [
            ('Challenger','Challenger',[101,109],4),
            ('Panamera','Panamera',[111,119],5),
            ('Kerekezo','UNICA',[121,129],6),
            ('Kazeneza','Wanjiku',[131,139],7),
            ('Ndamira','Shangi',[141,149],8),
            ('SyntheticOnly','SyntheticOnly',[151,159],9),
        ]:
            synthetic.append({
                'name':name, 'approved_catalogue_aliases':[alias],
                'cycle_days':cycle, 'page':page, 'synonym_source_page':page,
                'field_pages':{'cycle_days':page},
                'resistances':{
                    'LB':{'label':'Synthetic LB','page':page},
                    'PVY':{'label':'Synthetic PVY','page':page},
                    'PVX':{'label':None,'page':page},
                },
                'bacterial_wilt':{'label':'Synthetic BW','page':page},
                'potential_yield_t_ha':None, 'usage':[],
                'code':'SYNTHETIC', 'release_year':None,
                'adaptation_text':'Synthetic fixture, not agronomic information',
            })
        (self.base/'data/reference/rwanda_potato_guide_2025.json').write_text(
            json.dumps({'source':{'title':'Synthetic reference fixture',
                                  'citation':'Fabricated test data, not a source publication'},
                        'records':synthetic}), encoding='utf-8')
        for name in ['africa-demo.js', 'africa-demo.css']:
            (self.base/'assets'/name).write_text('/* synthetic */')
        self.raw = {'source_file':'synthetic.xlsx', 'records':[
            self.record('Challenger', 'potato'), self.record('Panamera', 'potato'),
            self.record('UNICA', 'potato'), self.record('Kabode', 'sweetpotato'),
            self.record('Unrelated', 'potato'), self.record('Wanjiku', 'potato'), self.record('Shangi', 'potato'),
        ]}
        self.path = self.base/'data/catalogue.json'
        self.path.write_text(json.dumps(self.raw))
        self.before = self.path.read_bytes()

    def tearDown(self):
        """Release the temporary resources created by this test."""
        self.assertEqual(self.before, self.path.read_bytes())
        self.temp.cleanup()

    def record(self, name, crop):
        """Construct a synthetic variety record for catalogue or interface tests."""
        return {'id':name, 'name':name, 'crop':crop, 'temperature_range':[10,30],
                'rainfall_range':[400,1400], 'ph_range':[5,7], 'cycle_days':[80,100],
                'late_blight':'Synthetic previous LB', 'bacterial_wilt':'Synthetic previous BW',
                'source':{'sheet':'Synthetic','range':'A1:P1'}, 'notes':'', 'is_unspecified':False}

    def internal(self):
        """Write an isolated internal-reference fixture for reference precedence tests."""
        (self.base/'data/reference/rab_sweetpotato_2018_internal.json').write_text(json.dumps({
            'source':{'label':'Synthetic internal source'}, 'records':[{
                'name':'Kabode', 'crop':'sweetpotato', 'cycle_days':[130,160],
                'resistances':{'SPVD':'Synthetic moderate','Alternaria':'Synthetic moderate','weevils':'Synthetic moderate'},
            }]}))

    def test_synthetic_reference_matches_cycles_previous_values_and_new_entry(self):
        """Verify alias precedence and missing-range insertion with fabricated records."""
        effective = load_catalogue(self.base)
        by_name = {r['name']:r for r in effective['records']}
        self.assertEqual(len(effective['records']), len(self.raw['records'])+1)
        self.assertEqual(by_name['Challenger']['cycle_days'], [101,109])
        self.assertEqual(by_name['Panamera']['cycle_days'], [111,119])
        self.assertEqual(by_name['UNICA']['official_name'], 'Kerekezo')
        self.assertEqual(by_name['UNICA']['cycle_days'], [121,129])
        self.assertEqual(by_name['Wanjiku']['official_name'], 'Kazeneza')
        self.assertEqual(by_name['Wanjiku']['cycle_days'], [131,139])
        self.assertEqual(by_name['Shangi']['official_name'], 'Ndamira')
        self.assertEqual(by_name['Shangi']['cycle_days'], [141,149])
        self.assertEqual(by_name['Wanjiku']['synonym_source'], 'Rwanda Potato Variety Description Guide 2025, p. 7')
        self.assertEqual(by_name['Shangi']['synonym_source'], 'Rwanda Potato Variety Description Guide 2025, p. 8')
        self.assertEqual(by_name['UNICA']['previous_values']['cycle_days'], [80,100])
        self.assertEqual(by_name['Challenger']['resistance_values']['LB'], 'Synthetic LB')
        self.assertEqual(by_name['Challenger']['resistance_values']['PVY'], 'Synthetic PVY')
        self.assertIsNone(by_name['Challenger']['resistance_values']['PVX'])
        self.assertEqual(by_name['Unrelated']['cycle_days'], [80,100])
        self.assertEqual(by_name['Kabode']['cycle_days'], [80,100])
        new = [r for r in effective['records'] if r['reference_only']]
        self.assertEqual(len(new), 1)
        self.assertTrue(all(not r['has_ranges'] for r in new))
        self.assertTrue(all(r['temperature_range']==[None,None] for r in new))

    def test_internal_overlay_is_local_optional_and_has_field_provenance(self):
        """Verify that internal overlay is local optional and has field provenance."""
        self.internal()
        kabode = next(r for r in load_catalogue(self.base)['records'] if r['name']=='Kabode')
        self.assertEqual(kabode['cycle_days'], [130,160])
        self.assertEqual(kabode['previous_values']['cycle_days'], [80,100])
        self.assertEqual(kabode['resistance_values']['Alternaria'], 'Synthetic moderate')
        self.assertEqual(kabode['field_sources']['cycle_days'], 'Synthetic internal source')
        self.assertEqual(kabode['temperature_range'], [10,30])

    def test_unknown_ranges_never_trigger_raster_read_or_run_creation(self):
        """Verify that unknown ranges never trigger raster read or run creation."""
        factory = RequestFactory()
        with override_settings(BASE_DIR=self.base), patch.object(africa_demo,'dataset',side_effect=AssertionError('Must not evaluate')):
            for view, payload in [
                (africa_demo.screen_variety_temperature,{}),
                (africa_demo.screen_variety_summary,{}),
                (africa_demo.screen_variety_criterion,{'criterion':'annual_rainfall'}),
                (africa_demo.screen_variety_criterion,{'criterion':'soil_ph'}),
            ]:
                request=factory.post('/criteria/',data=json.dumps({'variety_id':'rwanda-potato-syntheticonly','planting_month':11,**payload}),content_type='application/json')
                response=view(request)
                self.assertEqual(response.status_code,200,response.content)
                self.assertEqual(json.loads(response.content),{'status':'not_evaluable','reason':UNAVAILABLE_RANGES})
        self.assertFalse((self.base/'runs').exists())

    def test_card_renders_field_sources_previous_value_and_missing_ranges(self):
        """Verify that card renders field sources previous value and missing ranges."""
        with override_settings(BASE_DIR=self.base):
            html=africa_demo.home(RequestFactory().get('/demo/',{'crop':'potato','variety':'Challenger'})).content.decode()
            self.assertIn('Previous value: 80–100 days',html)
            self.assertIn('Rwanda Potato Variety Description Guide 2025, p. 4',html)
            self.assertIn('tolerance catalogue, not independently verified',html)
            html=africa_demo.home(RequestFactory().get('/demo/',{'crop':'potato','variety':'rwanda-potato-syntheticonly'})).content.decode()
            self.assertIn(UNAVAILABLE_RANGES,html)
            self.assertIn('Not available in the guide',html)
            html=africa_demo.home(RequestFactory().get('/demo/',{'crop':'potato','variety':'Wanjiku'})).content.decode()
            self.assertIn('Rwanda guide name: Kazeneza',html)
            self.assertIn('Synonym source: Rwanda Potato Variety Description Guide 2025, p. 7',html)
            self.assertIn('Previous value: 80–100 days',html)

    def test_missing_public_reference_preserves_tolerance_inputs(self):
        """Keep tolerance records usable when no external public guide is installed."""
        (self.base/'data/reference/rwanda_potato_guide_2025.json').unlink()
        effective=load_catalogue(self.base)
        self.assertEqual(len(effective['records']),len(self.raw['records']))
        self.assertTrue(all(not r['reference_only'] for r in effective['records']))
        self.assertTrue(all(r['cycle_days']==[80,100] for r in effective['records']))
        self.assertTrue(all(r['temperature_range']==[10,30] for r in effective['records']))
        self.assertEqual(self.before,self.path.read_bytes())
