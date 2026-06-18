import React, { useState, useEffect } from 'react';
import TopNav from '../components/TopNav.jsx';
import { useLanguage } from '../hooks/useLanguage.jsx';
import './MacroPulse.css';

const API = import.meta.env.VITE_API_URL || '';

function useFetch(url) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    fetch(`${API}${url}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [url]);
  return data;
}

/* ── i18n ── */
const I18N = {
  cn: {
    eyebrow: 'FOMC 鹰鸽倾向 · 带评估闭环的结构化读数',
    titlePre: '措辞会变，', titleEm: '市场会验证',
    lede: '把美联储声明与纪要的鹰鸽倾向做成可溯源、被市场反应检验过的结构化分数。每个读数都有原文出处、会被黄金的真实反应回测，不确定的进入人工复核——我们也如实承认样本仍然太小。',
    m1: '已分析文档', m2: '声明 · 纪要', m3: '覆盖区间', m4: '待人工复核',
    mod1: '鹰鸽分数时间线',
    mod1desc: '每篇文档一个总分（−5 极鸽 … +5 极鹰），中轴对齐。从加息周期的红色簇到降息周期的绿色簇，一眼读出政策重心的迁移。日期取自美联储真实 FOMC 日程。',
    legHawk: '鹰派 · 紧缩', legDove: '鸽派 · 宽松', legNeu: '中性', legStmt: '声明', legMin: '纪要', legReview: '待复核',
    tlDoc: '文档', tlFootL: '每次新 FOMC 会议自动追加，时间线持续增长', tlFootR: '分数为整数 −5…+5 · 中轴 = 0',
    mod2: '最新红线对比',
    mod2desc: '最近两期声明的逐处措辞改动。删除标红删除线、新增标绿，每处给出鹰／鸽方向与强度——这是把"措辞即信号"做给非技术观众看的核心模块。',
    diffNote: '红线引用美联储原文，逐字保留、不作翻译——比对的是 Fed 的确切措辞。方向与强度由模型标注。',
    mod3: '归因回测 · 分数 vs 市场反应',
    mod3desc: '用三个标的（黄金 XAU、美元指数 DXY、2 年期国债收益率 US2Y）在三个窗口的真实价格反应，检验分数方向是否被市场验证。一次真正的鹰派意外应同时压金价、推美元、抬收益率——三者一致才是强信号。',
    evtDate: '会议日期', evtScore: '分数', hitRate: '方向命中率', corr: '相关系数', consensus: '一致性命中率',
    limitLabel: '局限声明 · 不可弱化',
    limitText: '即时（15min）窗的一致性命中率约 59%、略高于硬币翻转，但样本仍小、未控制同时段其他数据发布与流动性差异；窗口越长、混杂越多。三标的的观测彼此相关、非独立。这不是"预测准确率"，而是一个仍在积累证据的检验框架——随每次新会议更新。',
    mod4: '人工裁决队列',
    mod4desc: '系统主动标出"不放心"的样本交人工复核——展示它知道自己可能在哪里出错。理由以标签呈现。',
    foot: '© 2026 临象财经 · 数据与读数仅供研究参考，不构成投资建议',
    docs: '篇',
    srcScores: '分数：MacroPulse 模型读数', srcDates: '会议与纪要日期：美联储官方 FOMC 日程（真实）', srcGold: '价格反应：FXLab 真实 XAU / 美元指数 / 2年期收益率分钟级行情（2021 至今）',
    rNeeds: '需复核', rLow: '低置信度', rQuote: '引用越界', rPrice: '价格背离',
    dHawkish: '偏鹰', dDovish: '偏鸽', dNeutral: '中性',
    phHawk: '加息周期 · 鹰', phHawkLean: '偏鹰', phNeu: '中性', phDoveLean: '偏鸽', phDove: '降息周期 · 鸽',
    scaleHawk: '鹰 →', scaleDove: '← 鸽',
    macroMod: '宏观数据归因 · 意外 vs 市场反应', macroModEn: 'Macro Surprise vs Market',
    macroDesc: '把硬数据（CPI、核心 CPI、核心 PCE、非农就业）的"意外"放进同一套三标的检验：一个 hot 数据＝鹰派，应同步压金价、推美元、抬 2 年收益率。意外的来源诚实分两段——历史段用 FRED 实际值相对近 12 期均值的偏离作代理（无市场预期），前向段用经济日历里的真实 consensus（实际值 − 预期值）。',
    macroEvt: '数据', macroPooled: '合并 · 全部',
    macroTypes: { CPI: 'CPI 通胀', CoreCPI: '核心 CPI', CorePCE: '核心 PCE', NFP: '非农就业' },
    macroLimitLabel: '局限声明 · 不可弱化',
    macroLimitText: '合并命中率仅在硬币翻转附近（15min≈46%、1日≈54%）——这正说明历史段的"代理意外"是弱信号：FRED 没有市场预期，用环比偏离顶替真 consensus，方向噪声大。前向段（真 consensus）理论更强，但 N 仍接近 0、要靠时间积累。三标的彼此相关、非独立，且同一时段常有多项数据同时发布，混杂未控制。这是个仍在积累证据的检验框架，不是预测准确率。',
    macroSrcFred: '历史意外：FRED 实际值 + 发布日（代理，无 consensus）', macroSrcCal: '前向意外：经济日历真实 consensus（实际 − 预期）',
    rateMod: '利率预期重定价 · 意外 → SOFR', rateModEn: 'Rate-Expectations Repricing',
    rateDesc: '不预测联储决议（市场用 SOFR 期货早已定价、赢不了），而是量化一个可做可验的问题：一次意外把市场的隐含政策利率重定价了多少 bp、往哪个方向。目标 = SOFR 期货隐含利率的窗口变动；信号 = FOMC 鹰鸽分 / 宏观 surprise。方向命中无参数、天然样本外；β = 每 1 个标准差信号对应的重定价 bp。',
    rateSignal: '信号源', rateFOMC: 'FOMC 鹰鸽分',
    rateLimitLabel: '局限声明 · 不可弱化',
    rateLimitText: '唯一稳定有效的信号是 FOMC 鹰鸽分（15min 方向命中 59%、β 跨窗口一致为正）——但 N=27 尚不统计显著（需约 19/27）。FRED 代理 surprise 命中 ≤50%、多为反号：这是个有价值的负结果，它证明宏观数据要贡献信号必须用真 consensus（实际−预期），前向日历轨正在逐月累积、几月后可重验。SOFR 仅覆盖 2022→今（2021 ZIRP 期对数据无反应）。结论作方法论演示，非统计显著、不构成投资建议。',
  },
  en: {
    eyebrow: 'FOMC hawk–dove read · structured, with an evaluation loop',
    titlePre: 'Wording shifts, ', titleEm: 'the market verifies',
    lede: "A traceable, market-tested read of how hawkish or dovish each Fed statement and minutes really is. Every score cites its source text, is back-tested against gold's actual reaction, and routes to human review when uncertain — and we openly admit the sample is still small.",
    m1: 'Docs analyzed', m2: 'Statements · Minutes', m3: 'Coverage', m4: 'In human review',
    mod1: 'Hawk–Dove Score Timeline',
    mod1desc: 'One overall score per document (−5 most dovish … +5 most hawkish), centre-aligned. From the red tightening cluster to the green easing cluster — read the policy migration in one glance. Dates are the real Fed FOMC calendar.',
    legHawk: 'Hawkish · tightening', legDove: 'Dovish · easing', legNeu: 'Neutral', legStmt: 'Statement', legMin: 'Minutes', legReview: 'Needs review',
    tlDoc: 'Doc', tlFootL: 'Appended automatically after each FOMC meeting — the timeline keeps growing', tlFootR: 'Integer score −5…+5 · centre axis = 0',
    mod2: 'Latest Red-line Diff',
    mod2desc: 'Every wording change between the two most recent statements. Deletions struck in red, additions in green, each tagged hawkish / dovish with a strength — the module built to make "wording is signal" legible to non-technical viewers.',
    diffNote: "The red-line quotes the Fed verbatim and is left untranslated — the comparison is against the Fed's exact wording. Direction and strength are model-annotated.",
    mod3: 'Attribution · Score vs Market reaction',
    mod3desc: "Test whether the score's direction is confirmed across three instruments (gold XAU, dollar index DXY, 2-year Treasury yield US2Y) over three windows. A genuine hawkish surprise should weigh on gold, lift the dollar, and push yields up at once — agreement across all three is the strong signal.",
    evtDate: 'Meeting', evtScore: 'Score', hitRate: 'directional hit-rate', corr: 'correlation', consensus: 'consensus hit-rate',
    limitLabel: 'Stated limitations · not to be softened',
    limitText: 'The immediate (15min) consensus hit-rate is ~59%, slightly above a coin flip — but the sample is still small, other same-window data releases and liquidity differences are uncontrolled, and longer windows accumulate more noise. The three instruments are correlated, not independent. This is not a "prediction accuracy" — it is an evidence-gathering test that updates as each new meeting is added.',
    mod4: 'Adjudication Queue',
    mod4desc: 'The system flags samples it is not confident about and routes them to a human — showing it knows where it might be wrong. Reasons are shown as chips.',
    foot: '© 2026 LinXiangFinance · Research read-outs only, not investment advice',
    docs: 'docs',
    srcScores: 'Scores · MacroPulse model read-out', srcDates: 'Meeting & minutes dates · official Fed FOMC calendar (real)', srcGold: 'Price reaction · FXLab real XAU / dollar index / 2Y yield minute data (2021–present)',
    rNeeds: 'needs_review', rLow: 'low_confidence', rQuote: 'quote_violation', rPrice: 'price_conflict',
    dHawkish: 'hawkish', dDovish: 'dovish', dNeutral: 'neutral',
    phHawk: 'Hiking · hawk', phHawkLean: 'Hawk-lean', phNeu: 'Neutral', phDoveLean: 'Dove-lean', phDove: 'Easing · dove',
    scaleHawk: 'hawk →', scaleDove: '← dove',
    macroMod: 'Macro-data Attribution · Surprise vs Market', macroModEn: 'Macro Surprise vs Market',
    macroDesc: 'Put hard-data "surprises" (CPI, core CPI, core PCE, non-farm payrolls) through the same three-instrument test: a hot print is hawkish and should weigh on gold, lift the dollar and push the 2-year yield up at once. The surprise source is split honestly — history uses a FRED proxy (actual vs its trailing 12-month mean, no market consensus), while forward releases use the real consensus from the economic calendar (actual − forecast).',
    macroEvt: 'Release', macroPooled: 'Pooled · all',
    macroTypes: { CPI: 'CPI', CoreCPI: 'Core CPI', CorePCE: 'Core PCE', NFP: 'Non-farm Payrolls' },
    macroLimitLabel: 'Stated limitations · not to be softened',
    macroLimitText: 'Pooled hit-rates sit around a coin flip (15min ≈46%, 1-day ≈54%) — which is exactly the point: the historical "proxy surprise" is a weak signal, since FRED carries no market expectation and a month-over-month deviation stands in for true consensus, adding directional noise. The forward track (real consensus) should be stronger but its N is still near zero and must accumulate over time. The three instruments are correlated, not independent, and multiple releases often share the same window — uncontrolled. This is an evidence-gathering test, not a prediction accuracy.',
    macroSrcFred: 'Historical surprise · FRED actuals + release dates (proxy, no consensus)', macroSrcCal: 'Forward surprise · economic-calendar real consensus (actual − forecast)',
    rateMod: 'Rate-Expectations Repricing · Surprise → SOFR', rateModEn: 'Rate-Expectations Repricing',
    rateDesc: "Not a forecast of the Fed's decision (the market already prices that via SOFR futures — you can't beat it), but a testable question: how many bp, and in which direction, does a surprise reprice the market-implied policy rate? Target = the windowed change in SOFR-implied rate; signal = FOMC hawk-dove score / macro surprise. Directional hit is parameter-free and inherently out-of-sample; β = bp repriced per 1 SD of signal.",
    rateSignal: 'Signal', rateFOMC: 'FOMC hawk-dove',
    rateLimitLabel: 'Stated limitations · not to be softened',
    rateLimitText: 'The only consistently useful signal is the FOMC hawk-dove score (59% directional hit at 15min, β positive across windows) — but N=27 is not yet statistically significant (~19/27 needed). FRED proxy surprises hit ≤50% and often with the wrong sign: a valuable negative result, proving that for macro data to carry signal it needs real consensus (actual − forecast), which the forward calendar track is accumulating month by month. SOFR covers 2022–present only (the 2021 ZIRP period does not react to data). Methodology demonstration, not statistically significant, not investment advice.',
  },
};

const MAXBAR = 0.46;
const side = s => (s > 0 ? 'hawk' : s < 0 ? 'dove' : 'neu');
const dotdate = d => (d || '').replace(/-/g, '·').slice(5);
const trunc = (s, n = 130) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s || '');

function phaseOf(mean, t) {
  if (mean >= 2) return { cls: 'hawk', label: t.phHawk };
  if (mean >= 0.5) return { cls: 'hawk', label: t.phHawkLean };
  if (mean > -0.5) return { cls: 'neu', label: t.phNeu };
  if (mean > -2) return { cls: 'dove', label: t.phDoveLean };
  return { cls: 'dove', label: t.phDove };
}

function Scale({ t }) {
  const marks = [{ v: -5, l: '−5' }, { v: 0, l: '0' }, { v: 5, l: '+5' }];
  return (
    <div className="tl__scale">
      {marks.map(m => {
        const pct = 50 + (m.v / 5) * MAXBAR * 100;
        return (
          <React.Fragment key={m.v}>
            <div className={'tick' + (m.v === 0 ? ' center' : '')} style={{ left: `${pct}%` }} />
            <div className="ticklabel" style={{ left: `${pct}%` }}>{m.l}</div>
          </React.Fragment>
        );
      })}
      <div className="ticklabel" style={{ left: '88%', color: 'var(--hawk)' }}>{t.scaleHawk}</div>
      <div className="ticklabel" style={{ left: '12%', color: 'var(--dove)' }}>{t.scaleDove}</div>
    </div>
  );
}

function Timeline({ scores, t }) {
  if (!scores) return null;
  const byYear = {};
  scores.forEach(d => { (byYear[d.meeting_date.slice(0, 4)] = byYear[d.meeting_date.slice(0, 4)] || []).push(d); });
  const years = Object.keys(byYear).sort();
  return (
    <div className="tl">
      <div className="tl__axis-head"><div className="l">{t.tlDoc}</div><Scale t={t} /></div>
      <div>
        {years.map(yr => {
          const rows = byYear[yr];
          const mean = rows.reduce((a, d) => a + d.overall_score, 0) / rows.length;
          const ph = phaseOf(mean, t);
          const phColor = `var(--${ph.cls === 'neu' ? 'neu' : ph.cls})`;
          const phBg = `var(--${ph.cls === 'neu' ? 'neu' : ph.cls}-dim)`;
          return (
            <React.Fragment key={yr}>
              <div className="tl__year">
                <span className="y">{yr}</span>
                <span className="phase" style={{ color: phColor, background: phBg }}>{ph.label}</span>
                <span className="cnt">{rows.length} {t.docs}</span>
              </div>
              {rows.map(d => {
                const s = d.overall_score;
                const mag = (Math.abs(s) / 5) * MAXBAR * 100;
                const type = d.doc_type === 'statement' ? 'S' : 'M';
                let barStyle, scoreStyle;
                if (s > 0) { barStyle = { left: '50%', width: `${mag}%` }; scoreStyle = { left: `calc(50% + ${mag}% + 6px)` }; }
                else if (s < 0) { barStyle = { right: '50%', width: `${mag}%` }; scoreStyle = { right: `calc(50% + ${mag}% + 6px)`, textAlign: 'right' }; }
                else { barStyle = { left: 'calc(50% - 3px)', width: '6px' }; scoreStyle = { left: 'calc(50% + 10px)' }; }
                return (
                  <div className="tl__row" key={d.document_id}>
                    <div className="tl__meta">
                      <span className={`tl__type tl__type--${type}`}>{type}</span>
                      <span className="tl__date">{dotdate(d.meeting_date)}</span>
                      {d.needs_human_review && <span className="tl__flag" title="needs review">⚑</span>}
                    </div>
                    <div className="tl__bar-cell">
                      <div className="axis" />
                      <div className={`tl__bar tl__bar--${side(s)}`} style={barStyle} />
                      <div className="tl__score" style={scoreStyle}>{s > 0 ? '+' : ''}{s}</div>
                    </div>
                  </div>
                );
              })}
            </React.Fragment>
          );
        })}
      </div>
      <div className="tl__footer"><span>{t.tlFootL}</span><span>{t.tlFootR}</span></div>
    </div>
  );
}

function RedLine({ detail, fromDate, t, lang }) {
  if (!detail) return null;
  const changes = (detail.diffs_vs_previous || []).filter(c => c.old || c.new);
  const nRep = changes.filter(c => c.old && c.new).length;
  const nAdd = changes.filter(c => c.new && !c.old).length;
  const nDel = changes.filter(c => c.old && !c.new).length;
  const dirLabel = d => (d === 'hawkish' ? t.dHawkish : d === 'dovish' ? t.dDovish : t.dNeutral);
  return (
    <div className="diff">
      <div className="diff__head">
        <div className="diff__route">
          <span className="mono">{dotdate(fromDate)}</span><span className="tag">S</span>
          <span className="arrow">→</span>
          <span className="mono">{dotdate(detail.meeting_date)}</span><span className="tag">S</span>
        </div>
        <div className="diff__counts">
          <span className="c-rep">{lang === 'cn' ? `改 ${nRep}` : `${nRep} changed`}</span>
          <span className="c-add">{lang === 'cn' ? `增 ${nAdd}` : `${nAdd} added`}</span>
          <span className="c-del">{lang === 'cn' ? `删 ${nDel}` : `${nDel} deleted`}</span>
        </div>
      </div>
      <div className="diff__list">
        {changes.map((c, i) => (
          <div className="diff__row" key={i}>
            <div>
              <div className="diff__text">
                {c.old && <span className="diff__del">{trunc(c.old)}</span>}{' '}
                {c.new && <span className="diff__add">{trunc(c.new)}</span>}
              </div>
            </div>
            <div className="diff__badge-wrap">
              <span className={`diff__badge diff__badge--${c.direction}`}>{dirLabel(c.direction)}</span>
              <div className="diff__strength" style={{ color: `var(--${c.direction === 'hawkish' ? 'hawk' : c.direction === 'dovish' ? 'dove' : 'neu'})` }}>
                {[1, 2, 3].map(n => <span key={n} className={`diff__pip${n <= (c.magnitude || 1) ? ' on' : ''}`} />)}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="diff__note">{t.diffNote}</div>
    </div>
  );
}

function Attribution({ attr, t, lang }) {
  if (!attr) return null;
  const wlabel = { '15': '15 min', '60': '1 hour', '1440': '1 day' };
  const insts = attr.instruments || ['XAU', 'DXY', 'US2Y'];
  // 1d 收益单元格：US2Y 用 bps（低利率期 %变化会误导），其余用 %
  const cell = (inst, r) => {
    if (!r) return <td key={inst} className="m-neu">—</td>;
    const m = r.hit === null ? <span className="evt__mark m-neu">·</span> : r.hit ? <span className="evt__mark m-hit">✓</span> : <span className="evt__mark m-miss">✗</span>;
    let disp, up;
    if (inst === 'US2Y') { const bp = (r.p1 - r.p0) * 100; up = bp > 0; disp = `${up ? '+' : ''}${bp.toFixed(0)}bp`; }
    else { up = r.return_pct > 0; disp = `${up ? '+' : ''}${r.return_pct.toFixed(2)}%`; }
    return <td key={inst}><span className="evt__ret"><span className={up ? 'up' : 'down'}>{disp}</span>{m}</span></td>;
  };
  return (
    <>
      <div className="attr-windows">
        {attr.windows_min.map(w => {
          const c = attr.aggregate.consensus[String(w)];
          return (
            <div className="win" key={w}>
              <div className="win__l">{wlabel[String(w)] || w} · {t.consensus}</div>
              <div className="win__main">
                <span className="win__rate">{c.hit_rate != null ? Math.round(c.hit_rate * 100) : '—'}<span style={{ fontSize: '16px' }}>%</span></span>
                <span className="win__rate-l">@ N={c.n_directional}</span>
              </div>
              <div className="win__insts">
                {insts.map(inst => {
                  const a = attr.aggregate[inst][String(w)];
                  return <div key={inst} className="win__inst"><span>{inst}</span><b>{a.hit_rate != null ? Math.round(a.hit_rate * 100) + '%' : '—'}</b></div>;
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="evt">
        <table>
          <thead><tr><th>{t.evtDate}</th><th>{t.evtScore}</th>{insts.map(i => <th key={i}>{i} · 1d</th>)}</tr></thead>
          <tbody>
            {attr.events.map(e => {
              const sd = side(e.overall_score);
              return (
                <tr key={e.document_id}>
                  <td>{dotdate(e.meeting_date)}</td>
                  <td><span className="evt__chip" style={{ color: `var(--${sd})`, background: `var(--${sd}-dim)` }}>{e.overall_score > 0 ? '+' : ''}{e.overall_score}</span></td>
                  {insts.map(inst => cell(inst, e.reactions[inst] && e.reactions[inst]['1440']))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="limit">
        <div className="limit__l"><span>⚑</span><span>{t.limitLabel}</span></div>
        <p className="limit__t">{t.limitText}</p>
      </div>
      <div className="mp-sources">
        <span className="src real">{t.srcDates}</span>
        <span className="src model">{t.srcScores}</span>
        <span className="src real">{t.srcGold}</span>
      </div>
    </>
  );
}

function MacroAttribution({ macro, t }) {
  if (!macro) return null;
  const wlabel = { '15': '15 min', '60': '1 hour', '1440': '1 day' };
  const order = ['CPI', 'CoreCPI', 'CorePCE', 'NFP'];
  const types = order.filter(et => macro.by_event_type && macro.by_event_type[et]);
  const rateCell = (agg, w) => {
    const c = agg.consensus[String(w)];
    if (!c || c.hit_rate == null) return <td key={w} className="m-neu">—</td>;
    const pct = Math.round(c.hit_rate * 100);
    const cls = pct > 55 ? 'up' : pct < 45 ? 'down' : '';
    return <td key={w}><span className={cls} style={{ fontWeight: 600 }}>{pct}%</span> <span className="macro-n">N={c.n_directional}</span></td>;
  };
  return (
    <>
      <div className="evt">
        <table>
          <thead><tr><th>{t.macroEvt}</th>{macro.windows_min.map(w => <th key={w}>{wlabel[String(w)] || w}</th>)}</tr></thead>
          <tbody>
            {types.map(et => (
              <tr key={et}>
                <td><b>{(t.macroTypes && t.macroTypes[et]) || et}</b> <span className="macro-n">{macro.by_event_type[et].n_events}</span></td>
                {macro.windows_min.map(w => rateCell(macro.by_event_type[et].aggregate, w))}
              </tr>
            ))}
            <tr className="macro-pooled">
              <td><b>{t.macroPooled}</b> <span className="macro-n">{macro.n_events}</span></td>
              {macro.windows_min.map(w => rateCell(macro.aggregate_pooled, w))}
            </tr>
          </tbody>
        </table>
      </div>
      <div className="limit">
        <div className="limit__l"><span>⚑</span><span>{t.macroLimitLabel}</span></div>
        <p className="limit__t">{t.macroLimitText}</p>
      </div>
      <div className="mp-sources">
        <span className="src real">{t.macroSrcFred}</span>
        <span className="src model">{t.macroSrcCal}</span>
        <span className="src real">{t.srcGold}</span>
      </div>
    </>
  );
}

function RateModel({ rm, t }) {
  if (!rm || !rm.by_window) return null;
  const wl = { '15': '15 min', '60': '1 hour', '1440': '1 day' };
  const order = ['FOMC', 'CPI', 'CoreCPI', 'CorePCE', 'NFP'];
  const labels = { FOMC: t.rateFOMC, ...(t.macroTypes || {}) };
  const base = rm.by_window[String(rm.windows_min[0])].by_event_type;
  const types = order.filter(et => base[et]);
  const cell = (et, w) => {
    const blk = rm.by_window[String(w)].by_event_type[et];
    const d = blk && blk.directional;
    if (!d || d.hit_rate == null) return <td key={w} className="m-neu">—</td>;
    const pct = Math.round(d.hit_rate * 100);
    const beta = blk.ols ? blk.ols.beta_bp : null;
    const cls = pct > 55 ? 'up' : pct < 45 ? 'down' : '';
    return <td key={w}><span className={cls} style={{ fontWeight: 600 }}>{pct}%</span> <span className="macro-n">β{beta > 0 ? '+' : ''}{beta != null ? beta : '—'}</span></td>;
  };
  return (
    <>
      <div className="evt">
        <table>
          <thead><tr><th>{t.rateSignal}</th>{rm.windows_min.map(w => <th key={w}>{wl[String(w)] || w}</th>)}</tr></thead>
          <tbody>
            {types.map(et => (
              <tr key={et} className={et === 'FOMC' ? 'rate-hot' : ''}>
                <td><b>{labels[et] || et}</b> {et === 'FOMC' && <span className="macro-n">✓ {base[et].directional.n}</span>}</td>
                {rm.windows_min.map(w => cell(et, w))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="limit">
        <div className="limit__l"><span>⚑</span><span>{t.rateLimitLabel}</span></div>
        <p className="limit__t">{t.rateLimitText}</p>
      </div>
      <div className="mp-sources">
        <span className="src model">{t.srcScores}</span>
        <span className="src real">SOFR · CME 3M futures (2022–present)</span>
      </div>
    </>
  );
}

function Queue({ queue, t }) {
  if (!queue) return null;
  const chip = (r) => {
    if (r.startsWith('needs_human_review')) return t.rNeeds;
    if (r.startsWith('low_confidence')) return t.rLow;
    if (r.startsWith('quote_violation')) return t.rQuote;
    if (r.startsWith('price_conflict')) return t.rPrice;
    return r;
  };
  return (
    <div className="queue">
      {queue.map(q => (
        <div className="q-card" key={q.document_id}>
          <div className="q-card__top">
            <span className="q-card__date">{dotdate(q.meeting_date)}</span>
            <span className="q-card__type">{q.doc_type === 'statement' ? 'S' : 'M'}</span>
            <span className="q-card__score" style={{ color: `var(--${side(q.overall_score)})` }}>{q.overall_score > 0 ? '+' : ''}{q.overall_score}</span>
          </div>
          <div className="q-card__reasons">
            {q.reasons.map((r, i) => <span key={i} className={`q-chip${i > 0 ? ' q-chip--alt' : ''}`} title={r}>{chip(r)}</span>)}
          </div>
        </div>
      ))}
    </div>
  );
}

const MacroPulse = () => {
  const { currentLanguage } = useLanguage();
  const lang = currentLanguage === 'zh-CN' ? 'cn' : 'en';
  const t = I18N[lang];

  const scoresData = useFetch('/api/macro/scores');
  const attr = useFetch('/api/macro/attribution');
  const macroAttr = useFetch('/api/macro/macro-attribution');
  const rateModel = useFetch('/api/macro/rate-model');
  const queueData = useFetch('/api/macro/adjudication-queue');

  const scores = scoresData?.scores;
  const statements = scores ? scores.filter(s => s.doc_type === 'statement') : [];
  const latestStmt = statements[statements.length - 1];
  const prevStmt = statements[statements.length - 2];
  const detail = useFetch(latestStmt ? `/api/macro/scores/${latestStmt.document_id}` : null);

  // masthead metrics
  const nStmt = statements.length;
  const nMin = scores ? scores.filter(s => s.doc_type === 'minutes').length : 0;
  const inReview = scores ? scores.filter(s => s.needs_human_review).length : 0;
  const years = scores ? scores.map(s => s.meeting_date.slice(0, 4)) : [];
  const coverage = years.length ? `${years[0]}–${years[years.length - 1]}` : '—';

  return (
    <>
      <TopNav />
      <div className="mp">
        <div className="mp-wrap">
          <header className="mp-mast">
            <p className="mp-mast__eyebrow"><span className="pulse" />{t.eyebrow}</p>
            <h1 className="mp-mast__title">{t.titlePre}<em>{t.titleEm}</em></h1>
            <p className="mp-mast__lede">{t.lede}</p>
            <div className="mp-mast__meta">
              <div className="mp-mast__metric"><div className="v mono">{scoresData?.count ?? '—'}</div><div className="l">{t.m1}</div></div>
              <div className="mp-mast__metric"><div className="v mono">{scores ? `${nStmt} · ${nMin}` : '—'}</div><div className="l">{t.m2}</div></div>
              <div className="mp-mast__metric"><div className="v mono">{coverage}</div><div className="l">{t.m3}</div></div>
              <div className="mp-mast__metric"><div className="v mono">{scores ? `${inReview} ⚑` : '—'}</div><div className="l">{t.m4}</div></div>
            </div>
          </header>

          <section className="mod">
            <div className="mod__head"><span className="mod__num">01</span><h2 className="mod__title">{t.mod1}</h2><span className="mod__en">Hawk–Dove Score Timeline</span></div>
            <p className="mod__desc">{t.mod1desc}</p>
            <div className="legend">
              <span className="legend__i"><span className="legend__sw" style={{ background: 'var(--hawk)' }} />{t.legHawk}</span>
              <span className="legend__i"><span className="legend__sw" style={{ background: 'var(--dove)' }} />{t.legDove}</span>
              <span className="legend__i"><span className="legend__sw" style={{ background: 'var(--neu)' }} />{t.legNeu}</span>
              <span className="legend__i" style={{ marginLeft: 'auto' }}><span className="tl__type tl__type--S" style={{ position: 'static' }}>S</span>{t.legStmt}</span>
              <span className="legend__i"><span className="tl__type tl__type--M" style={{ position: 'static' }}>M</span>{t.legMin}</span>
              <span className="legend__i"><span className="tl__flag">⚑</span>{t.legReview}</span>
            </div>
            <Timeline scores={scores} t={t} />
          </section>

          <section className="mod">
            <div className="mod__head"><span className="mod__num">02</span><h2 className="mod__title">{t.mod2}</h2><span className="mod__en">Latest Red-line Diff</span></div>
            <p className="mod__desc">{t.mod2desc}</p>
            <RedLine detail={detail} fromDate={prevStmt?.meeting_date} t={t} lang={lang} />
          </section>

          <section className="mod">
            <div className="mod__head"><span className="mod__num">03</span><h2 className="mod__title">{t.mod3}</h2><span className="mod__en">Attribution · Score vs XAU</span></div>
            <p className="mod__desc">{t.mod3desc}</p>
            <Attribution attr={attr} t={t} lang={lang} />
          </section>

          <section className="mod">
            <div className="mod__head"><span className="mod__num">04</span><h2 className="mod__title">{t.macroMod}</h2><span className="mod__en">{t.macroModEn}</span></div>
            <p className="mod__desc">{t.macroDesc}</p>
            <MacroAttribution macro={macroAttr} t={t} />
          </section>

          <section className="mod">
            <div className="mod__head"><span className="mod__num">05</span><h2 className="mod__title">{t.rateMod}</h2><span className="mod__en">{t.rateModEn}</span></div>
            <p className="mod__desc">{t.rateDesc}</p>
            <RateModel rm={rateModel} t={t} />
          </section>

          <section className="mod">
            <div className="mod__head"><span className="mod__num">06</span><h2 className="mod__title">{t.mod4}</h2><span className="mod__en">Adjudication Queue</span></div>
            <p className="mod__desc">{t.mod4desc}</p>
            <Queue queue={queueData?.queue} t={t} />
          </section>

          <footer className="mp-foot">
            <span className="mp-foot__c">{t.foot}</span>
            <span className="mp-foot__c">MacroPulse · LinXiangFinance</span>
          </footer>
        </div>
      </div>
    </>
  );
};

export default MacroPulse;
