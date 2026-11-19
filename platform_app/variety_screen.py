"""Descriptive screens against variety catalogue ranges."""
import calendar
import datetime as dt
import math
import numpy as np

def cycle_months(planting_month, duration_days):
    """Calendar months touched by a cycle starting on day 1 of planting month.

    Uses a non-leap representative year and includes every touched monthly
    normal in full, including a partial first/last month.
    """
    if type(planting_month) is not int or not 1 <= planting_month <= 12:
        raise ValueError('Planting month must be an integer from 1 to 12.')
    if type(duration_days) is not int or duration_days < 1 or duration_days > 730:
        raise ValueError('Cycle duration must be an integer from 1 to 730 days.')
    start=dt.date(2001,planting_month,1)
    end=start+dt.timedelta(days=duration_days-1)
    result=[]
    cursor=start
    while cursor <= end:
        if cursor.month not in result: result.append(cursor.month)
        if cursor.month==12: cursor=dt.date(cursor.year+1,1,1)
        else: cursor=dt.date(cursor.year,cursor.month+1,1)
    return result

def cycle_days_upper_bound(variety):
    """Return a usable upper-bound cycle duration, or None if unavailable."""
    cycle=variety.get('cycle_days') if isinstance(variety,dict) else None
    if not isinstance(cycle,(list,tuple)) or len(cycle)!=2 or cycle[1] is None:
        return None
    try:
        upper=float(cycle[1])
    except (TypeError,ValueError):
        return None
    if not math.isfinite(upper) or upper < 1 or upper > 730:
        return None
    return math.ceil(upper)

def combine_criteria(criteria):
    """Count three binary criteria; code 4 means at least one is not evaluable."""
    if len(criteria)!=3:
        raise ValueError('Exactly three criteria are required.')
    arrays=[np.asarray(item,dtype='float32') for item in criteria]
    if any(a.shape!=arrays[0].shape for a in arrays):
        raise ValueError('All criteria must use the same grid.')
    evaluable=np.logical_and.reduce([np.isfinite(a) for a in arrays])
    count=np.sum([np.nan_to_num(a,nan=0.0)>=0.5 for a in arrays],axis=0)
    return np.where(evaluable,count,4).astype('uint8')

def temperature_range_screen(monthly_values, months, lower_c, upper_c):
    """Share of cycle months whose monthly mean temperature is in range."""
    values=np.asarray(monthly_values)
    if values.ndim!=4 or values.shape[2:]!=(2,12):
        raise ValueError('Expected an Africa grid shaped (rows, columns, 2 variables, 12 months).')
    if not months or len(set(months))!=len(months) or any(type(m) is not int or not 1<=m<=12 for m in months):
        raise ValueError('Choose distinct calendar months from 1 to 12.')
    if not math.isfinite(lower_c+upper_c) or lower_c>=upper_c:
        raise ValueError('The temperature range is invalid.')
    selected=values[:,:,0,np.asarray(months)-1]
    valid=np.isfinite(selected).all(axis=-1)
    share=((selected>=lower_c)&(selected<=upper_c)).sum(axis=-1)/len(months)
    return np.where(valid,share,np.nan).astype('float32')

def annual_rainfall_range_screen(monthly_values, lower_mm, upper_mm):
    """Compare annual precipitation totals with an annual catalogue range.

    CHELSA stores monthly precipitation normals in mm/month, so the twelve
    monthly normals are summed to obtain the annual climatological total.
    """
    values=np.asarray(monthly_values)
    if values.ndim!=4 or values.shape[2:]!=(2,12):
        raise ValueError('Expected an Africa grid shaped (rows, columns, 2 variables, 12 months).')
    if not math.isfinite(lower_mm+upper_mm) or lower_mm>=upper_mm:
        raise ValueError('The rainfall range is invalid.')
    selected=values[:,:,1,:]
    valid=np.isfinite(selected).all(axis=-1)
    total=selected.sum(axis=-1)
    inside=(total>=lower_mm)&(total<=upper_mm)
    return np.where(valid,inside,np.nan).astype('float32')



def calculation_profile(variety):
    """Inputs determining criteria maps for every planting month; no catalogue edits."""
    if variety.get('is_unspecified'):
        return None
    ranges=[]
    for field in ('temperature_range','rainfall_range','ph_range'):
        values=variety.get(field)
        if not isinstance(values,(list,tuple)) or len(values)!=2:
            return None
        try:
            lower,upper=map(float,values)
        except (TypeError,ValueError):
            return None
        if not math.isfinite(lower) or not math.isfinite(upper) or lower>=upper:
            return None
        ranges.append((lower,upper))
    duration=cycle_days_upper_bound(variety)
    if duration is None:
        return None
    return tuple(ranges)+(tuple(tuple(cycle_months(month,duration)) for month in range(1,13)),)
