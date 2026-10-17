"use strict";
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => {const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
const kinds={project:'项目 / 课程',module:'模块',flow:'实现流程',knowledge:'知识点',option:'候选方案',claim:'简历条目'};
const masteryNames={unassessed:'未评估',weak:'薄弱',usable:'基本掌握',solid:'熟练'};
const learningNames={unknown:'学习情况未知',not_started:'未学习',learning:'学习中',learned:'学过'};
const relations={contains:'包含',uses:'使用',requires:'依赖',next:'下一步',fails_to:'异常分支',supports:'支撑',alternative_to:'替代方案',upgrade_to:'升级',abstracts_to:'抽出共性',analogous_to:'关联联想',related:'关联',prerequisite:'前置',used_in:'用于',contrasts_with:'对比'};
let data={nodes:[],edges:[],findings:[],question_refs:[]},selected=null,loadVersion=0,detailVersion=0,nextCursor=null,focusId=null;
async function api(path){const r=await fetch(path);const value=await r.json();if(!r.ok||value.error)throw Error(value.error||'读取失败');return value;}
function params(){const q=new URLSearchParams();if($('project').value)q.set('project_id',$('project').value);if(focusId)q.set('root_id',focusId);if(selected)q.set('node_id',selected);if($('domain').value)q.set('domains',$('domain').value);if($('mastery').value)q.set('mastery',$('mastery').value);q.set('dependency_expansion',$('expansion').value);q.set('include_extensions',$('extensions').checked?'1':'0');q.set('limit',$('project').value.startsWith('knowledge-system:')?'300':'100');return q;}
async function load(more=false){
  const version=++loadVersion,q=params();if(more&&nextCursor!=null)q.set('cursor',nextCursor);
  history.replaceState(null,'','#'+q);$('status').textContent='正在读取知识图…';
  try{
    const incoming=await api('/api/review_map?'+q);if(version!==loadVersion)return;
    if(more){
      const combined=[...data.nodes,...incoming.nodes];data.nodes=[...new Map(combined.map(n=>[n.id,n])).values()];
      // Fetch one bounded combined page to include edges crossing the page boundary.
      const joined=params();joined.set('limit',Math.min(data.nodes.length,300));
      const complete=await api('/api/review_map?'+joined);if(version!==loadVersion)return;
      data.edges=complete.edges;data.findings=complete.findings;data.question_refs=complete.question_refs;
    }else{data=incoming;}
    nextCursor=incoming.next_cursor;$('more').hidden=nextCursor==null||data.nodes.length>=300;$('all-project').hidden=!focusId;
    $('count').textContent=data.total;$('status').textContent=`显示 ${data.nodes.length} / ${data.total} 个节点 · ${data.edges.length} 条关联`;
    if(data.total>300)$('status').textContent+=' · 当前关系图最多展示 300 个，请选择项目或领域缩小范围';
    const pure=data.nodes.length>0&&data.nodes.every(n=>n.kind==='knowledge'||n.owner_ref?.type==='knowledge_system');
    const root=data.nodes.find(n=>n.id===(focusId||data.root_id));
    $('map-title').textContent=pure?(root?.title||'公共知识关系'):'把面试回答串起来';
    $('map-description').textContent=pure?'上位知识组织阅读范围，下位知识可以独立定位。实线表示包含，虚线表示前置依赖；点击节点阅读对应正文。':'从模块目的进入实现流程，再查看支撑它的知识。点击节点查看内容和掌握情况。';
    $('all-project').textContent=$('project').value?'返回整个项目':'返回全部知识';
    if(!selected&&root&&pure)selected=root.id;
    draw();if(selected&&data.nodes.some(n=>n.id===selected))selectNode(selected);
  }catch(e){if(version===loadVersion)$('status').textContent='读取失败：'+e.message;}
}
function svgEl(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs||{}))e.setAttribute(k,String(v));if(text!=null)e.textContent=text;return e;}
function lines(text,size=18){const chars=Array.from(text||'');const result=[];for(let i=0;i<chars.length&&result.length<2;i+=size)result.push(chars.slice(i,i+size).join(''));if(chars.length>size*2)result[1]=result[1].slice(0,-1)+'…';return result;}
function draw(){
  $('diagram').replaceChildren();$('node-list').replaceChildren();
  if(!data.nodes.length){const e=el('div',null,'empty-map');e.append(el('h3','此范围还没有关联的知识节点'),el('p','可先由讲解窗口登记模块、流程与已有知识的关系。'));$('diagram').append(e);return;}
  const pure=data.nodes.every(n=>n.kind==='knowledge'||n.owner_ref?.type==='knowledge_system');
  const parents=new Map(),order=new Map();
  for(const e of data.edges)if(e.relation==='contains'){if(!parents.has(e.to))parents.set(e.to,e.from);order.set(e.to,e.seq??0);}
  function depth(id){const seen=new Set();let d=0;while(parents.has(id)&&!seen.has(id)){seen.add(id);id=parents.get(id);d++;}return Math.min(d,3);}
  const depthMax=pure?Math.max(1,...data.nodes.map(n=>depth(n.id))):2;
  const columns=Array.from({length:depthMax+1},()=>[]);
  const sorted=[...data.nodes].sort((a,b)=>(order.get(a.id)??-1)-(order.get(b.id)??-1)||a.title.localeCompare(b.title,'zh-CN'));
  for(const n of sorted)columns[pure?depth(n.id):n.kind==='project'||n.kind==='module'?0:n.kind==='flow'||n.kind==='claim'?1:2].push(n);
  const width=Math.max(540,$('diagram').clientWidth-2),columnWidth=Math.floor((width-30)/columns.length),nodeWidth=columnWidth-28;
  const height=Math.max(370,...columns.map(c=>c.length*112+75)),svg=svgEl('svg',{width,height,role:'img','aria-label':pure?'公共知识层级与前置关联':'项目模块、实现流程与关联知识'});
  const defs=svgEl('defs'),marker=svgEl('marker',{id:'arrow',viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});
  marker.append(svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#98b7ab'}));defs.append(marker);svg.append(defs);
  const positions=new Map();
  columns.forEach((ns,c)=>{svg.append(svgEl('text',{x:20+c*columnWidth,y:28,class:'column-label'},(pure?(depthMax===1?['知识主题','下位知识']:['知识体系','知识主题','独立知识','细分知识']):['模块与目标','处理流程','知识与扩展'])[c]));ns.forEach((n,r)=>positions.set(n.id,{x:15+c*columnWidth,y:pure&&ns.length===1?Math.max(48,(height-88)/2):48+r*112}));});
  for(const e of data.edges){const a=positions.get(e.from),b=positions.get(e.to);if(!a||!b)continue;
    const same=a.x===b.x,forward=b.x>a.x;
    const ax=same?a.x+nodeWidth:forward?a.x+nodeWidth:a.x,bx=same?b.x+nodeWidth:forward?b.x:b.x+nodeWidth,ay=a.y+40,by=b.y+40;
    const bend=same?Math.max(ax,bx)+24:(ax+bx)/2;
    svg.append(svgEl('path',{d:`M ${ax} ${ay} C ${bend} ${ay}, ${bend} ${by}, ${bx} ${by}`,class:'graph-edge'+(e.inclusion==='extension'?' extension':'')+(pure&&e.relation==='requires'?' prerequisite':''),'marker-end':'url(#arrow)'}));
    const t=svgEl('text',{x:same?bend-8:(ax+bx)/2,y:(ay+by)/2-5,class:'edge-label','text-anchor':'middle'},relations[e.relation]||e.relation);const title=svgEl('title',{},e.usage||e.rationale||'');t.append(title);svg.append(t);
  }
  for(const n of data.nodes){const p=positions.get(n.id),g=svgEl('g',{class:`graph-node ${n.kind}${selected===n.id?' selected':''}`,transform:`translate(${p.x},${p.y})`,tabindex:0,role:'button','aria-label':n.title});
    g.append(svgEl('rect',{width:nodeWidth,height:88,rx:10}));g.append(svgEl('text',{x:13,y:18,class:'node-kind'},`${kinds[n.kind]||n.kind} · ${masteryNames[n.effective_mastery]||'未评估'}`));
    lines(n.title,Math.max(10,Math.floor((nodeWidth-26)/12))).forEach((line,i)=>g.append(svgEl('text',{x:13,y:40+i*17},line)));
    g.append(svgEl('text',{x:13,y:77,class:'node-kind'},pure?(parents.has(n.id)?'独立知识 · 点击定位正文':'上位知识 · 阅读完整知识块'):n.required?'项目核心关联':n.kind==='knowledge'?'公共知识 / 可复用':'可选关联'));
    g.onclick=()=>selectNode(n.id);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectNode(n.id);}};svg.append(g);
  }
  const visited=new Set();
  function listBranch(n,depth){if(visited.has(n.id))return;visited.add(n.id);const card=el('button',null,'node-card'+(selected===n.id?' active':''));card.style.marginLeft=Math.min(depth,4)*16+'px';card.style.width=`calc(100% - ${Math.min(depth,4)*16}px)`;card.append(el('strong',n.title),el('small',n.summary||`${kinds[n.kind]} · ${masteryNames[n.effective_mastery]}`));card.onclick=()=>selectNode(n.id);$('node-list').append(card);for(const child of sorted.filter(x=>parents.get(x.id)===n.id))listBranch(child,depth+1);}
  for(const n of sorted.filter(n=>!parents.has(n.id)))listBranch(n,0);
  for(const n of sorted)listBranch(n,0);
  $('diagram').append(svg);
}
async function selectNode(id){
  selected=id;history.replaceState(null,'','#'+params());const version=++detailVersion;draw();const box=$('detail');box.replaceChildren(el('p','正在读取节点…','muted'));
  try{
    const contexts=data.edges.filter(e=>e.to===id&&e.context_project_id===$('project').value);
    const context=contexts.length===1?'&context_edge_id='+encodeURIComponent(contexts[0].id):'';
    const n=await api('/api/review_node?id='+encodeURIComponent(id)+'&content=1'+context);if(version!==detailVersion)return;
    if(n.id!==selected){selected=n.id;history.replaceState(null,'','#'+params());draw();}
    box.replaceChildren(el('h2',n.title));box.append(el('span',masteryNames[n.effective_mastery],'state-pill '+n.effective_mastery),el('span',learningNames[n.learning_status],'state-pill'));
    if(n.kind==='module'||n.kind==='flow'||n.kind==='option'){const focus=el('button','只看此模块的关联'),row=el('p',null);focus.onclick=()=>{focusId=id;load();};row.append(focus);box.append(row);}
    if(n.context_mastery)box.append(el('p',`当前项目用法：${masteryNames[n.context_mastery]} · 公共原理：${masteryNames[n.general_mastery]}`,'state-note'));
    if(n.summary)box.append(WikiReader.markdown(n.summary));
    const note=el('p',n.content_state==='name_only'?'仅登记了名称，正文待关联。':n.content_state==='outline'?'当前是项目说明或提纲，可继续补充核心实现。':'正文引用已有知识内容。','state-note');box.append(note);
    const related=data.edges.filter(e=>e.from===id||e.to===id);
    if(related.length){const relationBox=n.kind==='knowledge'?el('details',null,'knowledge-connections'):box;if(n.kind==='knowledge'){relationBox.append(el('summary',`知识层级与关联 · ${related.length} 条`));box.append(relationBox);}else box.append(el('h3','流程位置与关联用法'));for(const e of related){
      const rid=e.from===id?e.to:e.from,target=data.nodes.find(x=>x.id===rid);const item=el('div',null,'map-relationship'),b=el('button',target?.title||rid);
      b.onclick=()=>selectNode(rid);item.append(b,el('small',(e.from===id?'→ ':'← ')+(relations[e.relation]||e.relation)));
      for(const key of ['usage','rationale','conditions','tradeoffs'])if(e[key])item.append(el('p',e[key]));relationBox.append(item);
    }}
    if(n.content){box.append(el('h3','知识内容'));if(n.content_ref.type==='knowledge_block')box.append(WikiReader.render(n.content,selectNode));else if(n.content.text)box.append(WikiReader.markdown(n.content.text));else if(n.content.material)box.append(WikiReader.markdown(n.content.material.text));else if(Array.isArray(n.content))for(const c of n.content)box.append(WikiReader.markdown(c.text||c.content||''));}
    for(const a of box.querySelectorAll('.wiki-point-index a')){const point=new URL(a.href,location.href).hash.slice(1);const pid=new URLSearchParams(point).get('point');if(pid)a.onclick=e=>{e.preventDefault();selectNode(pid);};}
    appendQuestions(box,n);
    const fs=data.findings.filter(f=>f.target_node_ids.includes(id));if(fs.length){box.append(el('h3','复盘待处理'));for(const f of fs)box.append(el('p',f.summary));}
    if(n.gaps.length){box.append(el('h3','当前缺口'));for(const gap of n.gaps)box.append(el('p',gap));}
    if(n.context_gaps?.length){box.append(el('h3','项目用法的缺口'));for(const gap of n.context_gaps)box.append(el('p',gap));}
    if(n.review_briefs.length){box.append(el('h3','复习排期'));for(const r of n.review_briefs)box.append(el('p',r.next_due?`下次提醒：${r.next_due}`:'尚未记录首次复述','state-note'));}
    for(const a of box.querySelectorAll('a[href^="#"]'))a.onclick=e=>{const target=box.querySelector('#'+CSS.escape(decodeURIComponent(a.getAttribute('href').slice(1))));if(target){e.preventDefault();let d=target.closest('details');while(d){d.open=true;d=d.parentElement?.closest('details');}const next=target.nextElementSibling;if(next?.tagName==='DETAILS')next.open=true;target.scrollIntoView({behavior:'smooth',block:'start'});}};
    const other=n.connections?.filter(e=>e.context_project_id&&e.context_project_id!==$('project').value)||[];
    if(other.length){box.append(el('h3','其他项目中的使用位置'));for(const e of other){const a=el('a',e.target_title);a.href='/review-map.html#'+new URLSearchParams({project_id:e.context_project_id});box.append(a,el('p',e.usage||relations[e.relation],'state-note'));}}
  }catch(e){if(version===detailVersion)box.replaceChildren(el('p','读取失败：'+e.message));}
}
function appendQuestions(box,n){
  // Collect descendant questions without copying their bodies into the note.
  const scope=new Set([n.id]);let changed=true;
  while(changed){changed=false;for(const e of data.edges)if(e.relation==='contains'&&scope.has(e.from)&&!scope.has(e.to)){scope.add(e.to);changed=true;}}
  const questions=new Map((data.question_refs||[]).filter(q=>q.node_ids.some(id=>scope.has(id))).map(q=>[q.id,q]));
  for(const q of n.question_refs||[])if(!questions.has(q.id))questions.set(q.id,q);
  const section=el('section',null,'question-section');section.id='knowledge-questions';
  section.append(el('h3',`这个知识点怎么考察 · ${questions.size} 题`),el('p',scope.size>1?'汇总本主题及下位知识的关联题目。答案按需展开，浏览不改变掌握或复习日期。':'题目引用独立题库。先尝试复述，再展开答案；浏览不改变掌握或复习日期。','state-note'));
  if(!questions.size)section.append(el('p','暂未关联题目，后续可复用面经题或补入教材练习。','muted'));
  for(const q of questions.values()){
    const card=el('article',null,'question-card');card.dataset.questionId=q.id;
    card.append(el('span',q.level==='firsthand'?'亲历题':q.origin==='knowledge_check'?'补充自测题':'普通面试题','question-label'),el('h4',q.stem));
    const scopes=(q.scopes||[]).filter(s=>scope.has(s.node_id));
    const focuses=[...new Set(scopes.map(s=>s.focus).filter(Boolean))];
    if(focuses.length)card.append(el('p','考察：'+focuses.join('；'),'question-focus'));
    const coverage=[...new Set(scopes.map(s=>s.coverage).filter(Boolean))];
    if(coverage.length)card.append(el('p',coverage.join('；'),'state-note'));
    const links=el('div',null,'question-knowledge-links');
    for(const nid of q.node_ids.filter(id=>scope.has(id))){const target=data.nodes.find(x=>x.id===nid);if(!target)continue;const b=el('button',target.title);b.onclick=()=>selectNode(nid);links.append(b);}card.append(links);
    const detail=el('details',null,'question-answer');detail.append(el('summary','参考回答与来源'));let loaded=false;
    detail.ontoggle=async()=>{
      if(!detail.open||loaded)return;loaded=true;const content=el('div','正在读取题库…','answer-content');detail.append(content);
      try{
        const entry=await api('/api/question?id='+encodeURIComponent(q.id));content.replaceChildren();
        content.append(WikiReader.markdown(entry.answer_basis||'当前题库仅登记了题干，参考回答待补。'));
        const source=entry.source_ref||{},origin=source.file||source.path||source.title||source.url;
        if(origin)content.append(el('p','来源：'+origin+(source.lines?.length?' · 原始行号 '+source.lines.join('、'):'')+(source.anchor?' · '+source.anchor:''),'state-note'));
        const judgment=entry.judgment;content.append(el('p',judgment?(judgment.result==='pass'?'最近作答：通过':'最近作答：需深入')+(judgment.gap_note?' · '+judgment.gap_note:''):'尚未记录实际作答判断。','state-note'));
      }catch(e){loaded=false;content.textContent='读取失败：'+e.message;}
    };card.append(detail);section.append(card);
  }
  box.append(section);
  if(questions.size){const jump=el('button',`查看相关题目（${questions.size}）`,'question-jump');jump.onclick=()=>section.scrollIntoView({behavior:'smooth',block:'start'});box.insertBefore(jump,box.querySelector('.knowledge-connections')||section);}
}
async function init(){
  const incoming=new URLSearchParams(location.hash.slice(1));let project=incoming.get('project_id')||incoming.get('course_id')||'';focusId=incoming.get('root_id');selected=incoming.get('node_id');
  try{
    const roots=await api('/api/review_map?limit=1');for(const r of roots.roots){const o=el('option',r.title);o.value=r.id;$('project').append(o);}
    if([...$('project').options].some(o=>o.value===project))$('project').value=project;
  }catch(e){$('status').textContent=e.message;}
  for(const [id,key]of [['domain','domains'],['mastery','mastery'],['expansion','dependency_expansion']])if(incoming.has(key))$(id).value=incoming.get(key);
  $('extensions').checked=incoming.get('include_extensions')==='1';
  for(const id of ['project','domain','mastery','expansion','extensions'])$(id).onchange=()=>{if(id==='project')focusId=null;selected=null;detailVersion++;$('detail').replaceChildren(el('h2','选择一个节点'),el('p','点击当前范围中的节点，查看正文和掌握情况。','muted'));load();};
  $('all-project').onclick=()=>{focusId=null;load();};
  $('reload').onclick=()=>load();$('more').onclick=()=>load(true);
  $('diagram-tab').onclick=()=>{$('diagram').hidden=false;$('node-list').hidden=true;$('diagram-tab').classList.add('active');$('list-tab').classList.remove('active');};
  $('list-tab').onclick=()=>{$('diagram').hidden=true;$('node-list').hidden=false;$('list-tab').classList.add('active');$('diagram-tab').classList.remove('active');};
  await load();
}
window.addEventListener('resize',()=>draw());
// Opening another knowledge/project link on this same page changes only the
// fragment. Restore its scope and selection rather than retaining the old map.
window.addEventListener('hashchange',()=>{
  const incoming=new URLSearchParams(location.hash.slice(1));
  focusId=incoming.get('root_id');selected=incoming.get('node_id');detailVersion++;
  $('project').value=incoming.get('project_id')||incoming.get('course_id')||'';
  $('domain').value=incoming.get('domains')||'';
  $('mastery').value=incoming.get('mastery')||'';
  $('expansion').value=incoming.get('dependency_expansion')||'reference';
  $('extensions').checked=incoming.get('include_extensions')==='1';
  load();
});
init();
