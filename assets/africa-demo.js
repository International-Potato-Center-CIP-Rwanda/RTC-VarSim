/** RTC documentation: Africa demo map interface: separate temperature, annual rainfall, soil pH and unweighted Summary results. Reference climate similarity is a separate workflow; missing values remain explicit. */
(() => {
  const $ = id => document.getElementById(id);
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  /** RTC documentation: Mark the selected criterion tab active without changing the underlying calculation. */
  function setActiveCriterionTab(id){document.querySelectorAll('.criterion-tabs button').forEach(b=>b.setAttribute('aria-pressed',String(b.id===id)));}
  /** RTC documentation: Format the available criterion counts and explicitly retain non-evaluable cells. */
  function criterionStats(metadata){
    const count=(key,fallback)=>{
      const value=metadata[key]!==undefined&&metadata[key]!==null&&metadata[key]!==''?metadata[key]:fallback;
      if(value===undefined||value===null||value==='')return null;
      return Number.isFinite(Number(value))&&Number(value)>=0?Math.trunc(Number(value)):null;
    };
    const classes=metadata.class_counts||{};
    const below=count('cells_below_range',classes['0']);
    const within=count('cells_in_range',classes['1']);
    const above=count('cells_above_range',classes['2']);
    const valid=count('valid_cells',below!==null&&within!==null&&above!==null?below+within+above:null);
    const shareValue=metadata.share_in_range_pct;
    const share=shareValue!==undefined&&shareValue!==null&&shareValue!==''&&Number.isFinite(Number(shareValue))
      ?Number(shareValue):(valid>0&&within!==null?100*within/valid:null);
    const fmt=value=>value===null?'not reported':value.toLocaleString();
    const breakdown=below!==null&&within!==null&&above!==null
      ?`${fmt(below)} below · ${fmt(within)} within · ${fmt(above)} above`
      :'category counts not included in the server response';
    const total=valid===null?'valid-cell total not reported':`${fmt(valid)} evaluable cells for this criterion`;
    const rate=share===null?'share not reported':`${share.toFixed(1)}% within`;
    return {below,within,above,valid,share,breakdown,total,rate};
  }
  const crop=$('crop'),variety=$('variety');
  crop.addEventListener('change',()=>{variety.disabled=true;$('catalogue-form').requestSubmit();});
  variety.addEventListener('change',()=>$('catalogue-form').requestSubmit());
  for (const id of ['month-start','month-end','planting-month']) months.forEach((name,i) => $(id).add(new Option(name, i+1)));
  $('planting-month').value='1';
  /** RTC documentation: Preview the complete calendar months touched by the catalogue upper cycle duration. */
  function cyclePreview(){const opt=variety.selectedOptions[0],days=Math.ceil(Number(opt?.dataset.cycleDays));if(!Number.isFinite(days)||days<1){$('cycle-summary').textContent='Cycle duration missing in catalogue.';return;}const startMonth=Number($('planting-month').value),start=new Date(Date.UTC(2001,startMonth-1,1)),end=new Date(start.getTime()+(days-1)*86400000),seq=[];let cursor=new Date(start);while(cursor<=end){const m=cursor.getUTCMonth()+1;if(!seq.includes(m))seq.push(m);cursor=new Date(Date.UTC(cursor.getUTCFullYear(),cursor.getUTCMonth()+1,1));}$('cycle-summary').textContent=`Using ${days} days (catalogue upper bound): ${seq.map(m=>months[m-1].slice(0,3)).join(', ')}. Whole month normals are included.`;}
  $('planting-month').addEventListener('change',cyclePreview);cyclePreview();
  $('month-start').value = '1'; $('month-end').value = '3';
  const map = L.map('map', {zoomControl:true, scrollWheelZoom:true, minZoom:2, zoomSnap:.25}).setView([2,18],3);
  const africaBounds = L.latLngBounds([[-36,-19],[38,53]]);
  map.fitBounds(africaBounds);
  // The demo map can be laid out after the first synchronous fitBounds call.
  // Recalculate once the browser has painted the panel so the first view is
  // centred correctly without requiring the user to click “Africa view”.
  map.whenReady(() => requestAnimationFrame(() => {
    map.invalidateSize({pan:false});
    map.fitBounds(africaBounds,{padding:[18,18]});
  }));
  fetch('/assets/africa-boundaries.json').then(r=>{if(!r.ok)throw new Error('Boundary file unavailable');return r.json();}).then(geo=>{
    map.createPane('country-fill');map.getPane('country-fill').style.zIndex=250;
    map.createPane('country-lines');map.getPane('country-lines').style.zIndex=450;
    L.geoJSON(geo,{pane:'country-fill',style:{color:'#89977a',weight:1.05,fillColor:'#f4f0da',fillOpacity:1},onEachFeature:(feature,polygon)=>{
      polygon.bindTooltip(feature.properties.name,{sticky:true});
      // The country polygons sit above the raster. Handle clicks on them too,
      // otherwise users may only see the country tooltip instead of a score.
      polygon.on('click',e=>{if(resultRun){L.DomEvent.stopPropagation(e);inspectScore(e.latlng);}});
    }}).addTo(map);
    L.geoJSON(geo,{pane:'country-lines',interactive:false,style:{color:'#89977a',weight:1,fillOpacity:0}}).addTo(map);
    map.attributionControl.addAttribution('Boundaries: geoBoundaries (local file)');
    const labels=L.layerGroup().addTo(map);
    /** RTC documentation: Refresh visible crop, variety and field-source text from the selected catalogue record. */
    function refreshLabels(){
      labels.clearLayers();const occupied=[],size=map.getSize();
      for(const feature of [...geo.features].sort((a,b)=>(b.properties.code==='RWA')-(a.properties.code==='RWA')||b.properties.area-a.properties.area)){
        const p=feature.properties;if(p.area<6&&map.getZoom()<5&&p.code!=='RWA')continue;
        const pos=map.latLngToContainerPoint(p.label),halfWidth=Math.min(55,p.name.length*2.8);
        if(pos.x<0||pos.y<0||pos.x>size.x||pos.y>size.y)continue;
        const rect={left:pos.x-halfWidth,right:pos.x+halfWidth,top:pos.y-10,bottom:pos.y+10};
        if(occupied.some(r=>rect.left<r.right&&rect.right>r.left&&rect.top<r.bottom&&rect.bottom>r.top))continue;
        occupied.push(rect);const label=document.createElement('span');label.textContent=p.name;
        L.marker(p.label,{interactive:false,icon:L.divIcon({className:'country-label',html:label,iconSize:[110,20],iconAnchor:[55,10]})}).addTo(labels);
      }
    }
    refreshLabels();map.on('moveend resize',refreshLabels);
  }).catch(()=>{$('map-message').textContent='Country boundaries are unavailable; climate results can still be viewed.';});
  let marker = null, overlay = null, reference = null, resultRun = null, screenRun = null, criterionRun = null, summaryRun = null;
  const fmt = (n,d=1) => Number(n).toFixed(d);
  const rangeColor = (part) => {
    const anchors=[[68,1,84],[33,145,140],[253,231,37]],t=Math.max(0,Math.min(1,part))*2,lo=Math.min(1,Math.floor(t)),mix=t-lo;
    return `rgb(${anchors[lo].map((v,i)=>Math.round(v+(anchors[lo+1][i]-v)*mix)).join(',')})`;
  };
  /** RTC documentation: Render one legend row per range class, keeping labels and cell totals within the frame. */
  function renderRangeLegend(metadata){
    $('legend').innerHTML='<strong>Months with mean temperature in range</strong><div id="range-classes" class="range-classes"></div><small class="range-note"></small>';
    const classes=$('range-classes'),count=metadata.months.length;
    for(let inside=0;inside<=count;inside++){
      const item=document.createElement('div'),swatch=document.createElement('span'),label=document.createElement('span');
      item.className='range-class';swatch.className='range-swatch';swatch.style.backgroundColor=rangeColor(count?inside/count:0);
      label.textContent=`${inside} of ${count} month${count===1?'':'s'} · ${Number(metadata.class_counts?.[String(inside)] || 0).toLocaleString()} cells`;item.append(swatch,label);classes.append(item);
    }
    const missing=document.createElement('div');missing.className='range-class';
    const missingSwatch=document.createElement('span');missingSwatch.className='range-swatch';missingSwatch.style.backgroundColor='#828282';
    const missingLabel=document.createElement('span');missingLabel.textContent=`Not evaluable · ${Number(metadata.not_evaluable_cells || 0).toLocaleString()} cells`;
    missing.append(missingSwatch,missingLabel);classes.append(missing);
    $('legend').querySelector('.range-note').textContent=`Total: ${metadata.valid_cells.toLocaleString()} evaluable cells · ${Number(metadata.not_evaluable_cells || 0).toLocaleString()} land cells not evaluable (grey). Sea and outside Africa are transparent.`;
  }
  const setStatus = (id,text,error=false) => { const el=$(id); el.textContent=text; el.classList.toggle('error',error); };
  const csrfToken = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || document.cookie.split('; ').find(row=>row.startsWith('csrftoken='))?.split('=').slice(1).join('=') || '';
  const coordinates = () => ({longitude:Number($('longitude').value),latitude:Number($('latitude').value)});
  /** RTC documentation: Enable the relevant actions only when their required reference and form inputs are ready. */
  function updateReadiness(){
    const w1=Number($('temperature-weight').value),w2=Number($('rainfall-weight').value),total=w1+w2;
    $('weight-total').textContent=Number.isFinite(total)&&total>0?`Weight total: ${total.toFixed(3)} / 1.000`:'Weight total: not set';
    $('weight-total').classList.toggle('bad-total',Math.abs(total-1)>1e-6);
    const ready=reference&&$('acknowledge').checked&&w1>0&&w2>0&&Math.abs(total-1)<=1e-6&&Number($('temperature-coefficient').value)>0&&Number($('rainfall-coefficient').value)>0;
    $('compute').disabled=!ready;
  }
  /** RTC documentation: Request native monthly climate for the selected reference coordinates and report missing data. */
  async function loadSite(lon,lat){
    if(resultRun||screenRun||criterionRun||summaryRun){resultRun=null;screenRun=null;criterionRun=null;summaryRun=null;if(overlay){map.removeLayer(overlay);overlay=null;}$('legend').hidden=true;$('downloads').hidden=true;}
    $('longitude').value=lon.toFixed(5);$('latitude').value=lat.toFixed(5);
    setStatus('site-status','Reading native monthly climate values…');
    try{
      const res=await fetch(`/api/demo/site/?longitude=${encodeURIComponent(lon)}&latitude=${encodeURIComponent(lat)}`),data=await res.json();
      if(!res.ok)throw new Error(data.error||'Could not read this location.');
      reference={longitude:lon,latitude:lat,values:data.values};
      if(marker)map.removeLayer(marker);
      marker=L.marker([lat,lon],{icon:L.divIcon({className:'',html:'<span class="reference-marker"></span>',iconSize:[15,15],iconAnchor:[7,7]})}).addTo(map);
      $('site-values').replaceChildren();
      for(let vi=0;vi<2;vi++){
        const title=vi===0?'Temperature (°C)':'Rainfall (mm/month)';
        for(let m=0;m<12;m++){const row=document.createElement('div');row.innerHTML=`<span>${title} · ${months[m].slice(0,3)}</span><strong>${fmt(data.values[vi][m],vi?1:2)}</strong>`;$('site-values').append(row);}
      }
      setStatus('site-status',`Reference ready · ${lat.toFixed(3)}°, ${lon.toFixed(3)}° · native raster values.`);
      $('map-title').textContent=`Reference site · ${lat.toFixed(2)}°, ${lon.toFixed(2)}°`;
      $('map-message').textContent='Reference climate loaded. Set months and exploratory parameters to calculate.';
      updateReadiness();
    }catch(e){reference=null;setStatus('site-status',e.message,true);updateReadiness();}
  }
  /** RTC documentation: Inspect the clicked climate-similarity pixel and show its descriptive score. */
  async function inspectScore(latlng){
    try{
      const q=new URLSearchParams({longitude:latlng.lng,latitude:latlng.lat});
      const res=await fetch(`/api/demo/runs/${resultRun}/score/?${q}`);
      const data=await res.json().catch(()=>{throw new Error(`The score endpoint returned a non-JSON page (HTTP ${res.status}). Restart the local Django server, then refresh the page.`);});
      if(!res.ok)throw new Error(data.error||'No score at this point.');
      L.popup().setLatLng(latlng).setContent(`<strong>Similarity index: ${data.index_percent.toFixed(2)}%</strong><br><small>Scaled exploratory score for this map location; not a probability or variety suitability.</small>`).openOn(map);
    }catch(err){setStatus('compute-status',err.message,true);}
  }
  /** RTC documentation: Inspect the clicked temperature result and display the cycle-month temperatures. */
  async function inspectTemperatureRange(latlng){
    try{
      const q=new URLSearchParams({longitude:latlng.lng,latitude:latlng.lat});
      const res=await fetch(`/api/demo/runs/${screenRun}/temperature-range/?${q}`);
      const data=await res.json().catch(()=>{throw new Error(`The result endpoint returned a non-JSON page (HTTP ${res.status}).`);});
      if(!res.ok)throw new Error(data.error||'No temperature check at this point.');
      const details=data.monthly_values.map(item=>`${months[item.month-1].slice(0,3)} ${item.temperature_c.toFixed(1)} °C ${item.within_range?'✓':'✗'}`).join(' · ');
      L.popup().setLatLng(latlng).setContent(`<strong>${data.inside_months} of ${data.month_count} monthly means in range (${(data.share*100).toFixed(0)}%)</strong><br><small>${details}<br>Catalogue range: ${data.lower_c}–${data.upper_c} °C. Monthly means only; not validated suitability.</small>`).openOn(map);
    }catch(err){setStatus('screen-status',err.message,true);}
  }
  /** RTC documentation: Inspect annual rainfall or soil pH at a clicked display cell. */
  async function inspectCriterion(latlng){
    try{const q=new URLSearchParams({longitude:latlng.lng,latitude:latlng.lat});const res=await fetch(`/api/demo/runs/${criterionRun}/criterion-range/?${q}`);const data=await res.json();if(!res.ok)throw new Error(data.error||'No value at this location.');const ph=data.criterion==='soil_ph',detail=data.monthly_values?.length?`<br>${data.monthly_values.map(x=>`${months[x.month-1].slice(0,3)} ${x.rainfall_mm.toFixed(1)} mm`).join(' · ')}`:'';const value=ph?data.value.toFixed(1):data.value.toFixed(1);const source=ph?`Source: ${data.source}.`:'Annual comparison using the catalogue rainfall period; seasonal requirements would be more precise.';L.popup().setLatLng(latlng).setContent(`<strong>${value} ${data.units} · ${data.in_range?'within':'outside'} range</strong><br><small>Catalogue range: ${data.lower}–${data.upper} ${data.units}.${detail}<br>${source}</small>`).openOn(map);}catch(err){setStatus('screen-status',err.message,true);}
  }
  /** RTC documentation: Display all three criteria for the clicked Summary cell, including missing-data status. */
  async function inspectSummary(latlng){
      try{
        const q=new URLSearchParams({longitude:latlng.lng,latitude:latlng.lat});
        const res=await fetch(`/api/demo/runs/${summaryRun}/summary/?${q}`);
        const data=await res.json();
        if(!res.ok)throw new Error(data.error||'No combined result at this location.');
        if(data.status==='outside_africa'){
          L.popup().setLatLng(latlng).setContent('<strong>Outside the African land analysis area.</strong>').openOn(map);return;
        }
        const mark=value=>value===null?'not evaluable':value?'✓':'✗';
        const c=data.criteria;
        const temp=c.temperature.monthly_values.map(x=>`${months[x.month-1].slice(0,3)} ${x.value_c===null?'—':x.value_c.toFixed(1)+' °C'} ${x.value_c===null?'':x.within_range?'✓':'✗'}`).join(' · ');
        const rain=c.rainfall.monthly_values.map(x=>`${months[x.month-1].slice(0,3)} ${x.value_mm===null?'—':x.value_mm.toFixed(1)+' mm'}`).join(' · ');
        const cycleRain=c.rainfall.cycle_monthly_values.map(x=>`${months[x.month-1].slice(0,3)} ${x.value_mm===null?'—':x.value_mm.toFixed(1)+' mm'}`).join(' · ');
        const count=data.status==='not_evaluable'?data.message:`${data.criteria_satisfied} of 3 criteria satisfied at this displayed cell.`;
        const annualRain=c.rainfall.annual_total_mm;
        const cycleRainTotal=c.rainfall.cycle_total_mm;
        const cycleShare=Number.isFinite(annualRain)&&annualRain>0&&Number.isFinite(cycleRainTotal)
          ? ` (${(100*cycleRainTotal/annualRain).toFixed(1)}% of annual total)` : '';
        const content=`<strong>${count}</strong><br><small>Cell: lat ${data.latitude.toFixed(4)}°, lon ${data.longitude.toFixed(4)}°<br>`+
          `Temperature (${c.temperature.lower}–${c.temperature.upper} °C): ${temp}; ${c.temperature.months_in_range}/${c.temperature.month_count} months in range · ${mark(c.temperature.within_range)}<br>`+
          `Annual rainfall (${c.rainfall.lower}–${c.rainfall.upper} mm/year): ${rain}; total ${c.rainfall.annual_total_mm===null?'not evaluable':c.rainfall.annual_total_mm.toFixed(1)+' mm/year'} · ${mark(c.rainfall.within_range)}<br>`+
          `Rainfall during cycle (${data.months.map(m=>months[m-1].slice(0,3)).join(', ')}): ${cycleRain}; total ${cycleRainTotal===null?'not evaluable':cycleRainTotal.toFixed(1)+' mm'+cycleShare}; descriptive only, not compared with the annual range. Annual rainfall can conceal dry-season gaps.<br>`+
          `Soil pH (${c.soil_ph.lower}–${c.soil_ph.upper}): ${c.soil_ph.value===null?'not evaluable':c.soil_ph.value.toFixed(1)} · ${mark(c.soil_ph.within_range)}<br>${c.soil_ph.source||'SoilGrids pH (H₂O), 0–30 cm, thickness-weighted mean.'}<br>`+
          `Planting month: ${months[data.planting_month-1]}; cycle months: ${data.months.map(m=>months[m-1].slice(0,3)).join(', ')}.<br>Unweighted exploratory count; not a validated suitability result.</small>`;
        L.popup().setLatLng(latlng).setContent(content).openOn(map);
      }catch(err){setStatus('screen-status',err.message,true);}
  }
  map.on('click',e=>{if(summaryRun)inspectSummary(e.latlng);else if(screenRun)inspectTemperatureRange(e.latlng);else if(criterionRun)inspectCriterion(e.latlng);else if(resultRun)inspectScore(e.latlng);else loadSite(e.latlng.lng,e.latlng.lat);});
  $('load-site').addEventListener('click',()=>{const p=coordinates();if(!Number.isFinite(p.longitude)||!Number.isFinite(p.latitude)){setStatus('site-status','Enter valid longitude and latitude.',true);return;}loadSite(p.longitude,p.latitude);});
  $('demo-settings').addEventListener('click',()=>{$('temperature-weight').value='0.5';$('rainfall-weight').value='0.5';$('temperature-coefficient').value='10';$('rainfall-coefficient').value='50';$('rationale').hidden=false;updateReadiness();});
  for(const id of ['temperature-weight','rainfall-weight','temperature-coefficient','rainfall-coefficient','acknowledge'])$(id).addEventListener('input',updateReadiness);
  $('compute').addEventListener('click',async()=>{
    if(!reference)return;
    const payload={longitude:reference.longitude,latitude:reference.latitude,start:Number($('month-start').value),end:Number($('month-end').value),temperature_weight:Number($('temperature-weight').value),rainfall_weight:Number($('rainfall-weight').value),temperature_coefficient:Number($('temperature-coefficient').value),rainfall_coefficient:Number($('rainfall-coefficient').value),acknowledge:$('acknowledge').checked};
    $('compute').disabled=true;setStatus('compute-status','Calculating the sampled Africa grid…');$('map-message').textContent='Calculating similarity…';
    try{
      const res=await fetch('/api/demo/compute/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken()},body:JSON.stringify(payload)});
      const data=await res.json().catch(()=>({error:`The server returned an unexpected response (HTTP ${res.status}). Refresh and try again.`}));
      if(!res.ok)throw new Error(data.error||'Calculation failed.');
      if(overlay)map.removeLayer(overlay);
      resultRun=data.id;screenRun=null;criterionRun=null;summaryRun=null;
      $('legend').innerHTML='<strong>Similarity index · 0–100%</strong><div class="score-gradient"></div><div class="score-labels"><span>0% · lower</span><span>100% · higher</span></div><small>Click a colored location to see its index. Rescaled score, not a probability or variety suitability.</small>';
      overlay=L.imageOverlay(`/demo/runs/${data.id}/similarity.png`,data.bounds,{opacity:.9,interactive:false,alt:'Monthly climate similarity score; not variety suitability'}).addTo(map);
      $('legend').hidden=false;$('downloads').hidden=false;$('downloads').replaceChildren();
      for(const [label,file] of [['Download GeoTIFF','similarity.tif'],['Download metadata','metadata.json']]){const a=document.createElement('a');a.href=`/demo/runs/${data.id}/${file}`;a.textContent=label;a.download=true;$('downloads').append(a);}
      const span=document.createElement('span');span.textContent=`${data.metadata.valid_cells.toLocaleString()} sampled cells · ${data.metadata.months.map(m=>months[m-1].slice(0,3)).join(', ')}`;$('downloads').append(span);
      map.fitBounds(africaBounds);$('map-title').textContent=`Similarity · ${months[data.metadata.months[0]-1]}–${months[data.metadata.months[data.metadata.months.length-1]-1]}`;
      $('map-note').textContent='Climate similarity only · selected variety is not scored';
      $('map-footer-primary').textContent='Higher scores mean closer selected-month climate under the chosen coefficients.';
      $('map-message').textContent='Similarity map ready. Click any colored location to see its score (%)';
      setStatus('compute-status',`Map ready · ${data.metadata.valid_cells.toLocaleString()} sampled cells. This result is exploratory, not a suitability map.`);
    }catch(e){setStatus('compute-status',e.message,true);$('map-message').textContent='Calculation could not be completed.';}
    updateReadiness();
  });
  $('screen-variety').addEventListener('click',async()=>{
    const button=$('screen-variety');button.disabled=true;
    setStatus('screen-status','Checking monthly mean temperatures over the selected crop cycle…');
    try{
      const res=await fetch('/api/demo/variety-temperature/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken()},body:JSON.stringify({variety_id:variety.value,planting_month:Number($('planting-month').value)})});
      const data=await res.json().catch(()=>({error:`The server returned an unexpected response (HTTP ${res.status}). Refresh and try again.`}));
      if(data.status==='not_evaluable'){setStatus('screen-status',`Not evaluable: ${data.reason}`);button.disabled=false;return;}
      if(!res.ok)throw new Error(data.error||'Temperature check failed.');
      if(!data.id||!Array.isArray(data.bounds)||data.bounds.length!==2||!Array.isArray(data.metadata?.months))throw new Error('Incomplete temperature response. Reload the page and try again.');
      setActiveCriterionTab('screen-variety');
      if(overlay)map.removeLayer(overlay);
      resultRun=null;screenRun=data.id;criterionRun=null;summaryRun=null;
      renderRangeLegend(data.metadata);
      overlay=L.imageOverlay(`/demo/runs/${data.id}/temperature-range.png`,data.bounds,{opacity:.9,interactive:false,alt:'Descriptive check of monthly mean temperatures against the selected variety range'}).addTo(map);
      $('legend').hidden=false;$('downloads').hidden=false;$('downloads').replaceChildren();
      for(const [label,file] of [['Download temperature check GeoTIFF','temperature-range.tif'],['Download check details','temperature-range.json']]){const a=document.createElement('a');a.href=`/demo/runs/${data.id}/${file}`;a.textContent=label;a.download=true;$('downloads').append(a);}
      const span=document.createElement('span');span.textContent=`${data.metadata.valid_cells.toLocaleString()} sampled cells · ${data.metadata.months.map(m=>months[m-1].slice(0,3)).join(', ')}`;$('downloads').append(span);
      map.fitBounds(africaBounds);$('map-title').textContent=`${data.metadata.variety_name} · temperature range check`;
      $('map-note').textContent='Descriptive temperature check · not crop suitability';
      $('map-footer-primary').textContent=`Temperature range check over ${data.metadata.months.map(m=>months[m-1].slice(0,3)).join(', ')}; full monthly means, upper cycle duration ${data.metadata.cycle_days_used} days.`;
      $('map-message').textContent='Click a colored location to see the temperature value for each selected month.';
      setStatus('screen-status',`Temperature check ready · ${data.metadata.valid_cells.toLocaleString()} cells · cycle months ${data.metadata.months.map(m=>months[m-1].slice(0,3)).join(', ')}.`);
    }catch(e){setStatus('screen-status',e.message,true);$('map-message').textContent='Temperature check could not be completed.';}
    button.disabled=false;
  });

  /** RTC documentation: Request the chosen exploratory criterion result and update the map, legend and counts. */
  async function runCriterionCheck(criterion,buttonId){
    const button=$(buttonId);button.disabled=true;
    setStatus('screen-status',criterion==='annual_rainfall'?'Summing the twelve monthly precipitation normals to compare annual rainfall…':'Comparing the catalogue pH range with SoilGrids across Africa…');
    try{
      const res=await fetch('/api/demo/variety-criterion/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken()},body:JSON.stringify({variety_id:variety.value,criterion,planting_month:Number($('planting-month').value)})});
      const data=await res.json().catch(()=>({error:`The server returned an unexpected response (HTTP ${res.status}). Refresh and try again.`}));
      if(data.status==='not_evaluable'){setStatus('screen-status',`Not evaluable: ${data.reason}`);button.disabled=false;return;}
      if(!res.ok)throw new Error(data.error||'Criterion check failed.');
      if(!data.id||!Array.isArray(data.bounds)||data.bounds.length!==2||!data.metadata)throw new Error('The server response is incomplete. Restart Django and reload the page with Ctrl+F5, then try again.');
      const stats=criterionStats(data.metadata);
      const coverage=typeof data.metadata.coverage==='string'?data.metadata.coverage:'Counts use valid sampled cells for this criterion only.';
      const source=criterion==='soil_ph'&&data.metadata.source?` · ${data.metadata.source}`:'';
      const rangeNote=`${stats.breakdown} · ${stats.total} (${stats.rate}). ${coverage} Summary counts only cells with valid temperature, rainfall and pH. Separate screening criterion, not validated suitability.${source}`;
      const countLabel=`${stats.breakdown} (${stats.total})`;
      const nextOverlay=L.imageOverlay(`/demo/runs/${data.id}/criterion-range.png`,data.bounds,{opacity:.9,interactive:false,alt:'Separate descriptive catalogue-range criterion check'});
      const nextDownloads=document.createDocumentFragment();
      for(const [label,file] of [['Download criterion GeoTIFF','criterion-range.tif'],['Download criterion details','criterion-range.json']]){const a=document.createElement('a');a.href=`/demo/runs/${data.id}/${file}`;a.textContent=label;a.download=true;nextDownloads.append(a);}
      const span=document.createElement('span');span.textContent=countLabel;nextDownloads.append(span);
      nextOverlay.addTo(map);
      const previousOverlay=overlay;
      overlay=nextOverlay;
      if(previousOverlay)map.removeLayer(previousOverlay);
      setActiveCriterionTab(buttonId);
      resultRun=null;screenRun=null;criterionRun=data.id;summaryRun=null;
      $('legend').innerHTML='<strong>Catalogue range check</strong><div class="criterion-legend"><span><i class="below-range"></i>Below range</span><span><i class="in-range"></i>Within range</span><span><i class="above-range"></i>Above range</span></div><small class="range-note"></small>';
      $('legend').querySelector('.range-note').textContent=rangeNote;
      $('legend').hidden=false;$('downloads').hidden=false;$('downloads').replaceChildren(nextDownloads);
      $('map-title').textContent=`${data.metadata.variety_name} · ${criterion==='annual_rainfall'?'annual rainfall':'soil pH'} check`;
      $('map-note').textContent=criterion==='annual_rainfall'?'Annual rainfall range · catalogue period':'Soil pH range · SoilGrids 0–30 cm';
      $('map-footer-primary').textContent=data.metadata.method;
      $('map-message').textContent='Click a colored cell to inspect its value and catalogue range.';
      setStatus('screen-status',`${stats.within===null?'The server did not report the in-range cell count.':`${stats.within.toLocaleString()} of ${stats.valid===null?'an unreported number of':stats.valid.toLocaleString()} criterion-valid cells fall in the listed range.`} ${coverage}${source}`);
      if(criterion==='soil_ph')map.fitBounds(data.bounds,{padding:[18,18]});else map.fitBounds(africaBounds);
    }catch(e){setStatus('screen-status',e.message,true);$('map-message').textContent='The previous map is still displayed. Criterion check could not be completed.';}
    button.disabled=false;
  }
  $('screen-rainfall').addEventListener('click',()=>runCriterionCheck('annual_rainfall','screen-rainfall'));
  $('screen-ph').addEventListener('click',()=>runCriterionCheck('soil_ph','screen-ph'));
  $('screen-summary').addEventListener('click',async()=>{
    const button=$('screen-summary');button.disabled=true;setStatus('screen-status','Counting satisfied temperature, rainfall and pH criteria…');
    try{
      const res=await fetch('/api/demo/variety-summary/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken()},body:JSON.stringify({variety_id:variety.value,planting_month:Number($('planting-month').value)})});
      const data=await res.json().catch(()=>({error:`The server returned an unexpected response (HTTP ${res.status}).`}));
      if(data.status==='not_evaluable'){setStatus('screen-status',`Not evaluable: ${data.reason}`);button.disabled=false;return;}
      if(!res.ok)throw new Error(data.error||'Combined check failed.');
      setActiveCriterionTab('screen-summary-tab');
      if(overlay)map.removeLayer(overlay);resultRun=null;screenRun=null;criterionRun=null;summaryRun=data.id;
      const criterionNames={temperature:'Temperature',rainfall:'Rainfall',soil_ph:'Soil pH'};
      const criterionShares=Object.entries(data.metadata.per_criterion).map(([name,item])=>'<span>'+criterionNames[name]+': '+(item.share_satisfied_pct===null?'n/a':item.share_satisfied_pct.toFixed(1)+'%')+' ('+item.satisfied_cells.toLocaleString()+' / '+item.valid_cells.toLocaleString()+')</span>').join('');
      $('legend').innerHTML='<strong>Number of criteria satisfied</strong><div class="criterion-legend"><span><i style="background:#d73027"></i>0 of 3</span><span><i style="background:#fc8d59"></i>1 of 3</span><span><i style="background:#91cf60"></i>2 of 3</span><span><i style="background:#1a9850"></i>3 of 3</span><span><i style="background:#828282"></i>African land · not evaluable</span></div><small>Unweighted count. Sea and areas outside Africa are transparent. Missing values, including −9999, are not evaluable; they are not failures.</small><div class="criterion-shares"><b>Individual criteria</b>'+criterionShares+'</div>';
      overlay=L.imageOverlay(`/demo/runs/${data.id}/summary.png`,data.bounds,{opacity:.9,interactive:false,alt:'Count of criteria satisfied; grey means not evaluable'}).addTo(map);
      $('legend').hidden=false;$('downloads').hidden=false;$('downloads').replaceChildren();
      for(const [label,file] of [['Download summary GeoTIFF','summary.tif'],['Download summary details','summary.json']]){const a=document.createElement('a');a.href=`/demo/runs/${data.id}/${file}`;a.textContent=label;a.download=true;$('downloads').append(a);}
      const span=document.createElement('span');span.textContent=`${data.metadata.valid_cells.toLocaleString()} evaluable land cells · ${data.metadata.not_evaluable_cells.toLocaleString()} African land cells not evaluable · ${data.metadata.outside_africa_or_sea_cells.toLocaleString()} sea/outside grid cells transparent`;$('downloads').append(span);
      $('map-title').textContent=`${data.metadata.variety_name} · criteria count (0–3)`;$('map-note').textContent='Unweighted exploratory criteria count · not validated suitability';$('map-footer-primary').textContent='Temperature, rainfall and SoilGrids pH use the sampled Africa grid; missing values are not evaluable.';$('map-message').textContent='Click a cell to see its criteria count, monthly temperatures, rainfall and soil pH; grey means not evaluable.';
      map.fitBounds(africaBounds);const counts=data.metadata.counts;setStatus('screen-status',`Summary ready · 0: ${counts['0'].toLocaleString()} · 1: ${counts['1'].toLocaleString()} · 2: ${counts['2'].toLocaleString()} · 3: ${counts['3'].toLocaleString()} · African land not evaluable: ${data.metadata.not_evaluable_cells.toLocaleString()}.`);
    }catch(e){setStatus('screen-status',e.message,true);}button.disabled=false;
  });
  $('screen-summary-tab').addEventListener('click',()=>$('screen-summary').click());
  $('africa-view').addEventListener('click',()=>map.fitBounds(africaBounds));
  $('reference-view').addEventListener('click',()=>{if(reference)map.setView([reference.latitude,reference.longitude],7);});
  updateReadiness();
})();
