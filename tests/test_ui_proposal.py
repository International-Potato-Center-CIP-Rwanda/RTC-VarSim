"""Interface proposal checks (no climate pipeline or calculation changes).

Renders the home page with a small synthetic catalogue, so these tests do not need the
private data/ files. They check text and wiring only, not scientific validity.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_app.settings')
import django
django.setup()
from django.test import Client

SOURCE = Path(__file__).resolve().parent.parent
TOLERANCE_NOTE = ('Variety tolerances are provided for information only and are not used in the '
                  'current similarity calculation.')


def record(number, crop, name, late_blight, wilt):
    """Construct a synthetic variety record for catalogue or interface tests."""
    return {'id': f'{crop}-{number}', 'crop': crop, 'name': name, 'observation_count': 2, 'attribution': 'Test',
            'category_weights': {'climate': .4, 'soil': .35, 'crop_rotation': .25},
            'temperature_range': [16, 34], 'rainfall_range': [450, 1250], 'rainfall_period': None,
            'ph_range': [5.5, 7.0], 'cycle_days': [100, 120], 'late_blight': late_blight,
            'bacterial_wilt': wilt, 'notes': '', 'is_unspecified': False,
            'source': {'sheet': 'Sheet1', 'range': f'A{number}:P{number}'}}


CATALOGUE = {'source_file': 'synthetic.xlsx', 'records': [
    record(2, 'potato', 'Shangi', 'Moderately susceptible', None),
    record(54, 'sweetpotato', 'Kabode', None, ''),
]}


class InterfaceProposalTests(unittest.TestCase):
    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        (base/'assets').mkdir()
        shutil.copy(SOURCE/'assets/app.js', base/'assets/app.js')
        layer = dict(url='/x.png', bounds=[[-2.9, 28.8], [-1.0, 30.9]], title='T', source='CHELSA · 1981–2010',
                     legend='T', minimum=0, maximum=1, colors=['#000', '#fff'], categories=[])
        (base/'assets/rwanda_layers.json').write_text(json.dumps({k: layer for k in
                                                                  ('temperature', 'rainfall', 'texture', 'ph', 'slope', 'elevation')}))
        self.patches = [patch('platform_app.views.configuration', return_value={'layers': []}),
                        patch('platform_app.views.catalogue', return_value=CATALOGUE),
                        patch('platform_app.views.settings.BASE_DIR', base)]
        for p in self.patches: p.start()

    def tearDown(self):
        """Release the temporary resources created by this test."""
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def page(self, **query):
        """Request the test interface with the supplied query parameters."""
        response = Client().get('/', query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_tolerance_warning_is_always_visible(self):
        """Verify that tolerance warning is always visible."""
        for query in ({}, {'crop': 'sweetpotato', 'variety': 'sweetpotato-54'}):
            html = self.page(**query)
            self.assertIn(TOLERANCE_NOTE, html)
            self.assertLess(html.index('id="tolerance-note"'), html.index('<details>'))  # outside the collapsed notes

    def test_resistances_shown_in_variety_card(self):
        """Verify that resistances shown in variety card."""
        html = self.page()
        card = html[html.index('class="traits"'):html.index('id="tolerance-note"')]
        self.assertIn('Late blight</small>Moderately susceptible', card)
        self.assertIn('Bacterial wilt</small>Not reported', card)            # None
        kabode = self.page(crop='sweetpotato', variety='sweetpotato-54')
        card = kabode[kabode.index('class="traits"'):kabode.index('id="tolerance-note"')]
        self.assertIn('Late blight</small>Not reported', card)                # None
        self.assertIn('Bacterial wilt</small>Not reported', card)             # empty string

    def test_unavailable_variables_are_labelled(self):
        """Verify that unavailable variables are labelled."""
        html = self.page()
        self.assertEqual(html.count('<small class="unavailable">not available</small>'), 2)

    def test_no_parameter_preset_and_form_stays_empty(self):
        """Parameters stay manual until values are justified (no preset, no pre-filled value)."""
        html = self.page()
        self.assertNotIn('preset', html.lower())
        for field in ('weight-temperature', 'coefficient-temperature', 'weight-rainfall', 'coefficient-rainfall',
                      'weight-ph', 'coefficient-ph', 'weight-elevation', 'coefficient-elevation', 'weight-slope', 'coefficient-slope'):
            start = html.index(f'id="{field}"')
            tag = html[html.rindex('<input', 0, start):html.index('>', start)]
            self.assertNotIn('value=', tag)

    def test_period_badge_and_coverage_note(self):
        """Verify that period badge and coverage note."""
        html = self.page()
        self.assertIn('CHELSA · 1981–2010', html)
        self.assertIn('dashed outline = pilot data extent', html)

    def test_outline_is_described_as_raster_extent_not_border(self):
        """Verify that outline is described as raster extent not border."""
        script = (SOURCE/'assets/app.js').read_text(encoding='utf-8')
        self.assertNotIn('PRESET', script)
        self.assertIn('Pilot data extent: raster bounds', script)
        self.assertIn('Not the Rwanda border and not a map of available pixels', script)


if __name__ == '__main__':
    unittest.main()
