"""Build local Web Mercator display overlays from the verified source rasters."""
import json
import struct
import zlib
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds

BASE=Path(__file__).resolve().parent
STYLES={
 'temperature':('Mean annual temperature','Temperature (°C)',['#2d784b','#add377','#fff5a1','#f4b04f','#c34d2e'],'CHELSA · 1981–2010'),
 'rainfall':('Annual precipitation','Precipitation (mm/year)',['#f9e799','#b4daae','#64b9c5','#317fb0','#25477f'],'CHELSA · 1981–2010'),
 'ph':('Soil pH · 0–5 cm','Soil pH',['#b85c38','#e5be72','#f4f0c6','#8ac49f','#357e74'],'SoilGrids · 0–5 cm'),
 'elevation':('Mean elevation','Elevation (m)',['#649558','#bad180','#e8d99a','#b29d85','#f4f1e9'],'User-prepared DEM · source to confirm'),
 'slope':('Mean local slope','Slope (%)',['#f1efcf','#c2d28d','#79a965','#bd984c','#82493d'],'Mean of local slopes · percent'),
 'texture':('Soil texture classes','Texture class codes',['#bd704b','#e3aa52','#a7b96b','#63947e','#73aabd','#9981aa','#c28291'],'USDA codes · class names to confirm')
}

def chunk(kind,data):
 """Encode one PNG chunk with its length and CRC for the generated map preview."""
 return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)

def main():
 """Generate Rwanda pilot PNG previews and layer metadata from the existing harmonized local rasters."""
 cfg=json.loads((BASE/'data/pilot.json').read_text(encoding='utf-8'))
 metadata={}
 for entry in cfg['layers']+cfg['supplemental_layers']:
  key=entry['id']; title,legend,colors,source=STYLES[key]
  with rasterio.open(entry['path']) as src:
   transform,width,height=calculate_default_transform(src.crs,'EPSG:3857',src.width,src.height,*src.bounds)
   original=src.read(1,masked=True).astype('float32')
   a=np.full((height,width),np.nan,dtype='float32')
   reproject(source=original.filled(np.nan),destination=a,src_transform=src.transform,src_crs=src.crs,src_nodata=np.nan,
             dst_transform=transform,dst_crs='EPSG:3857',dst_nodata=np.nan,resampling=Resampling.nearest)
   values=original.compressed(); values=values[np.isfinite(values)]
   low,high=float(values.min()),float(values.max())
   rgb=np.array([[int(c[i:i+2],16) for i in (1,3,5)] for c in colors])
   rgba=np.zeros((height,width,4),dtype='uint8')
   categories=[]
   if key=='texture':
    for i,code in enumerate(np.unique(values)):
     rgba[a==code,:3]=rgb[i]
     categories.append({'value':int(code),'label':f'Code {int(code)}','color':colors[i]})
   else:
    t=np.clip((np.nan_to_num(a,nan=low)-low)/(high-low),0,1)
    for band in range(3):rgba[:,:,band]=np.interp(t,np.linspace(0,1,len(rgb)),rgb[:,band])
   rgba[:,:,3]=np.where(np.isfinite(a),255,0)
   data=b''.join(b'\0'+row.tobytes() for row in rgba)
   png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(data))+chunk(b'IEND',b'')
   (BASE/'assets'/f'{key}.png').write_bytes(png)
   west,south,east,north=transform_bounds('EPSG:3857','EPSG:4326',transform.c,transform.f+transform.e*height,transform.c+transform.a*width,transform.f)
   metadata[key]={'url':f'/assets/{key}.png','bounds':[[south,west],[north,east]],'minimum':low,'maximum':high,
    'title':title,'legend':legend,'colors':colors,'categories':categories,'source':source,'unit':entry['unit'],
    'valid_cells':int(len(values)),'file':Path(entry['path']).name}
 (BASE/'assets/rwanda_layers.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
 print('Created 6 local overlays. Source rasters unchanged.')

if __name__=='__main__':main()
