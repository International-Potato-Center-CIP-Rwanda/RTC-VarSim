"""Serve the Rwanda pilot and its setup, computation and inspection APIs. Local pilot inputs are required; missing data are not imputed."""
import json
import uuid
import hashlib
import base64
import numpy as np
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, JsonResponse
import math
import rasterio
from rasterio.warp import transform
from django.shortcuts import render
from django.views.decorators.http import require_POST
from .engine import inspect_layers, static_similarity
from .setup import validate_setup
from .computation import compute
from .result_tools import filter_cells, preview_png


def result_view(request, run_id):
    """Inspect an existing pilot score raster or return a filtered preview; validate percentages and WGS84 coordinates."""
    path = settings.BASE_DIR / 'runs' / str(run_id) / 'similarity.tif'
    if not path.is_file():
        return JsonResponse({'error':'Result not found.'},status=404)
    try:
        mode=request.GET.get('mode','none')
        percent=float(request.GET.get('percent','100'))
        with rasterio.open(path) as src:
            values=src.read(1,masked=True).filled(np.nan)
            keep=filter_cells(values,mode,percent)
            result={'mode':mode,'percent':percent,'visible_cells':int(keep.sum()),'valid_cells':int(np.isfinite(values).sum()),
                    'tie_policy':'Stable row-major ordering; tied scores may be split.', 'display_only':True}
            if 'latitude' in request.GET or 'longitude' in request.GET:
                lat=float(request.GET['latitude']);lon=float(request.GET['longitude'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
                    raise ValueError('Valid WGS84 coordinates are required.')
                xs,ys=transform('EPSG:4326',src.crs,[lon],[lat])
                row,col=src.index(xs[0],ys[0])
                result.update(score=None, status='outside_extent')
                if 0<=row<src.height and 0<=col<src.width:
                    if not np.isfinite(values[row,col]):result['status']='no_data'
                    else:result.update(score=float(values[row,col]),status='visible' if keep[row,col] else 'filtered_out')
            else:
                result['image']='data:image/png;base64,'+base64.b64encode(preview_png(src,np.where(keep,values,np.nan))).decode('ascii')
        return JsonResponse(result,json_dumps_params={'allow_nan':False})
    except (ValueError,KeyError):
        return JsonResponse({'error':'Invalid filter or coordinates. Percentages must be between 0 and 100.'},status=400)


@require_POST
def compute_api(request):
    """Validate the pilot request, compute a run and return its result URLs; convert input and raster failures to API errors."""
    try:
        payload = json.loads(request.body)
        run_id = uuid.uuid4()
        directory = settings.BASE_DIR / 'runs' / str(run_id)
        result = compute(payload, configuration(), catalogue(), directory)
        result['result_url'] = f'/api/results/{run_id}/'
        result['files'] = {name: f'/runs/{run_id}/{name}' for name in ('similarity.png', 'similarity.tif', 'metadata.json')}
        return JsonResponse(result)
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except (OSError, rasterio.errors.RasterioError):
        return JsonResponse({'error': 'A local raster could not be read or the result could not be saved.'}, status=500)


def run_file(request, run_id, filename):
    """Serve an allowlisted pilot result file, returning not found for unknown or missing files."""
    from django.http import Http404
    if filename not in ('similarity.png', 'similarity.tif', 'metadata.json'):
        raise Http404
    path = settings.BASE_DIR / 'runs' / str(run_id) / filename
    if not path.is_file():
        raise Http404
    return FileResponse(path.open('rb'), as_attachment=filename != 'similarity.png', filename=filename)


def configuration():
    """Read the local Rwanda pilot configuration; no configuration is inferred when the file is missing."""
    return json.loads((settings.BASE_DIR / 'data' / 'pilot.json').read_text(encoding='utf-8'))


def catalogue():
    """Load the effective variety catalogue with reviewed reference precedence."""
    from .reference_catalogue import load_catalogue
    return load_catalogue(settings.BASE_DIR)


@require_POST
def export_setup(request):
    """Validate and return an analysis-setup draft as a JSON attachment without running an analysis."""
    try:
        setup=validate_setup(json.loads(request.body),configuration(),catalogue())
    except (ValueError,UnicodeDecodeError) as exc:
        return JsonResponse({'error':str(exc)},status=400)
    response=JsonResponse(setup,json_dumps_params={'indent':2,'ensure_ascii':False,'allow_nan':False})
    response['Content-Disposition']='attachment; filename="afsa-analysis-setup-draft.json"'
    return response


def sample_site(request):
    """Sample configured pilot rasters at validated WGS84 coordinates and report missing or out-of-extent values."""
    try:
        longitude=float(request.GET['longitude'])
        latitude=float(request.GET['latitude'])
        if not math.isfinite(longitude) or not math.isfinite(latitude) or not (-180<=longitude<=180 and -90<=latitude<=90):
            raise ValueError()
    except (ValueError,KeyError):
        return JsonResponse({'error':'Valid WGS84 coordinates are required.'},status=400)
    cfg=configuration()
    values=[]
    for layer in cfg['layers']+cfg.get('supplemental_layers',[]):
        value=None
        status='no_data'
        try:
            with rasterio.open(layer['path']) as src:
                x,y=transform('EPSG:4326',src.crs,[longitude],[latitude])
                row,col=src.index(x[0],y[0])
                if 0<=row<src.height and 0<=col<src.width:
                    pixel=src.read(1,window=rasterio.windows.Window(col,row,1,1),masked=True)
                    if not pixel.mask.all() and math.isfinite(float(pixel[0,0])):
                        value=float(pixel[0,0])*float(layer.get('scale',1)) + float(layer.get('offset',0)) if layer in cfg['layers'] else float(pixel[0,0])
                        status='available'
        except (OSError,rasterio.errors.RasterioError):
            status='unavailable'
        values.append({'id':layer['id'],'value':value,'unit':layer['unit'],'status':status})
    return JsonResponse({'longitude':longitude,'latitude':latitude,'values':values,
                         'complete':all(v['status']=='available' for v in values)},json_dumps_params={'allow_nan':False})


def home(request, error=None, status=200):
    """Render the Rwanda pilot with local catalogue, configuration and available raster previews."""
    cfg = configuration()
    rows = inspect_layers(cfg['layers'])
    ready = bool(rows) and all(r['ready'] and r.get('confirmed') for r in rows)
    cat = catalogue()
    crop = request.GET.get('crop', 'potato')
    if crop not in ('potato', 'sweetpotato'):
        crop = 'potato'
    varieties = [v for v in cat['records'] if v['crop'] == crop]
    default = next((v for v in varieties if v['name'] == 'Shangi'), varieties[0])
    selected = next((v for v in varieties if v['id'] == request.GET.get('variety')), default)
    map_data = json.loads((settings.BASE_DIR / 'assets' / 'rwanda_layers.json').read_text(encoding='utf-8'))
    app_version = hashlib.sha256((settings.BASE_DIR / 'assets/app.js').read_bytes()).hexdigest()[:12]
    return render(request, 'index.html', {'app_version': app_version, 'cfg': cfg, 'rows': rows, 'ready': ready, 'error': error,
        'catalogue': cat, 'crop': crop, 'varieties': varieties, 'selected': selected, 'map_data': map_data}, status=status)


@require_POST
def analyse(request):
    """Handle the pilot analysis form and render either its validated result or an actionable input error."""
    cfg = configuration()
    try:
        if request.POST.get('variety') != 'shangi':
            raise ValueError('Only the Shangi pilot is configured for computation at this stage.')
        if request.POST.get('acknowledge') != 'yes':
            raise ValueError('Please acknowledge the experimental status of this analysis.')
        if not all(l.get('confirmed') for l in cfg['layers']):
            raise ValueError('Analysis weights and normalization coefficients still need to be defined.')
        run = settings.BASE_DIR / 'runs' / str(uuid.uuid4())
        result = static_similarity(cfg['layers'], float(request.POST['longitude']), float(request.POST['latitude']), run / 'similarity.tif')
        metadata = {'configuration': cfg, 'reference': {'longitude': request.POST['longitude'], 'latitude': request.POST['latitude']}, 'method': 'Static similarity only; not a validated Shangi suitability map', 'result': result}
        (run / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
        return FileResponse((run / 'similarity.tif').open('rb'), as_attachment=True, filename='similarite_statique_experimentale.tif')
    except (ValueError, KeyError, OSError) as exc:
        return home(request, str(exc), status=400)
