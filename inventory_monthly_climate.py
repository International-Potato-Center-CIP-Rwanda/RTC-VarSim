"""Audit CHELSA monthly source availability; does not download raster data."""
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = 'https://os.unil.cloud.switch.ch/chelsa02/'
NS = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}

def inventory():
    """List CHELSA monthly tas and pr objects for 1991-2020 and write their URLs, sizes and source identities locally."""
    records = []
    missing = {}
    for variable in ('tas', 'pr'):
        marker = ''
        found = set()
        while True:
            query = urllib.parse.urlencode({'prefix': f'chelsa/global/monthly/{variable}/', 'max-keys': 1000, 'marker': marker})
            with urllib.request.urlopen(BASE + '?' + query, timeout=30) as response:
                root = ET.fromstring(response.read())
            for item in root.findall('s:Contents', NS):
                key = item.findtext('s:Key', namespaces=NS)
                match = re.search(rf'CHELSA_{variable}_(\d{{2}})_(\d{{4}})_V\.2\.1\.tif$', key)
                if not match: continue
                month, year = map(int, match.groups())
                if not 1991 <= year <= 2020: continue
                if (year, month) in found: raise ValueError('Duplicate month')
                found.add((year, month))
                records.append(dict(variable=variable, year=year, month=month, url=BASE+key,
                                    bytes=int(item.findtext('s:Size', namespaces=NS)),
                                    etag=item.findtext('s:ETag', namespaces=NS)))
            if root.findtext('s:IsTruncated', namespaces=NS) == 'false': break
            next_marker = root.findtext('s:NextMarker', namespaces=NS)
            if not next_marker or next_marker == marker: raise ValueError('Invalid pagination')
            marker = next_marker
        missing[variable] = [f'{y}-{m:02d}' for y in range(1991, 2021) for m in range(1,13) if (y,m) not in found]
    result = dict(scope='Africa, including Madagascar and African islands; source files are global',
                  period='1991-2020', status='Catalogue audit only; raster content and completeness not validated',
                  missing=missing, files=records)
    output = Path(__file__).parent / 'data' / 'africa-1991-2020-inventory.json'
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(dict(files=len(records), missing=missing, global_bytes=sum(r['bytes'] for r in records))))

if __name__ == '__main__': inventory()
