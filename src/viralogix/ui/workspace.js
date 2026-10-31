export default function(component) {
  const {parentElement, data, setTriggerValue} = component;
  const root = parentElement.querySelector('.bacto-root');
  root._dispose?.();
  const abort = new AbortController();
  root._dispose = () => abort.abort();
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
  const names = {overview:'Overview',samples:'Samples',cfasta:'cFASTA workbench',pipelines:'Pipelines',runs:'Runs',resources:'Databases & resources',setup:'Setup'};
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
    if(response.action==='inspect') U.inspection=response.ok?response:null;
    if(response.action==='register' && response.ok) U.draft={};
  }
  function sampleTable(samples) {
    if(!samples.length) return '<div class="empty">'+icon('samples')+'<h3>No samples to display</h3><p>Register local input paths to prepare your workspace.</p></div>';
    return `<div class="table-wrap"><table><thead><tr><th>Sample</th><th>Inputs</th><th>Reference</th><th>Status</th></tr></thead><tbody>${samples.map(s=>`<tr><td><strong class="sample-name">${e(s.id)}</strong><span class="secondary-line">${e(s.created)}</span></td><td class="v-path">${e(s.r1)}${s.r2?`<span class="secondary-line v-path">${e(s.r2)}</span>`:''}</td><td class="v-path">${e(s.reference || 'Not supplied')}</td><td>${pill('Registered')}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function overview(){
    return heading('Your virology workspace','Organize local inputs and inspect existing cFASTA files.',button('Register sample','samples',true))+
      `<div class="stats-grid"><div class="stat"><div class="stat-label">Registered samples${icon('samples')}</div><div class="stat-value">${S.samples.length}</div><div class="stat-foot">Local file references</div></div><div class="stat"><div class="stat-label">cFASTA inspection${icon('cfasta')}</div><div class="stat-value label">Available</div><div class="stat-foot">Syntax review & consensus export</div></div><div class="stat"><div class="stat-label">Pipeline execution${icon('pipelines')}</div><div class="stat-value label">Planned</div><div class="stat-foot">Foundation interface only</div></div></div>`+
      `<div class="split"><section class="card experiment-card"><div class="card-body"><div class="copy"><span class="mini-chip">PREPARE YOUR WORKSPACE</span><h2>Your inputs, ready for what comes next.</h2><p>Keep samples organized while the pipeline integrations are being developed.</p><div class="button-row">${button('Explore samples','samples',true)}${button('Inspect cFASTA','cfasta')}</div></div></div></section>`+
      card('Workspace capabilities','Available utilities and upcoming integrations.',`<div class="pipeline-row"><span class="pipeline-logo">S</span><div class="pipeline-info"><strong>Sample registry</strong><small>Register existing local files</small></div>${pill('Available')}</div><div class="pipeline-row"><span class="pipeline-logo">C</span><div class="pipeline-info"><strong>cFASTA workbench</strong><small>Inspect files and export consensus</small></div>${pill('Available')}</div><div class="pipeline-row"><span class="pipeline-logo">P</span><div class="pipeline-info"><strong>Pipeline integrations</strong><small>In development</small></div>${pill('Planned','off')}</div>`)+`</div>`+
      `<section class="card"><div class="card-head"><div><h2>Recent samples</h2><p>Your registered local inputs.</p></div><button class="quiet" data-nav="samples">View all ${icon('arrow')}</button></div>${sampleTable(S.samples.slice(0,5))}</section>`;
  }
  function samples(){
    const field=(key,label,required=false)=>`<div class="field ${key==='sample'?'':'wide'}"><label for="${key}">${label}</label><input id="${key}" name="${key}" value="${e(U.draft[key]||'')}" ${required?'required':''} autocomplete="off"></div>`;
    return heading('Samples','Register file paths without moving or uploading sequencing inputs.')+
      card('Register a sample','Use Linux paths in WSL, for example /mnt/c/data/sample_R1.fastq.gz.',`<form id="sample-form" class="v-form"><div class="form-grid">${field('sample','Sample ID',true)}${field('r1','R1 FASTQ path',true)}${field('r2','R2 FASTQ path (optional)')}${field('reference','Segment reference FASTA path (optional)')}</div><button class="btn primary" type="submit" ${U.pending?'disabled':''}>${U.pending==='register'?'Registering…':'Register sample'}</button></form>`)+
      `<div class="toolbar v-result"><h2>Registered samples (${S.samples.length})</h2><input class="search" id="sample-search" type="search" aria-label="Search samples" placeholder="Search samples…" value="${e(U.filter)}"></div><section class="card" id="sample-results">${sampleTable(S.samples.filter(s=>s.id.toLowerCase().includes(U.filter.toLowerCase())))}</section>`;
  }
  function inspection(){
    const r=U.inspection;if(!r)return '';
    const columns=['id','abundance','confidence','support','resolution','span','edits'];
    return `<div class="notice"><div><strong>Syntax valid: ${r.entries.length} ${r.entries.length===1?'segment':'segments'}</strong><p>This checks file syntax; it does not verify biological results.</p></div></div><div class="notice amber"><p>Draft semantics: consensus is not automatically an observed haplotype. Local rows may overlap and their abundances must not be pooled.</p></div><button class="btn" data-action="download">Download consensus FASTA</button>`+
      r.entries.map(entry=>`<details class="card v-result"><summary>${e(entry.metadata.sample)} / ${e(entry.metadata.segment)}</summary><div class="card-body"><pre class="code-block">${e(entry.consensus)}</pre></div><div class="table-wrap"><table><thead><tr>${columns.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>${entry.haplotypes.length?entry.haplotypes.map(row=>`<tr>${columns.map(c=>`<td>${e(row[c])}</td>`).join('')}</tr>`).join(''):'<tr><td colspan="7">No rows recorded.</td></tr>'}</tbody></table></div></details>`).join('');
  }
  function cfasta(){return heading('cFASTA workbench','Inspect an existing file and download a separate ordinary consensus FASTA export.')+card('Open a cFASTA file','Interactive preview supports UTF-8 .cfasta files up to 10 MiB.',`<label for="cfasta-file" class="v-note">Choose a local file for inspection</label><input class="v-file" id="cfasta-file" type="file" accept=".cfasta" ${U.pending?'disabled':''}><p class="v-note">${U.pending==='inspect'?'Inspecting '+e(U.filename)+'…':U.inspection?'Reviewed file: '+e(U.filename):'The selected file is read by your local Virologix instance. No pipeline is started.'}</p>`)+inspection();}
  function planned(view){
    const content={pipelines:['Pipelines','Prepare for future integrations.','Pipeline integrations are in development','Installation and execution controls will become available when a pipeline is connected.'],runs:['Runs','Execution and provenance will appear here when pipelines are connected.','No execution backend connected','Registering a sample or inspecting a file does not create an analysis run.'],resources:['Databases & resources','A consistent home for future pipeline resources.','No resource requirements published yet','Database setup and resource management will be connected alongside the pipelines.']}[view];
    return heading(content[0],content[1])+card(content[2],'Planned',`<div class="empty">${icon(view)}<h3>Ready for integration</h3><p>${content[3]}</p>${pill('Planned','off')}</div>`);
  }
  function setup(){return heading('Setup','Your local workspace and available system resources.')+
    `<div class="stats-grid"><div class="stat"><div class="stat-label">CPU cores</div><div class="stat-value">${e(S.cpu??'Unknown')}</div></div><div class="stat"><div class="stat-label">Available RAM</div><div class="stat-value">${e(S.ram_gib)} <small>GiB</small></div></div><div class="stat"><div class="stat-label">Application</div><div class="stat-value label">${e(S.version)}</div></div></div>`+
    card('Workspace details','Separate from your Bactologix workspace.',`<dl class="detail-list"><dt>Location</dt><dd class="mono">${e(S.home)}</dd><dt>Environment</dt><dd>viromics (standard installer environment)</dd><dt>Mode</dt><dd>${S.desktop?'Managed desktop':'Browser'}</dd></dl><div class="notice"><p>Resource profiles, GPU detection, environment repair and pipeline installation are planned.</p></div>`);}
  function render(){
    $('#app-version').textContent='v'+S.version;
    $('#navigation').innerHTML='<div class="nav-label">WORKSPACE</div>'+['overview','samples','cfasta','pipelines','runs'].map(nav).join('')+'<div class="nav-divider"></div><div class="nav-label">MANAGE</div>'+['resources','setup'].map(nav).join('');
    $('#crumb').textContent=names[U.view];
    $('#main').innerHTML=({overview,samples,cfasta,setup}[U.view]||(()=>planned(U.view)))();
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
      case 'restart-as-browser':send('restart-as-browser');break;
      case 'download':{const url=URL.createObjectURL(new Blob([U.inspection.consensus],{type:'text/plain'}));const a=document.createElement('a');a.href=url;a.download=U.inspection.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);break;}
      case 'app-updates':modal('Releases & updates',`<p>Installed version: <strong>${e(S.version)}</strong></p><p class="v-note">Use the official release page for available versions and installation instructions.</p><div class="button-row v-result"><a class="btn primary" href="https://github.com/crackberryq/Virologix/releases" target="_blank" rel="noopener noreferrer">Open releases ↗</a><a class="btn" href="https://github.com/crackberryq/Virologix#readme" target="_blank" rel="noopener noreferrer">Installation guide ↗</a></div>`);break;
      case 'get-support':modal('Virologix support','<p>Report interface or installation issues with your application version and relevant error details.</p><a class="btn primary v-result" href="https://github.com/crackberryq/Virologix/issues" target="_blank" rel="noopener noreferrer">Open GitHub issues ↗</a>');break;
      case 'about':modal('About Virologix',`<p>Created by <strong>Jimi Goldstein · Human Link GenoMix</strong>.</p><p class="v-note">Virologix ${e(S.version)} · Local alpha</p><p class="v-note">Bactologix workspace design, adapted for Virologix. Pipeline integrations are still in development.</p>`);break;
    }
  });
  on(root,'input',event=>{
    if(event.target.closest('#sample-form'))U.draft[event.target.name]=event.target.value;
    if(event.target.id==='sample-search'){U.filter=event.target.value;$('#sample-results').innerHTML=sampleTable(S.samples.filter(s=>s.id.toLowerCase().includes(U.filter.toLowerCase())));}
  });
  on(root,'submit',event=>{if(event.target.id==='sample-form'){event.preventDefault();send('register',U.draft);}});
  on(root,'change',async event=>{
    if(event.target.id!=='cfasta-file')return;const file=event.target.files[0];if(!file)return;
    U.inspection=null;
    if(file.size>10*1024*1024 || !file.name.toLowerCase().endsWith('.cfasta')){U.notice={ok:false,text:'Choose a .cfasta file no larger than 10 MiB.'};render();return;}
    try{U.filename=file.name;const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());send('inspect',{name:file.name,text});}
    catch(error){U.notice={ok:false,text:'Could not read this file as UTF-8.'};render();}
  });
  on(root,'keydown',event=>{
    if(event.key==='Escape'){closeModal();drawer(false);}
    const dialog=$('[role="dialog"]');
    if(dialog && event.key==='Tab'){const focusable=[...dialog.querySelectorAll('button,a[href],input')];const first=focusable[0],last=focusable.at(-1);const active=parentElement.getRootNode().activeElement;if(event.shiftKey&&active===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&active===last){event.preventDefault();first.focus();}}
  });
  render();
}
