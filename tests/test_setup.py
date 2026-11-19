"""Synthetic regression checks for setup. Temporary fixtures do not require the private research datasets."""
import unittest
from platform_app.setup import validate_setup

class SetupTests(unittest.TestCase):
    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        self.cfg={'layers':[{'id':'temperature','unit':'°C'},{'id':'rainfall','unit':'mm/year'}]}
        self.cat={'records':[{'id':'p1','name':'Shangi','crop':'potato','source':{'range':'A39:P39'}}]}
        self.payload={'variety':'p1','rationale':'Synthetic settings for validation tests only.',
                      'parameters':[{'id':'temperature','weight':.5,'normalization':10},{'id':'rainfall','weight':.5,'normalization':50}]}

    def test_draft_is_explicitly_unvalidated(self):
        """Verify that draft is explicitly unvalidated."""
        result=validate_setup(self.payload,self.cfg,self.cat)
        self.assertEqual(result['status'],'research_draft_not_validated')
        self.assertIsNone(result['reference_site'])
        self.assertEqual(result['parameters'][1]['unit'],'mm/year')

    def test_invalid_sum_and_normalization(self):
        """Verify that invalid sum and normalization."""
        self.payload['parameters'][0]['weight']=.4
        with self.assertRaisesRegex(ValueError,'sum'):validate_setup(self.payload,self.cfg,self.cat)
        self.payload['parameters'][0]['weight']=.5
        for invalid in [0,-1,float('nan'),float('inf')]:
            self.payload['parameters'][0]['normalization']=invalid
            with self.assertRaises(ValueError):validate_setup(self.payload,self.cfg,self.cat)

    def test_texture_duplicate_and_missing_rationale(self):
        """Verify that texture duplicate and missing rationale."""
        self.payload['parameters'][0]['id']='texture'
        with self.assertRaises(ValueError):validate_setup(self.payload,self.cfg,self.cat)
        self.payload['parameters'][0]['id']='rainfall'
        with self.assertRaises(ValueError):validate_setup(self.payload,self.cfg,self.cat)
        self.payload['parameters'][0]['id']='temperature';self.payload['rationale']=''
        with self.assertRaises(ValueError):validate_setup(self.payload,self.cfg,self.cat)

    def test_http_validation_and_attachment(self):
        """Verify that http validation and attachment."""
        from django.test import Client
        from unittest.mock import patch
        with patch('platform_app.views.configuration',return_value=self.cfg),patch('platform_app.views.catalogue',return_value=self.cat):
            response=Client().post('/api/setup/',self.payload,content_type='application/json')
            self.assertEqual(response.status_code,200)
            self.assertIn('attachment',response['Content-Disposition'])
            self.assertEqual(Client().post('/api/setup/',[],content_type='application/json').status_code,400)

    def test_roundtrip_preserves_site_and_parameters(self):
        """Verify that roundtrip preserves site and parameters."""
        self.payload['name']='Shangi site comparison'
        self.payload['reference_site']={'longitude':29.9,'latitude':-1.84}
        first=validate_setup(self.payload,self.cfg,self.cat)
        second=validate_setup(first,self.cfg,self.cat)
        for key in ['name','reference_site','variety','parameters','rationale','sources']:
            self.assertEqual(first[key],second[key])
        self.assertEqual(second['warnings'],[])

    def test_bad_reference_schema_and_stale_sources(self):
        """Verify that bad reference schema and stale sources."""
        self.payload['reference_site']={'longitude':float('nan'),'latitude':-1}
        with self.assertRaises(ValueError):validate_setup(self.payload,self.cfg,self.cat)
        self.payload['reference_site']=None
        self.payload['schema_version']=99
        with self.assertRaises(ValueError):validate_setup(self.payload,self.cfg,self.cat)
        self.payload['schema_version']=1
        self.payload['sources']=[{'id':'temperature','recorded_sha256':'changed'}]
        result=validate_setup(self.payload,self.cfg,self.cat)
        self.assertEqual(len(result['warnings']),2)

    def test_import_rejects_catalogue_mismatch(self):
        """Verify that import rejects catalogue mismatch."""
        self.payload['variety']={'id':'p1','name':'Different variety'}
        with self.assertRaisesRegex(ValueError,'catalogue'):validate_setup(self.payload,self.cfg,self.cat)
