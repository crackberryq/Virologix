export default function(component) {
  const {parentElement, data, setTriggerValue} = component;
  const root = parentElement.querySelector('.bacto-root');
  root._dispose?.();
  const abort = new AbortController();
  let pollTimer;
  root._dispose = () => {abort.abort();clearTimeout(pollTimer);};
  const on = (target, event, callback) => target.addEventListener(event, callback, {signal:abort.signal});
  const $ = selector => root.querySelector(selector);
  const U = root._virologixState ||= {view:'overview', filter:'', draft:{}, pending:null, responseId:null, inspection:null, filename:'', notice:null};
  const S = data.workspace;
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const paths = {overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',samples:'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',cfasta:'M8 3H5v18h14V7l-4-4H8 M14 3v5h5 M8 12h8 M8 16h5',pipelines:'M4 4h5v5H4z M15 15h5v5h-5z M6 9v8h9 M9 6h8v9',runs:'M8 5l11 7-11 7z',setup:'M4 7h16 M4 17h16 M8 4v6 M16 14v6',resources:'M3 5h18v14H3z M3 10h18 M7 14h3',updates:'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5',arrow:'M5 12h14 M14 7l5 5-5 5'};
  const sharedIcons={home:'M3 10 12 3l9 7M5 9v12h14V9M9 21v-7h6v7',samples:'M5 3h14v18H5zM9 8h6M9 12h6M9 16h4',install:'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',resources:'M4 6c0-4 16-4 16 0s-16 4-16 0m0 0v12c0 4 16 4 16 0V6M4 12c0 4 16 4 16 0',config:'M4 7h16M4 17h16M8 4v6m8 4v6',jobs:'M8 5h12v16H4V5h4m0-2h8v4H8zM8 12h8m-8 4h5',compare:'M5 20V10m7 10V4m7 16v-7M3 21h18',plus:'M12 5v14M5 12h14',arrow:'M5 12h14m-5-5 5 5-5 5',clone:'M8 8h12v12H8zM4 16H3V3h13v1',check:'m5 12 4 4 10-10',clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18m0 4v5l3 2',close:'m6 6 12 12M6 18 18 6',external:'M14 3h7v7m0-7-11 11M10 5H4v15h15v-6',play:'m8 4 12 8-12 8z',stop:'M6 6h12v12H6z',info:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18m0 7v6m0-9v.01',chevron:'m9 5 7 7-7 7',folder:'M3 7h7l2-3h9v16H3z',gear:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',file:'M5 3h9l5 5v13H5zM14 3v6h5M9 13h6m-6 4h6',cpu:'M7 7h10v10H7zM9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3',branch:'M6 3v14a4 4 0 0 0 4 4m-4-9h8a4 4 0 0 0 4-4V3',trash:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',download:'M12 3v12m-4-4 4 4 4-4M4 18v3h16v-3'};
  Object.assign(paths,{overview:sharedIcons.home,runs:sharedIcons.play,comparisons:sharedIcons.compare,jobs:sharedIcons.jobs,reports:sharedIcons.file,install:sharedIcons.install,resources:sharedIcons.resources,configure:sharedIcons.config,storage:sharedIcons.folder});
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.arrow}"/></svg>`;
  const button = (text, view, primary=false) => `<button class="btn ${primary?'primary':''}" data-nav="${view}">${text}${icon('arrow')}</button>`;
  const pill = (text, tone='blue') => `<span class="pill ${tone}">${e(text)}</span>`;
  const heading = (title, subtitle, action='') => `<div class="page-heading"><div><div class="eyebrow">VIROLOGY WORKSPACE</div><h1>${title}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`;
  const card = (title, subtitle, body) => `<section class="card"><div class="card-head"><div><h2>${title}</h2><p>${subtitle}</p></div></div><div class="card-body">${body}</div></section>`;
  const names={overview:'Overview',samples:'Samples',runs:'Runs',comparisons:'Comparisons',jobs:'Jobs & progress',reports:'Results & reports',install:'Install & update',resources:'Databases & models',configure:'Configuration',storage:'Storage'};
  const editorKey='virologix:run-editor:v1:'+S.home;
  if(!U.restored){try{U.editor=JSON.parse(sessionStorage.getItem(editorKey)||'null');}catch(_){}U.restored=true;}
  function persist(){try{if(U.editor)sessionStorage.setItem(editorKey,JSON.stringify(U.editor));else sessionStorage.removeItem(editorKey);}catch(_){}}
  function route(){const bits=location.hash.slice(1).split('/');U.view=names[bits[0]]?bits[0]:'overview';U.runId=bits[0]==='runs'?bits[1]:null;}
  function navigate(view){persist();location.hash=view;route();U.notice=null;drawer(false);render();$('#main').focus({preventScroll:true});}
  route();on(window,'hashchange',()=>{route();render();});
  const action=(name,text,id='',disabled=false)=>`<button class="btn" data-action="${name}" data-run="${e(id)}" ${disabled||U.pending?'disabled':''}>${text}</button>`;
  const status=r=>r.status==='succeeded'?'Completed':r.status||'Legacy report';
  const active=()=>S.tasks.filter(t=>['queued','running'].includes(t.status));
  const current=()=>S.cloud_runs.filter(r=>!r.archived);
  function beginDraft(sample='',demo=false,run=null){U.editor=run?{...run.input_paths,label:run.label||run.sample,sample:run.sample,demo:run.synthetic_demo,run_id:run.status==='draft'?run.id:null}:{sample,demo,label:demo?'Synthetic demo':'',consensus:'',haplotypes:'',evidence:''};persist();navigate('runs/editor');}
  function send(action,args={}) {
    if (U.pending) return;
    U.pending=action; U.notice=null;
    setTriggerValue('action',{id:crypto.randomUUID(),action,args});
    render();
  }
  const response=data.response;
  if(response && response.id!==U.responseId){
    U.responseId=response.id;U.pending=null;
    U.notice=response.message?{ok:response.ok,text:response.message}:null;
    if(response.action==='cloud-open' && response.ok) U.cloud=response;
    if(response.action==='browse' && response.ok)U.browser=response;
    if(response.job_id && response.ok && !['flupop-install','app-install'].includes(response.action)){U.waitingJob=response.job_id;U.cloud=null;}

    if(['register','sample-add'].includes(response.action) && response.ok){U.draft={};U.addSample=false;}
    if(response.action==='run-save' && response.ok){U.editor=null;persist();location.hash='runs/'+response.run_id;route();}
    if(response.action==='cloud-open' && response.ok){location.hash='reports';route();}
  }
  function sampleTable(samples){
    if(!samples.length)return '<div class="empty"><h3>No samples to display</h3><p>Start with a sample folder. Use Add sample to register its location.</p></div>';
    return `<div class="table-wrap"><table><thead><tr><th>Sample</th><th>Input folder</th><th>Runs</th><th>Actions</th></tr></thead><tbody>${samples.map(r=>`<tr><td><strong>${e(r.id)}</strong></td><td class="v-path">${e(r.path||r.r1)}</td><td>${current().filter(x=>x.sample===r.id).length}</td><td>${action('sample-draft','Create draft',r.id)} ${action('sample-runs','View runs',r.id)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function overview(){
    const next=!S.flupop.ready?button('Install pipelines','install',true):!S.samples.length?button('Add samples','samples',true):button('Create run drafts','runs',true);
    return heading('Pick up where you left off.','Samples, saved runs, jobs and reports in one workspace.',next)+
      `<div class="stats-grid overview-stats">${[['Samples',S.samples.length],['Runs',current().length],['Active jobs',active().length],['Reports',S.cloud_runs.filter(r=>!r.status||r.status==='succeeded').length]].map(([label,n])=>`<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${n}</div></div>`).join('')}</div>`+
      card('Next step','Add samples → create run drafts → run → review results.',`<p>${!S.flupop.ready?'Install FluPop in Install & update.':'Choose a registered sample and save its run configuration before starting a job.'}</p><div class="button-row">${next}${action('demo-draft','Create synthetic demo draft')}</div>`)+
      (U.editor?card('Unfinished draft','Your editor is saved in this browser.',button('Continue editing','runs/editor')):'')+
      card('Recent runs','Each run keeps its own settings and outputs.',runTable(current().slice(0,5)));
  }
  function samples(){
    const field=(key,label)=>`<div class="field wide"><label for="${key}">${label}</label><input id="${key}" name="${key}" value="${e(U.draft[key]||'')}" required></div>`;
    return heading('Samples','Register a sample folder, then create its run drafts.',U.addSample?'':action('new-sample','Add sample'))+
      (U.addSample?card('Add sample','Use a Linux / WSL folder or a Windows drive path.',`<form id="sample-form" class="v-form"><div class="form-grid">${field('sample','Sample ID')}${field('path','Sample folder')}<button type="button" class="btn" data-action="browse-folder" data-field="path">Browse folders</button></div><button class="btn primary" type="submit" ${U.pending?'disabled':''}>Add sample</button></form>`):'')+
      `<div class="toolbar"><h2>Registered samples (${S.samples.length})</h2><input class="search" id="sample-search" type="search" aria-label="Search samples" placeholder="Sample ID or folder…" value="${e(U.filter)}"></div><section class="card" id="sample-results">${sampleTable(S.samples.filter(r=>(r.id+' '+(r.path||'')).toLowerCase().includes(U.filter.toLowerCase())))}</section>`;
  }
  function cloudResult(){
    if(!U.cloud)return '';
    return card('Viral Cloud report',`${U.cloud.run.synthetic_demo?'Synthetic demo · ':''}Saved run: ${e(U.cloud.run.id)}`,`<div class="button-row"><button class="btn primary" data-action="cloud-download">Download report bundle</button></div><p class="v-note">${e(U.cloud.run.path)}</p><iframe id="cloud-report" title="Viral Cloud report" sandbox="" style="width:100%;height:850px;border:0" srcdoc="${e(U.cloud.html)}"></iframe>`);
  }
  function taskCards(kinds=null){
    return S.tasks.filter(t=>!kinds||kinds.includes(t.kind)).map(t=>`<details class="card v-result" ${['queued','running','failed'].includes(t.status)?'open':''}><summary>${t.kind==='app_update'?'Virologix update':t.kind==='flupop_install'?'FluPop installation':'FluPop run'} · ${e(t.status)}</summary><div class="card-body"><p>${e(t.error||t.id)}</p><pre class="code-block">${e(t.log||'Waiting for worker…')}</pre></div></details>`).join('');
  }
  function runTable(rows){
    if(!rows.length)return '<div class="empty"><h3>No saved runs</h3><p>Create a draft from Samples or use Create run drafts.</p></div>';
    return `<div class="table-wrap"><table><thead><tr><th>Saved run</th><th>Sample</th><th>Pipeline</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${e(r.label||r.sample)}</strong><span class="secondary-line">${e(r.id)}</span></td><td>${e(r.sample)}</td><td>FluPop</td><td>${pill(status(r))}</td><td>${button('Open run','runs/'+r.id)} ${action(r.archived?'restore-run':'archive-run',r.archived?'Restore':'Archive',r.id,['queued','running'].includes(r.status))}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function editor(){
    const d=U.editor;if(!d)return heading('Create run drafts','Choose a sample or create a synthetic demo draft.')+button('Choose samples','samples');
    const field=(key,label,required=false)=>`<div class="field wide"><label for="edit-${key}">${label}</label><input id="edit-${key}" name="${key}" value="${e(d[key]||'')}" ${required?'required':''}>${key==='label'?'':`<button type="button" class="btn" data-action="browse-input" data-field="${key}">Browse files</button>`}</div>`;
    return heading(d.run_id?'Edit saved draft':'Create run drafts','Saving a draft does not start a job.',button('Back to runs','runs'))+
      card('FluPop configuration','Independent Snakemake pipeline · supplied-record reports',`<form id="run-form" class="v-form"><div class="form-grid">${field('label','Run name',true)}<div class="field"><label for="edit-sample">Sample</label>${d.demo?'<p>DEMO · Synthetic inputs</p>':`<select id="edit-sample" name="sample" required><option value="">Choose a sample</option>${S.samples.map(r=>`<option value="${e(r.id)}" ${r.id===d.sample?'selected':''}>${e(r.id)}</option>`).join('')}</select>`}</div><div class="field"><label>Pipeline</label><p>FluPop</p></div>${d.demo?'':field('consensus','Consensus FASTA path',true)+field('haplotypes','Reviewed haplotypes TSV path',true)+field('evidence','Evidence JSON path (optional)')}</div><p class="v-note">${d.demo?'Uses the installed pipeline’s synthetic fixture.':'Inputs stay in their original locations. Each run receives its own input snapshot when started.'}</p><div class="button-row"><button class="btn primary" type="submit" ${U.pending?'disabled':''}>Save draft</button>${action('discard-editor','Discard unsaved edits')}</div></form>`);
  }
  function runDetail(r){
    if(!r)return heading('Run not found','Return to the saved runs list.')+button('Back to runs','runs');
    const busy=active().length>0;
    return heading(e(r.label||r.sample),'Saved configuration, activity and outputs.',button('Back to runs','runs'))+
      card('Run configuration',`${e(r.id)} · FluPop`, `<dl class="detail-list"><dt>Status</dt><dd>${e(status(r))}</dd><dt>Sample</dt><dd>${e(r.sample)}</dd><dt>Inputs</dt><dd class="v-path">${r.synthetic_demo?'Synthetic demo':Object.entries(r.input_paths||{}).filter(([,v])=>v).map(([k,v])=>e(k)+': '+e(v)).join('<br>')||'Saved with the original run'}</dd><dt>Source revision</dt><dd>${e(r.installation?.revision||'Recorded when started')}</dd><dt>Output folder</dt><dd class="v-path">${e(r.path||'Created when started')}</dd></dl><div class="button-row">${r.archived?action('restore-run','Restore',r.id):r.status==='draft'?action('edit-run','Edit draft',r.id)+action('run-start','Run / resume',r.id,busy||!S.flupop.ready):r.status==='failed'?action('flupop-resume','Run / resume',r.id,busy):''}${r.input_paths||r.synthetic_demo?action('clone-run','Create new draft',r.id):''}${!r.status||r.status==='succeeded'?action('cloud-open','View results',r.id):''}${button('Jobs & progress','jobs')}</div>${!S.flupop.ready?'<p>Install FluPop in Install & update before starting.</p>':''}${r.error?`<div class="notice amber">${e(r.error)}</div>`:''}`);
  }
  function runs(){
    if(U.runId==='editor')return editor();
    if(U.runId)return runDetail(S.cloud_runs.find(r=>r.id===U.runId));
    const rows=S.cloud_runs.filter(r=>!!r.archived===!!U.archived&&(!U.sampleFilter||r.sample===U.sampleFilter)&&(!U.runStatus||r.status===U.runStatus)&&`${r.label} ${r.sample} ${r.id}`.toLowerCase().includes((U.runSearch||'').toLowerCase()));
    return heading('Drafts, activity and history.','Each run keeps its own configuration, input references and outputs.',action('new-run','Create run drafts'))+
      (U.editor?card('Unfinished draft','Continue where you left off.',button('Continue editing','runs/editor')):'')+
      `<div class="toolbar"><div class="button-row">${action('current-runs','Current runs')}${action('archived-runs','Archived')}${action('reset-runs','Reset filters')}</div><input id="run-search" class="search" aria-label="Search runs" placeholder="Sample, name or run ID…" value="${e(U.runSearch||'')}"><select id="run-status" aria-label="Run status"><option value="">All statuses</option>${['draft','queued','running','failed','succeeded'].map(x=>`<option value="${x}" ${U.runStatus===x?'selected':''}>${x==='succeeded'?'Completed':x}</option>`).join('')}</select></div>${U.sampleFilter?`<p>Runs for ${e(U.sampleFilter)}</p>`:''}<section class="card" id="run-results">${runTable(rows)}</section><p class="v-note">${U.archived?'Restore a run to use it again.':'Archive hides inactive runs.'} Files, configurations and reports are kept.</p>`;
  }
  function reports(){return heading('Results & reports','Completed pipeline outputs, including reports saved by earlier versions.')+card('Saved reports','Open or download a completed run.',S.cloud_runs.filter(r=>!r.status||r.status==='succeeded').map(r=>`<div class="pipeline-row"><div class="pipeline-info"><strong>${e(r.label||r.sample)}</strong><small>${e(r.id)}${r.archived?' · Archived':''}</small></div>${action('cloud-open','Open report',r.id)}</div>`).join('')||'<p>No completed reports yet.</p>')+cloudResult();}
  function jobs(){return heading('Jobs & progress','Follow active jobs and inspect previous logs.')+(taskCards()||card('No jobs yet','Save a run draft before starting it.',button('Open runs','runs')));}
  function comparisons(){return heading('Comparisons','Review saved run settings.')+card('Saved configurations','Compare sample, status, inputs and source revision; no analysis is performed.',current().map(r=>`<details class="v-result"><summary>${e(r.label||r.sample)} · ${e(status(r))}</summary><pre class="code-block">${e(JSON.stringify({sample:r.sample,pipeline:r.pipeline,inputs:r.input_paths,synthetic_demo:r.synthetic_demo,revision:r.installation?.revision},null,2))}</pre>${button('Open run','runs/'+r.id)}</details>`).join('')||'<p>No saved runs yet.</p>');}
  function resources(){return heading('Databases & models','Resources required by installed pipelines.')+card('FluPop','No external databases or models required for the current supplied-record workflow.','<p>Resource installation controls will appear when a pipeline declares supported resources.</p>');}
  function storage(){return heading('Storage','Workspace locations and retained files.')+card('Local storage','Archiving a run keeps its files and reports.',`<dl class="detail-list">${['runs','logs','sources','envs','resources'].map(k=>`<dt>${e(k)}</dt><dd class="v-path">${e(S.home+'/'+k)}</dd>`).join('')}</dl>`);}
  function updates(){
    const u=S.app_update, catalog=u.catalog, channel=U.updateChannel||'all';
    const releases=(catalog?.releases||[]).filter(r=>channel!=='stable'||!r.prerelease);
    const eligible=releases.filter(r=>r.available&&r.newer);
    if(!eligible.some(r=>String(r.id)===String(U.releaseId)))U.releaseId=eligible[0]?.id;
    const chosen=eligible.find(r=>String(r.id)===String(U.releaseId));
    const latest=releases.find(r=>r.available);
    return heading('Install & update','Manage application releases and independent pipeline installations.')+
      `<div class="stats-grid"><div class="stat"><div class="stat-label">Running Virologix</div><div class="stat-value label">${e(u.running_version)}</div><div class="stat-foot">Loaded by this window</div></div><div class="stat"><div class="stat-label">Installed package</div><div class="stat-value label">${e(u.installed_version)}</div><div class="stat-foot">${u.restart_required?'Restart required':'Matches this session'}</div></div><div class="stat"><div class="stat-label">Latest checked release</div><div class="stat-value label">${e(latest?.version||'Not checked')}</div><div class="stat-foot">${e(catalog?.checked_at||'Check for available updates')}</div></div></div>`+
      (u.restart_required?`<div class="notice amber"><p>${u.automatic_restart?'Update installed. Virologix will restart and this page will refresh automatically.':'Restart Virologix to load the installed version. Close the app and reopen its desktop shortcut; for a terminal session, stop it with Ctrl+C and relaunch.'}</p></div>`:'')+
      card('Virologix application','Updates only the manager environment (viromics).',`<div class="button-row"><button class="btn" data-action="app-check" ${U.pending||u.active_job?'disabled':''}>${U.pending==='app-check'?'Checking…':'Check for updates'}</button><label for="update-channel">Release channel</label><select id="update-channel"><option value="all" ${channel==='all'?'selected':''}>Stable and preview</option><option value="stable" ${channel==='stable'?'selected':''}>Stable only</option></select><a class="btn" href="https://github.com/crackberryq/Virologix/releases" target="_blank" rel="noopener noreferrer">Open releases ↗</a></div><p class="v-note">Downloads are checked against the published size, SHA-256, package identity and Python requirement.</p>${catalog&&!releases.length?'<p>No releases in this channel.</p>':''}${releases.map(r=>`<details class="card v-result"><summary><label><input type="radio" name="update-release" value="${e(r.id)}" ${String(r.id)===String(U.releaseId)?'checked':''} ${!r.available||!r.newer||!u.can_install?'disabled':''}> ${e(r.tag)}</label> ${pill(r.version===u.running_version?'Running':r.older?'Older':r.prerelease?'Preview':'Stable',r.older?'off':'blue')}${!r.available?' · No verified wheel':''}</summary><div class="card-body"><p>${e(r.published_at||'')}</p><pre class="code-block">${e(r.notes||'No release notes provided.')}</pre></div></details>`).join('')}<button class="btn primary v-result" data-action="app-install" ${!chosen||!u.can_install||U.pending?'disabled':''}>${u.active_job?'Updating Virologix…':chosen?'Install '+e(chosen.tag):(catalog?'Up to date in this channel':'Check releases first')}</button><p class="v-note">${u.automatic_restart?'This managed session supports automatic restart.':'After installation, close and reopen Virologix.'} Application updates wait until active tasks finish. Your samples and pipeline installations stay in place.</p>`)+
      card('FluPop pipeline','Independent source and environment; updating Virologix does not update FluPop.',`<p>${S.flupop.ready?'Installed FluPop '+e(S.flupop.version)+' · '+e(S.flupop.revision.slice(0,12)):'FluPop is not installed.'}</p><div class="button-row"><button class="btn" data-action="flupop-install" ${!u.can_install||U.pending?'disabled':''}>${S.flupop.ready?'Update / repair FluPop':'Install FluPop'}</button>${button('Create run drafts','runs')}</div>`)+taskCards(['app_update','flupop_install']);
  }

  function setup(){return heading('Configuration','Your local workspace and available system resources.')+
    `<div class="stats-grid"><div class="stat"><div class="stat-label">CPU cores</div><div class="stat-value">${e(S.cpu??'Unknown')}</div></div><div class="stat"><div class="stat-label">Available RAM</div><div class="stat-value">${e(S.ram_gib)} <small>GiB</small></div></div><div class="stat"><div class="stat-label">Application</div><div class="stat-value label">${e(S.version)}</div></div></div>`+
    card('Workspace details','Separate from your Bactologix workspace.',`<dl class="detail-list"><dt>Location</dt><dd class="mono">${e(S.home)}</dd><dt>Environment</dt><dd>viromics (standard installer environment)</dd><dt>Mode</dt><dd>${S.desktop?'Managed desktop':'Browser'}</dd></dl><div class="notice"><p>FluPop installation and repair are available in Install & update. Resource profiles and GPU detection remain planned.</p></div>`);}
  function render(){
    $('#app-version').textContent='v'+S.version;
    $('#navigation').innerHTML='<div class="nav-label">WORK</div>'+['overview','samples','runs','comparisons','jobs','reports'].map(nav).join('')+'<div class="nav-divider"></div><div class="nav-label">MANAGE</div>'+['install','resources','configure','storage'].map(nav).join('');
    $('#crumb').textContent=names[U.view]+(U.runId?' / '+(U.runId==='editor'?'Unfinished draft':S.cloud_runs.find(r=>r.id===U.runId)?.label||U.runId):'');
    $('#queue-status').textContent=active().length?active().length+' active jobs':'No active jobs';
    $('#main').innerHTML=({overview,samples,runs,comparisons,jobs,reports,install:updates,resources,configure:setup,storage}[U.view]||overview)();
    if(U.notice){const box=document.createElement('div');box.className='notice v-feedback'+(U.notice.ok?'':' amber');box.setAttribute('role',U.notice.ok?'status':'alert');box.textContent=U.notice.text;$('#main').insertBefore(box,$('#main').children[1]||null);}
    $('[data-action="restart-as-browser"]').disabled=!S.desktop||Boolean(U.pending);
    $('#main').setAttribute('aria-busy',String(Boolean(U.pending)));
  }
  function nav(view){return `<a href="#${view}" data-nav="${view}" aria-label="${names[view]}" class="nav-item ${view===U.view?'active':''}" ${view===U.view?'aria-current="page"':''}>${icon(view)}${names[view]}${view==='jobs'&&active().length?`<span class="nav-count">${active().length}</span>`:''}</a>`;}
  function drawer(open){root.classList.toggle('nav-open',open);$('.nav-scrim').hidden=!open;$('#nav-toggle').setAttribute('aria-expanded',String(open));}
  function modal(title,body){
    const prior=root.activeElement || parentElement.getRootNode().activeElement;
    $('#modal-root').innerHTML=`<div class="modal-shade"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div class="card-head"><h2 id="dialog-title">${title}</h2><button class="icon-btn" data-action="close-modal" aria-label="Close dialog">×</button></div><div class="card-body">${body}</div></section></div>`;
    U.modalFocus=prior;$('[data-action="close-modal"]').focus();
  }
  function closeModal(){$('#modal-root').innerHTML='';U.browser=null;U.modalFocus?.focus();}
  function browserDialog(){
    if(!U.browser)return;
    const b=U.browser;
    modal(U.browseMode==='folder'?'Choose sample folder':'Choose input file',`<p class="v-path">${e(b.folder)}</p><div class="button-row"><button class="btn" data-action="browse-enter" data-path="${e(b.parent)}">Parent folder</button>${U.browseMode==='folder'?`<button class="btn primary" data-action="browse-select" data-path="${e(b.folder)}">Use this folder</button>`:''}</div><form id="browse-form" class="v-form"><label for="browse-path">Go to folder</label><input id="browse-path" value="${e(b.folder)}"><button class="btn" type="submit">Go</button></form><div style="max-height:340px;overflow:auto">${b.entries.filter(x=>U.browseMode!=='folder'||x.directory).map(x=>`<div class="pipeline-row"><button class="quiet" data-action="${x.directory?'browse-enter':'browse-select'}" data-path="${e(x.path)}">${icon(x.directory?'storage':'reports')}${e(x.name)}${x.directory?' /':''}</button></div>`).join('')||'<p>No matching entries.</p>'}</div>${b.truncated?'<p>Showing the first 500 entries. Use the path field for another location.</p>':''}`);
  }
  on(root,'click',event=>{
    const target=event.target.closest('[data-nav],[data-action]');if(!target)return;
    if(target.dataset.nav){event.preventDefault();navigate(target.dataset.nav);return;}
    switch(target.dataset.action){
      case 'toggle-navigation':drawer(!root.classList.contains('nav-open'));break;
      case 'close-navigation':drawer(false);$('#nav-toggle').focus();break;
      case 'close-modal':closeModal();break;
      case 'refresh':send('refresh');break;
      case 'browse-folder':case 'browse-input':U.browseMode=target.dataset.action==='browse-folder'?'folder':'file';U.browseField=target.dataset.field;send('browse',{path:U.browseMode==='folder'?U.draft.path:U.editor[U.browseField]||S.samples.find(r=>r.id===U.editor.sample)?.path});break;
      case 'browse-enter':send('browse',{path:target.dataset.path});break;
      case 'browse-select':if(U.browseMode==='folder')U.draft.path=target.dataset.path;else{U.editor[U.browseField]=target.dataset.path;persist();}closeModal();render();break;
      case 'new-sample':U.addSample=true;render();break;
      case 'sample-draft':beginDraft(target.dataset.run);break;
      case 'new-run':beginDraft();break;
      case 'demo-draft':beginDraft('',true);break;
      case 'sample-runs':U.sampleFilter=target.dataset.run;navigate('runs');break;
      case 'edit-run':beginDraft('',false,S.cloud_runs.find(r=>r.id===target.dataset.run));break;
      case 'clone-run':{const r=S.cloud_runs.find(r=>r.id===target.dataset.run);beginDraft('',false,{...r,status:'clone',label:(r.label||r.sample)+' copy'});break;}
      case 'discard-editor':U.editor=null;persist();navigate('runs');break;
      case 'run-start':send('run-start',{run_id:target.dataset.run});break;
      case 'archive-run':send('run-archive',{run_id:target.dataset.run,archived:true});break;
      case 'restore-run':send('run-archive',{run_id:target.dataset.run,archived:false});break;
      case 'current-runs':U.archived=false;render();break;
      case 'archived-runs':U.archived=true;render();break;
      case 'reset-runs':U.sampleFilter=null;U.runSearch='';U.runStatus='';render();break;
      case 'flupop-install':send('flupop-install');break;
      case 'flupop-resume':send('flupop-resume',{run_id:target.dataset.run});break;
      case 'cloud-open':send('cloud-open',{run_id:target.dataset.run});break;
      case 'cloud-download':{const bytes=Uint8Array.from(atob(U.cloud.archive),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));const a=document.createElement('a');a.href=url;a.download=U.cloud.run.id+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);break;}
      case 'restart-as-browser':send('restart-as-browser');break;
      case 'app-updates':navigate('install');if(!S.app_update.catalog)send('app-check');break;
      case 'app-check':send('app-check');break;
      case 'app-install':send('app-install',{release_id:U.releaseId});break;
      case 'get-support':modal('Virologix support','<p>Report interface or installation issues with your application version and relevant error details.</p><a class="btn primary v-result" href="https://github.com/crackberryq/Virologix/issues" target="_blank" rel="noopener noreferrer">Open GitHub issues ↗</a>');break;
      case 'about':modal('About Virologix',`<p>Created by <strong>Jimi Goldstein · Human Link GenoMix</strong>.</p><p class="v-note">Virologix ${e(S.version)} · Local alpha</p><p class="v-note">Bactologix workspace design, adapted for Virologix. Viral Cloud supplied-record reports are available. Raw-read analysis is not included.</p>`);break;
    }
  });
  on(root,'input',event=>{
    if(event.target.closest('#sample-form'))U.draft[event.target.name]=event.target.value;
    if(event.target.closest('#run-form')){U.editor[event.target.name]=event.target.value;persist();}
    if(event.target.id==='sample-search'){U.filter=event.target.value;$('#sample-results').innerHTML=sampleTable(S.samples.filter(r=>(r.id+' '+(r.path||'')).toLowerCase().includes(U.filter.toLowerCase())));}
    if(event.target.id==='run-search'){U.runSearch=event.target.value;const input=event.target,pos=input.selectionStart;render();$('#run-search').focus();$('#run-search').setSelectionRange(pos,pos);}
  });
  on(root,'submit',event=>{
    if(event.target.id==='browse-form'){event.preventDefault();send('browse',{path:$('#browse-path').value});}
    if(event.target.id==='sample-form'){event.preventDefault();send('sample-add',U.draft);}
    if(event.target.id==='run-form'){event.preventDefault();send('run-save',U.editor);}
  });
  on(root,'change',event=>{
    if(event.target.id==='run-status'){U.runStatus=event.target.value;render();}
    if(event.target.id==='edit-sample'){U.editor.sample=event.target.value;persist();}
    if(event.target.id==='update-channel'){U.updateChannel=event.target.value;render();}
    if(event.target.name==='update-release'){U.releaseId=event.target.value;render();}
  });
  on(root,'keydown',event=>{
    if(event.key==='Escape'){closeModal();drawer(false);}
    const dialog=$('[role="dialog"]');
    if(dialog && event.key==='Tab'){const focusable=[...dialog.querySelectorAll('button,a[href],input')];const first=focusable[0],last=focusable.at(-1);const active=parentElement.getRootNode().activeElement;if(event.shiftKey&&active===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&active===last){event.preventDefault();first.focus();}}
  });
function watchAppRestart(){
 const u=S.app_update;if(!u)return;
 let watcher=window.__virologixRestart;
 const fail=watcher&&(S.tasks.find(j=>j.id===watcher.job)?.status==='failed'||S.tasks.find(j=>j.id===watcher.job)?.status==='cancelled'||(u.last_update?.job===watcher.job&&u.last_update?.restart_status==='failed'));
 if(fail){clearTimeout(watcher.timer);watcher.cancelled=true;window.__virologixRestart=null;return;}
 const job=u.active_job&&S.tasks.find(j=>j.id===u.active_job);
 const target=u.target_version||(u.restart_required&&u.last_update?.status==='installed'?u.last_update.version:null);
 if(watcher||!u.automatic_restart||!u.launcher||!target)return;
 watcher={id:u.launcher.id,version:target,job:job?.id||u.last_update.job,deadline:Date.now()+1200000,cancelled:false};
 window.__virologixRestart=watcher;
 const check=async()=>{
  if(watcher.cancelled)return;
  if(Date.now()>watcher.deadline){window.__virologixRestart=null;const msg=document.createElement('div');msg.textContent='Automatic restart did not finish. Check the terminal, start viralogix if needed, then refresh this page.';msg.setAttribute('role','alert');msg.style.cssText='position:fixed;bottom:20px;left:20px;right:20px;padding:18px;background:#fff3d6;color:#543c13;z-index:99999;border:1px solid #d9bd76;border-radius:8px';document.body.append(msg);return;}
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),2500);
  try{
   const runtime=await fetch('/app/static/runtime.json',{cache:'no-store',signal:abort.signal});
   if(runtime.ok){const fresh=await runtime.json();if(fresh.id&&fresh.id!==watcher.id&&fresh.version===watcher.version){
    const health=await fetch('/_stcore/health',{cache:'no-store',signal:abort.signal});
    if(health.ok&&(await health.text()).trim()==='ok'&&!watcher.cancelled){window.__virologixRestart=null;window.location.reload();return;}
   }}
  }catch(_){/* The server is expected to be briefly unavailable during restart. */}
  finally{clearTimeout(timer);}
  if(!watcher.cancelled)watcher.timer=setTimeout(check,750);
 };
 watcher.timer=setTimeout(check,750);
}
watchAppRestart();
  render();
  browserDialog();
  const completed=S.cloud_runs.find(run=>run.job_id===U.waitingJob && run.status==='succeeded');
  if(completed && !U.pending){U.waitingJob=null;pollTimer=setTimeout(()=>send('cloud-open',{run_id:completed.id}),0);}
  else if(S.tasks.some(t=>['queued','running'].includes(t.status)) && !U.pending){pollTimer=setTimeout(()=>send('refresh'),2000);}
}
