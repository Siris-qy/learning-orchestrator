'use strict';
// Review reads one relationship catalog and exact published body slices. No teaching cursor.
(() => {
  const $ = s => document.querySelector(s);
  const el = (tag,text,cls) => {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const link = (text,href,cls) => {const a=el('a',text,cls);a.href=href;return a;};
  const button=(text,fn,cls)=>{const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;};
  const api=async url=>{const r=await fetch(url);const d=await r.json();if(!r.ok||d.error)throw Error(d.error||r.status);return d;};
  const mode=document.body.dataset.review;
  let nodes=new Map(),edges=[],children=new Map(),parents=new Map(),epoch=0,query='';
  const expanded=new Set(),collapsed=new Set(),detailCache=new Map();
  const labels={cpp:'C++',network:'网络',os:'操作系统',database:'数据库',algorithms:'算法',agent:'Agent'};
  const status=n=>({solid:'已掌握',usable:'基本可用',weak:'需巩固'}[n.mastery]||'未评估');
  const domain=n=>n.id.startsWith('node:')?n.id.split(':')[1]:(n.domains||[])[0]||'project';
  const foundation=n=>n.kind==='project'&&n.owner_ref?.type==='knowledge_system';
  const projects=()=>[...nodes.values()].filter(n=>n.kind==='project'&&!foundation(n));
  const roots=()=>[...nodes.values()].filter(foundation);
  const kids=id=>(children.get(id)||[]).map(e=>nodes.get(e.to_id)).filter(Boolean);
  const up=id=>(parents.get(id)||[])[0]?.from_id;
  function path(id){const a=[],seen=new Set();while(id&&nodes.has(id)&&!seen.has(id)){seen.add(id);a.unshift(nodes.get(id));id=up(id);}return a;}
  function ancestry(id,kind){return path(id).reverse().find(n=>n.kind===kind);}
  function route(){return new URLSearchParams(location.hash.slice(1));}
  const libraryURL=id=>'/library.html#node='+encodeURIComponent(id);
  function projectURL(root,module,node){const p=new URLSearchParams({root_id:root}),old=route();if(mode==='project'&&(!old.get('root_id')||old.get('root_id')===root)){for(const k of ['view','domains','hot','unassessed','extended'])if(old.has(k))p.set(k,old.get(k));}if(module){p.set('module',module);if(['optional','historical'].includes(nodes.get(module)?.provenance?.review_scope))p.set('extended','1');}if(node)p.set('node',node);return '/review-map.html#'+p;}
  function setRoute(values){const p=route();for(const[k,v]of Object.entries(values)){if(v)p.set(k,v);else p.delete(k);}location.hash=p.toString();}
  const outgoing=(id,rel)=>edges.filter(e=>e.from_id===id&&(!rel||e.relation===rel));
  const uniqueUses=list=>[...new Map(list.map(e=>[e.to_id,e])).values()];
  const incoming=(id,rel)=>edges.filter(e=>e.to_id===id&&(!rel||e.relation===rel));
  const dot=n=>el('span',undefined,'dot '+(n.mastery||'unassessed'));
  function nodeLink(n){if(n.kind==='step'){const root=ancestry(n.id,'project'),module=ancestry(n.id,'module'),flow=ancestry(n.id,'flow');if(root&&flow)return link(n.title,projectURL(root.id,module?.id,flow.id)+'&step='+encodeURIComponent(n.id));}if(['flow','module'].includes(n.kind)){const root=ancestry(n.id,'project'),module=ancestry(n.id,'module');if(root)return link(n.title,projectURL(root.id,module?.id)+(n.kind==='flow'?'&flow='+encodeURIComponent(n.id):''));}return link(n.title,libraryURL(n.id));}
  function relationList(host,title,list){const p=el('p');p.append(el('span',title+' ','muted'));if(!list.length)p.append(el('span','暂无登记','muted'));list.forEach((n,i)=>{if(i)p.append(' · ');p.append(nodeLink(n));});host.append(p);}
  function locationOf(e){const chain=path(e.from_id);return {project:nodes.get(e.context_project_id)||chain.find(n=>n.kind==='project'),module:chain.find(n=>n.kind==='module'),flow:chain.find(n=>n.kind==='flow')||nodes.get(e.from_id)};}
  function usageRow(e){const {project,module,flow}=locationOf(e);const row=el('div',undefined,'relation-row');const title=[project?.title,module?.title,flow?.kind==='flow'?flow.title:null].filter(Boolean).join(' › ');row.append(link(title||nodes.get(e.from_id)?.title||e.from_id,project?projectURL(project.id,module?.id)+(flow?.kind==='flow'?'&flow='+encodeURIComponent(flow.id):''):libraryURL(e.from_id)));row.append(el('div',e.payload.usage||'用途尚未登记','muted'),el('div','涉及：'+(e.payload.used_parts||[]).map(x=>nodes.get(x)?.title||x).join('、')+' · 深度：'+({concept:'概念',mechanism:'机制',implementation_tradeoff:'实现与取舍'}[e.payload.required_depth]||'未登记'),'muted'));return row;}
  function treeNode(n,depth,selected,seen=new Set()){
    if(seen.has(n.id))return document.createDocumentFragment();seen=new Set(seen).add(n.id);
    const box=el('div'),row=el('div',undefined,'tree-row'+(selected===n.id?' selected':''));
    const list=kids(n.id),isPath=path(selected).some(x=>x.id===n.id);
    const open=!collapsed.has(n.id)&&(depth===0||isPath||expanded.has(n.id)||!!query);
    let child;
    if(list.length){child=el('div',undefined,'tree-children');child.hidden=!open;const toggle=button(open?'▾':'▸',()=>{child.hidden=!child.hidden;toggle.textContent=child.hidden?'▸':'▾';if(child.hidden){collapsed.add(n.id);expanded.delete(n.id);}else{collapsed.delete(n.id);expanded.add(n.id);}toggle.setAttribute('aria-expanded',String(!child.hidden));},'arrow');toggle.setAttribute('aria-label','展开或收起 '+n.title);toggle.setAttribute('aria-expanded',String(open));row.append(toggle);}else row.append(el('span','·','arrow'));
    const a=nodeLink(n);a.prepend(dot(n));if(selected===n.id)a.setAttribute('aria-current','page');row.append(a);box.append(row);
    if(child){list.forEach(k=>child.append(treeNode(k,depth+1,selected,seen)));box.append(child);}return box;
  }
  function renderTree(selected){const host=$('#tree');host.replaceChildren();if(query){[...nodes.values()].filter(n=>n.kind==='knowledge'&&n.title.toLowerCase().includes(query)).forEach(n=>host.append(nodeLink(n),el('br')));}else roots().forEach(n=>host.append(treeNode(n,0,selected)));}
  function bodyView(body,blockId){const view=WikiReader.markdown(body),anchors=new Map();for(const match of body.matchAll(/<a\s+id=["']([^"']+)["']\s*><\/a>\s*\n#{1,6}\s+([^\n]+)/g))anchors.set(match[2].trim(),match[1]);view.querySelectorAll('h1,h2,h3,h4,h5').forEach((h,i)=>{h.id=anchors.get(h.textContent.trim())||h.id||'body-section-'+i;if(/^(材料位置|复习提示|作业关联|理解检查|来源与索引|相关资料)/.test(h.textContent)){h.classList.add('organization');h.prepend('栏目 · ');}});view.querySelectorAll('a[href^="#"]').forEach(a=>{a.onclick=e=>{const target=a.getAttribute('href').slice(1),h=[...view.querySelectorAll('[id]')].find(x=>x.id===target);e.preventDefault();if(h)h.scrollIntoView({behavior:'smooth'});else{const topic=[...nodes.values()].find(n=>n.content_ref?.type==='knowledge_block'&&n.content_ref.id===blockId);if(topic)location.href=libraryURL(topic.id)+'&section='+encodeURIComponent(target);}};});return view;}
  function stepGraph(structure,projectId,flowId){
    const section=el('section',undefined,'section flow-steps');section.append(el('h2','这条流程如何运转'));
    if(!structure?.steps.length){section.append(el('p','步骤图待整理。可先阅读下方流程正文。','muted'));return section;}
    const graph=el('div',undefined,'step-graph');graph.setAttribute('aria-label','流程步骤及各步使用的知识');
    const stepMap=new Map(structure.steps.map(s=>[s.id,s]));
    structure.steps.forEach((s,i)=>{const card=el('article',undefined,'flow-step');card.id='step-'+s.id;
      const main=el('div',undefined,'step-operation'),title=el('h3');title.append(el('span',String(i+1).padStart(2,'0'),'step-number'),document.createTextNode(s.title));main.append(title,el('p',s.description));card.append(main);
      if(s.knowledge.length){const used=el('div',undefined,'step-knowledge');used.append(el('h4','这一步使用的知识'));s.knowledge.forEach(u=>{const n={...u.general_assessment,...u.assessment},row=el('div',undefined,'step-knowledge-row');const module=ancestry(flowId,'module');const a=link(u.title,projectId?projectURL(projectId,module?.id,u.node_id)+'&edge='+encodeURIComponent(u.edge_id):libraryURL(u.node_id));a.prepend(dot(n));row.append(a,el('span',status(n),'mastery-label '+(n.mastery||'unassessed')));if(u.usage)row.append(el('p',u.usage,'muted'));if(n.gap_note)row.append(el('p',n.gap_note,'step-gap'));used.append(row);});card.append(used);}graph.append(card);
      const next=structure.connections.filter(e=>e.from===s.id);if(next.length){const branches=el('div',undefined,'step-connections');next.forEach(e=>{const target=stepMap.get(e.to);if(!target)return;const a=link((e.relation==='fails_to'?'异常 → ':'↓ ')+target.title,'#step-'+target.id,e.relation==='fails_to'?'step-failure':'');a.onclick=event=>{event.preventDefault();document.getElementById('step-'+target.id)?.scrollIntoView({behavior:'smooth',block:'center'});};branches.append(a);if(e.conditions)branches.append(el('span',e.conditions,'muted'));});graph.append(branches);}
    });section.append(graph);return section;
  }
  function knowledgeQuestionPreview(host,structure){
    if(!structure?.knowledge_question_count)return;
    const section=el('section',undefined,'section knowledge-question-preview');section.append(el('h2','步骤相关知识怎么考察'),el('p','节选 '+structure.knowledge_questions.length+' / '+structure.knowledge_question_count+' 题。题目来自知识点题库，与本流程的直接项目题分开展示。','muted'));
    const label=el('label','显示题数 '),select=el('select');for(const count of [3,5,10]){const option=el('option',String(count));option.value=count;option.selected=Number(route().get('top_k')||5)===count;select.append(option);}select.setAttribute('aria-label','知识点题目节选数量');select.onchange=()=>setRoute({top_k:select.value});label.append(select);section.append(label);
    structure.knowledge_questions.forEach(q=>{
      const card=el('article',undefined,'question'),title=el('h3');title.append(link(q.stem,'/question-bank.html#'+new URLSearchParams({q:q.id,return:location.pathname+location.hash})));card.append(title);
      const grouped=new Map();q.knowledge_refs.forEach(ref=>{if(!grouped.has(ref.node_id))grouped.set(ref.node_id,{...ref,steps:new Set()});if(ref.step_id)grouped.get(ref.node_id).steps.add(ref.step_id);});
      for(const ref of grouped.values()){
        const row=el('div',undefined,'knowledge-preview-ref');row.append(link(ref.title,libraryURL(ref.node_id),'chip'));
        for(const sid of ref.steps){const step=structure.steps.find(s=>s.id===sid);const a=link('用于：'+(step?.title||sid),'#step-'+sid,'step-question-location');a.onclick=e=>{e.preventDefault();document.getElementById('step-'+sid)?.scrollIntoView({behavior:'smooth',block:'center'});};row.append(a);}card.append(row);
      }section.append(card);
    });host.append(section);
  }
  async function renderDetail(host,id,projectId,ticket){
    const base=nodes.get(id);if(!base){host.replaceChildren(el('p','节点尚未登记','empty'));return;}
    const context=projectId?edges.find(e=>e.id===route().get('edge')&&e.to_id===id):null;
    const n={...base,...context?.assessment};
    host.replaceChildren(el('p','正在读取已发布正文…','muted'));
    const topK=route().get('top_k')||5,cacheKey=JSON.stringify([id,projectId||null,topK]);
    let d=detailCache.get(cacheKey);if(!d){const params=new URLSearchParams({id,top_k:topK});if(projectId)params.set('project_id',projectId);d=await api('/api/review_detail?'+params);detailCache.set(cacheKey,d);}if(ticket!==epoch)return;
    host.replaceChildren();const crumbs=el('nav',undefined,'breadcrumbs');crumbs.append(link('基础知识','/library.html'));path(id).forEach(p=>crumbs.append(' / ',nodeLink(p)));host.append(crumbs,el('h1',n.title));
    const tags=el('div',undefined,'chips');tags.append(el('span',labels[domain(n)]||'项目知识','chip'),el('span',status(n),'chip'));host.append(tags);
    const uses=incoming(id,'uses'),dependents=incoming(id,'requires'),prereq=outgoing(id,'requires');
    const projectUses=uses.filter(e=>locationOf(e).project&&!foundation(locationOf(e).project));
    const projectCount=new Set(projectUses.map(e=>locationOf(e).project.id)).size;
    const badges=el('div',undefined,'badges'),panel=el('div',undefined,'relation-box');panel.hidden=true;
    const show=(key)=>{if(panel.dataset.kind===key&&!panel.hidden){panel.hidden=true;return;}panel.hidden=false;panel.dataset.kind=key;panel.replaceChildren();if(key==='uses'){if(projectCount>=2)panel.append(el('strong','该知识点串联起 '+projectCount+' 个项目'));if(!uses.length)panel.append(el('p','暂无使用记录'));uses.forEach(e=>panel.append(usageRow(e)));}else{if(!dependents.length)panel.append(el('p','暂无依赖记录'));dependents.forEach(e=>{const x=nodes.get(e.from_id);if(x)panel.append(link(x.title,libraryURL(x.id),'relation-row'));});}};
    if(projectCount)badges.append(button('被 '+projectCount+' 个项目使用',()=>show('uses'),'badge'));
    if(dependents.length)badges.append(button('被 '+new Set(dependents.map(e=>e.from_id)).size+' 个知识依赖',()=>show('requires'),'badge'));
    if(badges.children.length)host.append(badges,panel);
    if(prereq.length)relationList(host,'学前先懂',prereq.map(e=>nodes.get(e.to_id)).filter(Boolean));
    const linked=(d.body||'').split(/(```[\s\S]*?```|`[^`\n]+`)/g).map((part,i)=>i%2?part:part.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,(raw,nid,label)=>nodes.has(nid)?'['+(label||nodes.get(nid).title).replace(/[\[\]]/g,'')+']('+libraryURL(nid)+')':raw)).join('');
    const body=bodyView(linked,d.block_id);const firstHeading=body.querySelector('h1');if(firstHeading&&firstHeading.textContent.trim()===n.title.trim())firstHeading.remove();const anchors=el('nav',undefined,'anchors');body.querySelectorAll('h2,h3').forEach(h=>{const a=link(h.textContent,'#'+h.id);a.onclick=e=>{e.preventDefault();h.scrollIntoView({behavior:'smooth'});};anchors.append(a);});host.append(anchors);
    if(n.kind==='flow')host.append(stepGraph(d.flow_structure,projectId,id));
    const section=el('section',undefined,'section');section.append(el('h2',({project:'项目总览',module:'模块职责与边界',flow:'流程笔记'}[n.kind]||'知识点正文')));if(d.body)section.append(body);else section.append(el('p',n.summary||'此节点暂无已发布正文。','empty'),el('p','正文待整理','muted'));host.append(section);
    const stepKnowledge=new Set((d.flow_structure?.steps||[]).flatMap(s=>s.knowledge.map(k=>k.node_id)));
    const relations=d.relations||{},used=(relations.uses||[]).filter(e=>!stepKnowledge.has(e.target.id));
    if(used.length){const section=el(n.kind==='flow'?'details':'section',undefined,'section');section.append(el(n.kind==='flow'?'summary':'h2',n.kind==='flow'?'流程级其他关联知识 · '+used.length:'这里使用的知识'));used.forEach(e=>{const target={...e.target,...e.general_assessment,...e.assessment};const row=el('article',undefined,'relation-row');const module=ancestry(id,'module');const url=projectId?projectURL(projectId,module?.id,target.id)+'&edge='+encodeURIComponent(e.id):libraryURL(target.id);row.append(link(target.title,url),el('span',' · '+status(target),'muted'));if(e.payload.usage)row.append(el('p',e.payload.usage));if(e.payload.used_parts?.length)row.append(el('p','涉及：'+e.payload.used_parts.map(x=>nodes.get(x)?.title||x).join('、'),'muted'));if(target.gap_note)row.append(el('p','待补：'+target.gap_note));section.append(row);});host.append(section);}
    const flowLinks=[['previous','上游'],['next','下一步'],['fails_to','异常去向'],['supported_by','由此准备'],['supports','供此流程使用']];
    if(flowLinks.some(([key])=>relations[key]?.length)){const nav=el('section',undefined,'section');nav.append(el('h2','流程衔接'));for(const[key,label]of flowLinks)for(const e of relations[key]||[]){const row=el('p');row.append(label+'：',nodeLink(e.target));const reason=e.payload.condition||e.payload.rationale;if(reason)row.append(' · '+reason);nav.append(row);}host.append(nav);}
    if(n.gap_note||d.gaps?.length){const gap=el(n.kind==='flow'?'details':'section',undefined,'section');gap.append(el(n.kind==='flow'?'summary':'h2','当前待补'+(d.gaps?.length?' · '+d.gaps.length+' 项':'')));if(n.gap_note)gap.append(el('p',n.gap_note));for(const g of d.gaps||[]){const row=el('p');row.append(link(g.title,'/review-batches.html#batch_id='+encodeURIComponent(g.batch_id)),el('span',' · '+({explained:'已讲解，待确认',open:'待处理',deferred:'暂缓'}[g.state]||g.state),'muted'));gap.append(row);}host.append(gap);}
    const qsection=el('section',undefined,'section');qsection.append(el('h2',(n.kind==='flow'?'直接考察这条流程':'关联考题')+' · '+d.questions.length));qsection.append(link('进入独立题库','/question-bank.html','chip'));if(d.question_scope==='direct_and_contained')qsection.append(el('p','包含本主题和下属知识点的题目，按题目编号去重；不是每道题都考察整块内容。','muted'));if(!d.questions.length)qsection.append(el('p','暂未关联题目，可在题库查看其他内容。','muted'));
    d.questions.forEach(q=>{const card=el('article',undefined,'question');const title=el('h3');title.append(link(q.stem,'/question-bank.html#'+new URLSearchParams({q:q.id,return:location.pathname+location.hash})));card.append(title);const result=q.judgment?.result;card.append(el('span',({pass:'基本通过',correct:'基本通过',deepen:'需要深入',incorrect:'需要深入'}[result]||result||'未作答'),'chip'));const focus=[...new Set(q.contexts.map(c=>c.focus).filter(Boolean))];if(focus.length)card.append(el('p','考查点：'+focus.join('；'),'muted'));if(q.pending_reason)card.append(el('p','关联范围：'+q.pending_reason,'muted'));if(q.judgment?.gap_note)card.append(el('p','待补：'+q.judgment.gap_note));const answer=el('details');answer.append(el('summary','查看题库参考内容'));let loaded=false;answer.ontoggle=async()=>{if(!answer.open||loaded)return;loaded=true;try{const full=await api('/api/question?id='+encodeURIComponent(q.id));answer.append(WikiReader.markdown(full.answer_basis||full.question?.answer_basis||'题库暂无参考答案。'));}catch(e){loaded=false;answer.append(el('p',e.message,'error'));}};card.append(answer);qsection.append(card);});host.append(qsection);
    knowledgeQuestionPreview(host,d.flow_structure);
    if(route().get('step'))document.getElementById('step-'+route().get('step'))?.scrollIntoView({block:'center'});
    const ext=el('section',undefined,'section');ext.append(el('h2','相关知识与使用位置'));if(dependents.length)relationList(ext,'被这些知识依赖',dependents.map(e=>nodes.get(e.from_id)).filter(Boolean));const filtered=projectId?uses.filter(e=>locationOf(e).project?.id===projectId):uses;if(filtered.length)ext.append(el('h3','被这些流程使用'));filtered.forEach(e=>ext.append(usageRow(e)));
    const focusSection=route().get('section');if(focusSection){const target=[...body.querySelectorAll('[id]')].find(x=>x.id===focusSection);if(target)target.scrollIntoView();}
    const relLabels={alternative_to:'同类方案',upgrade_to:'可升级方向',analogous_to:'关联类比',abstracts_to:'本质推广',supports:'支撑内容'};let extra=0;
    edges.filter(e=>(e.from_id===id||e.to_id===id)&&relLabels[e.relation]&&(!projectId||!e.context_project_id||e.context_project_id===projectId)).forEach(e=>{const x=nodes.get(e.from_id===id?e.to_id:e.from_id);if(!x)return;extra++;const p=el('p');p.append(relLabels[e.relation]+'：',nodeLink(x));if(e.payload.rationale)p.append(' · '+e.payload.rationale);ext.append(p);});if(extra||filtered.length||dependents.length)host.append(ext);
  }
  async function library(ticket){
    const p=route();let id=p.get('node')||p.get('root_id');if(!id&&p.get('point'))id=[...nodes.values()].find(n=>n.content_ref?.id===p.get('point'))?.id;if(!id&&p.get('block')){const block=p.get('block').replace(/^wiki:/,'');id=[...nodes.values()].find(n=>n.content_ref?.id===block)?.id;}
    renderTree(id);const host=$('#reader');if(id&&nodes.has(id)){if(nodes.get(id).kind==='project'&&!foundation(nodes.get(id))){location.href=projectURL(id);return;}if(['knowledge','option','claim'].includes(nodes.get(id).kind)){await renderDetail(host,id,null,ticket);return;}}
    host.replaceChildren(el('div','KNOWLEDGE & REVIEW','eyebrow'),el('h1',nodes.get(id)?.title||'基础知识复习'),el('p','从知识体系进入正文与考题。浏览不改变掌握程度；项目通过引用复用同一份知识。','muted'));
    const grid=el('div',undefined,'home-grid');(id?kids(id):roots()).forEach(n=>{const a=link('',libraryURL(n.id),'home-card');a.append(el('strong',n.title),el('p',n.summary||'', 'muted'));grid.append(a);});host.append(grid);
    if(!id){host.append(el('h2','项目复习'));const cards=el('div',undefined,'home-grid');projects().forEach(n=>{const a=link('',projectURL(n.id),'home-card');a.append(el('strong',n.title),el('p',n.summary,'muted'));cards.append(a);});host.append(cards);}
  }
  function knowledgeChip(e,root,module){const base=nodes.get(e.to_id);if(!base)return el('span');const n={...base,...e.assessment};const a=link('',projectURL(root,module,n.id)+'&edge='+encodeURIComponent(e.id),'chip');a.append(dot(n),el('span',labels[domain(n)]||'项目','muted'),el('span',n.title),el('span','题×'+n.question_count,n.question_count>=3?'high':''));if(e.open_gap_count)a.append(el('span','待补 '+e.open_gap_count,'high'));a.title=status(n)+'；'+(e.payload.usage||'');return a;}
  function project(){
    const p=route();let root=p.get('root_id')||p.get('project_id');const legacyNode=p.get('node_id');if(root==='linux-performance-monitor')root='monitor-interview-map';if(nodes.has(root)&&foundation(nodes.get(root))||nodes.get(root)?.kind==='knowledge'){location.href=libraryURL(nodes.has(legacyNode)?legacyNode:root);return;}if(!p.get('node')&&legacyNode&&nodes.get(legacyNode)?.kind==='knowledge')p.set('node',legacyNode);
    const available=projects();if(!nodes.has(root))root=available[0]?.id;const n=nodes.get(root),host=$('#project');host.replaceChildren();if(!n){host.append(el('p','尚未登记项目','empty'));return;}
    const header=el('div',undefined,'project-header'),intro=el('div');intro.append(el('div','PROJECT REVIEW','eyebrow'),el('h1',n.title),el('p',n.summary,'muted'));const select=el('select');select.setAttribute('aria-label','选择复习项目');available.forEach(x=>{const o=el('option',x.title);o.value=x.id;o.selected=x.id===root;select.append(o);});select.onchange=()=>{location.href=projectURL(select.value);};header.append(intro,select);host.append(header);
    const visibleReview=x=>p.get('extended')==='1'||!['optional','historical'].includes(x.provenance?.review_scope);
    const modules=kids(root).filter(x=>x.kind==='module'&&visibleReview(x));let mid=p.get('module');if(!modules.some(m=>m.id===mid))mid=modules[0]?.id;
    if(p.get('node')){host.append(link('← 返回模块与流程',projectURL(root,mid),'chip'));const detail=el('article',undefined,'reader detail-reader');host.append(detail);renderDetail(detail,p.get('node'),root,epoch).catch(e=>detail.replaceChildren(el('p',e.message,'error')));return;}
    host.append(link('已登记的复盘问题','/review-batches.html#project_id='+encodeURIComponent(root),'chip'));
    if(n.content_ref)host.append(link('阅读项目总览与完整链路',projectURL(root,mid,root),'chip'));
    if(!modules.length)host.append(el('p','项目已登记，但尚无可展示的模块结构；这不是没有学习记录。请补齐“项目 → 模块 → 流程”关系。','empty'));
    const pipeline=el('div',undefined,'pipeline');
    modules.forEach((m,i)=>{
      if(i)pipeline.append(el('span','›','pipe-arrow'));
      const flows=kids(m.id).filter(x=>x.kind==='flow'&&visibleReview(x));
      const scope=new Set([m.id,...flows.flatMap(f=>[f.id,...kids(f.id).filter(s=>s.kind==='step').map(s=>s.id)])]);
      const refs=edges.filter(e=>e.relation==='uses'&&scope.has(e.from_id)&&(!e.context_project_id||e.context_project_id===root));
      const b=button('',()=>setRoute({root_id:root,module:m.id,flow:null}), 'module-card'+(mid===m.id?' selected':''));
      b.append(el('strong',String(i+1).padStart(2,'0')+'  '+m.title),el('p',m.summary),el('span',flows.length+' 个流程 · '+refs.length+' 处知识点引用','muted'));
      if(m.provenance?.review_scope&&m.provenance.review_scope!=='core')b.append(el('div',m.provenance.review_scope==='historical'?'历史范围':'可备分支','muted'));
      pipeline.append(b);
    });host.append(pipeline,el('p','模块按结构顺序排列；真实处理先后见流程内“下一步 / 异常去向”。','muted'));
    const bar=el('div',undefined,'toolbar'),view=p.get('view')||'modules';bar.append(button('按模块',()=>setRoute({view:'modules'}),view==='modules'?'active':''),button('按知识体系',()=>setRoute({view:'domains'}),view==='domains'?'active':''));const domains=(p.get('domains')||'').split(',').filter(Boolean);
    for(const[d,label]of Object.entries(labels)){const l=el('label'),input=el('input');input.type='checkbox';input.checked=domains.includes(d);input.onchange=()=>setRoute({domains:input.checked?[...domains,d].join(','):domains.filter(x=>x!==d).join(',')});l.append(input,label);bar.append(l);}
    for(const[key,label]of [['hot','仅高频提问'],['unassessed','仅未评估'],['extended','包含历史/可备分支']]){const l=el('label'),input=el('input');input.type='checkbox';input.checked=p.get(key)==='1';input.onchange=()=>setRoute({[key]:input.checked?'1':null});l.append(input,label);bar.append(l);}host.append(bar);
    const matches=k=>(!domains.length||domains.includes(domain(k)))&&(!p.get('hot')||k.question_count>=3)&&(!p.get('unassessed')||!k.mastery||k.mastery==='unassessed');
    const flowScope=id=>[id,...kids(id).filter(x=>x.kind==='step').map(x=>x.id)];
    const moduleUses=m=>{const ids=new Set([m.id,...kids(m.id).filter(x=>x.kind==='flow'&&visibleReview(x)).flatMap(x=>flowScope(x.id))]);return edges.filter(e=>e.relation==='uses'&&ids.has(e.from_id)&&nodes.has(e.to_id)&&matches({...nodes.get(e.to_id),...e.assessment}));};
    if(view==='domains'){const entries=new Map();modules.forEach(m=>moduleUses(m).forEach(e=>{if(!entries.has(e.to_id))entries.set(e.to_id,[]);entries.get(e.to_id).push({e,m});}));if(!entries.size)host.append(el('p','当前筛选没有匹配知识点。','empty'));[...entries].sort((a,b)=>domain(nodes.get(a[0])).localeCompare(domain(nodes.get(b[0])))).forEach(([id,refs])=>{const row=el('div',undefined,'flat-row');row.append(knowledgeChip(refs[0].e,root,refs[0].m.id));refs.forEach(({e,m})=>row.append(el('div','来自：'+m.title+' › '+nodes.get(e.from_id).title,'muted')));host.append(row);});}
    else if(mid){
      const m=nodes.get(mid);host.append(el('h2',m.title));const intro=el('section',undefined,'module-introduction');host.append(intro);const introEpoch=epoch;api('/api/review_detail?'+new URLSearchParams({id:mid,project_id:root,top_k:0})).then(d=>{if(epoch!==introEpoch)return;if(d.body){const view=bodyView(d.body,d.block_id),heading=view.querySelector('h1');if(heading)heading.remove();intro.append(view);}else if(m.summary)intro.append(el('p',m.summary));}).catch(()=>{if(epoch===introEpoch&&m.summary)intro.append(el('p',m.summary));});const grid=el('div',undefined,'flow-grid');
      const flows=kids(mid).filter(x=>x.kind==='flow'&&visibleReview(x));
      const selectedUses=id=>{const ids=new Set(flowScope(id));return uniqueUses(edges.filter(e=>e.relation==='uses'&&ids.has(e.from_id)&&nodes.has(e.to_id)&&matches({...nodes.get(e.to_id),...e.assessment})));};
      const direct=selectedUses(mid);
      if(direct.length){const card=el('article',undefined,'flow-card module-shared');card.append(el('h3','模块共用知识'));direct.forEach(e=>card.append(knowledgeChip(e,root,mid)));grid.append(card);}
      flows.forEach(f=>{
        const uses=selectedUses(f.id);if((domains.length||p.get('hot')||p.get('unassessed'))&&!uses.length)return;
        const card=el('article',undefined,'flow-card');card.id='flow-'+f.id;const heading=el('h3');heading.append(link(f.title,projectURL(root,mid,f.id)));card.append(heading,el('p',f.summary));
        if(f.open_gap_count)card.append(el('span',f.open_gap_count+' 项待补或未确认','chip high'));
        if(f.provenance?.review_scope&&f.provenance.review_scope!=='core')card.append(el('span',f.provenance.review_scope==='historical'?'历史范围':'可备分支','chip'));
        const chips=el('div',undefined,'chips');uses.forEach(e=>chips.append(knowledgeChip(e,root,mid)));if(!uses.length)chips.append(el('span','暂未登记公共知识引用','muted'));card.append(chips);
        const next=outgoing(f.id).filter(e=>['next','fails_to','supports'].includes(e.relation));
        const supported=incoming(f.id,'supports');
        if(next.length||supported.length){const nav=el('div',undefined,'next');
          [...next,...supported].forEach(e=>{const reverse=e.to_id===f.id,target=nodes.get(reverse?e.from_id:e.to_id);if(!target)return;
            const label=e.relation==='fails_to'?'异常 → ':e.relation==='supports'?(reverse?'由此支撑：':'支撑：'):'下一步 → ';
            nav.append(link(label+target.title,projectURL(root,ancestry(target.id,'module')?.id)+'&flow='+encodeURIComponent(target.id)));
            const note=e.payload.branch_label||e.payload.conditions||e.payload.usage;if(note)nav.append(el('div',note,'muted'));nav.append(el('br'));
          });card.append(nav);
        }grid.append(card);
      });
      if(!grid.children.length)grid.append(el('p',flows.length?'当前筛选没有匹配项。':'此模块为项目范围或复盘检查入口，不伪造运行流程；相关内容见下方项目知识。','empty'));host.append(grid);
    }
    const local=kids(root).filter(x=>x.kind==='knowledge'&&visibleReview(x));if(local.length){host.append(el('h2','项目内知识'));host.append(el('p','尚未沉淀到公共知识体系','muted'));local.forEach(k=>{const row=el('div',undefined,'flat-row local');row.append(link(k.title,projectURL(root,mid,k.id)),el('p',k.summary,'muted'));host.append(row);});}
    if(p.get('flow')){const focus=document.getElementById('flow-'+p.get('flow'));if(focus)focus.scrollIntoView({block:'center'});}
    host.append(el('p','掌握度只读取复习评估：灰色未评估 · 红色需巩固 · 蓝色基本可用 · 绿色已掌握。题×N 为已关联题数，不代表实际面试出现频率。','legend'));
  }
  async function render(){const ticket=++epoch;try{if(mode==='library')await library(ticket);else project();}catch(e){const host=mode==='library'?$('#reader'):$('#project');host.replaceChildren(el('p','读取失败：'+e.message,'error'));}}
  async function start(){const data=await api('/api/review_catalog');nodes=new Map(data.nodes.map(n=>[n.id,n]));edges=data.edges;edges.filter(e=>e.relation==='contains').sort((a,b)=>(a.payload.seq||0)-(b.payload.seq||0)).forEach(e=>{if(!children.has(e.from_id))children.set(e.from_id,[]);children.get(e.from_id).push(e);if(!parents.has(e.to_id))parents.set(e.to_id,[]);parents.get(e.to_id).push(e);});if(mode==='library'){$('#search').oninput=e=>{query=e.target.value.trim().toLowerCase();renderTree(route().get('node'));};$('#toggle-tree').onclick=()=>{$('#shell').classList.toggle('closed');$('#toggle-tree').setAttribute('aria-expanded',String(!$('#shell').classList.contains('closed')));};}window.addEventListener('hashchange',render);await render();}
  start().catch(e=>{(mode==='library'?$('#reader'):$('#project')).replaceChildren(el('p','无法连接复习数据：'+e.message,'error'));});
})();
