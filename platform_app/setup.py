"""Validate explicit research settings; no defaults are promoted to evidence."""
import math
from datetime import datetime, timezone
from pathlib import Path

CONTINUOUS={'temperature','rainfall','ph','elevation','slope'}


def validate_setup(payload, cfg, catalogue):
    """Validate a portable pilot analysis draft against the current configuration and catalogue; reject stale, incomplete or inconsistent inputs."""
    if not isinstance(payload,dict):
        raise ValueError('An analysis setup object is required.')
    if payload.get('schema_version',2) not in (1,2):
        raise ValueError('This setup file version is not supported.')
    if payload.get('method','static_environmental_similarity')!='static_environmental_similarity':
        raise ValueError('Only static environmental similarity setups are supported.')
    requested=payload.get('variety')
    if isinstance(requested,dict):requested=requested.get('id')
    variety=next((v for v in catalogue['records'] if v['id']==requested),None)
    if variety is None or variety.get('is_unspecified'):
        raise ValueError('Choose an identified variety from the catalogue.')
    rationale=payload.get('rationale','')
    if not isinstance(rationale,str) or len(rationale.strip())<10 or len(rationale)>5000:
        raise ValueError('Describe the source or rationale for these settings (10–5000 characters).')
    supplied=payload.get('parameters')
    if not isinstance(supplied,list) or not supplied:
        raise ValueError('Enter at least one variable and a positive weight.')
    rows=[];seen=set()
    available={l['id']:l for l in cfg['layers']+cfg.get('supplemental_layers',[])}
    for row in supplied:
        if not isinstance(row,dict):raise ValueError('Invalid parameter row.')
        key=row.get('id')
        if not isinstance(key,str) or key not in CONTINUOUS or key in seen or key not in available:
            raise ValueError('Variables must be available, continuous and unique. Texture requires a categorical distance method.')
        seen.add(key)
        try:
            weight=float(row.get('weight'))
            coefficient=float(row.get('normalization'))
        except (TypeError,ValueError):
            raise ValueError('Enter numeric weights and normalization coefficients.')
        if not math.isfinite(weight) or not 0<weight<=1:
            raise ValueError('Each included weight must be greater than 0 and at most 1.')
        if not math.isfinite(coefficient) or coefficient<=0:
            raise ValueError('Normalization coefficients must be finite and greater than 0.')
        rows.append({'id':key,'weight':weight,'normalization':coefficient,'unit':available[key]['unit']})
    if not math.isclose(sum(r['weight'] for r in rows),1,abs_tol=1e-6):
        raise ValueError('Included weights must sum to 1.')
    reference=payload.get('reference_site')
    if reference is not None:
        if not isinstance(reference,dict):raise ValueError('Invalid reference site.')
        try:
            longitude=float(reference['longitude']);latitude=float(reference['latitude'])
        except (KeyError,TypeError,ValueError):raise ValueError('Both reference coordinates are required.')
        if not math.isfinite(longitude) or not math.isfinite(latitude) or not -180<=longitude<=180 or not -90<=latitude<=90:
            raise ValueError('Reference coordinates must be valid WGS84 longitude/latitude.')
        reference={'longitude':longitude,'latitude':latitude,'crs':'EPSG:4326','status':'user_selected_not_validated'}
    name=payload.get('name','Untitled analysis')
    if not isinstance(name,str) or not 1<=len(name.strip())<=120:
        raise ValueError('Use an analysis name between 1 and 120 characters.')
    sources=[{'id':r['id'],'file':Path(available[r['id']].get('path','')).name,
              'recorded_sha256':available[r['id']].get('sha256',available[r['id']].get('output_sha256'))} for r in rows]
    warnings=[]
    if payload.get('schema_version')==1:warnings.append('Legacy draft loaded; a reference site may need to be added.')
    if payload.get('sources') is not None and payload['sources']!=sources:
        warnings.append('Dataset provenance differs from this installation. Review the layers before computing.')
    if isinstance(payload.get('variety'),dict) and payload['variety'].get('name')!=variety['name']:
        raise ValueError('The variety identifier no longer matches the catalogue name.')
    return {'schema_version':2,'name':name.strip(),'exported_at':datetime.now(timezone.utc).isoformat(),
            'status':'research_draft_not_validated','variety':{'id':variety['id'],'name':variety['name'],'crop':variety['crop'],'source':variety['source']},
            'method':'static_environmental_similarity','parameters':rows,'rationale':rationale.strip(),
            'reference_site':reference,'sources':sources,'warnings':warnings,'rainfall_tolerance_period':'unconfirmed',
            'limitations':['No calculation has been run.','Variety tolerance ranges are not applied by this static similarity method.',
                          'Monthly climate and seasonal alignment are not included.','Texture and crop rotation are not represented by these continuous-variable settings.',
                          'User-entered parameters are not independently validated.']}
