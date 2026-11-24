const get=id=>document.getElementById(id);
const n=(tag,text=null,cls='')=>{const node=document.createElement(tag);if(text!==null)node.textContent=String(text);if(cls)node.className=cls;return node};
const append=(parent,...children)=>{parent.append(...children);return parent};
let state=null,page='download',urls='',codecs={},lastMessage='',lastAudio=0,polling=false,bridge={},pageKey='',closingDialog=false;
const speedSamples=[];
const t=(en,fa)=>state?.settings.language==='en'?en:fa;
const pages=[['download','⇩','Download','دانلود'],['search','⌕','Search','جست‌وجو'],['queue','≡','Queue','صف'],['history','◷','History','تاریخچه'],['log','⌘','Log','گزارش'],['settings','⚙','Settings','تنظیمات'],['browser','↗','Chrome Extension','افزونهٔ Chrome'],['packages','◇','Packages & Tools','بسته‌ها و ابزارها']];
const text=(value,cls='muted')=>n('p',value,cls);
const button=(label,callback,cls='quiet')=>{const element=n('button',label,cls);element.type='button';element.onclick=callback;return element};
const section=(title,...content)=>append(n('section',null,'glass card'),n('h2',title,'section'),...content);
const row=(...items)=>append(n('div',null,'flex action-row'),...items);
const entries=items=>items.map(item=>typeof item==='string'?[item,item]:Array.isArray(item)?item:[item.key,item.label]);
const bytes=value=>{if(value===null||value===undefined)return '—';let amount=Number(value),index=0;while(amount>=1024&&index<4){amount/=1024;index++}return amount.toFixed(index?1:0)+' '+['B','KB','MB','GB','TB'][index]};
const seconds=value=>Number.isFinite(value)?new Date(Math.max(0,value)*1000).toISOString().slice(11,19):'—';
function select(items,value,change){
 const control=n('select');
 for(const [key,label] of entries(items)){const option=n('option',label);option.value=key;control.append(option)}
 control.value=value;control.onchange=()=>change(control.value);return control;
}
function field(label,control){return append(n('label',label),control)}
function toggle(label,value,change){const control=n('input');control.type='checkbox';control.checked=Boolean(value);control.onchange=()=>change(control.checked);return append(n('label',null,'check-row'),control,n('span',label))}
function input(value,change,kind='text'){const control=n('input');control.type=kind;control.value=value??'';control.onchange=()=>change(kind==='number'?Math.round(Number(control.value)):control.value);return control}
function notify(message){if(!message)return;const toast=get('notice');toast.textContent=message;toast.hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>toast.hidden=true,3600)}
async function api(action,args={},refresh=true){
 try{
  const result=await pywebview.api.dispatch(action,args);
  if(result.error)notify(result.error);
  if(refresh)await poll();
  return result;
 }catch(err){notify(String(err));return {}}
}
const save=(key,value)=>api('save',{[key]:value});
const setting=(key,label,values=null,kind='text')=>{
 const value=state.settings[key];
 if(kind==='checkbox')return toggle(label,value,v=>save(key,v));
 return field(label,values?select(values,value,v=>save(key,v)):input(value,v=>save(key,v),kind));
};
function saveSelected(key,label,values){return field(label,select(values,state.settings[key],value=>save(key,value)))}
function setPage(next){page=next;pageKey='';render(true);if(next==='packages')void api('packages');if(next==='browser')void getBridge()}
async function getBridge(){const result=await api('bridge',{},false);bridge=result;render(true)}
async function editorAction(mode){
 const el=get('urls');
 if(el)urls=el.value;
 const options={urls,codecs};
 if(mode==='download'&&/(apkpure\.com|^apkpure:)/im.test(urls)&&
    !await confirmInline(t('APKPure is a third-party source. Continue?','APKPure منبع شخص ثالث است. ادامه می‌دهید؟')))return;
 return api(mode,options);
}
function changeLinks(value){urls=value;if(get('urls'))get('urls').value=urls}
function changeLink(url,replace=false){const all=replace?[]:urls.split(/\r?\n/).filter(Boolean);if(!all.includes(url))all.push(url);changeLinks(all.join('\n'))}
function removeLink(url,clearPreview=true){changeLinks(urls.split(/\r?\n/).filter(line=>line.trim()!==url).join('\n'));delete codecs[url];if(clearPreview)void api('remove',{url})}
async function paste(){try{const value=await navigator.clipboard.readText();if(value)changeLinks([urls,value].filter(Boolean).join('\n'))}catch{const value=(await api('clipboard_read',{},false)).text;if(value)changeLinks([urls,value].filter(Boolean).join('\n'))}}
async function copy(value){try{await navigator.clipboard.writeText(value)}catch{await api('clipboard_write',{text:value},false)}}
function portfolio(media,remove=false){
 const outer=n('div',null,'preview media-card');
 const url=String(media.thumbnail||'');
 const image=/^https:\/\//.test(url)?n('img'):n('div','▶','thumb');
 if(image.tagName==='IMG'){image.src=url;image.alt='';image.referrerPolicy='no-referrer'}
 const body=append(n('div',null,'detail'),n('strong',media.title||media.url),n('small',[media.service,seconds(media.duration)].filter(Boolean).join(' · '),'muted'));
 if(media.error)body.append(text(media.error));
 if(remove&&(media.audio_languages||[]).length)body.append(n('small',t('Audio','صدا')+': '+media.audio_languages.map(item=>item.label||item.name||item.code).filter(Boolean).slice(0,5).join(', '),'muted'));
 if(remove&&(media.subtitle_languages||[]).length)body.append(n('small',t('Subtitles','زیرنویس')+': '+media.subtitle_languages.map(item=>item.label||item.name||item.code).filter(Boolean).slice(0,5).join(', '),'muted'));
 if(remove&&media.estimate)body.append(n('small',t('Estimated size','حجم تخمینی')+' '+bytes(media.estimate),'muted'));
 if(remove&&(media.codecs||[]).length){
  const options=[['',t('Automatic','خودکار')],...media.codecs.map(key=>[key,state.codecs[key]])];
  const codec=select(options,codecs[media.url]||'',value=>codecs[media.url]=value);
  codec.disabled=state.settings.preset.startsWith('audio_');
  body.append(field(t('Video codec','کدک ویدیو'),codec));
 }
 outer.append(image,body);
 if(remove){const close=button('×',()=>removeLink(media.url),'media-remove');close.setAttribute('aria-label',t('Remove preview and link','حذف پیش‌نمایش و لینک')+' '+media.title);outer.append(close)}
 else outer.append(row(button(t('Use link','استفاده از لینک'),()=>{changeLink(media.url,true);setPage('download');void editorAction('preview')}),button(t('Add to Queue','افزودن به صف'),()=>api('queue_add',{urls:[media.url]}))));
 return outer;
}
function preview(){
 const list=n('div',null,'download-list');
 for(const item of state.preview)list.append(portfolio(item,true));
 if(!state.preview.length)list.append(text(t('Links will appear here after preview.','پس از پیش‌نمایش، لینک‌ها اینجا نمایش داده می‌شوند.')));
 return list;
}
function progress(){
 const data=state.progress;
 const percent=Number.isFinite(data.percent)?Math.max(0,Math.min(100,data.percent)):null;
 const labels={preparing:t('Preparing','آماده‌سازی'),downloading:t('Downloading','در حال دانلود'),finished:t('Processing','پردازش نهایی'),completed:t('Completed','دانلود کامل شد'),cancelled:t('Cancelled','دانلود لغو شد'),error:t('Download failed','خطا در دانلود')};
 const track=append(n('div',null,'track download-pill'),n('i'));
 track.firstChild.style.width=(percent??(state.busy?36:0))+'%';
 track.setAttribute('role','progressbar');track.setAttribute('aria-label',t('Download progress','پیشرفت دانلود'));
 if(percent!==null)track.setAttribute('aria-valuenow',percent);
 const metrics=n('div',null,'metrics');
 for(const [label,value] of [[t('Speed','سرعت'),data.speed?bytes(data.speed)+'/s':'—'],[t('Remaining','باقی‌مانده'),seconds(data.eta)],[t('Received','دریافتی'),bytes(data.downloaded)]])metrics.append(append(n('div'),n('small',label),n('strong',value)));
 speedSamples.push(Number(data.speed)||0);if(speedSamples.length>35)speedSamples.shift();
 const namespace='http://www.w3.org/2000/svg',chart=document.createElementNS(namespace,'svg'),line=document.createElementNS(namespace,'polyline'),peak=Math.max(1,...speedSamples);
 chart.setAttribute('class','speed-chart');chart.setAttribute('viewBox','0 0 180 30');chart.setAttribute('preserveAspectRatio','none');
 line.setAttribute('points',speedSamples.map((v,i)=>[i*180/Math.max(1,speedSamples.length-1),29-26*v/peak].join(',')).join(' '));chart.append(line);
 return append(n('div',null,percent===null&&state.busy?'is-busy':''),append(n('div',null,'progress-head'),n('strong',labels[data.status]||t('Ready','آماده')),n('span',data.service||'', 'progress-chip')),text(data.title||''),n('div',percent===null?(state.busy?'…':'0%'):Math.round(percent)+'%','progress-number'),track,metrics,chart);
}
function download(){
 const grid=n('div',null,'grid');
 const editor=n('textarea');editor.id='urls';editor.dir='ltr';editor.value=urls;editor.spellcheck=false;editor.oninput=()=>urls=editor.value;
 editor.ondragover=e=>e.preventDefault();editor.ondrop=e=>{e.preventDefault();const value=e.dataTransfer.getData('text/uri-list')||e.dataTransfer.getData('text/plain');if(value)changeLinks([urls,value].filter(Boolean).join('\n'))};
 const previewButton=button(t('Preview links','پیش‌نمایش لینک‌ها'),()=>editorAction('preview'),'primary');previewButton.id='preview-button';
 const startButton=button(t('Start download','شروع دانلود'),()=>editorAction('download'),'primary');startButton.id='start-button';
 const cancelButton=button(t('Cancel','لغو'),()=>api('cancel'));cancelButton.id='cancel-button';
 const formats=append(n('div',null,'controls'),setting('preset',t('Quality / format','کیفیت / فرمت'),state.presets),
  setting('audio_language',t('Audio language','زبان صدا'),[['',t('Automatic','خودکار')],...languages('audio_languages')]),
  setting('subtitle_language',t('Subtitles','زیرنویس'),[['all',t('All','همه')],...languages('subtitle_languages')]),
  field(t('Output folder','پوشهٔ خروجی'),button(state.settings.output_dir,()=>choose('output_dir',true),'quiet output-label')));
 formats.id='options-block';
 const previews=preview();previews.id='preview-block';
 const status=progress();status.id='progress-block';
 grid.append(section(t('Links','لینک‌ها'),editor,row(previewButton,button(t('Paste','چسباندن'),paste),button(t('Clear','پاک‌کردن'),()=>changeLinks('')),button(t('Add to Queue','افزودن به صف'),()=>editorAction('queue_add')))),
  section(t('Download options','گزینه‌های دانلود'),formats,row(startButton,cancelButton,button(t('Open folder','بازکردن پوشه'),()=>api('open_folder')),button(t('Settings','تنظیمات'),()=>setPage('settings')))),
  section(t('Preview','پیش‌نمایش'),previews),section(t('Download progress','پیشرفت دانلود'),status));
 const current=n('div',null,'list');current.id='active-queue';
 return append(n('div',null,'page-block'),grid,section(t('Current queue','صف فعلی'),current,button(t('Open queue','بازکردن صف'),()=>setPage('queue'))));
}
function languages(key){
 const options=new Map();
 for(const item of state.preview)for(const option of item[key]||[])if(option.code)options.set(option.code,option.label||option.name||option.code);
 return [...options];
}
async function choose(key,folder=false){
 const res=await api(folder?'choose_folder':'choose_file',{},false);if(res.path){await save(key,res.path);render(true)}
}
function search(){
 const query=input('',()=>{});query.id='query';
 const service=select(state.searchServices,state.settings.search_service,value=>save('search_service',value));
 const limit=input(state.settings.search_limit,value=>save('search_limit',value),'number');limit.min=1;limit.max=50;
 const run=button(t('Search','جست‌وجو'),()=>api('search',{service:service.value,query:query.value,limit:Number(limit.value)}),'primary');run.id='search-submit';
 const results=n('div',null,'list action-row');results.id='search-results';results.append(...state.search.map(item=>portfolio(item)));
 const form=append(n('div',null,'form-grid'),field(t('Search term','عبارت جست‌وجو'),query),field(t('Service','سرویس'),service),field(t('Limit','تعداد نتیجه'),limit));
 query.onkeydown=e=>{if(e.key==='Enter')run.click()};
 return section(t('Search','جست‌وجو'),form,row(run),results);
}
function selectedRows(){return [...document.querySelectorAll('[data-index]:checked')].map(item=>Number(item.dataset.index))}
function queue(){
 const list=n('div',null,'list');
 state.queue.forEach((item,index)=>{
  const check=n('input');check.type='checkbox';check.dataset.index=index;check.setAttribute('aria-label',item.title||item.url);
  const details=append(n('div'),n('strong',item.title||item.url),n('small',item.service||item.url,'muted'));
  const quality=select(state.presets,item.preset||state.settings.preset,preset=>api('queue_quality',{index,preset}));
  list.append(append(n('div',null,'row queue-row'),check,details,quality,button(t('Use link','استفاده از لینک'),()=>{changeLink(item.url,true);setPage('download');void editorAction('preview')})));
 });
 const entry=n('textarea');entry.placeholder=t('Add links to your queue','افزودن لینک به صف');
 return section(t('Download queue','صف دانلود'),entry,row(button(t('Add links','افزودن لینک‌ها'),async()=>{await api('queue_add',{urls:entry.value});entry.value=''}),button(t('Start selected or all','شروع انتخاب‌شده یا همه'),()=>api('queue_run',{indexes:selectedRows()}),'primary'),button(t('Remove selected','حذف انتخاب‌شده‌ها'),()=>api('queue_remove',{indexes:selectedRows()})),button(t('Clear queue','پاک‌کردن صف'),()=>confirmAction('queue_clear'))),list);
}
function table(headers,entries){
 const head=append(n('thead'),append(n('tr'),...headers.map(label=>n('th',label))));
 const body=n('tbody');
 for(const entry of entries){const line=n('tr');for(const value of entry){const cell=n('td');if(value instanceof Node)cell.append(value);else cell.textContent=value??'—';line.append(cell)}body.append(line)}
 return append(n('div',null,'table-wrap'),append(n('table'),head,body));
}
const confirmAction=async action=>{if(await confirmInline(t('Confirm this action?','این عملیات انجام شود؟')))await api(action)};
function confirmInline(message){
 return new Promise(resolve=>{
  const dialog=n('dialog',null,'glass card');dialog.append(text(message),row(button(t('Confirm','تأیید'),()=>finish(true),'primary'),button(t('Cancel','لغو'),()=>finish(false))));
  function finish(value){dialog.close();dialog.remove();resolve(value)}
  dialog.oncancel=event=>{event.preventDefault();finish(false)};document.body.append(dialog);dialog.showModal();
 });
}
function history(){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 svg.setAttribute('viewBox','0 0 232 124');svg.setAttribute('aria-hidden','true');
 const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','M20 116 A96 96 0 0 1 212 116');path.setAttribute('fill','none');path.setAttribute('stroke-width','6');path.setAttribute('stroke-linecap','round');path.setAttribute('class','arc-tint');svg.append(path);
 const dial=append(n('div',null,'usage-dial'),svg,append(n('div',null,'usage-display'),n('strong',bytes(state.received))));
 return append(n('div',null,'page-block'),section(t('Total download data received','مجموع دادهٔ دریافتی دانلودها'),append(n('div',null,'usage'),dial,text(t('Media data reported by yt-dlp since tracking began.','دادهٔ رسانهٔ گزارش‌شده توسط yt-dlp از زمان آغاز شمارش.')))),section(t('Download history','تاریخچهٔ دانلودها'),
 table([t('Date','زمان'),t('Title','عنوان'),t('Service','سرویس'),t('Received','دادهٔ دریافتی'),t('Actions','عملیات')],state.history.map((item,index)=>[String(item.downloaded_at||'').replace('T',' ').slice(0,19),item.title||item.url,item.service,bytes(item.received_bytes),row(button(t('Download again','دانلود دوباره'),()=>{changeLink(item.url,true);setPage('download');void editorAction('download')}),button(t('Open folder','پوشه'),()=>api('history_folder',{index})),button(t('Copy link','کپی لینک'),()=>copy(item.url)))])),row(button(t('Clear history','پاک‌کردن تاریخچه'),()=>confirmAction('history_clear')))));
}
const soundNames={download_complete:['Download complete','پایان دانلود'],queue_complete:['Queue complete','پایان صف'],error:['Error','خطا'],warning:['Warning','هشدار'],cancelled:['Cancelled','لغو'],notification:['Notification','اعلان']};
function soundSettings(){
 const s=state.settings,slider=n('input');slider.id='volume';slider.type='range';slider.min=0;slider.max=100;slider.value=s.sound_volume;
 const value=n('output',s.sound_volume+'%','volume-value');
 const line=append(n('div',null,'volume-line'),value,slider,append(n('div',null,'scale'),...[0,25,50,75,100].map(v=>n('span',v))));
 line.style.setProperty('--volume',s.sound_volume);
 slider.oninput=()=>{value.value=slider.value+'%';line.style.setProperty('--volume',slider.value)};
 slider.onchange=()=>save('sound_volume',Number(slider.value));
 const events=n('div',null,'sound-events');
 for(const event of state.soundEvents){
  const label=t(...(soundNames[event]||[event,event]));
  const source=input(s.sound_custom[event],value=>save('sound_custom',{...state.settings.sound_custom,[event]:value}));
  source.placeholder=t('Default sound or custom file','صدای پیش‌فرض یا فایل سفارشی');source.setAttribute('aria-label',label);
  const chooseFile=button(t('Choose…','انتخاب…'),async()=>{const result=await api('choose_file',{},false);if(result.path){source.value=result.path;await save('sound_custom',{...state.settings.sound_custom,[event]:result.path})}});
  events.append(append(n('div',null,'sound-event'),toggle(label,s.sound_events[event]!==false,value=>save('sound_events',{...state.settings.sound_events,[event]:value})),source,chooseFile,button(t('Test','تست'),()=>api('sound_test',{event}))));
 }
 return section(t('Sound settings','تنظیم صدا'),
  setting('sound_enabled',t('Enable app sounds','فعال‌بودن صداهای برنامه'),null,'checkbox'),
  setting('sound_theme',t('Sound pack','بستهٔ صدا'),[['gentle',t('Gentle & pleasant','ملایم و دلنشین')],['system',t('System sounds','صدای سیستم')]]),
  append(n('div',null,'sound-volume'),field(t('Volume','بلندی صدا'),line)),events,
  row(button(t('Clear custom sounds','پاک‌کردن صداهای سفارشی'),async()=>{await save('sound_custom',{});render(true)})));
}
const flags=items=>append(n('div',null,'form-grid'),...items.map(([key,en,fa])=>setting(key,t(en,fa),null,'checkbox')));
function settings(){
 const grid=n('div',null,'settings-grid');
 grid.append(section(t('Appearance and language','ظاهر و زبان'),append(n('div',null,'form-grid'),setting('theme',t('Theme','تم'),state.themes),setting('language',t('Language','زبان'),[['fa','فارسی'],['en','English']]))),
 section(t('Storage and download','ذخیره و دانلود'),append(n('div',null,'form-grid'),
 setting('output_dir',t('Output folder','پوشهٔ خروجی')),field(t('Browse','انتخاب'),button(t('Choose folder','انتخاب پوشه'),()=>choose('output_dir',true))),
 setting('preset',t('Quality / format','کیفیت / فرمت'),state.presets),setting('fragments',t('Concurrent fragments','بخش‌های همزمان'),null,'number')),
 flags([['organize_service','Organize by service','مرتب‌سازی بر اساس سرویس'],['playlist','Download playlists','دانلود پلی‌لیست'],['metadata','Embed metadata','درج متادیتا'],['thumbnail','Embed thumbnail','درج تصویر بندانگشتی'],['subtitles','Download subtitles','دانلود زیرنویس'],['auto_subtitles','Include automatic subtitles','زیرنویس خودکار'],['mark_watched','Mark watched','علامت دیده‌شده'],['clipboard_monitor','Watch clipboard','پایش کلیپ‌بورد']])),
 section(t('Cookies and login','کوکی و ورود'),append(n('div',null,'form-grid'),
 setting('auth_source',t('Authentication','روش احراز هویت'),[['none',t('None','بدون کوکی')],['auto',t('Automatic','خودکار')],['saved',t('Saved profile','پروفایل ذخیره‌شده')],['browser',t('Browser','مرورگر')],['file',t('Cookie file','فایل کوکی')],['manual',t('Manual','دستی')],['extension',t('Extension','افزونه')]]),
 setting('browser',t('Browser','مرورگر'),state.browsers),setting('browser_profile',t('Browser profile','پروفایل مرورگر')),
 setting('cookie_file',t('Cookie file','فایل کوکی')),field(t('Browse','انتخاب'),button(t('Choose file','انتخاب فایل'),()=>choose('cookie_file'))),
 setting('cookie_domain',t('Cookie domain','دامنهٔ کوکی')),field(t('Manual cookies','کوکی دستی'),input('',value=>save('manual_cookie',value),'password')),
 setting('remember_auth',t('Remember authentication','ذخیرهٔ روش احراز هویت'),null,'checkbox')),
 row(button(t('Clear saved authentication','پاک‌کردن احراز هویت ذخیره‌شده'),async()=>{if(await confirmInline(t('Remove saved authentication for these links?','احراز هویت ذخیره‌شده حذف شود؟')))await api('auth_clear',{urls})}))),
 section(t('JavaScript runtime and services','موتور JavaScript و سرویس‌ها'),append(n('div',null,'form-grid'),
 setting('js_runtime',t('Runtime','موتور'),['auto','deno','node','bun','quickjs','none']),setting('js_runtime_path',t('Runtime path','مسیر موتور')),
 setting('spotify_client_id','Spotify Client ID'),field('Spotify Client Secret',input('',v=>save('spotify_client_secret',v),'password')),
 setting('spotify_proxy','Spotify Proxy'),setting('spotify_use_official_api',t('Spotify official API','API رسمی Spotify'),null,'checkbox'),
 setting('google_play_email','Google Play e-mail'),field('Google Play AAS token',input('',v=>save('google_play_aas_token',v),'password')))),
 );
 const sound=soundSettings();sound.classList.add('sound-controls');grid.append(sound);return grid;
}
function packagePage(){
 const labels=[t('Package','بسته'),t('Version','نسخه'),t('Path','مسیر'),t('Action','عملیات')];
 const items=state.packages.map(item=>[item.name,item.version||'—',item.path||'—',button(item.installed?t('Update','به‌روزرسانی'):t('Install','نصب'),()=>api('package',{key:item.key,installed:item.installed}))]);
 for(const item of items)item[3].disabled=state.packageBusy;
 return section(t('Packages and tools','بسته‌ها و ابزارها'),row(button(t('Check system','بررسی سیستم'),()=>api('packages'),'primary')),table(labels,items),section(t('Package log','گزارش بسته‌ها'),n('pre',state.logs.slice(-25).join('\n'),'log-box')));
}
function browser(){
 const info=bridge.bridge||{};
 return section(t('Chrome connection','اتصال Chrome'),text(info.registered?t('Native host registered','میزبان بومی ثبت شده'):t('Native host not registered','میزبان بومی ثبت نشده')),
  field(t('Extension folder','پوشهٔ افزونه'),input(info.extension_path||'',()=>{})),
  row(button(t('Install / Repair bridge','نصب / تعمیر اتصال'),async()=>{await api('bridge_install');await getBridge()},'primary'),button(t('Remove bridge','حذف اتصال'),async()=>{await confirmAction('bridge_uninstall');await getBridge()}),button(t('Copy path','کپی مسیر'),()=>copy(info.extension_path||'')),button(t('Copy pairing code','کپی کد جفت‌سازی'),()=>copy(bridge.token||''))));
}
function heading(){
 get('version').textContent=state.version;
 const language=button(t('فارسی','English'),()=>save('language',t('fa','en')));
 const theme=select(state.themes,state.settings.theme,value=>save('theme',value));
 theme.setAttribute('aria-label',t('Theme','تم'));
 const update=state.updateReady?button(t('Apply update','اعمال به‌روزرسانی'),()=>api('update_apply')):state.update?
  button(t('Download update','دریافت به‌روزرسانی')+' '+state.update,()=>api('update_download')):
  button(t('Check for update','بررسی به‌روزرسانی'),()=>api('update_check'));
 get('heading-actions').replaceChildren(theme,language,update);
 get('nav').replaceChildren(...pages.map(([key,icon,en,fa])=>{
  const item=button('',()=>setPage(key),'nav');item.setAttribute('aria-selected',String(page===key));item.append(n('span',icon),n('div',t(en,fa)));return item;
 }));
}
function render(force=false){
 document.documentElement.dir=t('ltr','rtl');document.documentElement.lang=state.settings.language;document.documentElement.dataset.theme=state.settings.theme;
 const [key,icon,en,fa]=pages.find(item=>item[0]===page);
 const freshKey=[page,state.settings.language,state.settings.theme,state.update,state.updateReady].join('|');
 const fresh=force||pageKey!==freshKey;
 if(fresh){
  pageKey=freshKey;heading();
  const layouts={download,search,queue,history,log:()=>section(t('Runtime log','گزارش اجرا'),n('pre',state.logs.join('\n'),'log-box')),settings,browser,packages:packagePage};
  get('main').replaceChildren(n('h1',t(en,fa),'page-title'),layouts[page]());
 }
 if(page==='download'){
  get('preview-button').disabled=state.previewBusy;get('start-button').disabled=state.busy;get('cancel-button').disabled=!state.busy;
  const fingerprint=JSON.stringify([state.preview,state.settings.preset,state.settings.audio_language,state.settings.subtitle_language,state.settings.output_dir]);
  if(render.preview!==fingerprint||fresh){
   render.preview=fingerprint;
   get('preview-block').replaceChildren(...preview().childNodes);
   if(!get('options-block').contains(document.activeElement)){
    const options=download().querySelector('#options-block');get('options-block').replaceChildren(...options.childNodes);
   }
  }
  const batch=JSON.stringify(state.batch);
  if(fresh||render.batch!==batch){
   render.batch=batch;
   const labels={waiting:t('Waiting','در انتظار'),downloading:t('Downloading','در حال دانلود'),completed:t('Completed','کامل‌شده'),cancelled:t('Cancelled','لغوشده'),error:t('Failed','ناموفق')};
   get('active-queue').replaceChildren(...(state.batch.length?state.batch.map(item=>append(n('div',null,'row split'),n('strong',item.title),n('span',labels[item.status]||item.status,'muted'))):[text(t('No active downloads','دانلود فعالی وجود ندارد'))]));
  }
  const value=JSON.stringify(state.progress);
  if(fresh||render.progress!==value){render.progress=value;get('progress-block').replaceChildren(progress())}
 }
 if(page==='search'){
  get('search-submit').disabled=state.searchBusy;
  const value=JSON.stringify(state.search);
  if(fresh||render.search!==value){render.search=value;get('search-results').replaceChildren(...state.search.map(item=>portfolio(item)))}
 }
 if(!fresh&&['queue','history','packages','log'].includes(page)){
  const source={queue:state.queue,history:[state.history,state.received],packages:[state.packages,state.packageBusy,state.logs],log:state.logs}[page];
  const value=JSON.stringify(source);
  if(render.data!==value){render.data=value;render(true)}
 }
}
async function poll(){
 if(polling)return;
 polling=true;
 try{
  state=await pywebview.api.snapshot(lastAudio);
  if(state.closeConfirmation&&!closingDialog){
   closingDialog=true;
   void confirmInline(t('Cancel the running download and close?','دانلود در حال اجرا لغو و برنامه بسته شود؟'))
    .then(ok=>ok?api('window_close'):null).finally(()=>closingDialog=false);
  }
  for(const entry of state.incoming){
   if(entry.action==='open'||entry.action==='clipboard'){changeLink(entry.url);if(entry.action==='open'){setPage('download');void editorAction('preview');}}
   if(entry.action==='completed')removeLink(entry.url,false);
  }
  for(const sound of state.sounds){lastAudio=Math.max(lastAudio,sound.id);const player=new Audio(sound.audio);player.volume=sound.volume;player.play().catch(()=>{});}
  if(state.message&&state.message!==lastMessage){lastMessage=state.message;notify(lastMessage)}
  render();
 }catch(error){notify(String(error))}
 finally{polling=false}
}
window.addEventListener('pywebviewready',async()=>{await poll();await api('ready',{},false);setInterval(poll,330)});
