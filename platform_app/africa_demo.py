"""Local demonstration: monthly climate similarity over a sampled African grid."""
import hashlib
import json
import math
import uuid
from functools import lru_cache
from pathlib import Path
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window
from rasterio.warp import reproject, Resampling
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from .monthly import analysis_months, monthly_similarity
from .reference_catalogue import load_catalogue, UNAVAILABLE_RANGES
from .result_tools import criterion_count_preview_png, preview_png, range_class_preview_png
from .variety_screen import calculation_profile, annual_rainfall_range_screen, combine_criteria, cycle_days_upper_bound, cycle_months, temperature_range_screen

@lru_cache(maxsize=1)
def dataset():
    """Load the sampled Africa monthly array and its display transform; derive the active job directory from plan, mask and inventory."""
    base=settings.BASE_DIR
    plan=json.loads((base/'data/africa-tiles.json').read_text())
    inventory=(base/'data/africa-1991-2020-inventory.json').read_text()
    mask=(base/'data/africa-extraction-mask.geojson').read_text()
    signature=hashlib.sha256((json.dumps(plan,sort_keys=True)+mask+inventory).encode()).hexdigest()[:16]
    with np.load(base/'data/demo-climate/monthly.npz') as z:
        values=z['values']; row=int(z['row']); col=int(z['col']); step=int(z['step'])
    affine=rasterio.Affine(*plan['transform'][:6])
    # The display cells cover step-sized blocks and their centres align with
    # the centres of the source pixels sampled at STEP//2.
    display_affine=affine*rasterio.Affine.translation(col+0.5,row+0.5)*rasterio.Affine.scale(step)
    return values,display_affine,plan,row,col,step,base/'data/africa-jobs'/signature

@lru_cache(maxsize=1)
def africa_land_mask():
    """Rasterize the Africa extraction polygons on the sampled display grid."""
    values,affine,_,_,_,_,_=dataset()
    geo=json.loads((settings.BASE_DIR/'data/africa-extraction-mask.geojson').read_text(encoding='utf-8'))
    geometries=[]
    def collect(geom):
        """Collect polygonal members of a GeoJSON geometry for rasterization of the African land mask."""
        if not geom:return
        kind=geom.get('type')
        if kind=='GeometryCollection':
            for child in geom.get('geometries',[]):collect(child)
        elif kind in ('Polygon','MultiPolygon'):
            geometries.append(geom)
    for feature in geo.get('features',[]):collect(feature.get('geometry'))
    # display_affine locates sampled pixel centres; rasterization needs the
    # upper-left pixel corner, half a display cell to the west/north.
    corner_affine=affine*rasterio.Affine.translation(-0.5,-0.5)
    return rasterize(((g,1) for g in geometries),out_shape=values.shape[:2],transform=corner_affine,fill=0,dtype='uint8').astype(bool)

PH_SOURCE='SoilGrids (ISRIC), pH (H₂O), 0–30 cm, thickness-weighted mean'

@lru_cache(maxsize=1)
def africa_ph_display():
    """Read pH on the same sampled CHELSA cells used by the climate display."""
    values,_,plan,row0,col0,step,_=dataset()
    base=settings.BASE_DIR
    root=base/'data/soil-ph-0-30-diagnostic'
    tile_paths=[root/f"ph_0-30cm_provisional_r{tile['row']}-c{tile['col']}.tif" for tile in plan['tiles']]
    if any(not path.is_file() for path in tile_paths):
        raise FileNotFoundError('The Africa-wide SoilGrids pH 0–30 cm tiles are incomplete.')
    sampled=np.full(values.shape[:2],np.nan,dtype='float32')
    for tile,path in zip(plan['tiles'],tile_paths):
        with rasterio.open(path) as src:
            block=src.read(1,masked=True).filled(np.nan).astype('float32')[step//2::step,step//2::step]
        r=(tile['row']-row0)//step;c=(tile['col']-col0)//step
        if r<0 or c<0 or r>=sampled.shape[0] or c>=sampled.shape[1]:
            continue
        r1=min(sampled.shape[0],r+block.shape[0]);c1=min(sampled.shape[1],c+block.shape[1])
        sub=block[:r1-r,:c1-c]
        target=sampled[r:r1,c:c1]
        valid=np.isfinite(sub)
        target[valid]=sub[valid]
    return sampled

def point(lon,lat):
    """Read native CHELSA monthly values at WGS84 coordinates; reject incomplete coverage instead of filling missing months."""
    if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90:raise ValueError('Invalid coordinates.')
    _,_,plan,_,_,_,job_root=dataset(); affine=rasterio.Affine(*plan['transform'][:6]);col,row=(~affine)*(lon,lat);row=math.floor(row);col=math.floor(col)
    tile=next((t for t in plan['tiles'] if t['row']<=row<t['row']+t['height'] and t['col']<=col<t['col']+t['width']),None)
    if tile is None:raise ValueError('No climate tile at this location. Choose a land site in Africa.')
    values=np.full((2,12),np.nan)
    for vi,v in enumerate(('tas','pr')):
        for m in range(1,13):
            marker=job_root/f"r{tile['row']}-c{tile['col']}-{v}-{m:02d}.json"
            job=json.loads(marker.read_text())
            with rasterio.open(Path(job['folder'])/'africa-mean.tif') as src:
                x=src.read(1,window=Window(col-tile['col'],row-tile['row'],1,1),masked=True)
                if not np.ma.getmaskarray(x).all():values[vi,m-1]=float(x[0,0])
    if not np.isfinite(values).all():raise ValueError('This site has missing climate data. Choose another land point.')
    return values

@ensure_csrf_cookie
def home(request):
    """Render the Africa demo with effective variety records and the current local data readiness state."""
    catalogue=load_catalogue(settings.BASE_DIR)
    crop=request.GET.get('crop','sweetpotato')
    if crop not in ('potato','sweetpotato'):
        crop='sweetpotato'
    varieties=[row for row in catalogue['records'] if row['crop']==crop]
    default=next((row for row in varieties if row['name']=='Kabode'),varieties[0])
    selected=next((row for row in varieties if row['id']==request.GET.get('variety')),default)
    profile=calculation_profile(selected)
    same_criteria=[row['name'] for row in catalogue['records'] if row['id']!=selected['id'] and profile is not None and calculation_profile(row)==profile]
    labels=[('SPVD','SPVD'),('Alternaria','Alternaria'),('Sweetpotato weevils','weevils')] if crop=='sweetpotato' else [
        ('Late blight','LB'),('PVX','PVX'),('PVY','PVY'),('PLRV','PLRV'),('Bacterial wilt','BW')]
    disease_traits=[{'label':label,'value':selected['resistance_values'].get(key) or 'Not reported in source',
                     'source':selected['field_sources'].get('resistance_'+key,'tolerance catalogue, not independently verified'),
                     'previous':selected['previous_values'].get('resistance_'+key)} for label,key in labels]
    return render(request,'africa_demo.html',{
        'catalogue':catalogue,'crop':crop,'varieties':varieties,'selected':selected,'disease_traits':disease_traits,'same_criteria':same_criteria,
        'demo_style_version':hashlib.sha256((settings.BASE_DIR/'assets/africa-demo.css').read_bytes()).hexdigest()[:12],
        'demo_script_version':hashlib.sha256((settings.BASE_DIR/'assets/africa-demo.js').read_bytes()).hexdigest()[:12],
    })

def site(request):
    """Return native monthly reference climate for validated WGS84 coordinates."""
    try:
        lon=float(request.GET['longitude']);lat=float(request.GET['latitude']);v=point(lon,lat)
        return JsonResponse({'values':v.tolist(),'longitude':lon,'latitude':lat})
    except (ValueError,KeyError,FileNotFoundError) as e:return JsonResponse({'error':str(e)},status=400)


def result_file(request,run_id,filename):
    """Serve only approved files belonging to an existing Africa-demo result."""
    from django.http import FileResponse, Http404
    if filename not in ('similarity.png','similarity.tif','metadata.json','temperature-range.png','temperature-range.tif','temperature-range.json','criterion-range.png','criterion-range.tif','criterion-range.json','summary.png','summary.tif','summary.json'):
        raise Http404
    path=settings.BASE_DIR/'runs'/str(run_id)/filename
    if not path.is_file(): raise Http404
    return FileResponse(path.open('rb'),as_attachment=filename!='similarity.png',filename=filename)

@require_GET
def sample_result(request,run_id):
    """Read the exploratory score at a map coordinate without modifying the run."""
    try:
        lon=float(request.GET['longitude']);lat=float(request.GET['latitude'])
        if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90:
            raise ValueError('Invalid coordinates.')
        path=settings.BASE_DIR/'runs'/str(run_id)/'similarity.tif'
        if not path.is_file(): return JsonResponse({'error':'This result is no longer available.'},status=404)
        with rasterio.open(path) as src:
            row,col=src.index(lon,lat)
            if not (0<=row<src.height and 0<=col<src.width):
                return JsonResponse({'error':'This point is outside the displayed result.'},status=404)
            value=src.read(1,window=Window(col,row,1,1),masked=True)[0,0]
            if np.ma.is_masked(value) or not math.isfinite(float(value)):
                return JsonResponse({'error':'No score is available at this location.'},status=404)
        score=float(value)
        return JsonResponse({'score':score,'index_percent':score*100,'longitude':lon,'latitude':lat})
    except (ValueError,KeyError) as e:
        return JsonResponse({'error':str(e) or 'Invalid coordinates.'},status=400)

@require_GET
def sample_temperature_range(request,run_id):
    """Inspect the descriptive temperature-range check at a sampled cell."""
    try:
        lon=float(request.GET['longitude']);lat=float(request.GET['latitude'])
        if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90:
            raise ValueError('Invalid coordinates.')
        path=settings.BASE_DIR/'runs'/str(run_id)/'temperature-range.tif'
        if not path.is_file(): return JsonResponse({'error':'This result is no longer available.'},status=404)
        with rasterio.open(path) as src:
            row,col=src.index(lon,lat)
            if not (0<=row<src.height and 0<=col<src.width):
                return JsonResponse({'error':'This point is outside the displayed result.'},status=404)
            value=src.read(1,window=Window(col,row,1,1),masked=True)[0,0]
            if np.ma.is_masked(value) or not math.isfinite(float(value)):
                return JsonResponse({'error':'No temperature check is available at this location.'},status=404)
            tags=src.tags()
        share=float(value)
        months=json.loads(tags['months'])
        values,display_affine,_,_,_,_,_=dataset()
        display_col,display_row=(~display_affine)*(lon,lat)
        display_row,display_col=math.floor(display_row),math.floor(display_col)
        monthly_values=values[display_row,display_col,0,np.asarray(months)-1]
        lower,upper=float(tags['lower_c']),float(tags['upper_c'])
        details=[{'month':month,'temperature_c':float(temp),'within_range':bool(lower<=temp<=upper)} for month,temp in zip(months,monthly_values)]
        return JsonResponse({'share':share,'inside_months':round(share*int(tags['month_count'])),'month_count':int(tags['month_count']),'lower_c':lower,'upper_c':upper,'months':months,'monthly_values':details,'longitude':lon,'latitude':lat})
    except (ValueError,KeyError) as e:
        return JsonResponse({'error':str(e) or 'Invalid coordinates.'},status=400)

@require_POST
def screen_variety_temperature(request):
    """Create a clearly labelled, temperature-only range-screening preview."""
    try:
        p=json.loads(request.body)
        planting_month=int(p['planting_month'])
        variety_id=str(p['variety_id'])
        catalogue=load_catalogue(settings.BASE_DIR)
        variety=next((v for v in catalogue['records'] if v['id']==variety_id),None)
        if variety is None: raise ValueError('Choose a variety from the catalogue.')
        if variety.get('reference_only'): return JsonResponse({'status':'not_evaluable','reason':UNAVAILABLE_RANGES})
        cycle_days=cycle_days_upper_bound(variety)
        if cycle_days is None: return JsonResponse({'status':'not_evaluable','criterion':'temperature','reason':'This variety has no usable growing-cycle duration in the catalogue.'})
        months=cycle_months(planting_month,cycle_days)
        limits=variety.get('temperature_range')
        if not isinstance(limits,list) or len(limits)!=2 or any(x is None for x in limits):
            raise ValueError('This variety has no complete temperature range in the catalogue.')
        lower,upper=map(float,limits)
        if not math.isfinite(lower+upper) or lower>=upper: raise ValueError('The temperature range is invalid.')
        values,affine,_,row,col,step,_=dataset()
        screen=temperature_range_screen(values,months,lower,upper)
        land=africa_land_mask()
        screen=np.where(land,screen,np.nan)
        month_counts=np.rint(screen*len(months))
        class_counts={str(n):int((month_counts==n).sum()) for n in range(len(months)+1)}
        not_evaluable_cells=int((land & ~np.isfinite(screen)).sum())
        selected_month_values=values[:,:,0,np.asarray(months)-1]
        finite_selected=np.isfinite(selected_month_values)
        denominator=int(finite_selected.sum())
        upper_exceedance_pct=100*int(((selected_month_values>upper)&finite_selected).sum())/denominator if denominator else 0.0
        identifier=uuid.uuid4();folder=settings.BASE_DIR/'runs'/str(identifier);folder.mkdir(parents=True)
        with rasterio.open(folder/'temperature-range.tif','w',driver='GTiff',height=screen.shape[0],width=screen.shape[1],count=1,dtype='float32',crs='EPSG:4326',transform=affine,nodata=-9999,compress='deflate') as dst:
            dst.write(np.where(np.isfinite(screen),screen,-9999),1)
            dst.update_tags(variety_id=variety_id,variety_name=variety['name'],lower_c=lower,upper_c=upper,months=json.dumps(months),month_count=len(months),planting_month=planting_month,cycle_days=cycle_days,cycle_source=variety['field_sources']['cycle_days'],method='fraction of monthly mean temperatures in range across whole calendar months touched by the upper-bound crop cycle')
        with rasterio.open(folder/'temperature-range.tif') as src:
            (folder/'temperature-range.png').write_bytes(preview_png(src,screen,land_mask=land))
            b=src.bounds;bounds=[[b.bottom,b.left],[b.top,b.right]]
        metadata={'variety_id':variety_id,'variety_name':variety['name'],'temperature_range_c':[lower,upper],'planting_month':planting_month,'cycle_days_used':cycle_days,'cycle_source':variety['field_sources']['cycle_days'],'months':months,'valid_cells':int(np.isfinite(screen).sum()),'class_counts':class_counts,'not_evaluable_cells':not_evaluable_cells,'upper_bound_exceedance_pct_of_valid_month_values':upper_exceedance_pct,'method':'Share of full calendar-month CHELSA 1991–2020 monthly mean temperatures within the catalogue interval; cycle uses the catalogue upper duration bound from day 1 of the selected planting month.','interpretation':'Exploratory temperature criterion only, not validated suitability. The catalogue interval meaning/source is unconfirmed. Monthly means are not daily minima/maxima. Whole monthly normals are included for partial first/last cycle months. Same planting month is applied across Africa; no local planting calendar is used. One native cell per 16 x 16 block is displayed.'}
        (folder/'temperature-range.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        return JsonResponse({'id':str(identifier),'bounds':bounds,'metadata':metadata})
    except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:return JsonResponse({'error':str(e)},status=400)
    except FileNotFoundError:return JsonResponse({'error':'The monthly display dataset is still being prepared.'},status=503)


@require_POST
def screen_variety_criterion(request):
    """Map extra catalogue ranges independently; never combine them as suitability."""
    try:
        p=json.loads(request.body)
        criterion=str(p['criterion'])
        if criterion not in ('annual_rainfall','soil_ph'):
            raise ValueError('Choose annual rainfall or soil pH.')
        variety_id=str(p['variety_id'])
        catalogue=load_catalogue(settings.BASE_DIR)
        variety=next((v for v in catalogue['records'] if v['id']==variety_id),None)
        if variety is None: raise ValueError('Choose a variety from the catalogue.')
        if variety.get('reference_only'): return JsonResponse({'status':'not_evaluable','reason':UNAVAILABLE_RANGES})
        if criterion=='annual_rainfall':
            limits=variety.get('rainfall_range')
            if not isinstance(limits,list) or len(limits)!=2 or any(x is None for x in limits):
                raise ValueError('This variety has no complete rainfall range in the catalogue.')
            lower,upper=map(float,limits)
            if not math.isfinite(lower+upper) or lower>=upper: raise ValueError('The rainfall range is invalid.')
            cycle_days=None
            planting_month=int(p['planting_month'])
            months=list(range(1,13))
            values,affine,_,_,_,_,_=dataset()
            measured=np.where(np.isfinite(values[:, :, 1, :]).all(axis=2),values[:, :, 1, :].sum(axis=2),np.nan)
            land=africa_land_mask()
            screened=np.where(land & np.isfinite(measured),np.where(measured<lower,0,np.where(measured<=upper,1,2)),np.nan).astype('float32')
            profile=dict(driver='GTiff',height=screened.shape[0],width=screened.shape[1],count=1,dtype='uint8',crs='EPSG:4326',transform=affine,nodata=255,compress='deflate')
            transform=affine
            units='mm/year'
            method='Sum of the twelve CHELSA 1991–2020 mean monthly precipitation normals (mm/month) to obtain annual precipitation, compared with the catalogue annual rainfall range.'
            coverage='Africa sampled display grid'
        else:
            limits=variety.get('ph_range')
            if not isinstance(limits,list) or len(limits)!=2 or any(x is None for x in limits):
                raise ValueError('This variety has no complete soil pH range in the catalogue.')
            lower,upper=map(float,limits)
            if not math.isfinite(lower+upper) or lower>=upper: raise ValueError('The soil pH range is invalid.')
            _,affine,_,_,_,_,_=dataset()
            measured=africa_ph_display()
            land=africa_land_mask()
            screened=np.where(land & np.isfinite(measured),np.where(measured<lower,0,np.where(measured<=upper,1,2)),np.nan).astype('float32')
            profile=dict(driver='GTiff',height=screened.shape[0],width=screened.shape[1],count=1,dtype='uint8',crs='EPSG:4326',transform=affine,nodata=255,compress='deflate')
            transform=affine
            months=[];planting_month=None;cycle_days=None
            units='pH'
            method='Descriptive comparison with SoilGrids pH (H₂O), 0–30 cm, thickness-weighted arithmetic mean of 0–5, 5–15 and 15–30 cm. Native 250 m values were area-averaged to the CHELSA grid, then sampled at the centre of each 16 x 16 display block.'
            coverage='Africa sampled display grid; missing SoilGrids cells are not evaluable.'
        valid_cells=int(np.isfinite(screened).sum())
        class_counts={str(code):int((screened==code).sum()) for code in range(3)}
        inside=class_counts['1']
        identifier=uuid.uuid4();folder=settings.BASE_DIR/'runs'/str(identifier);folder.mkdir(parents=True)
        profile.update(height=screened.shape[0],width=screened.shape[1],transform=transform)
        with rasterio.open(folder/'criterion-range.tif','w',**profile) as dst:
            dst.write(np.where(np.isfinite(screened),screened,255).astype('uint8'),1)
            dst.update_tags(criterion=criterion,variety_id=variety_id,variety_name=variety['name'],lower=lower,upper=upper,units=units,method=method,coverage=coverage,source=PH_SOURCE if criterion=='soil_ph' else 'CHELSA monthly climate normals, 1991–2020',months=json.dumps(months),planting_month=planting_month or '',cycle_days=cycle_days or '')
        with rasterio.open(folder/'criterion-range.tif') as src:
            (folder/'criterion-range.png').write_bytes(range_class_preview_png(src,screened))
            b=src.bounds;bounds=[[b.bottom,b.left],[b.top,b.right]]
        metadata={'criterion':criterion,'variety_id':variety_id,'variety_name':variety['name'],'range':[lower,upper],'units':units,'valid_cells':valid_cells,'cells_below_range':class_counts['0'],'cells_in_range':inside,'cells_above_range':class_counts['2'],'class_counts':class_counts,'share_in_range_pct':100*inside/valid_cells if valid_cells else None,'coverage':'Evaluable African land cells only; sea and outside-Africa cells are transparent.','source':PH_SOURCE if criterion=='soil_ph' else 'CHELSA monthly climate normals, 1991–2020','planting_month':planting_month,'cycle_days_used':cycle_days,'cycle_source':variety['field_sources']['cycle_days'],'months':months,'method':method,'interpretation':'Shown as a separate descriptive criterion with below, within and above catalogue-range classes. Counts use evaluable African land cells only. The catalogue rainfall range is treated as annual, following supervisor guidance; a seasonal rainfall range would be more precise if available. This is not a validated crop-suitability score.'}
        (folder/'criterion-range.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        return JsonResponse({'id':str(identifier),'bounds':bounds,'metadata':metadata})
    except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:return JsonResponse({'error':str(e)},status=400)
    except FileNotFoundError:return JsonResponse({'error':'The selected criterion layer is not available.'},status=503)


@require_POST
def screen_variety_summary(request):
    """Count the three independent checks; code 4 is explicitly not evaluable."""
    try:
        p=json.loads(request.body);variety_id=str(p['variety_id'])
        catalogue=load_catalogue(settings.BASE_DIR)
        variety=next((v for v in catalogue['records'] if v['id']==variety_id),None)
        if variety is None: raise ValueError('Choose a variety from the catalogue.')
        if variety.get('reference_only'): return JsonResponse({'status':'not_evaluable','reason':UNAVAILABLE_RANGES})
        cycle_days=cycle_days_upper_bound(variety)
        if cycle_days is None:return JsonResponse({'status':'not_evaluable','reason':'The catalogue has no usable growing-cycle duration.'})
        limits_t=variety.get('temperature_range');limits_r=variety.get('rainfall_range');limits_p=variety.get('ph_range')
        if any(not isinstance(v,(list,tuple)) or len(v)!=2 or any(x is None for x in v) for v in (limits_t,limits_r,limits_p)):
            return JsonResponse({'status':'not_evaluable','reason':'At least one of temperature, rainfall, or soil pH has no complete catalogue range.'})
        lower_t,upper_t=map(float,limits_t);lower_r,upper_r=map(float,limits_r);lower_p,upper_p=map(float,limits_p)
        planting_month=int(p['planting_month']);months=cycle_months(planting_month,cycle_days)
        values,affine,_,_,_,_,_=dataset()
        temp_fraction=temperature_range_screen(values,months,lower_t,upper_t)
        temp_ok=np.where(np.isfinite(temp_fraction),temp_fraction>=1.0-1e-6,np.nan).astype('float32')
        rain_ok=annual_rainfall_range_screen(values,lower_r,upper_r)
        ph_on_display=africa_ph_display()
        ph_ok=np.where(np.isfinite(ph_on_display),(ph_on_display>=lower_p)&(ph_on_display<=upper_p),np.nan).astype('float32')
        codes=combine_criteria([temp_ok,rain_ok,ph_ok])
        land=africa_land_mask()
        outside=~land
        evaluated=(codes<4)&land
        not_evaluable=(codes==4)&land
        counts={str(i):int(((codes==i)&land).sum()) for i in range(4)}
        per_criterion={}
        for name,criterion in (('temperature',temp_ok),('rainfall',rain_ok),('soil_ph',ph_ok)):
            valid=np.isfinite(criterion)&land
            satisfied=(criterion>=1)&valid
            per_criterion[name]={'valid_cells':int(valid.sum()),'satisfied_cells':int(satisfied.sum()),'share_satisfied_pct':100*int(satisfied.sum())/int(valid.sum()) if valid.any() else None}
        identifier=uuid.uuid4();folder=settings.BASE_DIR/'runs'/str(identifier);folder.mkdir(parents=True)
        profile=dict(driver='GTiff',height=codes.shape[0],width=codes.shape[1],count=1,dtype='uint8',crs='EPSG:4326',transform=affine,nodata=255,compress='deflate')
        with rasterio.open(folder/'summary.tif','w',**profile) as dst:
            display_codes=np.full(codes.shape,255,dtype='uint8')
            display_codes[land]=np.where(codes[land]<4,codes[land],4).astype('uint8')
            dst.write(display_codes,1)
            dst.update_tags(variety_id=variety_id,variety_name=variety['name'],criterion_codes='0,1,2,3 satisfied; 4 not evaluable',criteria='temperature cycle; annual rainfall; soil pH',planting_month=planting_month,cycle_days=cycle_days,months=json.dumps(months),cycle_source=variety['field_sources']['cycle_days'],ph_coverage='Africa sampled display grid',ph_source=PH_SOURCE)
        with rasterio.open(folder/'summary.tif') as src:
            (folder/'summary.png').write_bytes(criterion_count_preview_png(src,display_codes))
            b=src.bounds;bounds=[[b.bottom,b.left],[b.top,b.right]]
        metadata={'variety_id':variety_id,'variety_name':variety['name'],'planting_month':planting_month,'cycle_days_used':cycle_days,'cycle_source':variety['field_sources']['cycle_days'],'months':months,'criteria':['temperature over cycle','annual rainfall','soil pH'],'combination':'Unweighted count of satisfied criteria; no suitability probability. A cell is classed not evaluable if any of the three inputs is missing.','valid_cells':int(evaluated.sum()),'not_evaluable_cells':int(not_evaluable.sum()),'outside_africa_or_sea_cells':int(outside.sum()),'counts':counts,'per_criterion':per_criterion,'coverage':'Africa sampled display grid for climate and SoilGrids pH. Missing values on African land are not evaluable, not failures; sea and outside-Africa cells are transparent.','ph_source':PH_SOURCE,'assumptions':['Temperature criterion requires every touched monthly mean to fall inside the catalogue range.','The catalogue rainfall range is annual; twelve CHELSA monthly normals are summed to annual precipitation. A seasonal requirement would be more precise if obtained.','Catalogue upper cycle duration is used for temperature.','Soil pH uses the thickness-weighted arithmetic mean of SoilGrids pH-water at 0–5, 5–15 and 15–30 cm; source layers were area-averaged onto the CHELSA grid.']}
        (folder/'summary.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        return JsonResponse({'id':str(identifier),'bounds':bounds,'metadata':metadata})
    except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:return JsonResponse({'error':str(e)},status=400)
    except FileNotFoundError:return JsonResponse({'error':'A required criterion layer is not available.'},status=503)

@require_GET
def sample_variety_summary(request,run_id):
    """Inspect the clicked display cell with the run cycle and current catalogue bounds; report criterion values and explicit missing-data status."""
    try:
        lon=float(request.GET['longitude']);lat=float(request.GET['latitude'])
        if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90:raise ValueError('Invalid coordinates.')
        path=settings.BASE_DIR/'runs'/str(run_id)/'summary.tif'
        if not path.is_file():return JsonResponse({'error':'This summary is no longer available.'},status=404)
        with rasterio.open(path) as src:
            row,col=src.index(lon,lat)
            if not (0<=row<src.height and 0<=col<src.width):return JsonResponse({'error':'Outside the displayed result extent.'},status=404)
            code=int(src.read(1,window=Window(col,row,1,1))[0,0])
            tags=src.tags()
        if code==255:return JsonResponse({'status':'outside_africa','message':'This location is outside the African land analysis area.','longitude':lon,'latitude':lat})
        variety_id=tags['variety_id'];months=json.loads(tags['months'])
        catalogue=load_catalogue(settings.BASE_DIR)
        variety=next((v for v in catalogue['records'] if v['id']==variety_id),None)
        if variety is None:raise ValueError('The variety for this result is no longer available in the catalogue.')
        t_low,t_high=map(float,variety['temperature_range']);r_low,r_high=map(float,variety['rainfall_range']);p_low,p_high=map(float,variety['ph_range'])
        climate,affine,_,_,_,_,_=dataset();dc,dr=(~affine)*(lon,lat);dr,dc=math.floor(dr),math.floor(dc)
        if not (0<=dr<climate.shape[0] and 0<=dc<climate.shape[1]):return JsonResponse({'error':'No climate value at this displayed cell.'},status=404)
        monthly_temperature=[];monthly_rainfall=[]
        for month in months:
            tv=float(climate[dr,dc,0,month-1]);rv=float(climate[dr,dc,1,month-1])
            monthly_temperature.append({'month':month,'value_c':tv if math.isfinite(tv) else None,'within_range':t_low<=tv<=t_high if math.isfinite(tv) else None})
        annual_months=list(range(1,13))
        for month in annual_months:
            rv=float(climate[dr,dc,1,month-1])
            monthly_rainfall.append({'month':month,'value_mm':rv if math.isfinite(rv) else None})
        temp_evaluable=all(x['value_c'] is not None for x in monthly_temperature)
        temp_ok=all(x['within_range'] for x in monthly_temperature) if temp_evaluable else None
        rain_evaluable=all(x['value_mm'] is not None for x in monthly_rainfall)
        annual_rainfall=sum(x['value_mm'] for x in monthly_rainfall) if rain_evaluable else None
        rainfall_by_month={x['month']:x for x in monthly_rainfall}
        cycle_rainfall=[rainfall_by_month[month] for month in months]
        cycle_rain_evaluable=all(x['value_mm'] is not None for x in cycle_rainfall)
        cycle_total=sum(x['value_mm'] for x in cycle_rainfall) if cycle_rain_evaluable else None
        rain_ok=r_low<=annual_rainfall<=r_high if rain_evaluable else None
        ph_values=africa_ph_display();ph_sample=float(ph_values[dr,dc])
        ph=ph_sample if math.isfinite(ph_sample) else None
        ph_ok=p_low<=ph<=p_high if ph is not None else None
        criteria={'temperature':{'evaluable':temp_evaluable,'within_range':temp_ok,'lower':t_low,'upper':t_high,'units':'°C','monthly_values':monthly_temperature,'months_in_range':sum(x['within_range'] is True for x in monthly_temperature),'month_count':len(months)},'rainfall':{'evaluable':rain_evaluable,'within_range':rain_ok,'lower':r_low,'upper':r_high,'units':'mm/year','monthly_values':monthly_rainfall,'annual_total_mm':annual_rainfall,'cycle_monthly_values':cycle_rainfall,'cycle_total_mm':cycle_total,'cycle_evaluable':cycle_rain_evaluable,'cycle_note':'Cycle total is descriptive only; the catalogue range is annual. Annual totals can conceal dry-season gaps.'},'soil_ph':{'evaluable':ph is not None,'within_range':ph_ok,'lower':p_low,'upper':p_high,'units':'pH','value':ph,'source':PH_SOURCE}}
        response={'status':'not_evaluable' if code==4 else 'evaluated','message':'At least one criterion has no data here; missing data are not counted as a failure.' if code==4 else None,'criteria_satisfied':None if code==4 else code,'criteria_total':3,'variety_name':tags.get('variety_name',variety['name']),'planting_month':int(tags['planting_month']),'cycle_days':int(tags['cycle_days']),'months':months,'criteria':criteria,'longitude':lon,'latitude':lat}
        return JsonResponse(response)
    except (ValueError,KeyError) as e:return JsonResponse({'error':str(e) or 'Invalid coordinates.'},status=400)

@require_GET
def sample_variety_criterion(request,run_id):
    """Inspect a criterion value at one point in its available raster."""
    try:
        lon=float(request.GET['longitude']);lat=float(request.GET['latitude'])
        if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90: raise ValueError('Invalid coordinates.')
        path=settings.BASE_DIR/'runs'/str(run_id)/'criterion-range.tif'
        if not path.is_file(): return JsonResponse({'error':'This criterion result is no longer available.'},status=404)
        with rasterio.open(path) as src:
            row,col=src.index(lon,lat)
            if not (0<=row<src.height and 0<=col<src.width): return JsonResponse({'error':'This point is outside the criterion layer.'},status=404)
            hit=src.read(1,window=Window(col,row,1,1),masked=True)[0,0]
            if np.ma.is_masked(hit): return JsonResponse({'error':'No data for this criterion at this location.'},status=404)
            tags=src.tags()
        if tags['criterion']=='annual_rainfall':
            values,affine,_,_,_,_,_=dataset();r,c=(~affine)*(lon,lat);r,c=math.floor(r),math.floor(c)
            if not (0<=r<values.shape[0] and 0<=c<values.shape[1]): return JsonResponse({'error':'No sampled climate value at this location.'},status=404)
            months=list(range(1,13));monthly=values[r,c,1,:]
            if not np.isfinite(monthly).all(): return JsonResponse({'error':'Incomplete annual rainfall data at this location.'},status=404)
            measured=float(monthly.sum())
        else:
            ph_values=africa_ph_display();_,affine,_,_,_,_,_=dataset();c,r=(~affine)*(lon,lat);r,c=math.floor(r),math.floor(c)
            if not (0<=r<ph_values.shape[0] and 0<=c<ph_values.shape[1]): return JsonResponse({'error':'This point is outside the Africa pH display grid.'},status=404)
            sample=ph_values[r,c]
            if not math.isfinite(float(sample)): return JsonResponse({'error':'No SoilGrids pH data at this location; this cell is not evaluable.'},status=404)
            measured=float(sample)
        lower,upper=float(tags['lower']),float(tags['upper'])
        details=[{'month':m,'rainfall_mm':float(v)} for m,v in zip(months,monthly)] if tags['criterion']=='annual_rainfall' else []
        return JsonResponse({'criterion':tags['criterion'],'value':measured,'units':tags['units'],'source':PH_SOURCE if tags['criterion']=='soil_ph' else 'CHELSA monthly climate normals, 1991–2020','lower':lower,'upper':upper,'in_range':lower<=measured<=upper,'months':json.loads(tags.get('months','[]')),'monthly_values':details,'longitude':lon,'latitude':lat})
    except (ValueError,KeyError) as e:return JsonResponse({'error':str(e) or 'Invalid coordinates.'},status=400)

@require_POST
def compute(request):
    """Compute the separate monthly climate-similarity preview and save its raster, image and metadata as a new run."""
    try:
        p=json.loads(request.body);lon=float(p['longitude']);lat=float(p['latitude'])
        months=analysis_months(int(p['start']),int(p['end']))
        weights=[float(p['temperature_weight']),float(p['rainfall_weight'])]
        coefficients=[float(p['temperature_coefficient']),float(p['rainfall_coefficient'])]
        if p.get('acknowledge') is not True:raise ValueError('Acknowledge the exploratory status.')
        values,affine,_,row,col,step,_=dataset();reference=point(lon,lat)
        score=monthly_similarity(reference,values,months,weights,coefficients)
        identifier=uuid.uuid4();folder=settings.BASE_DIR/'runs'/str(identifier);folder.mkdir(parents=True)
        with rasterio.open(folder/'similarity.tif','w',driver='GTiff',height=score.shape[0],width=score.shape[1],count=1,dtype='float32',crs='EPSG:4326',transform=affine,nodata=-9999,compress='deflate') as dst:
            dst.write(np.where(np.isfinite(score),score,-9999).astype('float32'),1)
            dst.update_tags(period='1991-2020',method='weighted c/(c+monthly RMSE)',status='exploratory sampled-grid demonstration')
        with rasterio.open(folder/'similarity.tif') as src:
            (folder/'similarity.png').write_bytes(preview_png(src,score))
            b=src.bounds;bounds=[[b.bottom,b.left],[b.top,b.right]]
        metadata=dict(period='1991-2020',months=months,reference={'longitude':lon,'latitude':lat,'values':reference.tolist()},weights=weights,coefficients=coefficients,method='Weighted climate similarity: per-variable c/(c+RMSE) over selected calendar months, then weighted sum; no seasonal alignment.',score_display='Similarity index percent = model score × 100; not a probability.',sampling=f'One native pixel per {step} x {step} block (about 15 km at the equator); reference sampled at native resolution. Small islands and local variation may be omitted.',limitations='Exploratory climate comparison, not variety suitability or yield prediction. The five-cell mask discrepancy and rainfall extremes are still under review.',valid_cells=int(np.isfinite(score).sum()),display_grid={'row':row,'col':col,'step':step})
        (folder/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        return JsonResponse({'id':str(identifier),'bounds':bounds,'metadata':metadata})
    except (ValueError,KeyError,TypeError) as e:return JsonResponse({'error':str(e)},status=400)
    except FileNotFoundError:return JsonResponse({'error':'The monthly display dataset is still being prepared.'},status=503)
