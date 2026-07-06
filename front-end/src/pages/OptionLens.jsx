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

/* ── ① 预期范围：用 spot / band_low / band_high 画预测锥 ── */
function BandChart({ spot, low, high }) {
  const H = 188, hi = 24, lo = 164, x0 = 150, x1 = 332;
  const yOf = p => lo - ((p - low) / (high - low)) * (lo - hi);
  const sy = yOf(spot);
  return (
    <svg className="band-svg" viewBox="0 0 340 188" preserveAspectRatio="xMidYMid meet">
      <line className="band-vline" x1={x0} y1="14" x2={x0} y2="172" />
      <polygon className="band-area" points={`${x0},${sy} ${x1},${hi} ${x1},${lo}`} />
      <line className="band-edge" x1={x0} y1={sy} x2={x1} y2={hi} />
      <line className="band-edge" x1={x0} y1={sy} x2={x1} y2={lo} />
      <line className="band-mid" x1={x0} y1={sy} x2={x1} y2={(hi + lo) / 2} />
      <polyline className="band-edge" style={{ strokeDasharray: 'none', opacity: 0.5 }}
        points={`14,${sy + 26} 50,${sy + 14} 86,${sy + 18} 118,${sy + 6} ${x0},${sy}`} />
      <circle className="band-dot" cx={x0} cy={sy} r="3.5" />
      <text className="band-lab" x={x1} y={hi + 4} textAnchor="end">${high.toFixed(0)}</text>
      <text className="band-lab" x={x1} y={lo} textAnchor="end">${low.toFixed(0)}</text>
      <text className="band-lab" x={x0 - 6} y={sy - 6} textAnchor="end">${spot.toFixed(0)}</text>
      <text className="band-ax" x={x0} y="184" textAnchor="middle">今天</text>
      <text className="band-ax" x={x1} y="184" textAnchor="end">到期</text>
    </svg>
  );
}

const moodOf = p => (p >= 0.55 ? '挺有可能' : p >= 0.25 ? '机会一般' : '有点难');

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

/* ── watchlist 概览榜单：消费 /daily-report，临近财报置顶、其余按 IV Rank 降序 ── */
const PC_ARROW = { rising: ['↑', '防守升温'], falling: ['↓', '防守降温'], flat: ['→', '大体平稳'] };

function tension(c) {
  // 紧张度 = IV Rank 位置。数据未成熟(<30天)时不给结论，显示"积累中"。
  if (c.iv_maturing || c.iv_rank == null) return ['积累中', 'mature'];
  if (c.iv_rank >= 80) return ['偏贵', 'hot'];
  if (c.iv_rank >= 50) return ['中等', 'mid'];
  return ['偏便宜', 'calm'];
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
                <span className="wb-tension__lab">紧张度 {tLabel}</span>
                {c.iv_rank != null && !c.iv_maturing && <span className="wb-tension__rank">IV Rank {Math.round(c.iv_rank)}</span>}
                {c.iv_maturing && <span className="wb-tension__rank dim">{c.data_days}天</span>}
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

const OptionLens = () => {
  const [view, setView] = useState('board');      // board 榜单首页 | detail 单票详情
  const [sym, setSym] = useState(SYMS[0]);
  const [tab, setTab] = useState('overview');
  const board = useFetch(view === 'board' ? '/api/option/daily-report' : null);
  const em = useFetch(view === 'detail' ? `/api/option/expected-move?symbol=${sym.code}` : null);
  const dist = useFetch(view === 'detail' ? `/api/option/distribution?symbol=${sym.code}` : null);
  const imp = useFetch(tab === 'impact' ? `/api/option/impact?symbol=${sym.code}` : null);
  const ts = useFetch(tab === 'term' ? `/api/option/term-structure?symbol=${sym.code}` : null);

  // ② 目标价 → 防抖查概率
  const [target, setTarget] = useState('');
  const [prob, setProb] = useState(null);
  const tmr = useRef();
  useEffect(() => {
    if (em && em.available && !target) setTarget(String(Math.round(em.band_high)));
  }, [em]); // eslint-disable-line
  useEffect(() => {
    const v = parseFloat(String(target).replace(/[^0-9.]/g, ''));
    if (isNaN(v)) { setProb(null); return; }
    clearTimeout(tmr.current);
    tmr.current = setTimeout(() => {
      fetch(`${API}/api/option/probability?symbol=${sym.code}&price=${v}`)
        .then(r => r.ok ? r.json() : null).then(setProb).catch(() => setProb(null));
    }, 220);
    return () => clearTimeout(tmr.current);
  }, [target, sym]);

  const [sel, setSel] = useState(null);
  const [notes, setNotes] = useState({});
  const toggle = k => setNotes(n => ({ ...n, [k]: !n[k] }));

  const [menu, setMenu] = useState(false);

  const pick = code => {
    setSym(SYM_BY_CODE[code] || { code, short: code.split(':').pop(), cn: '' });
    setView('detail'); setTab('overview'); setProb(null); setTarget(''); setSel(null);
  };

  const maxOI = dist && dist.available
    ? Math.max(1, ...dist.strikes.flatMap(s => [s.call_oi, s.put_oi])) : 1;

  return (
    <>
      <TopNav />
      <div className="olp">
        <div className="ol-bar">
          <div className="ol-brand">期权<span className="lt">透镜</span></div>
          {view === 'detail' && (
            <div className="ol-tickwrap">
              <button className="ol-back" onClick={() => setView('board')}>← 榜单</button>
              <button className="ol-ticker" onClick={() => setMenu(m => !m)}>
                {sym.short} <span className="cn">{sym.cn}</span> <span className="car">▾</span>
              </button>
              {menu && (
                <div className="ol-menu">
                  {SYMS.map(s => (
                    <button key={s.code} className={`ol-menu__item${s.code === sym.code ? ' on' : ''}`}
                      onClick={() => { setSym(s); setMenu(false); setProb(null); setTarget(''); setSel(null); }}>
                      {s.short} <span className="cn">{s.cn}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {view === 'board' ? <WatchBoard report={board} onPick={pick} /> : (
        <>
        <div className="ol-tabs">
          {[['overview', '总览'], ['impact', '影响'], ['term', '期限']].map(([k, label]) => (
            <button key={k} className={`ol-tab${tab === k ? ' on' : ''}`} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>

        <div className="wrap">
          {tab === 'impact' ? <ImpactPanel imp={imp} /> : tab === 'term' ? <TermPanel ts={ts} /> : (
          <div className="ol-cols">
          <div className="ol-col">
          {/* ① 预期范围 */}
          <section className="card">
            <p className="card__eyebrow"><span className="n">01</span><span>预期范围 · EXPECTED RANGE</span><span className="rule" /></p>
            {em && em.available ? (
              <>
                <div className="quote">
                  <span className="quote__price">${em.spot.toFixed(2)}</span>
                  <span className="quote__tag">现价</span>
                </div>
                <p className="lead">
                  到 <em>{dotdate(em.expiry)}</em>,{sym.short} 大概率落在{' '}
                  <span className="rng">${em.band_low.toFixed(0)} – ${em.band_high.toFixed(0)}</span> 之间{' '}
                  <span className="dim">(±{Math.round(em.pct * 100)}%)</span>
                </p>
                <BandChart spot={em.spot} low={em.band_low} high={em.band_high} />
                <p className="caption">阴影 = 市场押注的波动范围,越宽说明市场越不确定。{em.pct >= 0.4 && ' 当前 IV 异常高,这票正被按极端波动定价。'}</p>
              </>
            ) : <div className="ol-empty">{em ? '该标的暂无快照数据' : '加载中…'}</div>}
          </section>

          {/* ② 问问市场 */}
          <section className="card">
            <p className="card__eyebrow"><span className="n">02</span><span>问问市场 · ASK THE MARKET</span><span className="rule" /></p>
            <h2 className="ask__title">到了你的目标价,有多大可能?</h2>
            <p className="ask__sub">输入一个价格,看市场现在怎么定价它的概率。</p>
            <div className="ask__field">
              <span className="ask__pfx">$</span>
              <input className="ask__input mono" inputMode="decimal" value={target}
                onChange={e => setTarget(e.target.value)} />
              <div className="ask__steppers">
                <button className="ask__step" onClick={() => setTarget(t => String(Math.round((parseFloat(t) || 0) - 1)))}>−</button>
                <button className="ask__step" onClick={() => setTarget(t => String(Math.round((parseFloat(t) || 0) + 1)))}>+</button>
              </div>
            </div>
            {prob && prob.available && (() => {
              const v = parseFloat(String(target).replace(/[^0-9.]/g, ''));
              const above = v >= prob.spot;
              const shown = above ? prob.prob_above : prob.prob_below;
              return (
                <div className="ask__result">
                  <div className="ask__prob">
                    <span className="ask__pct">{Math.round(shown * 100)}%</span>
                    <span className="ask__mood">{moodOf(shown)}</span>
                  </div>
                  <p className="ask__sentence" dangerouslySetInnerHTML={{
                    __html: `市场认为 ${dotdate(prob.expiry)} 收在 <b>$${v}</b> ${prob.direction}的概率约 <b>${Math.round(shown * 100)}%</b>。`
                  }} />
                  {notes.ask && <p className="info-note">这是市场<b>定价</b>出来的概率(用风险中性 delta 估算),反映现在大家愿意花多少钱赌这件事 —— 不是预言,也不保证发生。</p>}
                  <div className="info-row"><span className="info" onClick={() => toggle('ask')}>i</span><span className="lbl">概率怎么来的?</span></div>
                </div>
              );
            })()}
          </section>

          </div>
          <div className="ol-col">
          {/* ③ 押注分布 */}
          <section className="card">
            <p className="card__eyebrow"><span className="n">03</span><span>押注分布 · WHERE THE MONEY IS</span><span className="rule" /></p>
            <h2 className="ask__title" style={{ marginBottom: 12 }}>大家把钱押在哪儿?</h2>
            {dist && dist.available ? (
              <>
                <p className="lead" style={{ fontSize: 17, marginBottom: 18 }}
                  dangerouslySetInnerHTML={{ __html: (dist.headline || '').replace('赌涨', '<em style="color:var(--ol-up)">赌涨</em>').replace('买保护', '<em style="color:var(--ol-prot)">买保护</em>') }} />
                <div className="lad-labels"><span className="l">← 赌跌 · 买保护</span><span className="r">赌涨 →</span></div>
                <div className="ladder">
                  {dist.strikes.map((s, i) => {
                    const wall = s.is_wall ? (s.side === 'call' ? 'up' : 'prot') : undefined;
                    const next = dist.strikes[i + 1];
                    const crossNow = s.strike >= dist.spot && next && next.strike < dist.spot;
                    return (
                      <React.Fragment key={s.strike}>
                        <div className={`lrow${sel === i ? ' sel' : ''}`} data-wall={wall} onClick={() => setSel(i)}>
                          <div className="ltrack ltrack--l"><div className="ltrack__bar" style={{ width: `${s.put_oi / maxOI * 100}%` }} /></div>
                          <div className="lprice">${s.strike.toFixed(0)}</div>
                          <div className="ltrack ltrack--r"><div className="ltrack__bar" style={{ width: `${s.call_oi / maxOI * 100}%` }} /></div>
                        </div>
                        {crossNow && (
                          <div className="lad-now"><div className="lad-now__line" /><div className="lad-now__tag">现价 ${dist.spot.toFixed(2)}</div><div className="lad-now__line" /></div>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
                <p className="caption">条越长 = 在那个价位押注的钱越多。<span style={{ color: 'var(--ol-4)' }}>点任意价位看明细。</span></p>
                {sel != null && dist.strikes[sel] && (() => {
                  const s = dist.strikes[sel];
                  const lead = s.call_oi > s.put_oi ? '<span class="up">赌涨为主</span>' : '<span class="prot">买保护为主</span>';
                  return <div className="lad-detail" dangerouslySetInnerHTML={{
                    __html: `<span class="mono">$${s.strike.toFixed(0)}</span>:<span class="up">${fmt(s.call_oi)} 份赌涨</span> · <span class="prot">${fmt(s.put_oi)} 份买保护</span> — 这里以${lead}${s.is_wall ? ' · 押注最重之一' : ''}。`
                  }} />;
                })()}
                <div style={{ marginTop: 12, display: 'flex', gap: 16, fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ol-3)' }}>
                  <span>磁吸位 ${Number(dist.max_pain).toFixed(0)}</span>
                  <span>看跌/看涨 {dist.pc_ratio}</span>
                </div>
                {notes.dist && <p className="info-note">这些是未平仓的合约数量,反映"还没了结"的押注。数据截至昨日收盘,盘中不实时更新。</p>}
                <div className="info-row"><span className="info" onClick={() => toggle('dist')}>i</span><span className="lbl">数据什么时候的?</span></div>
              </>
            ) : <div className="ol-empty">{dist ? '该标的暂无快照数据' : '加载中…'}</div>}
          </section>

          </div>
          </div>
          )}
          <p className="ol-foot">期权透镜 · 市场信号翻译,仅供参考,不构成投资建议</p>
        </div>
        </>
        )}
      </div>
    </>
  );
};

export default OptionLens;
