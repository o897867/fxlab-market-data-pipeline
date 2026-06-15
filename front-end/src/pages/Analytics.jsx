import React, { useState, useEffect, useMemo } from 'react';
import { useLanguage } from '../hooks/useLanguage.jsx';
import TopNav from '../components/TopNav.jsx';
import './Analytics.css';

const API = import.meta.env.VITE_API_URL || '';

/* ═══════════════════════════════════════════════════════════════════
 * Data fetching
 * ═══════════════════════════════════════════════════════════════════ */

function useFetch(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetch(`${API}${url}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [url]);
  return { data, loading };
}

/* ═══════════════════════════════════════════════════════════════════
 * Helpers
 * ═══════════════════════════════════════════════════════════════════ */

function pad(n) { return String(n).padStart(2, '0'); }

function fmt(n, dig = 2) {
  if (n == null) return '\u2014';
  return typeof n === 'number'
    ? n.toLocaleString('en-US', { minimumFractionDigits: dig, maximumFractionDigits: dig })
    : n;
}

function pctClass(v) { return v >= 0 ? 'an-up' : 'an-down'; }
function pctSign(v) { return v >= 0 ? '+' : ''; }

/* ── SVG chart helpers ── */

/** Map value to SVG y coordinate */
function scaleY(val, min, max, top, bottom) {
  if (max === min) return (top + bottom) / 2;
  return bottom - ((val - min) / (max - min)) * (bottom - top);
}

/** Build SVG polyline path from series */
function buildLinePath(series, xStart, xEnd, yTop, yBot, getValue) {
  if (!series.length) return '';
  const vals = series.map(getValue);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const step = (xEnd - xStart) / Math.max(series.length - 1, 1);
  return vals.map((v, i) => {
    const x = (xStart + i * step).toFixed(1);
    const y = scaleY(v, min, max, yTop, yBot).toFixed(1);
    return `${i === 0 ? 'M' : 'L'} ${x},${y}`;
  }).join(' ');
}

/** Build SVG area path (line + close to bottom) */
function buildAreaPath(linePath, xStart, xEnd, yBot) {
  if (!linePath) return '';
  return `${linePath} L ${xEnd},${yBot} L ${xStart},${yBot} Z`;
}

/** Simple inline sparkline */
function Sparkline({ points, up, width = 44, height = 14 }) {
  if (!points || points.length < 2) return null;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const step = width / (points.length - 1);
  const pts = points.map((v, i) =>
    `${(i * step).toFixed(1)},${((1 - (v - min) / range) * (height - 2) + 1).toFixed(1)}`
  ).join(' ');
  const col = up ? '#166534' : '#991b1b';
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={pts} fill="none" stroke={col} strokeWidth="1.2" />
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════
 * XAU Tab
 * ═══════════════════════════════════════════════════════════════════ */

const INSTS = {
  xau:  { prefix: 'xau',  ticker: 'XAU',  cn: '黄金现货 · Gold Spot', en: 'Gold Spot · XAUUSD',     ex: 'COMEX', dec: 2, unit: '' },
  dxy:  { prefix: 'dxy',  ticker: 'DXY',  cn: '美元指数 · Dollar Index', en: 'US Dollar Index',       ex: 'ICE',   dec: 2, unit: '' },
  us2y: { prefix: 'us2y', ticker: 'US2Y', cn: '2年期美债收益率',         en: 'US 2Y Treasury Yield',  ex: 'TVC',   dec: 3, unit: '%' },
};

function InstrumentTab({ inst, isChinese, days, setDays }) {
  const { data: daily, loading: l1 } = useFetch(`/api/analytics/${inst.prefix}/daily-stats?days=${days}`);
  const { data: vol, loading: l2 } = useFetch(`/api/analytics/${inst.prefix}/volatility?days=${days}`);
  const { data: sess } = useFetch(`/api/analytics/${inst.prefix}/sessions`);
  const { data: weekly } = useFetch(`/api/analytics/${inst.prefix}/weekly`);

  if (l1 || l2) return <div className="an-loading">{isChinese ? '加载中...' : 'Loading...'}</div>;

  const ds = daily?.results || [];
  if (!ds.length) return <div className="an-loading">{isChinese ? '暂无数据' : 'No data available'}</div>;

  const latest = ds[ds.length - 1];
  const prev = ds.length > 1 ? ds[ds.length - 2] : null;
  const changePct = latest.change_pct ?? 0;
  const changeAbs = prev ? (latest.close - prev.close) : 0;
  const isUp = changePct >= 0;

  // Price chart data
  const closes = ds.map(d => d.close);
  const highs = ds.map(d => d.high);
  const lows = ds.map(d => d.low);
  const allPrices = [...closes];
  const pMin = Math.min(...allPrices);
  const pMax = Math.max(...allPrices);
  const chartW = 940, chartH = 300;
  const xStart = 50, xEnd = 920, yTop = 30, yBot = 270;
  const step = (xEnd - xStart) / Math.max(ds.length - 1, 1);

  const linePath = buildLinePath(ds, xStart, xEnd, yTop, yBot, d => d.close);
  const areaPath = buildAreaPath(linePath, xStart, xEnd, yBot);

  // Y axis labels
  const yRange = pMax - pMin || 1;
  const yLabels = Array.from({ length: 5 }, (_, i) => {
    const val = pMax - (yRange * i / 4);
    const y = scaleY(val, pMin, pMax, yTop, yBot);
    return { val: val.toFixed(inst.dec === 3 ? 2 : 0), y: y + 4 };
  });

  // X axis labels (evenly spaced)
  const xCount = Math.min(6, ds.length);
  const xLabels = Array.from({ length: xCount }, (_, i) => {
    const idx = Math.round(i * (ds.length - 1) / Math.max(xCount - 1, 1));
    const d = ds[idx];
    return { label: d.date.slice(5), x: xStart + idx * step };
  });

  // Volatility data
  const volSeries = vol?.results?.series || [];
  const volCurrent = vol?.results?.current_vol_20d;
  const volPercentile = vol?.results?.vol_percentile;
  const volRegime = vol?.results?.current_regime;

  // Build vol line paths
  const vol20d = volSeries.filter(v => v.vol_20d != null);
  const atr14 = volSeries.filter(v => v.atr_14 != null);

  const volLinePath = vol20d.length > 1
    ? buildLinePath(vol20d, 0, 900, 15, 125, d => d.vol_20d * 100)
    : '';
  const atrLinePath = atr14.length > 1
    ? buildLinePath(atr14, 0, 900, 15, 125, d => d.atr_14)
    : '';

  // Sessions
  const sessions = sess?.results || {};
  const sessKeys = Object.keys(sessions);
  const sessNames = { asian: isChinese ? '亚洲' : 'Asian', london: isChinese ? '伦敦' : 'London', newyork: isChinese ? '纽约' : 'New York' };

  // Weekly
  const weeklyData = weekly?.results || [];
  const recentWeeks = weeklyData.slice(-8);

  return (
    <>
      {/* ── Asset picker + quote ── */}
      <div className="an-asset-row">
        <div className="an-asset">
          <div className="an-asset__ticker">{inst.ticker}</div>
          <div>
            <div className="an-asset__name">{isChinese ? inst.cn : inst.en}</div>
            <div><span className="an-asset__ex">{inst.ex}</span></div>
          </div>
        </div>
        <div className="an-quote">
          <div className="an-quote__price">{fmt(latest.close, inst.dec)}{inst.unit}</div>
          <div className={`an-quote__delta ${pctClass(changePct)}`}>
            {isUp ? '▲' : '▼'} {pctSign(changeAbs)}{fmt(changeAbs, inst.dec)} &nbsp; {pctSign(changePct)}{fmt(changePct, 2)}% &nbsp;·&nbsp; {isChinese ? '今日' : 'today'}
          </div>
        </div>
      </div>

      {/* ── Time window tabs ── */}
      <div className="an-controls-row">
        <div className="an-window-tabs">
          {[30, 60, 90, 180, 365].map(d => (
            <button key={d} className={`an-wtab${d === days ? ' active' : ''}`} onClick={() => setDays(d)}>
              {d}D
            </button>
          ))}
        </div>
        <div className="an-range-label">
          {ds.length > 0 && `${ds[0].date.slice(5).replace('-', '\u00b7')} \u2014 ${latest.date.slice(5).replace('-', '\u00b7')} \u00a0·\u00a0 ${ds.length} SESSIONS`}
        </div>
      </div>

      {/* ── Main price chart ── */}
      <div className="an-chart-card">
        <svg className="an-chart-svg" viewBox={`0 0 ${chartW} ${chartH}`} preserveAspectRatio="none">
          <defs>
            <linearGradient id="area-grad" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#D4AF37" stopOpacity="0.15" />
              <stop offset="100%" stopColor="#D4AF37" stopOpacity="0.00" />
            </linearGradient>
          </defs>
          {/* Grid lines */}
          {yLabels.map((l, i) => (
            <line key={i} className="an-grid-line" x1={xStart} y1={l.y - 4} x2={xEnd} y2={l.y - 4} />
          ))}
          {/* Y labels */}
          <g className="an-chart-axis-y">
            {yLabels.map((l, i) => (
              <text key={i} x={xStart - 6} y={l.y} textAnchor="end">{l.val}</text>
            ))}
          </g>
          {/* Area + Line */}
          {areaPath && <path fill="url(#area-grad)" opacity="0.9" d={areaPath} />}
          {linePath && <path className="an-price-line" d={linePath} style={{ stroke: '#D4AF37' }} />}
          {/* Current dot */}
          <circle cx={xEnd} cy={scaleY(latest.close, pMin, pMax, yTop, yBot)} r="4" fill={isUp ? '#166534' : '#991b1b'} />
          <text className="an-price-annot" x={xEnd - 5} y={scaleY(latest.close, pMin, pMax, yTop, yBot) - 8} textAnchor="end" fill={isUp ? '#166534' : '#991b1b'}>
            {fmt(latest.close, 2)}
          </text>
          {/* X labels */}
          <g className="an-chart-axis-x">
            {xLabels.map((l, i) => (
              <text key={i} x={l.x} y={chartH - 5} textAnchor={i === xLabels.length - 1 ? 'end' : 'start'}>
                {i === xLabels.length - 1 ? 'TODAY' : l.label}
              </text>
            ))}
          </g>
        </svg>
        <div className="an-chart-legend">
          <span className="an-leg"><span className="an-leg__sq" style={{ background: '#D4AF37' }} />Close</span>
          <span style={{ marginLeft: 'auto' }}>Source · S3 / Lambda</span>
        </div>
      </div>

      {/* ── Stat strip ── */}
      <div className="an-stats">
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '开盘 · Open' : 'Open'}</div>
          <div className="an-stat__v">{fmt(latest.open, 2)}</div>
          <div className="an-stat__sub">{latest.gap != null ? `gap ${pctSign(latest.gap)}${fmt(latest.gap, 2)}` : ''}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '日高 · High' : 'High'}</div>
          <div className="an-stat__v an-up">{fmt(latest.high, 2)}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '日低 · Low' : 'Low'}</div>
          <div className="an-stat__v an-down">{fmt(latest.low, 2)}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '日内波幅 · Range' : 'Day range'}</div>
          <div className="an-stat__v">{latest.range_pct != null ? `${fmt(latest.range_pct, 2)}%` : '\u2014'}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '波动率 · Vol' : 'Volatility'}</div>
          <div className="an-stat__v">{volCurrent != null ? `${(volCurrent * 100).toFixed(1)}%` : '\u2014'}</div>
          <div className="an-stat__sub">{volRegime || ''}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '百分位 · Pctile' : 'Vol pctile'}</div>
          <div className="an-stat__v">{volPercentile != null ? `${volPercentile}%` : '\u2014'}</div>
          <div className="an-stat__sub">20d rank</div>
        </div>
      </div>

      {/* ── Volatility Panel ── */}
      <div className="an-sec-head">
        <span className="an-sec-head__l">{isChinese ? '波动率 · Volatility' : 'Volatility'}</span>
        <span className="an-sec-head__rule" />
        <span className="an-sec-head__more">20d Vol vs ATR-14</span>
      </div>
      <div className="an-vola-panel">
        <h3 className="an-vola-title">
          {isChinese ? '波动率走势 · Volatility trend' : 'Volatility trend'}
        </h3>
        <p className="an-vola-sub">
          {isChinese
            ? `当前 20 日波动率 ${volCurrent != null ? (volCurrent * 100).toFixed(1) + '%' : '\u2014'}，处于 ${volPercentile ?? '\u2014'}% 分位，市场判定为「${volRegime || '\u2014'}」波动区间。`
            : `Current 20-day volatility ${volCurrent != null ? (volCurrent * 100).toFixed(1) + '%' : '\u2014'}, at the ${volPercentile ?? '\u2014'}th percentile. Regime: ${volRegime || '\u2014'}.`}
        </p>
        {vol20d.length > 1 && (
          <svg className="an-vola-svg" viewBox="0 0 900 140" preserveAspectRatio="none">
            <line className="an-grid-line" x1="0" y1="30" x2="900" y2="30" />
            <line className="an-grid-line" x1="0" y1="70" x2="900" y2="70" />
            <line className="an-grid-line" x1="0" y1="110" x2="900" y2="110" />
            <path className="an-vola-hv" d={volLinePath} />
            {atrLinePath && <path className="an-vola-iv" d={atrLinePath} />}
          </svg>
        )}
        <div className="an-chart-legend">
          <span className="an-leg"><span className="an-leg__sq" />20d Vol</span>
          <span className="an-leg"><span className="an-leg__sq an-leg__sq--ma" />ATR-14</span>
        </div>
      </div>

      {/* ── Sessions + Weekly: two-col ── */}
      <div className="an-two-col" style={{ marginTop: 40 }}>
        {/* Session performance */}
        <div>
          <div className="an-sec-head" style={{ marginTop: 0 }}>
            <span className="an-sec-head__l">{isChinese ? '交易时段 · Sessions' : 'Session performance'}</span>
            <span className="an-sec-head__rule" />
          </div>
          {sessKeys.length > 0 && (
            <div className="an-sess-grid">
              {sessKeys.map(s => {
                const d = sessions[s];
                return (
                  <div key={s} className="an-sess-card">
                    <div className="an-sess-card__name">{sessNames[s] || s}</div>
                    <div className="an-sess-card__rows">
                      <div className="an-sess-card__row">
                        <span className="an-sess-card__label">{isChinese ? '平均回报' : 'Avg return'}</span>
                        <span className={`an-sess-card__val ${pctClass(d.avg_return_pct)}`}>
                          {pctSign(d.avg_return_pct)}{fmt(d.avg_return_pct, 3)}%
                        </span>
                      </div>
                      <div className="an-sess-card__row">
                        <span className="an-sess-card__label">{isChinese ? '胜率' : 'Win rate'}</span>
                        <span className="an-sess-card__val">{fmt(d.win_rate, 1)}%</span>
                      </div>
                      <div className="an-sess-card__row">
                        <span className="an-sess-card__label">{isChinese ? '平均波幅' : 'Avg range'}</span>
                        <span className="an-sess-card__val">{fmt(d.avg_range_pct, 3)}%</span>
                      </div>
                      <div className="an-sess-card__row">
                        <span className="an-sess-card__label">{isChinese ? '交易日' : 'Days'}</span>
                        <span className="an-sess-card__val">{d.trading_days}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Weekly summary */}
        <div>
          <div className="an-sec-head" style={{ marginTop: 0 }}>
            <span className="an-sec-head__l">{isChinese ? '周度回顾 · Weekly' : 'Weekly review'}</span>
            <span className="an-sec-head__rule" />
          </div>
          {recentWeeks.length > 0 && (
            <table className="an-tbl">
              <thead>
                <tr>
                  <th>{isChinese ? '周' : 'Week'}</th>
                  <th>{isChinese ? '开盘' : 'Open'}</th>
                  <th>{isChinese ? '收盘' : 'Close'}</th>
                  <th>{isChinese ? '回报' : 'Return'}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {recentWeeks.map(w => (
                  <tr key={w.week_ending}>
                    <td><span className="an-sym">{w.week_ending.slice(5)}</span></td>
                    <td>{fmt(w.open, 0)}</td>
                    <td>{fmt(w.close, 0)}</td>
                    <td className={pctClass(w.return_pct)}>{pctSign(w.return_pct)}{fmt(w.return_pct, 2)}%</td>
                    <td>{w.trend === 'up' ? '\u2191' : '\u2193'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

/* ═══════════════════════════════════════════════════════════════════
 * News Tab
 * ═══════════════════════════════════════════════════════════════════ */

function NewsTab({ isChinese }) {
  const { data: sent, loading: l1 } = useFetch('/api/analytics/news/sentiment');
  const { data: cats } = useFetch('/api/analytics/news/categories');
  const { data: corr } = useFetch('/api/analytics/news/correlation');
  const { data: syms } = useFetch('/api/analytics/news/symbols');

  if (l1) return <div className="an-loading">{isChinese ? '加载中...' : 'Loading...'}</div>;

  const series = sent?.results?.series || [];
  const last60 = series.slice(-60);
  const summary = sent?.results?.summary || {};

  // Sentiment bar chart: stacked bars rendered in SVG
  const sentMax = Math.max(...last60.map(d => (d.positive || 0) + (d.neutral || 0) + (d.negative || 0)), 1);
  const sentChartW = 920, sentChartH = 200;
  const barW = Math.max(2, (sentChartW - 60) / last60.length - 1);

  // Category data
  const overall = cats?.results?.overall || {};
  const catLabels = Object.keys(overall);
  const catTotal = catLabels.reduce((s, k) => s + (overall[k] || 0), 0);

  // Correlation
  const corrData = corr?.results || {};

  // Top symbols
  const topSyms = syms?.results?.top_symbols || [];
  const topMax = topSyms.length > 0 ? topSyms[0].count : 1;

  return (
    <>
      {/* ── Sentiment overview stats ── */}
      <div className="an-stats" style={{ marginTop: 28 }}>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '总文章 · Total' : 'Total articles'}</div>
          <div className="an-stat__v">{summary.total_articles_with_sentiment?.toLocaleString() || '\u2014'}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '积极 · Positive' : 'Positive'}</div>
          <div className="an-stat__v an-up">{summary.overall_positive?.toLocaleString() || '\u2014'}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '消极 · Negative' : 'Negative'}</div>
          <div className="an-stat__v an-down">{summary.overall_negative?.toLocaleString() || '\u2014'}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '中性 · Neutral' : 'Neutral'}</div>
          <div className="an-stat__v">{summary.overall_neutral?.toLocaleString() || '\u2014'}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '净情绪 · Net' : 'Avg net sentiment'}</div>
          <div className="an-stat__v">{summary.avg_net_sentiment != null ? fmt(summary.avg_net_sentiment, 3) : '\u2014'}</div>
        </div>
        <div className="an-stat">
          <div className="an-stat__l">{isChinese ? '同日相关 · Same-day' : 'Same-day corr.'}</div>
          <div className="an-stat__v">{corrData.same_day_correlation ?? '\u2014'}</div>
        </div>
      </div>

      {/* ── Sentiment stacked bar chart ── */}
      <div className="an-sec-head">
        <span className="an-sec-head__l">{isChinese ? '每日情绪 · Daily sentiment' : 'Daily sentiment'}</span>
        <span className="an-sec-head__rule" />
        <span className="an-sec-head__more">{isChinese ? '最近 60 天' : 'Last 60 days'}</span>
      </div>
      <div className="an-chart-card">
        <svg className="an-chart-svg" viewBox={`0 0 ${sentChartW} ${sentChartH}`} preserveAspectRatio="none" style={{ height: 220 }}>
          {/* Grid */}
          <line className="an-grid-line" x1="40" y1="10" x2={sentChartW} y2="10" />
          <line className="an-grid-line" x1="40" y1="60" x2={sentChartW} y2="60" />
          <line className="an-grid-line" x1="40" y1="110" x2={sentChartW} y2="110" />
          <line className="an-grid-line" x1="40" y1="160" x2={sentChartW} y2="160" />
          <line className="an-grid-line" x1="40" y1={sentChartH - 10} x2={sentChartW} y2={sentChartH - 10} />
          {/* Stacked bars */}
          {last60.map((d, i) => {
            const x = 50 + i * (barW + 1);
            const total = (d.positive || 0) + (d.neutral || 0) + (d.negative || 0);
            const h = (total / sentMax) * (sentChartH - 30);
            const hPos = ((d.positive || 0) / sentMax) * (sentChartH - 30);
            const hNeu = ((d.neutral || 0) / sentMax) * (sentChartH - 30);
            const hNeg = ((d.negative || 0) / sentMax) * (sentChartH - 30);
            const base = sentChartH - 10;
            return (
              <g key={i}>
                <rect x={x} y={base - hNeg} width={barW} height={hNeg} fill="rgba(239,68,68,0.6)" />
                <rect x={x} y={base - hNeg - hNeu} width={barW} height={hNeu} fill="rgba(245,158,11,0.4)" />
                <rect x={x} y={base - hNeg - hNeu - hPos} width={barW} height={hPos} fill="rgba(34,197,94,0.6)" />
              </g>
            );
          })}
          {/* X labels (sparse) */}
          <g className="an-chart-axis-x">
            {last60.filter((_, i) => i % 10 === 0).map((d, i) => (
              <text key={i} x={50 + (last60.indexOf(d)) * (barW + 1)} y={sentChartH - 0}>{d.date.slice(5)}</text>
            ))}
          </g>
        </svg>
        <div className="an-chart-legend">
          <span className="an-leg"><span className="an-leg__sq" style={{ background: 'rgba(34,197,94,0.7)' }} />{isChinese ? '积极' : 'Positive'}</span>
          <span className="an-leg"><span className="an-leg__sq" style={{ background: 'rgba(245,158,11,0.5)' }} />{isChinese ? '中性' : 'Neutral'}</span>
          <span className="an-leg"><span className="an-leg__sq" style={{ background: 'rgba(239,68,68,0.7)' }} />{isChinese ? '消极' : 'Negative'}</span>
        </div>
      </div>

      {/* ── Categories + Correlation: two-col ── */}
      <div className="an-two-col" style={{ marginTop: 40 }}>
        {/* Categories */}
        <div>
          <div className="an-sec-head" style={{ marginTop: 0 }}>
            <span className="an-sec-head__l">{isChinese ? '分类分布 · Categories' : 'Category distribution'}</span>
            <span className="an-sec-head__rule" />
          </div>
          {catLabels.length > 0 && (
            <div className="an-cat-bars">
              {catLabels.map(k => {
                const pct = catTotal > 0 ? (overall[k] / catTotal * 100) : 0;
                return (
                  <div key={k} className="an-cat-row">
                    <span className="an-cat-row__label">{k.replace(/_/g, ' ')}</span>
                    <div className="an-cat-row__track">
                      <div className="an-cat-row__fill" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="an-cat-row__val">{overall[k]}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Correlation */}
        <div>
          <div className="an-sec-head" style={{ marginTop: 0 }}>
            <span className="an-sec-head__l">{isChinese ? '情绪-价格相关 · Correlation' : 'Sentiment-price correlation'}</span>
            <span className="an-sec-head__rule" />
          </div>
          <div className="an-corr-grid">
            <div className="an-corr-cell">
              <div className="an-corr-cell__label">{isChinese ? '同日' : 'Same day'}</div>
              <div className="an-corr-cell__val">{corrData.same_day_correlation ?? '\u2014'}</div>
            </div>
            <div className="an-corr-cell">
              <div className="an-corr-cell__label">{isChinese ? '次日' : 'Next day'}</div>
              <div className="an-corr-cell__val">{corrData.next_day_correlation ?? '\u2014'}</div>
            </div>
            {corrData.lag_correlations && Object.entries(corrData.lag_correlations).map(([k, v]) => (
              <div key={k} className="an-corr-cell">
                <div className="an-corr-cell__label">{isChinese ? `滞后 ${k.split('_')[1]} 日` : `Lag ${k.split('_')[1]}d`}</div>
                <div className="an-corr-cell__val">{v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Top symbols ── */}
      {topSyms.length > 0 && (
        <>
          <div className="an-sec-head">
            <span className="an-sec-head__l">{isChinese ? '热门标的 · Top symbols' : 'Most mentioned symbols'}</span>
            <span className="an-sec-head__rule" />
            <span className="an-sec-head__more">Top 15</span>
          </div>
          <div className="an-sym-bars">
            {topSyms.slice(0, 15).map(s => (
              <div key={s.symbol} className="an-sym-row">
                <span className="an-sym-row__label">{s.symbol}</span>
                <div className="an-sym-row__track">
                  <div className="an-sym-row__fill" style={{ width: `${(s.count / topMax * 100)}%` }} />
                </div>
                <span className="an-sym-row__val">{s.count}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}

/* ═══════════════════════════════════════════════════════════════════
 * Main component
 * ═══════════════════════════════════════════════════════════════════ */

export default function Analytics({ onNavigate }) {
  const { currentLanguage } = useLanguage();
  const isChinese = currentLanguage === 'zh-CN';

  const [tab, setTab] = useState('xau');
  const [days, setDays] = useState(90);

  // Clock
  const [clock, setClock] = useState('');
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setClock(`${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // Status
  const { data: status } = useFetch('/api/analytics/status');
  const lastUpdate = status?.analyses?.xau_daily_stats?.last_modified;

  // Date formatting
  const now = new Date();
  const dayNamesCn = ['周日','周一','周二','周三','周四','周五','周六'];
  const dateStr = isChinese
    ? `${now.getFullYear()}\u00b7${pad(now.getMonth()+1)}\u00b7${pad(now.getDate())} \u00b7 ${dayNamesCn[now.getDay()]}`
    : now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });

  return (
    <>
      <TopNav onNavigate={onNavigate} activePage="analytics" />

      <div className="an-col">
        {/* ── Masthead ── */}
        <section className="an-mast">
          <p className="an-mast__eyebrow">
            {isChinese ? '数据分析 · Market analytics' : 'Market analytics · 数据分析'}
          </p>
          <h1 className="an-mast__title">
            {isChinese
              ? <>数据说的话，<em>比人说的干净</em></>
              : <>Data speaks cleaner <em>than people do</em></>}
          </h1>
          <p className="an-mast__sub">
            {isChinese
              ? '黄金、美元指数、2年期美债收益率的走势与波动率、交易时段表现与新闻情绪——用数据读懂市场。'
              : 'Gold, the dollar index and 2-year Treasury yield \u2014 price trends, volatility, session performance and news sentiment, reading the market through data.'}
          </p>
          <div className="an-mast__bar">
            <span className="an-mast__stamp">{dateStr}</span>
            <span className="an-dot" />
            <span className="an-mast__clock">{clock}</span>
            {lastUpdate && (
              <>
                <span className="an-dot" />
                <span className="an-mast__clock">
                  {isChinese ? '数据更新' : 'Updated'}: {lastUpdate.slice(0, 16).replace('T', ' ')}
                </span>
              </>
            )}
            <span className="an-live">
              <span className="an-live__dot" />
              {isChinese ? 'S3 · Lambda' : 'S3 · Lambda'}
            </span>
          </div>
        </section>

        {/* ── Tab switcher ── */}
        <div className="an-tab-row">
          <button className={`an-tab${tab === 'xau' ? ' active' : ''}`} onClick={() => setTab('xau')}>
            {isChinese ? '黄金 · XAU' : 'XAU / Gold'}
          </button>
          <button className={`an-tab${tab === 'dxy' ? ' active' : ''}`} onClick={() => setTab('dxy')}>
            {isChinese ? '美元 · DXY' : 'DXY / Dollar'}
          </button>
          <button className={`an-tab${tab === 'us2y' ? ' active' : ''}`} onClick={() => setTab('us2y')}>
            {isChinese ? '2年期 · US2Y' : 'US2Y / Yield'}
          </button>
          <button className={`an-tab${tab === 'news' ? ' active' : ''}`} onClick={() => setTab('news')}>
            {isChinese ? '新闻情绪 · Sentiment' : 'News sentiment'}
          </button>
        </div>

        {/* ── Tab content ── */}
        {tab === 'news'
          ? <NewsTab isChinese={isChinese} />
          : <InstrumentTab key={tab} inst={INSTS[tab]} isChinese={isChinese} days={days} setDays={setDays} />
        }

        {/* ── Footer ── */}
        <footer className="an-footer">
          <p className="an-footer__copy">
            {isChinese
              ? '© 2026 临象财经 · 数据仅供参考 · 投资有风险'
              : '© 2026 LinXiangFinance · Data for reference only · Invest at your own risk'}
          </p>
          <div className="an-footer__links">
            <button className="an-footer__link">{isChinese ? '数据说明' : 'Data disclaimer'}</button>
            <button className="an-footer__link">{isChinese ? '隐私政策' : 'Privacy'}</button>
            <button className="an-footer__link">{isChinese ? '联系我们' : 'Contact'}</button>
          </div>
        </footer>
      </div>
    </>
  );
}
