"""Read-only Excel import. Run using bundled Python with openpyxl installed."""
import hashlib
import json
from pathlib import Path
import re
import sys
from collections import Counter
import openpyxl


def percentage(value):
    """Parse an explicit percentage or fraction and reject values with ambiguous scale."""
    if isinstance(value, str) and value.strip().endswith('%'):
        return float(value.strip().rstrip('%')) / 100
    if isinstance(value, (int, float)) and 0 <= value <= 1:
        return float(value)
    raise ValueError(f'Pourcentage ambigu : {value!r}')


def parse_range(value):
    """Parse an ordered numeric interval and reject unrecognized or reversed bounds."""
    m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:days)?\s*', str(value))
    if not m:
        raise ValueError(f'Intervalle non reconnu : {value!r}')
    low, high = map(float, m.groups())
    if low > high:
        raise ValueError('Bornes inversées')
    return [low, high]


def import_catalogue(source):
    """Read the authorized Sheet1 workbook without editing it; validate records and return JSON-ready catalogue data with provenance."""
    source = Path(source)
    workbook = openpyxl.load_workbook(source, data_only=True, read_only=True)
    sheet = workbook['Sheet1']
    headers = [cell.value for cell in next(sheet.iter_rows())]
    records = []
    seen = set()
    for number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
        if all(v is None for v in values):
            continue
        raw = dict(zip(headers, values))
        crop = {'Potato': 'potato', 'Sweetpotato': 'sweetpotato'}[raw['crop_name']]
        name = str(raw['variety_name']).strip()
        key = (crop, name.casefold())
        if key in seen:
            raise ValueError(f'Doublon culture/variété : {key}')
        seen.add(key)
        weights = dict(zip(['climate', 'soil', 'crop_rotation'], [percentage(raw[k]) for k in headers[4:7]]))
        if abs(sum(weights.values()) - 1) > 1e-8:
            raise ValueError(f'Somme des poids invalide ligne {number}')
        temperatures = [raw[headers[7]], raw[headers[8]]]
        rainfall = [raw[headers[9]], raw[headers[10]]]
        if temperatures[0] > temperatures[1] or rainfall[0] > rainfall[1]:
            raise ValueError(f'Bornes inversées ligne {number}')
        records.append({'id': f'{crop}-{number}', 'crop': crop, 'name': name,
            'observation_count': raw['observation_count'], 'attribution': raw['Name of Expert'],
            'category_weights': weights, 'temperature_range': temperatures,
            'rainfall_range': rainfall, 'rainfall_period': None,
            'ph_range': parse_range(raw[headers[11]]), 'cycle_days': parse_range(raw[headers[14]]),
            'late_blight': raw[headers[12]], 'bacterial_wilt': raw[headers[13]],
            'notes': raw[headers[15]], 'is_unspecified': name.casefold() == 'other',
            'validation_status': 'source_provided_not_independently_verified',
            'source': {'sheet': sheet.title, 'range': f'A{number}:P{number}'}, 'raw': raw})
    workbook.close()
    return {'source_file': source.name, 'source_path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'counts': dict(Counter(r['crop'] for r in records)), 'records': records,
        'notes': ['La période des précipitations est absente des en-têtes.',
                  'Les attributions sont transcrites du fichier ; elles ne constituent pas une vérification indépendante.',
                  'Other représente une catégorie non spécifiée, pas une variété identifiée.',
                  'Kenspot-4 et Vitamu sont liés dans les notes sources ; conservés séparément en attente de confirmation.',
                  'Les poids de catégories ne sont pas des poids individuels AFSA ni une matrice AHP.']}


if __name__ == '__main__':
    catalogue = import_catalogue(sys.argv[1])
    target = Path(__file__).parent / 'data' / 'catalogue.json'
    target.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'counts': catalogue['counts'], 'records': len(catalogue['records'])}))
