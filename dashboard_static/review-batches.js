(() => {
  const host = document.querySelector('#batches');
  const e = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const link = (text, href) => { const n = e('a', text, 'chip'); n.href = href; return n; };
  const api = async url => { const r = await fetch(url); const d = await r.json(); if (!r.ok || d.error) throw Error(d.error || r.status); return d; };
  const query = () => new URLSearchParams(location.hash.slice(1));
  const url = data => '/review-batches.html#' + new URLSearchParams(data);
  let revision = 0;
  function download(name, text, mime) {
    const blob = URL.createObjectURL(new Blob([text], {type: mime}));
    const a = e('a'); a.href = blob; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(blob), 1000);
  }
  function renderGap(g, all, seen = new Set()) {
    if (seen.has(g.id)) return e('p', g.title);
    const details = e('details', null, 'relation-box'); details.open = Boolean(g.parent_id) && g.state !== 'resolved';
    details.append(e('summary', g.title + ' · ' + ({open:'待处理', explained:'已讲解，待确认', resolved:'已确认', deferred:'暂缓'}[g.state] || g.state)));
    if (g.note) details.append(e('p', g.note));
    for (const child of all.filter(x => x.parent_id === g.id)) details.append(renderGap(child, all, new Set([...seen, g.id])));
    return details;
  }
  async function render() {
    const ticket = ++revision, p = query(), project = p.get('project_id'), id = p.get('batch_id');
    host.replaceChildren(e('p', '正在读取…'));
    try {
      if (!id) {
        const rows = await api('/api/review_batches' + (project ? '?project_id=' + encodeURIComponent(project) : ''));
        if (ticket !== revision) return;
        host.replaceChildren(e('h1', '已登记的复盘问题'), e('p', '从自己回答、补学过的原题继续。批次一直可打开，知识点的复习日期单独保留。', 'muted'));
        if (project) host.append(link('← 返回项目', '/review-map.html#root_id=' + encodeURIComponent(project)), link('查看全部批次', '/review-batches.html'));
        for (const b of rows) {
          const card = e('article', null, 'flow-card');
          card.append(link(b.title, url({batch_id:b.id, ...(project ? {project_id:project} : {})})), e('p', b.question_count + ' 道原题 · 最近登记 ' + b.updated_at)); host.append(card);
        }
        if (!rows.length) host.append(e('p', '此范围尚未登记复盘批次。可以请记录AI把已回答的问题按原题身份登记回来。', 'empty'));
        return;
      }
      const batch = await api('/api/review_batch?id=' + encodeURIComponent(id));
      if (ticket !== revision) return;
      host.replaceChildren(link('← 返回复盘批次', url(batch.project_id ? {project_id:batch.project_id} : {})), e('h1', batch.title));
      if (batch.project_id) host.append(link('回到项目结构', '/review-map.html#root_id=' + encodeURIComponent(batch.project_id)));
      const answered = batch.items.filter(i => i.attempts.some(a => a.kind === 'answer')).length;
      const open = batch.gaps.filter(g => g.state !== 'resolved');
      host.append(e('p', batch.items.length + ' 道原题 · 已登记回答 ' + answered + ' 道 · 遗留问题 ' + open.length + ' 项', 'muted'));
      const bar = e('div', null, 'toolbar');
      for (const [text, answers] of [['导出网页AI复盘包', false], ['导出含参考内容的版本', true]]) {
        const b = e('button', text); b.onclick = async () => { b.disabled = true; try {
          const pack = await api('/api/review_batch/export?id=' + encodeURIComponent(id) + (answers ? '&answers=1' : ''));
          download('review-' + id.replace(/[^a-zA-Z0-9_-]/g, '-') + '.md', pack.markdown, 'text/markdown;charset=utf-8');
          if (pack.missing_content.length) status.textContent = '已导出；有 ' + pack.missing_content.length + ' 个关联节点尚待补正文，包内未用摘要冒充。';
        } catch (err) { status.textContent = err.message; } finally { b.disabled = false; } }; bar.append(b);
      }
      const manifestButton = e('button', '下载关联清单');
      manifestButton.onclick = async () => { try { const pack = await api('/api/review_batch/export?id=' + encodeURIComponent(id)); download('review-manifest.json', JSON.stringify(pack.manifest, null, 2), 'application/json'); } catch(err) { status.textContent = err.message; } };
      bar.append(manifestButton);
      const status = e('p', '', 'muted'); host.append(bar, status);
      if (open.length) { const pending=e('details',null,'section');pending.append(e('summary','上次未解决或未确认 · '+open.length+' 项'));for (const g of batch.gaps.filter(g => !g.parent_id)) pending.append(renderGap(g, batch.gaps));host.append(pending); }
      host.append(e('h2', '本批原题与回答'));
      for (const item of batch.items) {
        const card = e('article', null, 'flow-card'), title = e('h3');
        title.append(link(item.label + ' · ' + item.stem, '/question-bank.html#' + new URLSearchParams({q:item.question_id, return:location.pathname + location.hash}))); card.append(title);
        const answer = [...item.attempts].reverse().find(a => a.kind === 'answer');
        card.append(e('p', answer ? ({pass:'本次回答基本通过', deepen:'本次回答需要补充'}[answer.result] || '已登记回答，尚未判断') : '尚未登记本批回答', 'muted'));
        if (answer?.gap_note) card.append(e('p', '待补：' + answer.gap_note));
        if (item.nodes?.length) { const refs = e('div', null, 'chips'); for (const n of item.nodes) refs.append(link(n.title, ['flow','module','project'].includes(n.kind)&&batch.project_id ? '/review-map.html#'+new URLSearchParams({root_id:batch.project_id,node:n.id}) : '/library.html#node='+encodeURIComponent(n.id))); card.append(refs); }
        if (item.attempts.length) { const details = e('details'); details.append(e('summary', '查看已登记回答与补学记录 · ' + item.attempts.length)); for (const a of item.attempts) { details.append(e('h4', {answer:'用户回答', explanation:'补学讲解', confirmation:'用户确认'}[a.kind]), e('p', a.answer)); } card.append(details); }
        host.append(card);
      }
      if (batch.unmatched.length) { host.append(e('h2', '待匹配的原始片段')); for (const x of batch.unmatched) host.append(e('p', x.text || JSON.stringify(x))); }
    } catch (err) { if (ticket === revision) host.replaceChildren(e('p', '读取失败：' + err.message, 'error')); }
  }
  window.addEventListener('hashchange', render); render();
})();
