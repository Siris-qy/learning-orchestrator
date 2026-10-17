"use strict";
let libraryData, selectedView = '', selectedPath = [], selectedBlock = null, loadVersion = 0;
let contextVersion = 0, selectedCourse = null;
let pointMatches=[], searchVersion=0, searchTimer;
const incomingReturn = new URLSearchParams(location.search).get('return');
const label = (tag, text, cls) => {const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;};
const byId = id => document.getElementById(id);
function navigate(view, path=[]) {
  selectedView=view;selectedPath=path;selectedBlock=null;loadVersion++;
  history.pushState(null,'', '#'+new URLSearchParams({view,path:JSON.stringify(path)}));
  byId('search').value='';pointMatches=[];searchVersion++;clearTimeout(searchTimer);render();
  byId('reader').replaceChildren(label('h2','从一个知识块开始'),label('p','选中后查看正文、增量补充和来源。','muted'));
}
function navButton(title, subtitle, action, active=false) {
  const b=label('button','', 'nav-card'+(active?' active':''));
  b.append(label('strong',title),label('span',subtitle));b.onclick=action;return b;
}
function scopeItems() {return libraryData.items.filter(i=>i.view_key===selectedView && selectedPath.every((p,n)=>i.path[n]===p));}
function viewKind() {return selectedView==='foundations'?'foundations':selectedView==='projects'||selectedView.startsWith('project:')?'project':selectedView==='courses'||selectedView.startsWith('course:')?'course':'';}
function learningUrl(course, mode='tree') {
  if (!course) return incomingReturn?.startsWith('/#')?incomingReturn:'/';
  if (mode==='tree') {
    const incoming=new URLSearchParams((incomingReturn||'').split('#')[1]||'');
    if(incoming.get('course')===course && incomingReturn.startsWith('/#'))return incomingReturn;
    try {const saved=localStorage.getItem('lo.learning:'+course);if(saved?.startsWith('#')&&new URLSearchParams(saved.slice(1)).get('course')===course)return '/'+saved;}catch{}
  }
  return '/#'+new URLSearchParams({course,view:mode});
}
function updateLearningLinks(course) {
  selectedCourse=course||selectedCourse;
  let fallback=selectedCourse;
  try {fallback=fallback||localStorage.getItem('lo.last-course');}catch{}
  byId('learning-link').href=learningUrl(fallback);
  byId('resume-link').href=learningUrl(fallback);
  byId('review-map-link').href='/review-map.html'+(fallback?'#'+new URLSearchParams({project_id:fallback}):'');
  byId('resume-link').textContent=fallback?'继续学习 →':'返回学习 →';
}
async function learningContext(view) {
  const version=++contextVersion,box=byId('learning-context');box.replaceChildren();box.hidden=!view?.course_id;
  if(view?.root_node_id){
    box.hidden=false;const copy=label('div','', 'learning-context-copy');copy.append(label('span','公共知识体系','eyebrow'),label('p','正文按知识块保存，关系图按知识节点组织；相关面试题在节点详情下展示。'));
    const a=label('a','查看知识图与关联题目 →');a.href='/review-map.html#'+new URLSearchParams({project_id:view.root_node_id});box.append(copy,a);
    byId('review-map-link').href=a.href;return;
  }
  updateLearningLinks(view?.course_id);
  if(!view?.course_id)return;
  const text=label('div','', 'learning-context-copy');text.append(label('span','学习与知识相连','eyebrow'),label('p','读取当前讲解位置…'));
  const actions=label('div','', 'context-actions');
  for(const [title,mode] of [['继续学习','tree'],[view.kind==='project'?'结构与通路':'课程知识目录',view.kind==='project'?'project':'knowledge'],['题目与掌握检查','cockpit']]) {
    const a=label('a',title);a.href=learningUrl(view.course_id,mode);actions.append(a);
  }
  box.append(text,actions);
  try{
    const state=await jsonApi('/api/teaching?course_id='+encodeURIComponent(view.course_id));
    if(version!==contextVersion)return;
    text.lastChild.textContent=state.current_item?.title?'当前讲解：'+state.current_item.title:'学习计划和讲解记录保留在学习页，整理出的知识在这里积累。';
  }catch{if(version===contextVersion)text.lastChild.textContent='进入学习页查看教学计划与进度。';}
}
function render() {
  const nav=byId('navigation'),crumb=byId('breadcrumb');nav.replaceChildren();crumb.replaceChildren();
  const home=label('button','复习总览');home.onclick=()=>navigate('');crumb.append(home);
  const view=libraryData.views.find(v=>v.key===selectedView);
  const kind=viewKind();
  if(kind==='project'||kind==='course'){
    crumb.append(label('span','›'));const parent=label('button',kind==='project'?'项目':'课程');
    parent.onclick=()=>navigate(kind==='project'?'projects':'courses');crumb.append(parent);
  }
  if(view){crumb.append(label('span','›'));const b=label('button',view.title);b.onclick=()=>navigate(selectedView);crumb.append(b);}
  selectedPath.forEach((p,n)=>{crumb.append(label('span','›'));const b=label('button',p);b.onclick=()=>navigate(selectedView,selectedPath.slice(0,n+1));crumb.append(b);});
  if(view && (kind==='project'||kind==='course')) {
    const switcher=label('select','', 'scope-switcher');switcher.setAttribute('aria-label',kind==='project'?'切换项目':'切换课程');
    for(const v of libraryData.views.filter(v=>v.kind===kind)){
      const option=label('option',v.title);option.value=v.key;switcher.append(option);
    }
    switcher.value=selectedView;switcher.onchange=()=>navigate(switcher.value);crumb.append(switcher);
  }
  const tabs=byId('scope-tabs');tabs.replaceChildren();
  for(const [title,key,k] of [['全部','', ''],['基础能力','foundations','foundations'],['项目','projects','project'],['课程','courses','course']]){
    const b=label('button',title,kind===k?'active':'');b.onclick=()=>navigate(key);tabs.append(b);
  }
  const total=selectedView==='projects'||selectedView==='courses'?libraryData.items.filter(i=>i.view_key.startsWith(kind+':')):scopeItems();
  byId('page-title').textContent=selectedPath.at(-1)||view?.title||(selectedView==='projects'?'项目知识':selectedView==='courses'?'课程知识':'把学过的内容串起来');
  byId('page-description').textContent=view?.knowledge_system?'按主题找到公共知识正文，查看上下位关系和相关题目；项目使用同一份知识，不重复保存。':kind==='project'?'沿模块、处理通路和基础原理理解项目，回到学习页继续深入。':kind==='course'?'按课程位置找到已学内容，逐步沉淀为可复用的知识。':'从概念到使用场景，找到已有知识，也看见后续补充的位置。';
  byId('block-count').textContent=new Set((total.length?total:!selectedView?libraryData.items:[]).map(i=>i.id)).size;
  byId('count-label').textContent='已接入的知识块';
  document.querySelector('.workspace').hidden=!selectedView||selectedView==='projects'||selectedView==='courses';
  document.querySelector('.intro').classList.toggle('overview',!selectedView);
  learningContext(view);
  if(!selectedView){
    nav.append(navButton('基础能力','网络、C++、算法、数据库',()=>navigate('foundations')));
    nav.append(navButton('项目','每个项目有独立模块与通路',()=>navigate('projects')));
    nav.append(navButton('课程','沿课程目录回到学过的内容',()=>navigate('courses')));
    for(const v of libraryData.views.filter(v=>v.knowledge_system))nav.append(navButton(v.title,'独立知识体系 · 正文、知识图与关联题目',()=>navigate(v.key)));
  }else if(selectedView==='projects'||selectedView==='courses'){
    for(const v of libraryData.views.filter(v=>v.kind===(selectedView==='projects'?'project':'course')))
      nav.append(navButton(v.title, `${new Set(libraryData.items.filter(i=>i.view_key===v.key).map(i=>i.id)).size} 个知识块 · ${v.knowledge_system?'公共知识体系':selectedView==='projects'?'进入项目':'进入课程'}`,()=>navigate(v.key)));
  }else{
    const paths=new Set(scopeItems().filter(i=>i.path.length>selectedPath.length).map(i=>i.path[selectedPath.length]));
    if(selectedView==='foundations'&&!selectedPath.length) Object.values(libraryData.areas).forEach(p=>paths.add(p));
    for(const p of paths) nav.append(navButton(p,'进入这一范围',()=>navigate(selectedView,[...selectedPath,p])));
  }
  renderList();
}
function renderList() {
  const list=byId('list');list.replaceChildren();
  const term=byId('search').value.toLowerCase();
  const rows=scopeItems().filter(i=>[i.title,i.description,i.original_title].filter(Boolean).join(' ').toLowerCase().includes(term)||pointMatches.some(p=>'wiki:'+p.block_id===i.id));
  byId('list-title').textContent=selectedPath.at(-1)||libraryData.views.find(v=>v.key===selectedView)?.title||'浏览知识范围';
  byId('list-note').textContent=`${new Set(rows.map(r=>r.id)).size} 个知识块 · 点击阅读`;
  if(!selectedView || selectedView==='projects' || selectedView==='courses') {
    byId('list-note').textContent='';
    list.append(label('p','从上方选择范围，进入专题或模块目录。','muted'));return;
  }
  const groups=new Map();
  for(const row of rows){const key=row.path.slice(selectedPath.length).join(' / ')||'当前范围';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
  for(const [group,items] of groups){
    const details=label('details','', 'group');details.open=true;details.append(label('summary',group));
    for(const item of items){const b=label('button','', 'knowledge-card'+(selectedBlock===item.id?' selected':''));
      b.title=item.original_title||item.title;
      b.append(label('strong',item.title),label('small',item.description||(item.reference_only?'已接入笔记':item.has_synthesis?`已整理 · ${item.entry_count} 份来源记录`:`${item.entry_count} 条补充`)));
      b.onclick=()=>openItem(item);details.append(b);
      for(const p of pointMatches.filter(p=>'wiki:'+p.block_id===item.id)){
        const hit=label('button','↳ '+p.title,'point-match');hit.onclick=async()=>{await openItem(item);jumpPoint(p.id);};details.append(hit);
      }}
    list.append(details);
  }
  if(!rows.length)list.append(label('p',selectedView?'这个范围暂未登记知识块。后续教学可逐节补入。':'选择上方入口浏览已有内容。','muted'));
}
async function jsonApi(url){const r=await fetch(url,{cache:'no-store'}),d=await r.json();if(!r.ok||d.error)throw Error(d.error||r.status);return d;}
async function openWiki(id){return openItem(libraryData.items.find(i=>i.id==='wiki:'+id)||{id:'wiki:'+id});}
async function openItem(item, persist=true){
  const version=++loadVersion;selectedBlock=item.id;renderList();
  const params=new URLSearchParams({view:selectedView,path:JSON.stringify(selectedPath),block:item.id});if(persist)history.pushState(null,'','#'+params);
  updateLearningLinks(item.course_id||libraryData.views.find(v=>v.key===selectedView)?.course_id);
  const currentView=libraryData.views.find(v=>v.key===selectedView);
  if(currentView?.root_node_id)byId('review-map-link').href='/review-map.html#'+new URLSearchParams({project_id:currentView.root_node_id});
  const reader=byId('reader');reader.replaceChildren(label('p','读取知识内容…','muted'));
  try{
    if(item.id.startsWith('wiki:')){
      const b=await jsonApi('/api/wiki?id='+encodeURIComponent(item.id.slice(5)));if(version!==loadVersion)return;
      reader.replaceChildren(WikiReader.render(b,openWiki));
      const point=new URLSearchParams(location.hash.slice(1)).get('point');if(point)WikiReader.focus(reader,point);
    }else if(item.legacy_points){
      reader.replaceChildren(label('h2',item.title),label('p','这是原笔记的知识点索引，展开时读取原正文。','muted'));
      for(const point of item.legacy_points){
        const d=label('details','');d.append(label('summary',point.point_id+' · '+point.title));let loaded=false;
        d.ontoggle=async()=>{if(!d.open||loaded)return;loaded=true;try{
          const body=await jsonApi('/api/knowledge_item?course_id='+encodeURIComponent(item.course_id)+'&id='+encodeURIComponent(point.id));
          const text=body.prepare?.material?.text;if(text)d.append(WikiReader.markdown(text));else d.append(label('p','暂无准确关联的正文。','muted'));
        }catch(err){loaded=false;d.append(label('p',err.message));}};reader.append(d);
      }
    }else{
      const b=await jsonApi('/api/knowledge_item?course_id='+encodeURIComponent(item.course_id)+'&id='+encodeURIComponent(item.id));if(version!==loadVersion)return;
      reader.replaceChildren(label('h2',item.title));if(item.description)reader.append(label('p',item.description,'muted'));for(const c of b.chunks||[])reader.append(WikiReader.markdown(c.text));
      const a=label('a','进入原项目／复习页面 →');a.href='/#'+new URLSearchParams({course:item.course_id,view:'cockpit',cp:item.id});reader.append(a);
    }
  }catch(err){if(version===loadVersion)reader.replaceChildren(label('p','读取失败：'+err.message));}
}
function jumpPoint(id){
  const params=new URLSearchParams(location.hash.slice(1));params.set('point',id);
  history.pushState(null,'','#'+params);WikiReader.focus(byId('reader'),id);
}
function searchPoints(){
  const version=++searchVersion;pointMatches=[];renderList();clearTimeout(searchTimer);
  const term=byId('search').value.trim();if(!term)return;
  searchTimer=setTimeout(async()=>{try{
    const results=await jsonApi('/api/knowledge_points?q='+encodeURIComponent(term));
    if(version===searchVersion){pointMatches=results;renderList();}
  }catch{}},180);
}
async function restoreLocation(){
  loadVersion++;
  const hash=new URLSearchParams(location.hash.slice(1));selectedView=hash.get('view')||'';
  if(selectedView.includes(':')&&!libraryData.views.some(v=>v.key===selectedView)) {
    selectedView=libraryData.views.find(v=>v.course_id===selectedView.slice(selectedView.indexOf(':')+1))?.key||'';
  }
  try{selectedPath=JSON.parse(hash.get('path')||'[]');if(!Array.isArray(selectedPath))selectedPath=[];}catch{selectedPath=[];}
  render();
  byId('reader').replaceChildren(label('h2','选择一个知识块'),label('p','先选内容，再沿关联找到它的上下游和项目用法。','muted'));
  const b=libraryData.items.find(i=>i.id===hash.get('block'));if(b)await openItem(b,false);
}
async function start(){
  libraryData=await jsonApi('/api/library');
  byId('search').oninput=searchPoints;
  window.addEventListener('popstate',()=>restoreLocation());
  await restoreLocation();
}
start().catch(err=>byId('list').replaceChildren(label('p','知识库读取失败：'+err.message)));
