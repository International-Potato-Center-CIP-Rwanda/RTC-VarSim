"""Monthly AFSA distance core. Not yet connected to the web calculation.

No automatic seasonal alignment. Missing selected months invalidate a cell.
"""
import math
import numpy as np


def analysis_months(start, end):
    """Inclusive month sequence, including December crossings and one month."""
    if any(type(m) is not int or not 1 <= m <= 12 for m in (start, end)):
        raise ValueError('Months must be integers from 1 to 12.')
    return [((start - 1 + step) % 12) + 1 for step in range((end-start) % 12 + 1)]


def monthly_similarity(reference, targets, months, weights, coefficients):
    """Arrays: reference (variables,12), targets (...,variables,12).

    Implements weighted c/(c+RMSE) over specified months without shifts.
    Uses a strict complete-month mask, intentionally unlike upstream nanmean.
    No rounding of scores, and no interpretation as variety suitability.
    """
    if not isinstance(months, (list,tuple)) or not months or any(type(m) is not int or not 1<=m<=12 for m in months) or len(set(months))!=len(months):
        raise ValueError('Select unique calendar months from 1 to 12.')
    ref=np.asarray(reference,dtype=float)
    target=np.asarray(targets,dtype=float)
    w=np.asarray(weights,dtype=float)
    c=np.asarray(coefficients,dtype=float)
    if ref.ndim!=2 or ref.shape[1]!=12 or ref.shape[0]==0 or target.ndim<2 or target.shape[-2:]!=ref.shape:
        raise ValueError('Each variable requires twelve ordered monthly values.')
    if w.shape!=(ref.shape[0],) or c.shape!=w.shape:
        raise ValueError('Supply one weight and coefficient per variable.')
    if not np.all(np.isfinite(w)) or np.any(w<=0) or not math.isclose(float(w.sum()),1,abs_tol=1e-6):
        raise ValueError('Positive weights must sum to one.')
    if not np.all(np.isfinite(c)) or np.any(c<=0):
        raise ValueError('Coefficients must be finite and positive.')
    indices=np.array(months)-1
    ref=ref[:,indices];target=target[...,indices]
    if not np.all(np.isfinite(ref)):
        raise ValueError('A selected reference month has no data.')
    complete=np.all(np.isfinite(target),axis=(-2,-1))
    with np.errstate(invalid='ignore',over='ignore'):
        distance=np.sqrt(np.mean(np.square(target-ref),axis=-1))
        score=np.sum(w*c/(c+distance),axis=-1)
    return np.where(complete,score,np.nan)
