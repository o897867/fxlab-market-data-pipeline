import React, { useState, useEffect, useRef } from 'react';
import TopNav from '../components/TopNav.jsx';
import './OptionLens.css';

const API = import.meta.env.VITE_API_URL || '';

// 核心层 watchlist + 中文名（与后端 config.DEFAULT_SYMBOLS 对齐，18 只）
const SYMS = [
  { code: 'NASDAQ:NVDA', short: 'NVDA', cn: '英伟达' },
  { code: 'NASDAQ:AMD', short: 'AMD', cn: '超微' },
  { code: 'NASDAQ:TSLA', short: 'TSLA', cn: '特斯拉' },
  { code: 'NASDAQ:AAPL', short: 'AAPL', cn: '苹果' },
  { code: 'NASDAQ:META', short: 'META', cn: 'Meta' },
  { code: 'NASDAQ:MSFT', short: 'MSFT', cn: '微软' },
  { code: 'NASDAQ:AMZN', short: 'AMZN', cn: '亚马逊' },
  { code: 'NASDAQ:AVGO', short: 'AVGO', cn: '博通' },
  { code: 'NASDAQ:GOOG', short: 'GOOG', cn: '谷歌' },
  { code: 'NASDAQ:MU', short: 'MU', cn: '美光' },
  { code: 'AMEX:SPY', short: 'SPY', cn: '标普500' },
  { code: 'NASDAQ:QQQ', short: 'QQQ', cn: '纳指100' },
  { code: 'AMEX:IWM', short: 'IWM', cn: '罗素2000' },
  { code: 'NASDAQ:COIN', short: 'COIN', cn: 'Coinbase' },
  { code: 'NASDAQ:PLTR', short: 'PLTR', cn: 'Palantir' },
  { code: 'NASDAQ:SMCI', short: 'SMCI', cn: '超微电脑' },
  { code: 'NASDAQ:NFLX', short: 'NFLX', cn: '奈飞' },
  { code: 'NYSE:ORCL', short: 'ORCL', cn: '甲骨文' },
];
const SYM_BY_CODE = Object.fromEntries(SYMS.map(s => [s.code, s]));

function useFetch(url) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!url) { setData(null); return; }
    let cancelled = false;
    setData(null);
    fetch(`${API}${url}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData({ available: false }); });
    return () => { cancelled = true; };
  }, [url]);
  return data;
}

const fmt = n => Number(n).toLocaleString('en-US');
const dotdate = s => { const [, m, d] = (s || '').split('-'); return m ? `${+m}月${+d}日` : s; };
const mdShort = s => { const [, m, d] = (s || '').split('-'); return m ? `${+m}/${+d}` : s; };
const moodOf = p => (p >= 0.55 ? '挺有可能' : p >= 0.25 ? '机会一般' : '有点难');
const chgStr = c => (c == null ? '' : `${c > 0 ? '+' : c < 0 ? '−' : ''}${Math.abs(c).toFixed(1)}%`);

/* ── 共享价格刻度：band 图与价格阶梯用同一把尺子，纵向对齐 ── */
const PLOT_H = 380, PAD = 18, APEX_X = 232, RIGHT_X = 505;
function priceScale(em, dist, spark) {
  const pts = [];
  if (em && em.available) pts.push(em.band_low, em.band_high, em.spot);
  if (dist && dist.available) { dist.strikes.forEach(s => pts.push(s.strike)); if (dist.spot) pts.push(dist.spot); }
  if (spark && spark.available && spark.closes.length) spark.closes.forEach(c => pts.push(c));
  if (!pts.length) return null;
  let lo = Math.min(...pts), hi = Math.max(...pts);
  if (hi <= lo) hi = lo + 1;
  const pad = (hi - lo) * 0.06;
  return [lo - pad, hi + pad];
}
const yOf = (p, sc) => PAD + (sc[1] - p) / (sc[1] - sc[0]) * (PLOT_H - 2 * PAD);

/* ── ① 预期范围 band 图：真实走势线 → 今天顶点 → 张开到到期日的锥 ── */
function BandPlot({ em, spark, scale }) {
  if (!scale || !em || !em.available) return <div className="plot" />;
  const yHi = yOf(em.band_high, scale), yLo = yOf(em.band_low, scale), yNow = yOf(em.spot, scale);
  const closes = (spark && spark.available) ? spark.closes : [];
  const hpts = closes.map((c, i, a) => {
    const x = 14 + (APEX_X - 14) * (i / Math.max(1, a.length - 1));
    return `${x.toFixed(0)},${yOf(c, scale).toFixed(0)}`;
  }).join(' ');
  return (
    <div className="plot">
      <svg className="band-svg" viewBox={`0 0 520 ${PLOT_H}`} preserveAspectRatio="none">
        <line className="band-vline" x1={APEX_X} y1="6" x2={APEX_X} y2={PLOT_H - 22} />
        <line className="band-guide" x1={APEX_X} y1={yHi} x2={RIGHT_X} y2={yHi} />
        <line className="band-guide" x1={APEX_X} y1={yLo} x2={RIGHT_X} y2={yLo} />
        <polygon className="band-area" points={`${APEX_X},${yNow} ${RIGHT_X},${yHi} ${RIGHT_X},${yLo}`} />
        <line className="band-edge" x1={APEX_X} y1={yNow} x2={RIGHT_X} y2={yHi} />
        <line className="band-edge" x1={APEX_X} y1={yNow} x2={RIGHT_X} y2={yLo} />
        <line className="band-mid" x1={APEX_X} y1={yNow} x2={RIGHT_X} y2={(yHi + yLo) / 2} />
        {closes.length > 1 && <polyline className="band-hist" points={`${hpts} ${APEX_X},${yNow}`} />}
        <circle className="band-dot" cx={APEX_X} cy={yNow} r="4" />
        <text className="band-lab" x={RIGHT_X} y={yHi - 7} textAnchor="end">${em.band_high.toFixed(0)} · 上界</text>
        <text className="band-lab" x={RIGHT_X} y={yLo + 15} textAnchor="end">${em.band_low.toFixed(0)} · 下界</text>
        <text className="band-lab" x={APEX_X - 8} y={yNow - 9} textAnchor="end">${em.spot.toFixed(2)}</text>
        <text className="band-ax" x={APEX_X} y={PLOT_H - 4} textAnchor="middle">今天</text>
        <text className="band-ax" x={RIGHT_X} y={PLOT_H - 4} textAnchor="end">{mdShort(em.expiry)} 到期</text>
      </svg>
    </div>
  );
}

/* ── ② 押注分布：按价格定位的阶梯，与 band 图同刻度对齐 ── */
function Ladder({ dist, em, scale, sel, setSel }) {
  if (!scale || !dist || !dist.available) return <div className="plot" />;
  const mo = Math.max(1, ...dist.strikes.flatMap(s => [s.call_oi, s.put_oi]));
  const yHi = em && em.available ? yOf(em.band_high, scale) : null;
  const yLo = em && em.available ? yOf(em.band_low, scale) : null;
  return (
    <div className="plot">
      <div className="dl">
        <div className="dl-axis" />
        {yHi != null && <>
          <div className="dl-guide" style={{ top: `${yHi}px` }} />
          <div className="dl-guide" style={{ top: `${yLo}px` }} />
          <div className="dl-bandtag" style={{ top: `${yHi}px` }}>预期上界 ${em.band_high.toFixed(0)}</div>
          <div className="dl-bandtag" style={{ top: `${yLo}px` }}>预期下界 ${em.band_low.toFixed(0)}</div>
        </>}
        {dist.strikes.map((s, i) => {
          const wall = s.is_wall ? (s.side === 'call' ? 'up' : 'prot') : undefined;
          return (
            <div key={s.strike} className={`dl-row${sel === i ? ' sel' : ''}`} data-wall={wall}
              style={{ top: `${yOf(s.strike, scale)}px` }}
              onMouseEnter={() => setSel(i)} onClick={() => setSel(i)}>
              <div className="dl-track dl-track--l"><div className="dl-bar" style={{ width: `${(s.put_oi / mo * 100).toFixed(1)}%` }} /></div>
              <div className="dl-price">${s.strike.toFixed(0)}</div>
              <div className="dl-track dl-track--r"><div className="dl-bar" style={{ width: `${(s.call_oi / mo * 100).toFixed(1)}%` }} /></div>
            </div>
          );
        })}
        <div className="dl-now" style={{ top: `${yOf(dist.spot, scale)}px` }}>
          <div className="dl-now__line" /><div className="dl-now__tag">现价 ${dist.spot.toFixed(2)}</div><div className="dl-now__line" />
        </div>
      </div>
    </div>
  );
}

function ladderDetail(s, em) {
  if (!s) return '';
  const lead = s.call_oi > s.put_oi ? '<span class="up">赌涨为主</span>' : '<span class="prot">买保护为主</span>';
  const tail = s.is_wall ? (s.side === 'call' ? ' · 全场赌涨押得最重' : ' · 全场保护盘押得最重') : '';
  const inR = em && em.available ? (s.strike <= em.band_high && s.strike >= em.band_low) : true;
  return `<span class="mono">$${s.strike.toFixed(0)}</span>:<span class="up">${fmt(s.call_oi)} 份赌涨</span> · <span class="prot">${fmt(s.put_oi)} 份买保护</span> — 这里以${lead}${tail}。<span style="color:var(--ol-4)">${inR ? ' 在预期范围内。' : ' 已在预期范围之外。'}</span>`;
}

/* ── 为你划重点 digest：从 band + 墙 客观陈述，不预测 ── */
function digestItems(em, dist) {
  if (!em || !em.available) return [];
  const short = mdShort(em.expiry), pct = Math.round(em.pct * 100);
  const items = [`市场认为到 <b>${short}</b>,大概率在 <b>$${em.band_low.toFixed(0)}–$${em.band_high.toFixed(0)}</b>（±${pct}%）。范围越宽,说明分歧越大。`];
  if (dist && dist.available) {
    const callWall = dist.strikes.filter(s => s.side === 'call' && s.is_wall).sort((a, b) => b.call_oi - a.call_oi)[0];
    const putWalls = dist.strikes.filter(s => s.side === 'put' && s.is_wall).sort((a, b) => b.put_oi - a.put_oi).slice(0, 2);
    if (callWall) {
      const inUp = callWall.strike <= em.band_high && callWall.strike >= em.band_low;
      items.push(`钱押得最重的是 <span class="up">$${callWall.strike.toFixed(0)} 赌涨墙</span>,${inUp ? '落在预期范围内 —— 多头目标不算激进' : '已在预期范围之上 —— 属偏乐观下注'}。`);
    }
    const protStr = putWalls.map(x => '$' + x.strike.toFixed(0)).join('/');
    items.push(`${putWalls.length ? `<span class="prot">${protStr} 有保护盘</span>堆积,是持股者在给下行买保险。` : '下方保护盘不明显。'}对持有正股的你:把它当支撑/阻力参考,别追最重的墙。`);
  }
  return items;
}

/* ── ⑤ 期限结构：ATM IV vs 距到期天数 折线 ── */
function TermPanel({ ts }) {
  if (!ts) return <div className="ol-empty">加载中…</div>;
  if (!ts.available) return <div className="ol-empty">该标的暂无快照数据</div>;
  const c = ts.curve;
  const W = 520, H = 240, padL = 46, padR = 22, padT = 18, padB = 34;
  const dtes = c.map(p => p.dte), ivs = c.map(p => p.iv_pct);
  const xMin = Math.min(...dtes), xMax = Math.max(...dtes);
  const yMin = Math.min(...ivs), yMax = Math.max(...ivs);
  const xs = d => padL + (d - xMin) / (xMax - xMin || 1) * (W - padL - padR);
  const ys = v => H - padB - (v - yMin) / (yMax - yMin || 1) * (H - padT - padB);
  const pts = c.map(p => `${xs(p.dte).toFixed(1)},${ys(p.iv_pct).toFixed(1)}`).join(' ');
  const shapeTag = ts.shape === 'backwardation' ? ['近月更贵 · 近期有事', 'mid']
    : ts.shape === 'contango' ? ['远月更贵 · 常态', 'high'] : ['平 · 无特别定价', 'low'];
  return (
    <section className="card imp-card">
      <p className="card__eyebrow"><span className="n">05</span><span>期限结构 · TERM STRUCTURE</span><span className="rule" /></p>
      <p className="lead" style={{ fontSize: 17, marginBottom: 8 }}>{ts.headline}</p>
      <span className={`imp-tier lv-${shapeTag[1]}`}>{shapeTag[0]}</span>
      <svg className="ts-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        <polyline className="ts-line" points={pts} />
        {c.map(p => <circle key={p.dte} className="ts-dot" cx={xs(p.dte)} cy={ys(p.iv_pct)} r="3" />)}
        <text className="band-ax" x={padL - 7} y={ys(yMax) + 3} textAnchor="end">{yMax.toFixed(0)}%</text>
        <text className="band-ax" x={padL - 7} y={ys(yMin) + 3} textAnchor="end">{yMin.toFixed(0)}%</text>
        <text className="band-ax" x={xs(xMin)} y={H - padB + 18} textAnchor="middle">{xMin}天</text>
        <text className="band-ax" x={xs(xMax)} y={H - padB + 18} textAnchor="middle">{xMax}天</text>
      </svg>
      <p className="caption">{ts.sub}</p>
    </section>
  );
}

/* ── ⑥⑦ 时序：IV Rank（贵贱）+ P/C 情绪。皆为市场当前定价的客观统计，不预测。 ── */
const PC_ICON = { rising: '↑', falling: '↓', flat: '→' };

function SeriesPanel({ ivr, pcr }) {
  if (!ivr) return <div className="ol-empty">加载中…</div>;
  if (!ivr.available) return <div className="ol-empty">该标的暂无快照数据</div>;
  const lv = ivr.level_code || 'mature';
  const iv = ivr.iv_current, hv = ivr.hv20;
  const cmpMax = iv != null && hv != null ? Math.max(iv, hv) : null;
  const pctW = v => cmpMax ? `${Math.max(3, v / cmpMax * 100)}%` : '0%';
  return (
    <section className="card imp-card">
      <p className="card__eyebrow"><span className="n">06</span><span>时序 · 贵贱与情绪 · OVER TIME</span><span className="rule" /></p>
      <div className="sr-block">
        <div className="sr-top">
          <span className="sr-title">现在期权贵不贵</span>
          <span className="sr-lv"><span className={`wb-dot lv-${lv}`} />{ivr.level}</span>
        </div>
        <p className="lead" style={{ fontSize: 17, margin: '4px 0 12px' }}>{ivr.description}</p>
        {cmpMax && (
          <div className="sr-cmp">
            <div className="sr-cmp__row">
              <span className="sr-cmp__k">期权定价 IV</span>
              <div className="sr-bar"><div className={`sr-bar__fill lv-${lv}`} style={{ width: pctW(iv) }} /></div>
              <span className="sr-cmp__v mono">±{Math.round(iv * 100)}%</span>
            </div>
            <div className="sr-cmp__row">
              <span className="sr-cmp__k">实际波动 HV20</span>
              <div className="sr-bar"><div className="sr-bar__fill neutral" style={{ width: pctW(hv) }} /></div>
              <span className="sr-cmp__v mono">±{Math.round(hv * 100)}%</span>
            </div>
          </div>
        )}
        <p className="caption">{ivr.rank_note}</p>
      </div>
      {pcr && pcr.available && (
        <div className="sr-block">
          <div className="sr-top">
            <span className="sr-title">情绪风向 · P/C</span>
            <span className={`sr-lv wb-arrow ${pcr.trend}`}>{PC_ICON[pcr.trend]} {pcr.stance}</span>
          </div>
          <p className="lead" style={{ fontSize: 17, margin: '4px 0 8px' }}>{pcr.headline}</p>
          <p className="caption">{pcr.sub}</p>
        </div>
      )}
      <p className="caption" style={{ marginTop: 16, color: 'var(--ol-4)' }}>{ivr.sub}</p>
    </section>
  );
}

/* ── ④ 影响面板：可信度从高到低，GEX(低)整块淡红底提醒 ── */
function ImpactPanel({ imp }) {
  if (!imp) return <div className="ol-empty">加载中…</div>;
  if (!imp.available) return <div className="ol-empty">该标的暂无快照数据</div>;
  return (
    <section className="card imp-card">
      <p className="card__eyebrow"><span className="n">04</span><span>期权怎么影响正股 · IMPACT</span><span className="rule" /></p>
      <p className="imp-sub">{imp.sub}</p>
      {imp.items.map(it => (
        <div key={it.key} className={`imp-item lv-${it.tier_level}`}>
          <div className="imp-item__top">
            <span className="imp-item__title">{it.title}</span>
            <span className="imp-item__val">{it.value}</span>
          </div>
          <span className={`imp-tier lv-${it.tier_level}`}>{it.tier_level === 'low' ? '⚠ ' : ''}{it.tier}</span>
          <p className="imp-head">{it.headline}</p>
          <p className="imp-detail">{it.detail}</p>
        </div>
      ))}
    </section>
  );
}

/* ── watchlist 概览榜单（次级视图，从"全部"进入）── */
const PC_ARROW = { rising: ['↑', '防守升温'], falling: ['↓', '防守降温'], flat: ['→', '大体平稳'] };
function tension(c) {
  if (c.valuation_code) return [c.valuation, c.valuation_code];
  return ['数据积累中', 'mature'];
}
function WatchBoard({ report, onPick }) {
  if (!report) return <div className="ol-empty">加载中…</div>;
  if (!report.cards) return <div className="ol-empty">暂无数据（先跑快照 + dbt run）</div>;
  return (
    <div className="wb-wrap">
      <div className="wb-head">
        <h1 className="wb-title">期权体检 · 全市场一览</h1>
        <p className="wb-sub">{report.count} 只标的 · 数据 {report.as_of} · 有临近财报的置顶，其余按期权贵贱排序</p>
      </div>
      <div className="wb-grid">
        {report.cards.map(c => {
          const [tLabel, tLv] = tension(c);
          const [arrow, pcTxt] = PC_ARROW[c.pc_trend] || ['', ''];
          return (
            <button key={c.symbol} className="wb-card" onClick={() => onPick(c.symbol)}>
              <div className="wb-card__top">
                <div className="wb-tick">
                  <span className="wb-tick__sym">{c.name}</span>
                  <span className="wb-tick__cn">{(SYM_BY_CODE[c.symbol] || {}).cn || ''}</span>
                </div>
                {c.earnings_soon && <span className="wb-earn">{c.days_to_earnings}天后财报</span>}
              </div>
              <div className="wb-tension">
                <span className={`wb-dot lv-${tLv}`} />
                <span className="wb-tension__lab">期权贵贱 {tLabel}</span>
                {c.iv_vs_hv != null && <span className="wb-tension__rank mono">IV/实际 {c.iv_vs_hv.toFixed(2)}×</span>}
              </div>
              <div className="wb-metrics">
                <div className="wb-m">
                  <span className="wb-m__k">本期波动</span>
                  <span className="wb-m__v mono">{c.em_pct != null ? `±${c.em_pct}%` : '—'}</span>
                  <span className="wb-m__x mono">{c.band_low != null ? `$${Math.round(c.band_low)}–$${Math.round(c.band_high)}` : ''}</span>
                </div>
                <div className="wb-m">
                  <span className="wb-m__k">情绪 P/C</span>
                  <span className="wb-m__v mono">{c.pc_today != null ? c.pc_today : '—'} <span className={`wb-arrow ${c.pc_trend}`}>{arrow}</span></span>
                  <span className="wb-m__x">{pcTxt}</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <p className="wb-foot">{report.disclaimer || '以上为期权市场当前定价的客观统计，不预测走势、不构成投资建议。'}</p>
    </div>
  );
}

/* ── 横向切股器：当前 ± 邻居三张卡，← → 或点卡切换 ── */
function Switcher({ cardBy, sym, onPick, onMove }) {
  const idx = SYMS.findIndex(s => s.code === sym.code);
  const win = [-1, 0, 1].map(o => SYMS[(idx + o + SYMS.length) % SYMS.length]);
  return (
    <div className="switch">
      <button className="sw-arrow" aria-label="上一只" onClick={() => onMove(-1)}>
        <svg viewBox="0 0 24 24" fill="none"><path d="M15 6l-6 6 6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      <div className="sw-rail">
        {win.map(s => {
          const c = cardBy[s.code] || {};
          const take = c.valuation ? `期权${c.valuation}${c.em_pct != null ? ` · 本周 ±${c.em_pct}%` : ''}` : '数据积累中';
          return (
            <button key={s.code} className={`sw-card${s.code === sym.code ? ' on' : ''}`} onClick={() => onPick(s.code)}>
              <div className="sw-top">
                <span className="sw-tk">{s.short}</span><span className="sw-cn">{s.cn}</span>
                <span className="sw-px mono">{c.spot != null ? `$${c.spot.toFixed(2)}` : '—'}</span>
              </div>
              <div className="sw-chg mono">{c.change_pct != null ? `${chgStr(c.change_pct)} 今天` : ''}</div>
              <div className="sw-take">{take}</div>
            </button>
          );
        })}
      </div>
      <button className="sw-arrow" aria-label="下一只" onClick={() => onMove(1)}>
        <svg viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
    </div>
  );
}

const OptionLens = () => {
  const [view, setView] = useState('focus');      // focus 单股聚焦（主页）| board 全部榜单（次级）
  const [sym, setSym] = useState(SYMS[0]);
  const [tab, setTab] = useState('overview');
  const [expiry, setExpiry] = useState(null);     // null = 用后端默认
  const [target, setTarget] = useState('');
  const [prob, setProb] = useState(null);
  const [sel, setSel] = useState(0);

  const expQ = expiry ? `&expiry=${expiry}` : '';
  const board = useFetch('/api/option/daily-report');
  const expData = useFetch(`/api/option/expiries?symbol=${sym.code}`);
  const em = useFetch(`/api/option/expected-move?symbol=${sym.code}${expQ}`);
  const dist = useFetch(`/api/option/distribution?symbol=${sym.code}${expQ}`);
  const spark = useFetch(`/api/option/spark?symbol=${sym.code}`);
  const imp = useFetch(tab === 'impact' ? `/api/option/impact?symbol=${sym.code}` : null);
  const ts = useFetch(tab === 'term' ? `/api/option/term-structure?symbol=${sym.code}` : null);
  const ivr = useFetch(tab === 'series' ? `/api/option/iv-rank?symbol=${sym.code}` : null);
  const pcr = useFetch(tab === 'series' ? `/api/option/pc-trend?symbol=${sym.code}` : null);

  const cardBy = {};
  (board && board.cards ? board.cards : []).forEach(c => { cardBy[c.symbol] = c; });
  const scale = priceScale(em, dist, spark);

  // 默认目标价：预期上界（换股/换到期后自动重置）
  useEffect(() => { if (em && em.available) setTarget(String(Math.round(em.band_high))); }, [em]); // eslint-disable-line
  // 概率查询防抖
  const tmr = useRef();
  useEffect(() => {
    const v = parseFloat(String(target).replace(/[^0-9.]/g, ''));
    if (isNaN(v)) { setProb(null); return; }
    clearTimeout(tmr.current);
    tmr.current = setTimeout(() => {
      fetch(`${API}/api/option/probability?symbol=${sym.code}&price=${v}${expQ}`)
        .then(r => r.ok ? r.json() : null).then(setProb).catch(() => setProb(null));
    }, 220);
    return () => clearTimeout(tmr.current);
  }, [target, sym, expiry]); // eslint-disable-line

  const focus = code => {
    setSym(SYM_BY_CODE[code] || { code, short: code.split(':').pop(), cn: '' });
    setView('focus'); setExpiry(null); setProb(null); setSel(0);
  };
  const move = d => focus(SYMS[(SYMS.findIndex(s => s.code === sym.code) + d + SYMS.length) % SYMS.length].code);

  // 键盘 ← → 切股（焦点在输入框时不拦截）
  useEffect(() => {
    const onKey = e => {
      if (view !== 'focus' || e.target.tagName === 'INPUT') return;
      if (e.key === 'ArrowLeft') move(-1); else if (e.key === 'ArrowRight') move(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }); // eslint-disable-line

  const lead = (() => {
    const c = cardBy[sym.code] || {};
    const px = (em && em.available) ? em.spot : c.spot;
    return { px, chg: c.change_pct };
  })();
  const digest = digestItems(em, dist);

  return (
    <>
      <TopNav />
      <div className="olp">
        {/* header */}
        <header className="dt-head">
          <span className="ol-brand">期权<span className="lt">透镜</span></span>
          <div className="dt-head__r">
            {view === 'focus' && <span className="dt-hint">← → 切换股票</span>}
            {view === 'focus' && expData && expData.expiries && expData.expiries.length > 0 && (
              <div className="dt-expiry">
                <span className="dt-expiry__lab">到期日</span>
                <select value={expiry || expData.default || ''} onChange={e => { setExpiry(e.target.value); setProb(null); }}>
                  {expData.expiries.map(x => <option key={x} value={x}>{mdShort(x)}</option>)}
                </select>
              </div>
            )}
            <button className="dt-allbtn" onClick={() => setView(view === 'board' ? 'focus' : 'board')}>
              {view === 'board' ? '← 聚焦' : '全部 ▦'}
            </button>
          </div>
        </header>

        {view === 'board' ? <WatchBoard report={board} onPick={focus} /> : (
          <div className="wrap">
            <Switcher cardBy={cardBy} sym={sym} onPick={focus} onMove={move} />

            <div className="focus-head">
              <span className="focus-head__tk">{sym.short}</span>
              <span className="focus-head__cn">{sym.cn}</span>
              <span className="focus-head__lead">
                {lead.px != null ? <>现价 <b>${lead.px.toFixed(2)}</b></> : '—'}
                {lead.chg != null && <span className="mono"> · {chgStr(lead.chg)} 今天</span>}
              </span>
            </div>

            <div className="ol-tabs">
              {[['overview', '总览'], ['impact', '影响'], ['term', '期限'], ['series', '时序']].map(([k, label]) => (
                <button key={k} className={`ol-tab${tab === k ? ' on' : ''}`} onClick={() => setTab(k)}>{label}</button>
              ))}
            </div>

            {tab === 'impact' ? <ImpactPanel imp={imp} /> : tab === 'term' ? <TermPanel ts={ts} />
              : tab === 'series' ? <SeriesPanel ivr={ivr} pcr={pcr} /> : (
                <div className="foc-cols">
                  {/* ① 预期范围 */}
                  <section className="card">
                    <p className="card__eyebrow"><span className="n">01</span><span>预期范围 · EXPECTED RANGE</span><span className="rule" /></p>
                    {em && em.available ? (
                      <>
                        <p className="lead">
                          到 <em>{dotdate(em.expiry)}</em>,{sym.short} 大概率落在{' '}
                          <span className="rng">${em.band_low.toFixed(0)} – ${em.band_high.toFixed(0)}</span>{' '}
                          <span className="q">之间(±{Math.round(em.pct * 100)}%)</span>
                        </p>
                        <BandPlot em={em} spark={spark} scale={scale} />
                        <p className="caption">阴影 = 市场押注的波动范围,越宽说明市场越不确定。左侧是最近走势,从现价向右张开到到期日。</p>
                        <p className="foot-honest">范围由当前期权价格反推,反映市场此刻的预期 —— 不是保证,也不是预测。</p>
                      </>
                    ) : <div className="ol-empty">{em ? '该标的暂无快照数据' : '加载中…'}</div>}
                  </section>

                  {/* ② 押注分布 */}
                  <section className="card">
                    <p className="card__eyebrow"><span className="n">02</span><span>押注分布 · WHERE THE MONEY IS</span><span className="rule" /></p>
                    {dist && dist.available ? (
                      <>
                        <p className="lead" dangerouslySetInnerHTML={{ __html: (dist.headline || '').replace('赌涨', '<em style="color:var(--ol-up)">赌涨</em>').replace('买保护', '<em style="color:var(--ol-prot)">买保护</em>') }} />
                        <div className="lad-labels"><span className="l">← 赌跌 · 买保护</span><span className="r">赌涨 →</span></div>
                        <Ladder dist={dist} em={em} scale={scale} sel={sel} setSel={setSel} />
                        <div className="lad-detail" dangerouslySetInnerHTML={{ __html: ladderDetail(dist.strikes[sel], em) }} />
                        <p className="foot-honest">未平仓量截至昨收,盘中不更新。价格轴与左侧预期范围对齐。磁吸位 ${dist.max_pain != null ? Number(dist.max_pain).toFixed(0) : '—'} · 看跌/看涨 {dist.pc_ratio ?? '—'}</p>
                      </>
                    ) : <div className="ol-empty">{dist ? '该标的暂无快照数据' : '加载中…'}</div>}
                  </section>

                  {/* ③ 问问市场 + 划重点 */}
                  <section className="card">
                    <p className="card__eyebrow"><span className="n">03</span><span>问问市场 · ASK THE MARKET</span><span className="rule" /></p>
                    <h2 className="ask__title">到了你的目标价,有多大可能?</h2>
                    <p className="ask__sub">输入一个价格,看市场怎么定价它的概率。</p>
                    <div className="ask__field">
                      <span className="ask__pfx">$</span>
                      <input className="ask__input mono" inputMode="decimal" value={target} onChange={e => setTarget(e.target.value)} />
                      <div className="ask__steppers">
                        <button className="ask__step" onClick={() => setTarget(t => String(Math.round((parseFloat(t) || 0) + 1)))}>+</button>
                        <button className="ask__step" onClick={() => setTarget(t => String(Math.round((parseFloat(t) || 0) - 1)))}>−</button>
                      </div>
                    </div>
                    {prob && prob.available ? (() => {
                      const v = parseFloat(String(target).replace(/[^0-9.]/g, ''));
                      const above = v >= prob.spot;
                      const shown = above ? prob.prob_above : prob.prob_below;
                      return (
                        <>
                          <div className="ask__prob">
                            <span className="ask__pct mono">{Math.round(shown * 100)}%</span>
                            <span className="ask__mood mono">{moodOf(shown)}</span>
                          </div>
                          <p className="ask__sentence" dangerouslySetInnerHTML={{ __html: `市场认为 ${mdShort(prob.expiry)} 收在 <b>$${v}</b> ${prob.direction}的概率约 <b>${Math.round(shown * 100)}%</b> · ${moodOf(shown)}。` }} />
                        </>
                      );
                    })() : <p className="ask__sentence" style={{ marginTop: 14, color: 'var(--ol-3)' }}>输入一个目标价试试。</p>}

                    {digest.length > 0 && (
                      <div className="digest">
                        <p className="digest__h">为你划重点 · IN PLAIN WORDS</p>
                        {digest.map((h, i) => (
                          <div key={i} className="digest__item"><span className="digest__dot" /><p dangerouslySetInnerHTML={{ __html: h }} /></div>
                        ))}
                      </div>
                    )}
                    <div className="spacer" />
                    <p className="foot-honest">「问问市场」是市场<b style={{ color: 'var(--ol-2)' }}>定价</b>出来的概率,不是预言。</p>
                  </section>
                </div>
              )}
            <p className="ol-foot">期权透镜 · 市场信号翻译,仅供参考,不构成投资建议</p>
          </div>
        )}
      </div>
    </>
  );
};

export default OptionLens;
