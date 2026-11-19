"""Compose an effective catalogue in memory; never edit the tolerance catalogue.

Public potato references and local-only internal references are separate files.
Only explicitly reviewed potato matches are applied automatically; each
accepted synonym keeps its guide-page provenance.
"""
import copy
import json
import math
from collections import Counter
from pathlib import Path

TOLERANCE_SOURCE = 'tolerance catalogue, not independently verified'
UNAVAILABLE_RANGES = 'Climate and soil ranges not yet available for this variety'
PUBLIC_REFERENCE = 'rwanda_potato_guide_2025.json'
INTERNAL_REFERENCE = 'rab_sweetpotato_2018_internal.json'


def _source(guide, page):
    """Format the public guide title, year and page used as field-level provenance."""
    return f"Rwanda Potato Variety Description Guide 2025, p. {page}"


def _inferred_spvd(record):
    """Interpret the tolerance workbook notes for SPVD display, before any reviewed reference override."""
    notes = (record.get('notes') or '').lower()
    if 'high virus resistance' in notes:
        return 'High virus resistance noted'
    if 'strong resistance' in notes:
        return 'Strong resistance noted'
    if 'spvd' in notes or 'sweetpotato virus disease' in notes:
        return 'Resistance/tolerance noted'
    return None


def _complete_ranges(record):
    """Return whether temperature, annual rainfall and soil pH all have usable numerical bounds."""
    for field in ('temperature_range', 'rainfall_range', 'ph_range'):
        values = record.get(field)
        if not isinstance(values, (list, tuple)) or len(values) != 2:
            return False
        try:
            low, high = map(float, values)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(low + high) or low >= high:
            return False
    return True


def load_catalogue(base, tolerance=None):
    """Compose an effective catalogue in memory from tolerance data, the public Rwanda guide and an optional authorized internal RAB overlay; preserve previous values and never rewrite source JSON."""
    base = Path(base)
    if tolerance is None:
        tolerance = json.loads((base / 'data/catalogue.json').read_text(encoding='utf-8'))
    result = copy.deepcopy(tolerance)
    records = result['records']
    for record in records:
        record['previous_values'] = {}
        record['field_sources'] = {field: TOLERANCE_SOURCE for field in (
            'temperature_range', 'rainfall_range', 'ph_range', 'cycle_days',
            'resistance_LB', 'resistance_BW', 'resistance_SPVD',
            'resistance_Alternaria', 'resistance_weevils')}
        record['record_source'] = tolerance.get('source_file', 'Tolerance catalogue')
        record['resistance_values'] = {
            'LB': record.get('late_blight'), 'BW': record.get('bacterial_wilt'),
            'SPVD': _inferred_spvd(record), 'Alternaria': None, 'weevils': None,
        }
        record['reference_only'] = False

    public_path = base / 'data/reference' / PUBLIC_REFERENCE
    if public_path.is_file():
        guide = json.loads(public_path.read_text(encoding='utf-8'))
        for reference in guide['records']:
            aliases = {name.casefold() for name in reference['approved_catalogue_aliases']}
            record = next((r for r in records if r.get('crop') == 'potato' and r['name'].casefold() in aliases), None)
            if record is None:
                record = {
                    'id': 'rwanda-potato-' + reference['name'].lower(),
                    'name': reference['name'], 'crop': 'potato', 'is_unspecified': False,
                    'temperature_range': [None, None], 'rainfall_range': [None, None],
                    'ph_range': [None, None], 'cycle_days': None,
                    'observation_count': None, 'notes': '', 'previous_values': {},
                    'field_sources': {field: 'Not available in the guide' for field in (
                        'temperature_range', 'rainfall_range', 'ph_range')},
                    'resistance_values': {}, 'reference_only': True,
                    'record_source': guide['source']['title'] + ' (2025)',
                    'source': {'sheet': 'Guide', 'range': 'p. ' + str(reference['page'])},
                    'attribution': guide['source']['citation'],
                }
                records.append(record)
            else:
                record['previous_values']['cycle_days'] = copy.deepcopy(record.get('cycle_days'))
                record['previous_values']['resistance_LB'] = record.get('late_blight')
                record['previous_values']['resistance_BW'] = record.get('bacterial_wilt')
            record['cycle_days'] = copy.deepcopy(reference['cycle_days'])
            record['field_sources']['cycle_days'] = _source(guide, reference['field_pages']['cycle_days'])
            record['official_name'] = reference['name']
            if record['name'].casefold() != reference['name'].casefold():
                record['synonym_source'] = _source(guide, reference.get('synonym_source_page',reference['page']))
            record['guide_reference'] = copy.deepcopy(reference)
            record['guide_source'] = _source(guide, reference['page'])
            for disease, details in reference['resistances'].items():
                record['resistance_values'][disease] = details['label']
                record['field_sources']['resistance_' + disease] = _source(guide, details['page'])
            record['resistance_values']['BW'] = reference['bacterial_wilt']['label']
            record['field_sources']['resistance_BW'] = _source(guide, reference['bacterial_wilt']['page'])
            record['late_blight'] = record['resistance_values'].get('LB')
            record['bacterial_wilt'] = record['resistance_values']['BW']

    # This internal file is deliberately absent from the clean Git copy.
    # Its absence never grants permission to embed its contents in code.
    internal_path = base / 'data/reference' / INTERNAL_REFERENCE
    if internal_path.is_file():
        internal = json.loads(internal_path.read_text(encoding='utf-8'))
        for reference in internal['records']:
            record = next((r for r in records if r.get('crop') == reference['crop']
                           and r['name'].strip().casefold() == reference['name'].strip().casefold()), None)
            if record is None:
                continue
            source = internal['source']['label']
            record['previous_values']['cycle_days'] = copy.deepcopy(record.get('cycle_days'))
            record['cycle_days'] = copy.deepcopy(reference['cycle_days'])
            record['field_sources']['cycle_days'] = source
            for disease, label in reference['resistances'].items():
                record['previous_values']['resistance_' + disease] = record['resistance_values'].get(disease)
                record['resistance_values'][disease] = label
                record['field_sources']['resistance_' + disease] = source
            record['internal_reference_applied'] = True

    for record in records:
        record['has_ranges'] = _complete_ranges(record)
    result['counts'] = dict(Counter(record.get('crop','unknown') for record in records))
    return result
