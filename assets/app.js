/** RTC documentation: Rwanda pilot interface: manual parameters, reference-site selection, setup drafts and raster result inspection. No scientific parameter preset is inferred. */
const crop = document.getElementById('crop');
crop.addEventListener('change', () => {document.getElementById('variety').disabled = true; document.getElementById('catalogue-form').requestSubmit();});
document.getElementById('variety').addEventListener('change', () => document.getElementById('catalogue-form').requestSubmit());
const data = JSON.parse(document.getElementById('map-data').textContent);
const weights=[...document.querySelectorAll('[data-weight]')];
/** RTC documentation: Show the current manually entered weight sum so the pilot can validate it against one. */
function weightTotal(){const total=weights.reduce((sum,input)=>sum+(Number(input.value)||0),0);document.getElementById('weight-total').textContent='Weight total: '+total.toFixed(3)+' / 1.000';}
weights.forEach(input=>input.addEventListener('input',weightTotal));
document.getElementById('setup-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const status=document.getElementById('setup-status'),button=document.getElementById('export-setup');
  const parameters=[];
  for(const input of weights){
    if(input.value===''||Number(input.value)===0)continue;
    const coefficient=document.getElementById('coefficient-'+input.dataset.weight).value;
    if(coefficient===''||!Number.isFinite(Number(coefficient))||Number(coefficient)<=0){status.textContent='Enter a positive normalization coefficient for every included variable.';return;}
    parameters.push({id:input.dataset.weight,weight:Number(input.value),normalization:Number(coefficient)});
  }
  const lon=document.getElementById('longitude').value,lat=document.getElementById('latitude').value;
  if((lon==='')!==(lat==='')){status.textContent='Enter both reference coordinates, or leave both blank.';return;}
  const reference=lon===''?null:{longitude:Number(lon),latitude:Number(lat)};
  button.disabled=true;status.textContent='Checking setup…';
  try{
    const response=await fetch('/api/setup/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('#setup-form [name=csrfmiddlewaretoken]').value},body:JSON.stringify({name:document.getElementById('setup-name').value,variety:document.getElementById('setup-variety').value,parameters,rationale:document.getElementById('setup-rationale').value,reference_site:reference})});
    const result=await response.json();
    if(!response.ok){status.textContent=result.error||'Setup could not be exported.';return;}
    const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='afsa-analysis-setup-draft.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    status.textContent='Analysis file saved. No calculation was run; settings still require scientific review.';
  }catch(error){status.textContent='Unable to export. Check that the local server is running.';}
  finally{button.disabled=false;}
});
if (typeof L === 'undefined') {
  document.getElementById('map-feedback').textContent = 'Map library could not load. Please reload the page.';
} else {
  const africaBounds=[[-36,-19],[38,53]];
  const map = L.map('map', {scrollWheelZoom:true, minZoom:2, zoomSnap:.25}).fitBounds(africaBounds, {padding:[20,20]});
  map.createPane('boundaries');map.getPane('boundaries').style.zIndex=250;
  fetch('/assets/africa-boundaries.json').then(r=>{if(!r.ok)throw new Error('Boundary file unavailable');return r.json();}).then(geo=>{
    L.geoJSON(geo,{pane:'boundaries',style:{color:'#89977a',weight:1.2,fillColor:'#f4f0da',fillOpacity:1},onEachFeature:(feature,polygon)=>polygon.bindTooltip(feature.properties.name,{sticky:true})}).addTo(map);
    map.attributionControl.addAttribution('Boundaries: geoBoundaries (local file)');
    const labels=L.layerGroup().addTo(map);
    /** RTC documentation: Refresh visible crop, variety and field-source text from the selected catalogue record. */
    function refreshLabels(){
      labels.clearLayers();
      const occupied=[];
      const size=map.getSize();
      for(const feature of [...geo.features].sort((a,b)=>(b.properties.code==='RWA')-(a.properties.code==='RWA')||b.properties.area-a.properties.area)){
        const p=feature.properties;
        if(p.area<6 && map.getZoom()<5 && p.code!=='RWA')continue;
        const pos=map.latLngToContainerPoint(p.label), halfWidth=Math.min(55,p.name.length*2.8);
        if(pos.x<0||pos.y<0||pos.x>size.x||pos.y>size.y)continue;
        const rect={left:pos.x-halfWidth,right:pos.x+halfWidth,top:pos.y-10,bottom:pos.y+10};
        if(occupied.some(r=>rect.left<r.right&&rect.right>r.left&&rect.top<r.bottom&&rect.bottom>r.top))continue;
        occupied.push(rect);
        const label=document.createElement('span');label.textContent=p.name;
        L.marker(p.label,{interactive:false,icon:L.divIcon({className:'country-label',html:label,iconSize:[110,20],iconAnchor:[55,10]})}).addTo(labels);
      }
    }
    refreshLabels();map.on('moveend resize',refreshLabels);
  }).catch(()=>{document.getElementById('map-feedback').textContent='Local boundaries unavailable. Climate overlays remain visible.';});
  let layer = L.imageOverlay(data.temperature.url, data.temperature.bounds, {opacity:.85, attribution:'User-provided layers: CHELSA, SoilGrids, terrain'}).addTo(map);
  // Keep the Africa view, but show the pilot data extent (raster bounds) at any zoom.
  const coverage=L.rectangle(data.temperature.bounds,{color:'#b94d08',weight:2,dashArray:'6 4',fill:false,bubblingMouseEvents:false}).addTo(map);
  coverage.bindTooltip('Pilot data extent: raster bounds (~1 km grid). Not the Rwanda border and not a map of available pixels. Click the outline to zoom.',{sticky:true});
  coverage.on('click',()=>map.fitBounds(data.temperature.bounds,{padding:[20,20]}));
  let marker;
  let resultShown=false;
  let computationVersion=0;
  let activeResult=null, appliedFilter={mode:'none',percent:100}, viewVersion=0, inspectVersion=0, inspectMarker=null;
  const action=document.getElementById('map-action');
  const filterMode=document.getElementById('filter-mode'), filterValue=document.getElementById('filter-value');
  /** RTC documentation: Clear the previous clicked-cell display before inspecting a new result. */
  function clearInspection(){
    inspectVersion++;
    if(inspectMarker){map.removeLayer(inspectMarker);inspectMarker=null;}
    document.getElementById('inspection-status').textContent='No result cell inspected.';
  }
  /** RTC documentation: Build the legend for a pilot result preview. */
  function resultLegend(){
    document.querySelector('.legend small').textContent='Transparent: filtered out or no data';
    for(const key of Object.keys(data)){document.getElementById(key).classList.remove('active');document.getElementById(key).setAttribute('aria-pressed','false');}
    document.getElementById('map-title').textContent='Exploratory environmental similarity';
    document.getElementById('layer-source').textContent='Static method · unvalidated';
    document.querySelector('.map-note').textContent='Similarity result · filtered or NoData cells transparent';
    document.getElementById('legend-title').textContent='Similarity score (0–1)';
    document.getElementById('legend-gradient').hidden=false;document.getElementById('legend-labels').hidden=false;
    document.getElementById('legend-gradient').style.background='linear-gradient(90deg,'+activeResult.colors.join(',')+')';
    document.getElementById('legend-min').textContent='0';document.getElementById('legend-max').textContent='1';document.getElementById('legend-categories').replaceChildren();
  }
  filterMode.addEventListener('change',()=>{filterValue.disabled=filterMode.value==='none';});
  document.getElementById('apply-filter').addEventListener('click',async()=>{
    if(!activeResult)return;
    const percent=Number(filterValue.value), mode=filterMode.value;
    const status=document.getElementById('filter-status');
    if(mode!=='none'&&(filterValue.value===''||!Number.isFinite(percent)||percent<0||percent>100)){status.textContent='Enter a percentage between 0 and 100.';return;}
    const version=++viewVersion, result=activeResult;
    status.textContent='Updating display…';clearInspection();
    try{
      const response=await fetch(result.result_url+'?'+new URLSearchParams({mode,percent}));
      const preview=await response.json();
      if(version!==viewVersion||result!==activeResult)return;
      if(!response.ok)throw new Error(preview.error);
      clearInspection();appliedFilter={mode,percent};layer.setUrl(preview.image);layer.setBounds(result.bounds);resultShown=true;resultLegend();
      action.value='inspect';
      status.textContent=preview.visible_cells+' / '+preview.valid_cells+' valid cells displayed. '+(mode==='top'?'Top '+percent+'% by score. ':mode==='absolute'?'Minimum score '+percent+'%. ':'No filter. ')+'Full GeoTIFF unchanged.';
    }catch(error){if(version===viewVersion)status.textContent='Filter could not be applied. Previous display retained. '+error.message;}
  });
  document.getElementById('save-filter').addEventListener('click',()=>{
    if(!activeResult)return;
    const record={result:activeResult.files['metadata.json'],filter:appliedFilter,display_only:true,tie_policy:'Stable raster order',full_raster_unchanged:true};
    const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='afsa-display-settings.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  action.addEventListener('change',()=>{clearInspection();document.getElementById('map-feedback').textContent=action.value==='inspect'?'Click to inspect the result. Reference site stays fixed.':'Click to select a new reference. This clears the current result.';});
  /** RTC documentation: Request the clicked pilot result or filter preview and handle absent or filtered cells. */
  async function inspectResult(lat,lon){
    if(!activeResult)return;
    if(!resultShown){document.getElementById('inspection-status').textContent='Use Apply filter / Show result before inspecting.';return;}
    clearInspection();const version=inspectVersion, result=activeResult;
    const status=document.getElementById('inspection-status');status.textContent='Reading result cell…';
    try{
      const response=await fetch(result.result_url+'?'+new URLSearchParams({...appliedFilter,latitude:lat,longitude:lon}));
      const sample=await response.json();
      if(version!==inspectVersion||result!==activeResult)return;
      if(!response.ok)throw new Error(sample.error);
      const message=sample.score===null?(sample.status==='outside_extent'?'Outside result coverage.':'No data at this cell.'):'Similarity: '+(sample.score*100).toFixed(2)+'%'+(sample.status==='filtered_out'?' · hidden by display filter.':' · displayed cell.');
      status.textContent=message+' Reference site unchanged.';
      inspectMarker=L.circleMarker([lat,lon],{radius:6,color:'#1669a1',fillColor:'#fff',fillOpacity:1}).addTo(map);
      const content=document.createElement('span');content.textContent=message;inspectMarker.bindPopup(content).openPopup();
    }catch(error){if(version===inspectVersion)status.textContent='Result could not be read. '+error.message;}
  }
  /** RTC documentation: Remove the previous result layer and inspection state from the pilot map. */
  function clearResult(){
    computationVersion++;
    viewVersion++;clearInspection();activeResult=null;
    document.getElementById('result-controls').disabled=true;action.value='reference';action.options[1].disabled=true;
    document.getElementById('filter-status').textContent='Compute a result to enable inspection and filtering.';
    document.getElementById('map-feedback').textContent='Click to select a reference site in Rwanda.';
    if(resultShown){document.getElementById('temperature').click();resultShown=false;}
    document.getElementById('result-downloads').replaceChildren();
    document.getElementById('compute-status').textContent='Settings changed. Compute again to update the result.';
  }
  document.getElementById('setup-form').addEventListener('input',clearResult);
  document.addEventListener('afsa-reference-loaded',clearResult);
  [document.getElementById('longitude'),document.getElementById('latitude')].forEach(el=>el.addEventListener('input',clearResult));
  document.getElementById('run').addEventListener('click',async()=>{
    clearResult();
    let version=computationVersion;
    const status=document.getElementById('compute-status'),button=document.getElementById('run');
    const lon=document.getElementById('longitude').value,lat=document.getElementById('latitude').value;
    if(lon===''||lat===''){status.textContent='Select a reference site first.';return;}
    selectSite(Number(lat),Number(lon));
    version=computationVersion;
    const parameters=weights.filter(input=>input.value!==''&&Number(input.value)!==0).map(input=>({id:input.dataset.weight,weight:Number(input.value),normalization:Number(document.getElementById('coefficient-'+input.dataset.weight).value)}));
    const payload={name:document.getElementById('setup-name').value,variety:document.getElementById('setup-variety').value,rationale:document.getElementById('setup-rationale').value,parameters,reference_site:{longitude:Number(lon),latitude:Number(lat)}};
    button.disabled=true;status.textContent='Computing exploratory similarity…';
    try{
      const response=await fetch('/api/compute/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('#setup-form [name=csrfmiddlewaretoken]').value},body:JSON.stringify(payload)});
      const result=await response.json();
      if(version!==computationVersion)return;
      if(!response.ok)throw new Error(result.error||'Computation failed.');
      layer.setUrl(result.files['similarity.png']);layer.setBounds(result.bounds);resultShown=true;
      activeResult=result;appliedFilter={mode:'none',percent:100};filterMode.value='none';filterValue.value='100';filterValue.disabled=true;
      document.getElementById('result-controls').disabled=false;action.options[1].disabled=false;action.value='inspect';
      document.getElementById('filter-status').textContent='All valid cells displayed. Click the map to inspect scores.';
      document.getElementById('map-feedback').textContent='Inspect result mode: reference site stays fixed.';
      for(const key of Object.keys(data)){document.getElementById(key).classList.remove('active');document.getElementById(key).setAttribute('aria-pressed','false');}
      document.getElementById('map-title').textContent='Exploratory environmental similarity';
      document.getElementById('layer-source').textContent='Static method · unvalidated';
      document.querySelector('.map-note').textContent='Similarity to selected site · not crop suitability';
      document.getElementById('legend-title').textContent='Similarity score (0–1)';
      document.getElementById('legend-gradient').hidden=false;document.getElementById('legend-labels').hidden=false;
      document.getElementById('legend-gradient').style.background='linear-gradient(90deg,'+result.colors.join(',')+')';
      document.getElementById('legend-min').textContent='0';document.getElementById('legend-max').textContent='1';document.getElementById('legend-categories').replaceChildren();
      status.textContent=result.statistics.valid_cells+' valid cells. Score range: '+result.statistics.minimum.toFixed(3)+'–'+result.statistics.maximum.toFixed(3)+'. Variety tolerances are not used. Results require scientific review.';
      for(const [file,label] of [['similarity.tif','Download GeoTIFF'],['metadata.json','Download analysis record']]){const link=document.createElement('a');link.href=result.files[file];link.textContent=label;link.style.display='block';document.getElementById('result-downloads').append(link);}
    }catch(error){if(version===computationVersion)status.textContent=error.message;}
    finally{button.disabled=false;}
  });
  let requestVersion=0;
  const longitude = document.getElementById('longitude'), latitude = document.getElementById('latitude');
  const feedback = document.getElementById('site-status');
  /** RTC documentation: Update the pilot reference location from validated map or coordinate input. */
  async function selectSite(lat, lon) {
    clearResult();
    const version=++requestVersion;
    const panel=document.getElementById('site-values');panel.replaceChildren();
    if (marker) {map.removeLayer(marker);marker=null;}
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat)>90 || Math.abs(lon)>180) {feedback.textContent='Enter valid WGS84 coordinates.';return;}
    if (!L.latLngBounds(data.temperature.bounds).contains([lat,lon])) {feedback.textContent='Choose a point within the Rwanda layer extent.';return;}
    if (marker) map.removeLayer(marker);
    marker=L.marker([lat,lon],{icon:L.divIcon({className:'ref-dot',iconSize:[18,18],iconAnchor:[9,9]})}).addTo(map);
    marker.bindPopup('Selected reference site<br>'+lat.toFixed(5)+', '+lon.toFixed(5)+'<br>Field performance not verified.').openPopup();
    longitude.value=lon.toFixed(6);latitude.value=lat.toFixed(6);
    feedback.textContent='Reading environmental values…';
    try {
      const response=await fetch('/api/site/?latitude='+encodeURIComponent(lat)+'&longitude='+encodeURIComponent(lon));
      if(!response.ok)throw new Error('Unable to sample site');
      const result=await response.json();
      if(version!==requestVersion)return;
      for(const item of result.values){
        const row=document.createElement('div'),name=document.createElement('span'),value=document.createElement('strong');
        name.textContent=data[item.id].legend;
        value.textContent=item.value===null?(item.status==='unavailable'?'Layer unavailable':'No data'):(item.id==='texture'?'Code '+item.value.toFixed(0):item.value.toFixed(2));
        row.append(name,value);panel.append(row);
      }
      feedback.textContent=result.complete?'All six variables available here. Agronomic performance is not verified.':'Some variables have no data here. Do not assume complete coverage.';
    } catch(error){if(version===requestVersion)feedback.textContent='Site values could not be read. Please try again.';}
  }
  document.addEventListener('afsa-reference-loaded',event=>{
    if(event.detail){selectSite(event.detail.latitude,event.detail.longitude);}
    else{requestVersion++;if(marker){map.removeLayer(marker);marker=null;}document.getElementById('site-values').replaceChildren();feedback.textContent='No reference site selected.';}
  });
  map.on('click', e=>action.value==='inspect'?inspectResult(e.latlng.lat,e.latlng.lng):selectSite(e.latlng.lat,e.latlng.lng));
  [longitude,latitude].forEach(el=>el.addEventListener('change',()=>{if(longitude.value!==''&&latitude.value!=='')selectSite(Number(latitude.value),Number(longitude.value));}));
  document.getElementById('fit-rwanda').addEventListener('click',()=>map.fitBounds(data.temperature.bounds,{padding:[20,20]}));
  document.getElementById('fit-africa').addEventListener('click',()=>map.fitBounds(africaBounds,{padding:[20,20]}));
  for(const id of Object.keys(data))document.getElementById(id).addEventListener('click',()=>{
    document.querySelector('.legend small').textContent='Transparent areas: no data';
    viewVersion++;clearInspection();
    resultShown=false;document.querySelector('.map-note').textContent='Input layer preview · dashed outline = pilot data extent';
    layer.setUrl(data[id].url);layer.setBounds(data[id].bounds);
    for(const key of Object.keys(data)){document.getElementById(key).classList.toggle('active',key===id);document.getElementById(key).setAttribute('aria-pressed',String(key===id));}
    document.getElementById('map-title').textContent=data[id].title;
    document.getElementById('layer-source').textContent=data[id].source;
    document.getElementById('legend-title').textContent=data[id].legend;
    document.getElementById('legend-min').textContent=data[id].minimum.toFixed(2);
    document.getElementById('legend-max').textContent=data[id].maximum.toFixed(2);
    document.getElementById('legend-gradient').style.background='linear-gradient(90deg,'+data[id].colors.join(',')+')';
    const categories=document.getElementById('legend-categories');categories.replaceChildren();
    const discrete=data[id].categories.length>0;
    document.getElementById('legend-gradient').hidden=discrete;document.getElementById('legend-labels').hidden=discrete;
    for(const item of data[id].categories){const row=document.createElement('div'),swatch=document.createElement('i'),label=document.createElement('span');swatch.style.background=item.color;label.textContent=item.label;row.append(swatch,label);categories.append(row);}
  });
  document.getElementById('opacity').addEventListener('input',e=>{layer.setOpacity(Number(e.target.value)/100);document.getElementById('opacity-value').textContent=e.target.value+'%';});
}

// Restore only a server-validated file; imported text is never inserted as HTML.
/** RTC documentation: Restore a validated analysis draft into the pilot form without running a calculation. */
async function applySetup(setup){
  if(setup.variety.id!==document.getElementById('setup-variety').value){
    try{sessionStorage.setItem('afsa-pending-setup',JSON.stringify(setup));}
    catch(error){throw new Error('Browser storage is unavailable. Choose the matching variety and import again.');}
    location.href='/?crop='+encodeURIComponent(setup.variety.crop)+'&variety='+encodeURIComponent(setup.variety.id);return;
  }
  for(const input of weights){input.value='';document.getElementById('coefficient-'+input.dataset.weight).value='';}
  for(const row of setup.parameters){document.getElementById('weight-'+row.id).value=row.weight;document.getElementById('coefficient-'+row.id).value=row.normalization;}
  document.getElementById('setup-name').value=setup.name;
  document.getElementById('setup-rationale').value=setup.rationale;
  const lon=document.getElementById('longitude'),lat=document.getElementById('latitude');
  lon.value=setup.reference_site?setup.reference_site.longitude:'';
  lat.value=setup.reference_site?setup.reference_site.latitude:'';
  document.dispatchEvent(new CustomEvent('afsa-reference-loaded',{detail:setup.reference_site}));
  weightTotal();
  document.getElementById('setup-status').textContent='Analysis restored. No calculation was run. '+(setup.warnings||[]).join(' ');
}
/** RTC documentation: Ask the server to validate an imported analysis draft against current local inputs. */
async function validateImportedSetup(payload){
  const response=await fetch('/api/setup/validate/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('#setup-form [name=csrfmiddlewaretoken]').value},body:JSON.stringify(payload)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Invalid setup file.');return result;
}
document.getElementById('import-setup').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;
  const status=document.getElementById('setup-status');
  try{
    if(file.size>200000)throw new Error('Setup file is too large (maximum 200 KB).');
    const payload=JSON.parse(await file.text());
    const validated=await validateImportedSetup(payload);
    await applySetup(validated);
  }catch(error){status.textContent='Could not load setup: '+error.message;}
  finally{event.target.value='';}
});
/** RTC documentation: Restore the pending setup draft after the page has loaded, reporting validation errors. */
async function restorePendingSetup(){
  try{
    const pending=sessionStorage.getItem('afsa-pending-setup');if(!pending)return;
    sessionStorage.removeItem('afsa-pending-setup');
    const parsed=JSON.parse(pending);
    if(parsed.variety.id!==document.getElementById('setup-variety').value)throw new Error('The requested variety is not available.');
    const originalWarnings=parsed.warnings||[];
    const validated=await validateImportedSetup(parsed);
    validated.warnings=[...new Set([...originalWarnings,...validated.warnings])];
    await applySetup(validated);
  }catch(error){document.getElementById('setup-status').textContent='Restore failed: '+error.message;}
}
restorePendingSetup();
