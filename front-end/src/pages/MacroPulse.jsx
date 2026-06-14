import React, { useState, useEffect } from 'react';
import TopNav from '../components/TopNav.jsx';
import { useLanguage } from '../hooks/useLanguage.jsx';
import './MacroPulse.css';

const API = import.meta.env.VITE_API_URL || '';

function useFetch(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetch(`${API}${url}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [url]);
  return { data, loading };
}

const T = {
  cn: {
    title: 'MacroPulse · 央行通讯鹰鸽计量',
    sub: 'Fed FOMC 声明/纪要的结构化鹰鸽打分、跨期红线对比、与黄金价格反应的归因回测',
    timeline: '鹰鸽分数时间线', hawk: '鹰', dove: '鸽', neutral: '中性',
    redline: '最新红线对比', attribution: '归因回测 · 鹰鸽分数 vs XAU 反应',
    queue: '人工裁决队列', window: '窗口', hit: '方向命中', corr: '相关',
    score: '分', conf: '置信', noprice: '超出价格覆盖', empty: '暂无数据',
    hitcol: '命中', misscol: '未命中', neu: '中性', reviewFlag: '待复核',
    limitation: '局限：仅 XAU 单标的、样本 N 极小（受价格历史限制）、未控混杂因素，结论仅作方法论演示。',
  },
  en: {
    title: 'MacroPulse · Central-Bank Hawk-Dove Metrics',
    sub: 'Structured hawk-dove scoring of Fed FOMC statements/minutes, cross-meeting red-line diffs, and attribution against gold price reactions',
    timeline: 'Hawk-Dove Score Timeline', hawk: 'Hawk', dove: 'Dove', neutral: 'Neutral',
    redline: 'Latest Red-line Diff', attribution: 'Attribution · Hawk-Dove Score vs XAU Reaction',
    queue: 'Human Adjudication Queue', window: 'Window', hit: 'Direction Hit', corr: 'Corr',
    score: 'score', conf: 'conf', noprice: 'outside price coverage', empty: 'No data',
    hitcol: 'hit', misscol: 'miss', neu: 'neutral', reviewFlag: 'needs review',
    limitation: 'Limitation: gold-only, very small N (bounded by price history), confounders uncontrolled — methodology demo, not statistically significant.',
  },
};

function scoreColor(s) {
  if (s > 0) return `rgba(220, 80, 60, ${0.35 + 0.13 * Math.min(s, 5)})`;   // 鹰 红
  if (s < 0) return `rgba(40, 160, 130, ${0.35 + 0.13 * Math.min(-s, 5)})`; // 鸽 绿
  return 'rgba(140,140,150,0.4)';
}

function ScoreTimeline({ scores, tr }) {
  const rows = (scores || []).slice().sort((a, b) => a.meeting_date.localeCompare(b.meeting_date));
  const max = 5;
  return (
    <div className="mp-timeline">
      {rows.map(r => {
        const s = r.overall_score;
        const w = (Math.abs(s) / max) * 50; // 半轴 50%
        return (
          <div key={r.document_id} className="mp-tl-row" title={`${r.document_id}  ${tr.conf} ${r.confidence_overall}`}>
            <span className="mp-tl-date">{r.meeting_date}</span>
            <span className={`mp-tl-type mp-${r.doc_type}`}>{r.doc_type === 'statement' ? 'S' : 'M'}</span>
            <div className="mp-tl-track">
              <div className="mp-tl-mid" />
              <div className="mp-tl-bar"
                   style={{
                     [s >= 0 ? 'left' : 'right']: '50%',
                     width: `${w}%`,
                     background: scoreColor(s),
                   }} />
            </div>
            <span className="mp-tl-val" style={{ color: s > 0 ? '#d8503c' : s < 0 ? '#28a082' : '#888' }}>
              {s > 0 ? '+' : ''}{s}
            </span>
            {r.needs_human_review && <span className="mp-flag" title={tr.reviewFlag}>⚑</span>}
          </div>
        );
      })}
    </div>
  );
}

function RedLine({ diff, tr }) {
  if (!diff) return <div className="mp-muted">{tr.empty}</div>;
  const dirBadge = (d) => (
    <span className={`mp-dir mp-dir-${d.direction}`}>
      {d.direction}{d.magnitude ? ` ·${d.magnitude}` : ''}
    </span>
  );
  return (
    <div>
      <div className="mp-redline-head">
        {diff.from_date} → {diff.to_date}
        <span className="mp-muted">  改 {diff.summary.modified} · 增 {diff.summary.added} · 删 {diff.summary.removed} · 未变 {diff.summary.unchanged}</span>
      </div>
      {(diff.diffs_vs_previous || diff.paragraphs || []).filter(p => p.status && p.status !== 'unchanged').map((p, i) => (
        <div key={i} className="mp-diff-row">
          {p.direction && dirBadge(p)}
          {p.old && <span className="mp-del">{p.old}</span>}
          {p.new && <span className="mp-ins">{p.new}</span>}
        </div>
      ))}
    </div>
  );
}

function Attribution({ attr, tr }) {
  if (!attr) return <div className="mp-muted">{tr.empty}</div>;
  const wlabel = { '15': '15min', '60': '1h', '1440': '1d' };
  return (
    <div>
      <div className="mp-attr-agg">
        {attr.windows_min.map(w => {
          const a = attr.aggregate[String(w)];
          return (
            <div key={w} className="mp-attr-card">
              <div className="mp-attr-w">{wlabel[String(w)] || w}</div>
              <div className="mp-attr-hit">{tr.hit} {a.hits}/{a.n_directional}
                {a.hit_rate != null && <b> {Math.round(a.hit_rate * 100)}%</b>}</div>
              <div className="mp-muted">{tr.corr} {a.pearson_score_vs_return ?? '—'}</div>
            </div>
          );
        })}
      </div>
      <table className="mp-attr-tbl">
        <thead><tr><th></th><th>{tr.score}</th>{attr.windows_min.map(w => <th key={w}>{wlabel[String(w)] || w}</th>)}</tr></thead>
        <tbody>
          {attr.events.map(e => (
            <tr key={e.document_id}>
              <td>{e.meeting_date}</td>
              <td style={{ color: e.overall_score > 0 ? '#d8503c' : e.overall_score < 0 ? '#28a082' : '#888' }}>
                {e.overall_score > 0 ? '+' : ''}{e.overall_score}</td>
              {attr.windows_min.map(w => {
                const r = e.reactions[String(w)];
                if (!r) return <td key={w} className="mp-muted">—</td>;
                const mark = r.hit === null ? '·' : (r.hit ? '✓' : '✗');
                const cls = r.hit === null ? '' : (r.hit ? 'mp-hit' : 'mp-miss');
                return <td key={w} className={cls}>{r.return_pct > 0 ? '+' : ''}{r.return_pct.toFixed(2)}<span className="mp-mark">{mark}</span></td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mp-limit">⚠️ {tr.limitation}</div>
    </div>
  );
}

function Queue({ queue, tr }) {
  if (!queue || !queue.length) return <div className="mp-muted">{tr.empty}</div>;
  return (
    <div className="mp-queue">
      {queue.map(q => (
        <div key={q.document_id} className="mp-q-row">
          <span className="mp-q-date">{q.meeting_date} <i className={`mp-${q.doc_type}`}>{q.doc_type === 'statement' ? 'S' : 'M'}</i></span>
          <span className="mp-q-score" style={{ color: q.overall_score > 0 ? '#d8503c' : q.overall_score < 0 ? '#28a082' : '#888' }}>
            {q.overall_score > 0 ? '+' : ''}{q.overall_score}</span>
          <span className="mp-q-reasons">{q.reasons.map((rs, i) => <span key={i} className="mp-q-tag">{rs}</span>)}</span>
        </div>
      ))}
    </div>
  );
}

const MacroPulse = () => {
  const { currentLanguage } = useLanguage();
  const tr = T[currentLanguage === 'cn' ? 'cn' : 'en'];
  const { data: scores } = useFetch('/api/macro/scores');
  const { data: diff } = useFetch('/api/macro/diff');
  const { data: attr } = useFetch('/api/macro/attribution');
  const { data: queue } = useFetch('/api/macro/adjudication-queue');

  return (
    <div className="mp-page">
      <TopNav />
      <header className="mp-header">
        <h1>{tr.title}</h1>
        <p>{tr.sub}</p>
        <div className="mp-legend">
          <span><i className="mp-sw" style={{ background: scoreColor(4) }} /> {tr.hawk}</span>
          <span><i className="mp-sw" style={{ background: scoreColor(-4) }} /> {tr.dove}</span>
          <span><i className="mp-sw" style={{ background: scoreColor(0) }} /> {tr.neutral}</span>
        </div>
      </header>

      <section className="mp-card">
        <h2>{tr.timeline} {scores && <span className="mp-muted">({scores.count})</span>}</h2>
        <ScoreTimeline scores={scores?.scores} tr={tr} />
      </section>

      <section className="mp-card">
        <h2>{tr.redline}</h2>
        <RedLine diff={diff} tr={tr} />
      </section>

      <section className="mp-card">
        <h2>{tr.attribution}</h2>
        <Attribution attr={attr} tr={tr} />
      </section>

      <section className="mp-card">
        <h2>{tr.queue} {queue && <span className="mp-muted">({queue.count})</span>}</h2>
        <Queue queue={queue?.queue} tr={tr} />
      </section>
    </div>
  );
};

export default MacroPulse;
