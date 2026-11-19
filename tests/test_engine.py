"""Synthetic regression checks for engine. Temporary fixtures do not require the private research datasets."""
import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_app.settings')
import django
django.setup()
from django.test import Client
from platform_app.engine import inspect_layers, static_similarity


class EngineTests(unittest.TestCase):
    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = []
        for key, values, coeff in [('temperature', [[20, 30], [20, -9999]], 10), ('rainfall', [[100, 150], [200, 100]], 50)]:
            path = self.root / (key + '.tif')
            self.write(path, values)
            self.layers.append({'id': key, 'path': str(path), 'weight': .5, 'normalization': coeff, 'confirmed': True})

    def tearDown(self):
        """Release the temporary resources created by this test."""
        self.temp.cleanup()

    def write(self, path, values, transform=None):
        """Write a synthetic raster fixture with the supplied values and grid."""
        with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=1, dtype='float32', crs='EPSG:4326', transform=transform or from_origin(29, -1, .1, .1), nodata=-9999) as dst:
            dst.write(np.array(values, dtype='float32'), 1)

    def test_scores_nodata_and_georeference(self):
        """Verify that scores nodata and georeference."""
        out = self.root / 'out.tif'
        stats = static_similarity(self.layers, 29.05, -1.05, out)
        with rasterio.open(out) as src:
            np.testing.assert_allclose(src.read(1), [[1, .5], [2/3, -9999]], rtol=1e-6)
            self.assertEqual(src.crs.to_epsg(), 4326)
            self.assertEqual(src.nodata, -9999)
        self.assertEqual(stats['valid_cells'], 3)

    def test_upstream_normalization_parity(self):
        """Verify that upstream normalization parity."""
        source = Path('upstream/utils.py').read_text(encoding='utf-8')
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef))
        func = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'perform_distance_normalization')
        func.decorator_list = []
        module = ast.Module(body=[func], type_ignores=[])
        namespace = {'np': np}
        exec(compile(ast.fix_missing_locations(module), 'upstream_normalization', 'exec'), namespace)
        distance = np.array([0, 1, 10, 100, np.nan])
        np.testing.assert_allclose(namespace[func.name](distance, 10), 10/(10+distance), equal_nan=True)

    def test_bad_weights(self):
        """Verify that bad weights."""
        self.layers[0]['weight'] = .8
        with self.assertRaisesRegex(ValueError, 'Weights'):
            static_similarity(self.layers, 29.05, -1.05, self.root/'out.tif')

    def test_grid_mismatch(self):
        """Verify that grid mismatch."""
        self.write(self.layers[1]['path'], [[1, 2], [3, 4]], from_origin(28, -1, .1, .1))
        self.assertFalse(inspect_layers(self.layers)[1]['ready'])
        with self.assertRaisesRegex(ValueError, 'grid'):
            static_similarity(self.layers, 29.05, -1.05, self.root/'out.tif')

    def test_reference_outside(self):
        """Verify that reference outside."""
        with self.assertRaisesRegex(ValueError, 'outside'):
            static_similarity(self.layers, 0, 0, self.root/'out.tif')

    def test_missing_reference(self):
        """Verify that missing reference."""
        with self.assertRaisesRegex(ValueError, 'missing'):
            static_similarity(self.layers, 29.15, -1.15, self.root/'out.tif')

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'data/catalogue.json').is_file(), 'Local integration check requires the private catalogue and data; never distributed')
    def test_ui_and_gate(self):
        """Verify that ui and gate."""
        client = Client()
        response = client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContainsText(response, 'Sweetpotato')
        self.assertEqual(client.post('/analyse/', {'variety': 'shangi', 'acknowledge': 'yes', 'longitude': 29.05, 'latitude': -1.05}).status_code, 400)
        self.assertEqual(Client(enforce_csrf_checks=True).post('/analyse/', {}).status_code, 403)

    def assertContainsText(self, response, text):
        """Assert that a response contains the expected interface text."""
        self.assertIn(text, response.content.decode())

    def test_download_and_provenance(self):
        """Verify that download and provenance."""
        with patch('platform_app.views.configuration', return_value={'layers': self.layers}), patch('platform_app.views.settings.BASE_DIR', self.root):
            response = Client().post('/analyse/', {'variety': 'shangi', 'acknowledge': 'yes', 'longitude': 29.05, 'latitude': -1.05})
            self.assertEqual(response.status_code, 200)
            self.assertGreater(len(b''.join(response.streaming_content)), 0)
            response.close()
            self.assertEqual(len(list((self.root/'runs').glob('*/metadata.json'))), 1)

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'data/catalogue.json').is_file(), 'Local integration check requires the private catalogue and data; never distributed')
    def test_catalogue_selection_and_rainfall_period(self):
        """Verify that catalogue selection and rainfall period."""
        response = Client().get('/', {'crop': 'sweetpotato', 'variety': 'sweetpotato-54'})
        self.assertEqual(response.status_code, 200)
        self.assertContainsText(response, 'id="variety-title">Kabode</strong>')
        self.assertContainsText(response, 'Rainfall · period unknown')
        self.assertContainsText(response, 'Sheet1!A54:P54')
        other = Client().get('/', {'crop': 'sweetpotato', 'variety': 'sweetpotato-65'})
        self.assertContainsText(other, 'not an identified variety')

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'data/catalogue.json').is_file(), 'Local integration check requires the private catalogue and data; never distributed')
    def test_catalogue_counts_and_source_integrity(self):
        """Verify that catalogue counts and source integrity."""
        import json
        from django.conf import settings
        cat = json.loads((settings.BASE_DIR/'data/catalogue.json').read_text(encoding='utf-8'))
        self.assertEqual(cat['counts'], {'potato': 45, 'sweetpotato': 20})
        self.assertEqual(len({v['id'] for v in cat['records']}), 65)
        for v in cat['records']:
            self.assertIsNone(v['rainfall_period'])
            self.assertAlmostEqual(sum(v['category_weights'].values()), 1)
        shangi = next(v for v in cat['records'] if v['name'] == 'Shangi')
        self.assertEqual(shangi['observation_count'], 14396)
        self.assertEqual(shangi['source']['range'], 'A39:P39')

    def test_site_sampling_values_missing_and_invalid_coordinates(self):
        """Verify that site sampling values missing and invalid coordinates."""
        layers=[dict(v,unit='test unit') for v in self.layers]
        # Harmonized pH already has physical units; provenance scale must not be applied again.
        ph=dict(layers[0],id='ph',scale=.1)
        with patch('platform_app.views.configuration',return_value={'layers':layers,'supplemental_layers':[ph]}):
            data=Client().get('/api/site/',{'longitude':29.05,'latitude':-1.05}).json()
            self.assertTrue(data['complete'])
            self.assertEqual([v['value'] for v in data['values']],[20,100,20])
            missing=Client().get('/api/site/',{'longitude':29.15,'latitude':-1.15}).json()
            self.assertFalse(missing['complete'])
            self.assertIsNone(missing['values'][0]['value'])
            outside=Client().get('/api/site/',{'longitude':0,'latitude':0}).json()
            self.assertTrue(all(v['value'] is None for v in outside['values']))
            for bad in ['nan','inf','abc','181']:
                self.assertEqual(Client().get('/api/site/',{'longitude':bad,'latitude':0}).status_code,400)


if __name__ == '__main__':
    unittest.main()
