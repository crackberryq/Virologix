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
  const paths = {overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',samples:'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',cfasta:'M8 3H5v18h14V7l-4-4H8 M14 3v5h5 M8 12h8 M8 16h5',pipelines:'M4 4h5v5H4z M15 15h5v5h-5z M6 9v8h9 M9 6h8v9',runs:'M8 5l11 7-11 7z',setup:'M4 7h16 M4 17h16 M8 4v6 M16 14v6',resources:'M3 5h18v14H3z M3 10h18 M7 14h3',arrow:'M5 12h14 M14 7l5 5-5 5'};
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.arrow}"/></svg>`;
  const button = (text, view, primary=false) => `<button class="btn ${primary?'primary':''}" data-nav="${view}">${text}${icon('arrow')}</button>`;
  const pill = (text, tone='blue') => `<span class="pill ${tone}">${e(text)}</span>`;
  const heading = (title, subtitle, action='') => `<div class="page-heading"><div><div class="eyebrow">VIROLOGY WORKSPACE</div><h1>${title}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`;
  const card = (title, subtitle, body) => `<section class="card"><div class="card-head"><div><h2>${title}</h2><p>${subtitle}</p></div></div><div class="card-body">${body}</div></section>`;
  const names = {overview:'Overview',samples:'Samples',pipelines:'Pipelines',runs:'Runs',resources:'Databases & resources',setup:'Setup'};
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
    if(response.job_id && response.ok && response.action!=='flupop-install'){U.waitingJob=response.job_id;U.cloud=null;}

    if(response.action==='register' && response.ok) U.draft={};
  }
  function sampleTable(samples) {
    if(!samples.length) return '<div class="empty">'+icon('samples')+'<h3>No samples to display</h3><p>Register local input paths to prepare your workspace.</p></div>';
    return `<div class="table-wrap"><table><thead><tr><th>Sample</th><th>Inputs</th><th>Reference</th><th>Status</th></tr></thead><tbody>${samples.map(s=>`<tr><td><strong class="sample-name">${e(s.id)}</strong><span class="secondary-line">${e(s.created)}</span></td><td class="v-path">${e(s.r1)}${s.r2?`<span class="secondary-line v-path">${e(s.r2)}</span>`:''}</td><td class="v-path">${e(s.reference || 'Not supplied')}</td><td>${pill('Registered')}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function overview(){
    return heading('Your virology workspace','Organize local inputs and manage independent pipelines.',button('Register sample','samples',true))+
      `<div class="stats-grid"><div class="stat"><div class="stat-label">Registered samples${icon('samples')}</div><div class="stat-value">${S.samples.length}</div><div class="stat-foot">Local file references</div></div><div class="stat"><div class="stat-label">FluPop installation${icon('pipelines')}</div><div class="stat-value label">${S.flupop.ready?'Ready':'Not installed'}</div><div class="stat-foot">Separate pipeline environment</div></div><div class="stat"><div class="stat-label">Saved reports${icon('pipelines')}</div><div class="stat-value label">${S.cloud_runs.length}</div><div class="stat-foot">Pipeline results and legacy reports</div></div></div>`+
      `<div class="split"><section class="card experiment-card"><div class="card-body"><div class="copy"><span class="mini-chip">PREPARE YOUR WORKSPACE</span><h2>Your inputs, ready for what comes next.</h2><p>Keep samples organized and launch FluPop from Pipelines.</p><div class="button-row">${button('Explore samples','samples',true)}${button('Manage FluPop','pipelines')}</div></div></div></section>`+
      card('Workspace capabilities','Available utilities and upcoming integrations.',`<div class="pipeline-row"><span class="pipeline-logo">S</span><div class="pipeline-info"><strong>Sample registry</strong><small>Register existing local files</small></div>${pill('Available')}</div><div class="pipeline-row"><span class="pipeline-logo">C</span><div class="pipeline-info"><strong>FluPop manager</strong><small>Install, launch and monitor</small></div>${pill('Available')}</div><div class="pipeline-row"><span class="pipeline-logo">P</span><div class="pipeline-info"><strong>Viral Cloud</strong><small>cFASTA packaging and reports</small></div>${pill('Available')}</div>`)+`</div>`+
      `<section class="card"><div class="card-head"><div><h2>Recent samples</h2><p>Your registered local inputs.</p></div><button class="quiet" data-nav="samples">View all ${icon('arrow')}</button></div>${sampleTable(S.samples.slice(0,5))}</section>`;
  }
  function samples(){
    const field=(key,label,required=false)=>`<div class="field ${key==='sample'?'':'wide'}"><label for="${key}">${label}</label><input id="${key}" name="${key}" value="${e(U.draft[key]||'')}" ${required?'required':''} autocomplete="off"></div>`;
    return heading('Samples','Register file paths without moving or uploading sequencing inputs.')+
      card('Register a sample','Use Linux paths in WSL, for example /mnt/c/data/sample_R1.fastq.gz.',`<form id="sample-form" class="v-form"><div class="form-grid">${field('sample','Sample ID',true)}${field('r1','R1 FASTQ path',true)}${field('r2','R2 FASTQ path (optional)')}${field('reference','Segment reference FASTA path (optional)')}</div><button class="btn primary" type="submit" ${U.pending?'disabled':''}>${U.pending==='register'?'Registering…':'Register sample'}</button></form>`)+
      `<div class="toolbar v-result"><h2>Registered samples (${S.samples.length})</h2><input class="search" id="sample-search" type="search" aria-label="Search samples" placeholder="Search samples…" value="${e(U.filter)}"></div><section class="card" id="sample-results">${sampleTable(S.samples.filter(s=>s.id.toLowerCase().includes(U.filter.toLowerCase())))}</section>`;
  }
  function cloudResult(){
    if(!U.cloud)return '';
    return card('Viral Cloud report',`${U.cloud.run.synthetic_demo?'Synthetic demo · ':''}Saved run: ${e(U.cloud.run.id)}`,`<div class="button-row"><button class="btn primary" data-action="cloud-download">Download report bundle</button></div><p class="v-note">${e(U.cloud.run.path)}</p><iframe id="cloud-report" title="Viral Cloud report" sandbox="" style="width:100%;height:850px;border:0" srcdoc="${e(U.cloud.html)}"></iframe>`);
  }
  function taskCards(){
    return S.tasks.map(t=>`<details class="card v-result" ${['queued','running','failed'].includes(t.status)?'open':''}><summary>${t.kind==='flupop_install'?'FluPop installation':'FluPop run'} · ${e(t.status)}</summary><div class="card-body"><p>${e(t.error||t.id)}</p><pre class="code-block">${e(t.log||'Waiting for worker…')}</pre></div></details>`).join('');
  }
  function pipelines(){
    const ready=S.flupop.ready, busy=S.tasks.some(t=>['queued','running'].includes(t.status));
    return heading('Pipelines','Install and launch independent workflows managed by Virologix.')+
      card('FluPop','Independent Snakemake pipeline · Viral Cloud reports',`<p>${ready?'Installed: '+e(S.flupop.version)+' · Snakemake '+e(S.flupop.engine_version):'Not installed. Install FluPop to create cFASTA and Viral Cloud reports.'}</p><p class="v-note">FluPop runs in its own environment. Virologix manages installation, inputs, execution and reports.</p><div class="button-row"><button class="btn primary" data-action="flupop-install" ${busy||U.pending?'disabled':''}>${ready?'Update / repair FluPop':'Install FluPop'}</button><button class="btn" data-action="cloud-demo" ${!ready||busy||U.pending?'disabled':''}>Run synthetic demo</button></div>${ready?`<details class="v-result"><summary>Installation details</summary><p class="v-path">Revision: ${e(S.flupop.revision)}<br>Environment: ${e(S.flupop.python)}</p></details>`:''}<p class="v-note">Current FluPop supports supplied consensus and reviewed haplotype records. Raw-read reconstruction is not included.</p>`)+
      card('Run FluPop','Choose UTF-8 files, each up to 10 MiB.',`<form id="cloud-form" class="v-form"><fieldset ${!ready||busy?'disabled':''} style="border:0;padding:0"><div class="form-grid"><div class="field"><label for="cloud-sample">Report sample ID</label><input id="cloud-sample" required pattern="[A-Za-z0-9][A-Za-z0-9_.-]*"></div><div class="field"><label for="cloud-consensus">Consensus FASTA</label><input id="cloud-consensus" type="file" accept=".fasta,.fa,.fna" required></div><div class="field"><label for="cloud-haplotypes">Reviewed haplotypes TSV</label><input id="cloud-haplotypes" type="file" accept=".tsv" required></div><div class="field"><label for="cloud-evidence">Evidence JSON (optional)</label><input id="cloud-evidence" type="file" accept=".json"></div></div><button class="btn primary v-result" type="submit" ${U.pending?'disabled':''}>Start FluPop</button></fieldset></form>`)+taskCards()+cloudResult();
  }
  function runs(){
    return heading('Runs','FluPop runs and saved reports from earlier Virologix versions.')+card('Run history','Completed reports stay accessible after updates.',S.cloud_runs.length?S.cloud_runs.map(run=>`<div class="pipeline-row"><div class="pipeline-info"><strong>${e(run.sample)} ${run.synthetic_demo?'· Synthetic demo':''}</strong><small>${e(run.created)} · ${e(run.status||'Legacy report')} · ${e(run.id)}</small></div>${(!run.status||run.status==='succeeded')?`<button class="btn" data-action="cloud-open" data-run="${e(run.id)}">Open report</button>`:run.status==='failed'?`<button class="btn" data-action="flupop-resume" data-run="${e(run.id)}">Resume run</button>`:''}</div>`).join(''):'<p>No runs yet.</p>')+taskCards()+cloudResult();
  }
  function planned(view){
    const content={pipelines:['Pipelines','Prepare for future integrations.','Pipeline integrations are in development','Installation and execution controls will become available when a pipeline is connected.'],runs:['Runs','Execution and provenance will appear here when pipelines are connected.','No execution backend connected','Registering a sample or inspecting a file does not create an analysis run.'],resources:['Databases & resources','A consistent home for future pipeline resources.','No resource requirements published yet','Database setup and resource management will be connected alongside the pipelines.']}[view];
    return heading(content[0],content[1])+card(content[2],'Planned',`<div class="empty">${icon(view)}<h3>Ready for integration</h3><p>${content[3]}</p>${pill('Planned','off')}</div>`);
  }
  function setup(){return heading('Setup','Your local workspace and available system resources.')+
    `<div class="stats-grid"><div class="stat"><div class="stat-label">CPU cores</div><div class="stat-value">${e(S.cpu??'Unknown')}</div></div><div class="stat"><div class="stat-label">Available RAM</div><div class="stat-value">${e(S.ram_gib)} <small>GiB</small></div></div><div class="stat"><div class="stat-label">Application</div><div class="stat-value label">${e(S.version)}</div></div></div>`+
    card('Workspace details','Separate from your Bactologix workspace.',`<dl class="detail-list"><dt>Location</dt><dd class="mono">${e(S.home)}</dd><dt>Environment</dt><dd>viromics (standard installer environment)</dd><dt>Mode</dt><dd>${S.desktop?'Managed desktop':'Browser'}</dd></dl><div class="notice"><p>FluPop installation and repair are available in Pipelines. Resource profiles and GPU detection remain planned.</p></div>`);}
  function render(){
    $('#app-version').textContent='v'+S.version;
    $('#navigation').innerHTML='<div class="nav-label">WORKSPACE</div>'+['overview','samples','pipelines','runs'].map(nav).join('')+'<div class="nav-divider"></div><div class="nav-label">MANAGE</div>'+['resources','setup'].map(nav).join('');
    $('#crumb').textContent=names[U.view];
    $('#main').innerHTML=({overview,samples,setup,pipelines,runs}[U.view]||(()=>planned(U.view)))();
    if(U.notice){const box=document.createElement('div');box.className='notice v-feedback'+(U.notice.ok?'':' amber');box.setAttribute('role',U.notice.ok?'status':'alert');box.textContent=U.notice.text;$('#main').insertBefore(box,$('#main').children[1]||null);}
    $('[data-action="restart-as-browser"]').disabled=!S.desktop||Boolean(U.pending);
    $('#main').setAttribute('aria-busy',String(Boolean(U.pending)));
  }
  function nav(view){return `<a href="#${view}" data-nav="${view}" aria-label="${names[view]}" class="nav-item ${view===U.view?'active':''}" ${view===U.view?'aria-current="page"':''}>${icon(view)}${names[view]}${view==='samples'?`<span class="nav-count">${S.samples.length}</span>`:''}</a>`;}
  function drawer(open){root.classList.toggle('nav-open',open);$('.nav-scrim').hidden=!open;$('#nav-toggle').setAttribute('aria-expanded',String(open));}
  function modal(title,body){
    const prior=root.activeElement || parentElement.getRootNode().activeElement;
    $('#modal-root').innerHTML=`<div class="modal-shade"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div class="card-head"><h2 id="dialog-title">${title}</h2><button class="icon-btn" data-action="close-modal" aria-label="Close dialog">×</button></div><div class="card-body">${body}</div></section></div>`;
    U.modalFocus=prior;$('[data-action="close-modal"]').focus();
  }
  function closeModal(){$('#modal-root').innerHTML='';U.modalFocus?.focus();}
  on(root,'click',event=>{
    const target=event.target.closest('[data-nav],[data-action]');if(!target)return;
    if(target.dataset.nav){event.preventDefault();U.view=target.dataset.nav;U.notice=null;drawer(false);render();$('#main').focus({preventScroll:true});return;}
    switch(target.dataset.action){
      case 'toggle-navigation':drawer(!root.classList.contains('nav-open'));break;
      case 'close-navigation':drawer(false);$('#nav-toggle').focus();break;
      case 'close-modal':closeModal();break;
      case 'refresh':send('refresh');break;
      case 'cloud-demo':send('cloud-demo');break;
      case 'flupop-install':send('flupop-install');break;
      case 'flupop-resume':send('flupop-resume',{run_id:target.dataset.run});break;
      case 'cloud-open':send('cloud-open',{run_id:target.dataset.run});break;
      case 'cloud-download':{const bytes=Uint8Array.from(atob(U.cloud.archive),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));const a=document.createElement('a');a.href=url;a.download=U.cloud.run.id+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);break;}
      case 'restart-as-browser':send('restart-as-browser');break;
      case 'app-updates':modal('Releases & updates',`<p>Installed version: <strong>${e(S.version)}</strong></p><p class="v-note">Use the official release page for available versions and installation instructions.</p><div class="button-row v-result"><a class="btn primary" href="https://github.com/crackberryq/Virologix/releases" target="_blank" rel="noopener noreferrer">Open releases ↗</a><a class="btn" href="https://github.com/crackberryq/Virologix#readme" target="_blank" rel="noopener noreferrer">Installation guide ↗</a></div>`);break;
      case 'get-support':modal('Virologix support','<p>Report interface or installation issues with your application version and relevant error details.</p><a class="btn primary v-result" href="https://github.com/crackberryq/Virologix/issues" target="_blank" rel="noopener noreferrer">Open GitHub issues ↗</a>');break;
      case 'about':modal('About Virologix',`<p>Created by <strong>Jimi Goldstein · Human Link GenoMix</strong>.</p><p class="v-note">Virologix ${e(S.version)} · Local alpha</p><p class="v-note">Bactologix workspace design, adapted for Virologix. Viral Cloud supplied-record reports are available. Raw-read analysis is not included.</p>`);break;
    }
  });
  on(root,'input',event=>{
    if(event.target.closest('#sample-form'))U.draft[event.target.name]=event.target.value;
    if(event.target.id==='sample-search'){U.filter=event.target.value;$('#sample-results').innerHTML=sampleTable(S.samples.filter(s=>s.id.toLowerCase().includes(U.filter.toLowerCase())));}
  });
  on(root,'submit',async event=>{
    if(event.target.id==='sample-form'){event.preventDefault();send('register',U.draft);}
    if(event.target.id==='cloud-form'){
      event.preventDefault();if(U.pending)return;
      const args={sample:$('#cloud-sample').value};
      try{
        for(const key of ['consensus','haplotypes','evidence']){
          const file=$('#cloud-'+key).files[0];
          if(file && file.size>10*1024*1024)throw Error('Each input must be no larger than 10 MiB.');
          args[key]=file?new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer()):'';
        }
        send('cloud-package',args);
      }catch(error){U.notice={ok:false,text:error.message};render();}
    }
  });
  on(root,'keydown',event=>{
    if(event.key==='Escape'){closeModal();drawer(false);}
    const dialog=$('[role="dialog"]');
    if(dialog && event.key==='Tab'){const focusable=[...dialog.querySelectorAll('button,a[href],input')];const first=focusable[0],last=focusable.at(-1);const active=parentElement.getRootNode().activeElement;if(event.shiftKey&&active===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&active===last){event.preventDefault();first.focus();}}
  });
  render();
  const completed=S.cloud_runs.find(run=>run.job_id===U.waitingJob && run.status==='succeeded');
  if(completed && !U.pending){U.waitingJob=null;pollTimer=setTimeout(()=>send('cloud-open',{run_id:completed.id}),0);}
  else if(S.tasks.some(t=>['queued','running'].includes(t.status)) && !U.pending){pollTimer=setTimeout(()=>send('refresh'),2000);}
}
