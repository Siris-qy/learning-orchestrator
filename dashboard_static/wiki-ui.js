/* Shared wiki reader. Markdown is sanitized before display; TeX is rendered
   separately with trust disabled. Libraries are vendored for offline reading. */
"use strict";
window.WikiReader = (() => {
  const el = (tag, text, cls) => {
    const n = document.createElement(tag); if (text != null) n.textContent = text;
    if (cls) n.className = cls; return n;
  };
  function inline(n, text) {
    const pattern = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g;
    let offset = 0, m;
    while ((m = pattern.exec(text))) {
      n.append(document.createTextNode(text.slice(offset, m.index)));
      if (m[1]) n.append(el('strong', m[1]));
      else if (m[2]) n.append(el('code', m[2]));
      else {
        const a = el(/^https?:\/\//i.test(m[4]) ? 'a' : 'span', m[3]);
        if (a.tagName === 'A') { a.href = m[4]; a.target = '_blank'; a.rel = 'noopener'; }
        a.title = m[4]; n.append(a);
      }
      offset = pattern.lastIndex;
    }
    n.append(document.createTextNode(text.slice(offset)));
    return n;
  }
  function markdown(text) {
    const box = el('div', null, 'wiki-prose');
    if (!window.marked || !window.DOMPurify || !window.katex) {
      box.append(el('p','阅读组件未加载，请刷新页面。','muted'),el('pre',text||''));return box;
    }
    const math = [];
    const cleaned = (text||'').replace(/<!--[\s\S]*?-->/g,'').replace(/<a\s+id=[^>]*><\/a>/g,'');
    // Protect TeX from Markdown escapes/emphasis; never transform code strings.
    const protectedText = cleaned.split(/(```[\s\S]*?```|`[^`\n]+`)/g).map((part,index)=>index%2?part:
      part.replace(/\$\$[\s\S]+?\$\$|(?<!\\)\$(?!\$)[^\n$]+?\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]/g,raw=>{
        const display=raw.startsWith('$$')||raw.startsWith('\\[');
        const strip=raw.startsWith('$')?(display?2:1):2;
        math.push({text:raw.slice(strip,-strip),display});return 'WIKIMATHBEGIN'+(math.length-1)+'END';
      })).join('');
    const fragment = DOMPurify.sanitize(marked.parse(protectedText,{gfm:true,breaks:false}),
      {RETURN_DOM_FRAGMENT:true, USE_PROFILES:{html:true}, FORBID_TAGS:['style','iframe','form','input']});
    box.append(fragment);
    const walker=document.createTreeWalker(box,NodeFilter.SHOW_TEXT);
    const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    for(const node of nodes){
      if(node.parentElement.closest('pre,code'))continue;
      const pattern=/WIKIMATHBEGIN(\d+)END/g;let match,offset=0,out=document.createDocumentFragment(),found=false;
      while((match=pattern.exec(node.textContent))){
        const m=math[Number(match[1])];if(!m)continue;found=true;
        out.append(document.createTextNode(node.textContent.slice(offset,match.index)));
        const span=el('span');katex.render(m.text,span,{displayMode:m.display,throwOnError:false,trust:false,strict:false});
        out.append(span);offset=pattern.lastIndex;
      }
      if(found){out.append(document.createTextNode(node.textContent.slice(offset)));node.replaceWith(out);}
    }
    for(const img of box.querySelectorAll('img')){
      const src=img.getAttribute('src')||'';
      if(!/^\/note-assets\/[\w.-]+$/.test(src)){
        img.replaceWith(el('span','配图尚未接入：'+(img.alt||src),'wiki-missing-image'));continue;
      }
      const figure=el('figure');img.replaceWith(figure);figure.append(img);img.loading='lazy';img.decoding='async';
      img.alt=img.alt||'笔记配图';
      img.onerror=()=>figure.replaceChildren(el('p','配图暂时无法读取。','wiki-missing-image'));
    }
    for(const code of box.querySelectorAll('pre>code')){
      const language=[...code.classList].find(c=>c.startsWith('language-'))?.slice(9);
      if(language)code.before(el('div',language,'code-label'));
    }
    for(const a of box.querySelectorAll('a[href]')){
      const href=a.getAttribute('href');if(/^https?:\/\//i.test(href)){a.target='_blank';a.rel='noopener noreferrer';}
    }
    return box;
  }
  function entry(e) {
    const box = el('section', null, 'wiki-entry');
    box.append(el('h3', e.heading));
    const kind = {explanation:'解释',example:'例子',question:'待确认问题',correction:'修正',reference:'已有笔记引用'};
    box.append(el('span', kind[e.kind] || e.kind, 'wiki-label'));
    box.append(markdown(e.content));
    for (const ref of e.reference_body || []) box.append(markdown(ref.text));
    if (e.kind === 'question') box.append(el('p', '保留为疑问，待后续讲解或材料确认。', 'muted'));
    return box;
  }
  function sectionedMarkdown(text, points=[]) {
    const box = markdown(text), used = new Set();
    for(const h of box.querySelectorAll('h1,h2,h3,h4,h5,h6')){
      const point=points.find(p=>!used.has(p.id)&&markdown(p.title).textContent.trim()===h.textContent.trim());
      if(point){h.id=point.id;h.dataset.knowledgePoint=point.id;used.add(point.id);}
    }
    // Fold only top-level H2 sections, retaining nested heading anchors.
    for(const h of [...box.children].filter(n=>n.tagName==='H2')){
      const d=el('details'),summary=el('summary',h.textContent);
      if(h.id){summary.id=h.id;summary.dataset.knowledgePoint=h.id;}
      h.before(d);d.append(summary);
      h.remove();
      let n=d.nextSibling;
      while(n && !(n.nodeType===1 && n.tagName==='H2')){const next=n.nextSibling;d.append(n);n=next;}
    }
    return box;
  }
  function focus(root, pointId) {
    const target=[...root.querySelectorAll('[data-knowledge-point]')].find(n=>n.dataset.knowledgePoint===pointId);
    if(!target)return false;
    for(let n=target;n&&n!==root;n=n.parentElement)if(n.tagName==='DETAILS')n.open=true;
    target.scrollIntoView({behavior:'smooth',block:'center'});
    target.tabIndex=-1;target.focus({preventScroll:true});return true;
  }
  function render(block, openBlock) {
    const root = el('article', null, 'wiki-reader');
    root.append(el('h2', block.title));
    if(block.description)root.append(el('p',block.description,'muted'));
    root.append(el('p', block.legacy_sections?.length && !block.entry_count ? '已有知识正文 · 展开小标题阅读'
      : `${block.entry_count} 条补充 · ${block.synthesis ? '已有整理正文' : '逐步积累中'} · ${block.additions.length} 条待整合`, 'muted'));
    if (block.synthesis) {
      if(block.points?.length){
        const toc=el('nav',null,'wiki-point-index');toc.setAttribute('aria-label','块内知识点');
        toc.append(el('strong','块内知识点'));
        for(const p of block.points){
          const a=el('a',p.title);const params=new URLSearchParams(location.hash.slice(1));
          params.set('block','wiki:'+block.id);params.set('point',p.id);a.href='/library.html#'+params;
          a.style.paddingLeft=(10+Math.max(0,p.level-2)*16)+'px';
          a.onclick=event=>{event.preventDefault();history.pushState(null,'',a.href);focus(root,p.id);};toc.append(a);
        }
        root.append(toc);
      }
      root.append(el('h3', '整理正文'), sectionedMarkdown(block.synthesis.content,block.points));
      if (block.additions.length) root.append(el('h3', '后来补充 · 尚未合并'));
    }
    if (block.legacy_sections?.length) {
      const legacy = el('section'); legacy.append(el('h3', '已有知识笔记'));
      for (const section of block.legacy_sections) {
        const d = el('details'); const title=section.anchor===block.original_title
          ? '主题导读' : section.anchor.replace(/^[NDTSHRUM]\d+\s+/, '');
        const heading=el('summary', title);heading.title=section.anchor;
        d.append(heading, markdown(section.text)); legacy.append(d);
      }
      root.append(legacy);
    }
    for (const e of block.additions) root.append(entry(e));
    if (block.practice_links?.length) {
      const practice = el('details'); practice.append(el('summary', '关联题目与项目中的使用 · 检查掌握'));
      for (const p of block.practice_links) {
        const a = el('a', p.title + ' →');
        a.href = '/#' + new URLSearchParams({course:p.course_id,view:'cockpit',cp:'review:'+p.id});
        const line = el('p'); line.append(a); practice.append(line);
      }
      root.append(practice);
    }
    if (block.links?.length) {
      root.append(el('h3', '相关知识'));
      const targets = new Map();
      for (const link of block.links) {
        if(!targets.has(link.target_id))targets.set(link.target_id,[]);
        targets.get(link.target_id).push(link);
      }
      for (const links of targets.values()) {
        const link=links[0];
        const labels = {related:'关联',prerequisite:'前置',used_in:'使用',contrasts_with:'对比'};
        const kinds=[...new Set(links.map(l=>labels[l.relation]))].join(' / ');
        const b = el('button', `${kinds} · ${link.target_title}`, 'wiki-link');
        b.title = links.map(l=>(l.from_id===block.id?'→ ':'← ')+l.note).join('\n');
        b.onclick = () => openBlock(link.target_id); root.append(b);
      }
    }
    const src = el('details'); src.append(el('summary', '来源与展示位置'));
    if(block.original_title && block.original_title!==block.title)src.append(el('p','原始标题：'+block.original_title));
    for (const p of block.placements || []) src.append(el('p', `${p.view_key} · ${p.path.join(' / ')}`));
    for (const r of block.source_refs || []) {
      const line = [r.source_id || r.path || r.course_id || r.label,
        r.anchor, r.teaching_item_id != null ? `教学小项 #${r.teaching_item_id}` : ''].filter(Boolean).join(' · ');
      src.append(el('p', line || JSON.stringify(r)));
    }
    root.append(src);
    const history = el('details'); history.append(el('summary', '原始补充与整理版本 · 按需追溯'));
    let loaded = false;
    history.ontoggle = async () => {
      if (!history.open || loaded) return;
      loaded = true;
      try {
        const response = await fetch('/api/wiki?id=' + encodeURIComponent(block.id) + '&history=1');
        const data = await response.json(); if (!response.ok || data.error) throw Error(data.error);
        for (const e of data.entries) history.append(entry(e));
        for (const s of data.synthesis_history) {
          const d = el('details'); d.append(el('summary', `整理版本 #${s.id} · ${s.created_at.slice(0,10)}`), markdown(s.content)); history.append(d);
        }
      } catch (err) { loaded = false; history.append(el('p', '读取失败：' + err.message)); }
    };
    root.append(history);
    return root;
  }
  return {render, markdown, focus};
})();
