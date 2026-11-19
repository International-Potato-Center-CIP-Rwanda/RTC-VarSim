"""Non-destructive result display and exact raster-cell inspection."""
import math
import struct
import zlib
import numpy as np
from rasterio.warp import calculate_default_transform, reproject, Resampling
from build_map_layers import chunk


def filter_cells(values, mode, percent):
    """Apply the requested display threshold or top-percentage filter without modifying the original score array."""
    if mode not in ('none', 'absolute', 'top') or not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError('Choose a valid filter and a percentage between 0 and 100.')
    valid = np.isfinite(values)
    keep = valid.copy()
    if mode == 'absolute':
        keep &= values >= percent / 100
    elif mode == 'top':
        # Match upstream retention count and stable row-major tie handling.
        indices = np.flatnonzero(valid)
        remove = int(((100 - percent) / 100) * len(indices))
        order = np.argsort(values.ravel()[indices], kind='stable')
        keep.ravel()[indices[order[:remove]]] = False
    return keep


def criterion_count_preview_png(src, values):
    """Render criterion counts 0-3 and code 4 (not evaluable) as distinct classes."""
    affine,width,height=calculate_default_transform(src.crs,'EPSG:3857',src.width,src.height,*src.bounds)
    projected=np.full((height,width),255,dtype='uint8')
    reproject(values,projected,src_transform=src.transform,src_crs=src.crs,src_nodata=255,
              dst_transform=affine,dst_crs='EPSG:3857',dst_nodata=255,resampling=Resampling.nearest)
    palette=np.array([[215,48,39],[252,141,89],[145,207,96],[26,152,80],[130,130,130]],dtype='uint8')
    rgba=np.zeros((height,width,4),dtype='uint8')
    valid=projected<=4
    rgba[:,:,:3][valid]=palette[projected[valid]]
    rgba[:,:,3][valid]=255
    raw=b''.join(b'\0'+row.tobytes() for row in rgba)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

def range_class_preview_png(src, values):
    """Render below / within / above range codes as distinct transparent classes."""
    affine,width,height=calculate_default_transform(src.crs,'EPSG:3857',src.width,src.height,*src.bounds)
    projected=np.full((height,width),255,dtype='uint8')
    source=np.where(np.isfinite(values),values,255).astype('uint8')
    reproject(source,projected,src_transform=src.transform,src_crs=src.crs,src_nodata=255,
              dst_transform=affine,dst_crs='EPSG:3857',dst_nodata=255,resampling=Resampling.nearest)
    palette=np.array([[213,94,0],[0,158,115],[0,114,178]],dtype='uint8')
    rgba=np.zeros((height,width,4),dtype='uint8')
    valid=projected<=2
    rgba[:,:,:3][valid]=palette[projected[valid]]
    rgba[:,:,3][valid]=255
    raw=b''.join(b'\0'+row.tobytes() for row in rgba)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

def preview_png(src, values, land_mask=None):
    """Render a score array to PNG, distinguishing missing African land from transparent sea or outside coverage when a land mask is supplied."""
    affine, width, height = calculate_default_transform(src.crs,'EPSG:3857',src.width,src.height,*src.bounds)
    projected = np.full((height,width),np.nan,dtype='float32')
    reproject(values, projected, src_transform=src.transform,src_crs=src.crs,src_nodata=np.nan,
              dst_transform=affine,dst_crs='EPSG:3857',dst_nodata=np.nan,resampling=Resampling.nearest)
    rgba = np.zeros((height,width,4),dtype='uint8')
    t = np.clip(np.nan_to_num(projected),0,1)
    rgb = np.array([[68,1,84],[33,145,140],[253,231,37]])
    for band in range(3):
        rgba[:,:,band] = np.interp(t,[0,.5,1],rgb[:,band])
    rgba[:,:,3] = np.where(np.isfinite(projected),255,0)
    if land_mask is not None:
        projected_land=np.zeros((height,width),dtype='uint8')
        reproject(np.asarray(land_mask,dtype='uint8'),projected_land,src_transform=src.transform,src_crs=src.crs,
                  dst_transform=affine,dst_crs='EPSG:3857',resampling=Resampling.nearest)
        missing_land=(projected_land==1)&~np.isfinite(projected)
        rgba[missing_land]=[130,130,130,255]
    raw = b''.join(b'\0'+row.tobytes() for row in rgba)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
