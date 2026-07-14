import React, { useCallback, useState, useEffect } from 'react';
import './Home.css';
import TopNav from '../components/TopNav.jsx';
import { useLanguage } from '../hooks/useLanguage.jsx';
import { t } from '../translations/index';

const OPEN_ACCOUNT_URL = 'https://portal.cnfxhero.com/register?node=MjE4MzQw&language=zh-Hans';
const API = import.meta.env.VITE_API_URL || '';

const Home = ({ onNavigate }) => {
  const { currentLanguage } = useLanguage();
  const isChinese = currentLanguage === 'zh-CN';
  const translate = useCallback((key, params = {}) => t(key, currentLanguage, params), [currentLanguage]);

  const [news, setNews] = useState([]);
  const [weekly, setWeekly] = useState(null);
  const [gua, setGua] = useState(null);
  const [indices, setIndices] = useState([]);
  const [newsLoading, setNewsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/news/latest?limit=6`);
        if (!res.ok) throw new Error('Failed');
        const data = await res.json();
        if (!cancelled) setNews((data.news || []).filter(item => item.summary).slice(0, 6));
      } catch (e) { console.warn('news:', e); }
      finally { if (!cancelled) setNewsLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/weekly/reports`);
        if (!res.ok) throw new Error('Failed');
        const reports = await res.json();
        if (!cancelled && reports.length > 0) {
          const detailRes = await fetch(`${API}/api/weekly/reports/${reports[0].id}`);
          if (detailRes.ok) { const detail = await detailRes.json(); if (!cancelled) setWeekly(detail); }
        }
      } catch (e) { console.warn('weekly:', e); }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/fortune`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data?.gua) setGua(data.gua);
      } catch (e) { console.warn('fortune:', e); }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/market/indices`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data?.indices) setIndices(data.indices);
      } catch (e) { console.warn('indices:', e); }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleNavigate = (target) => {
    if (target === 'weekly-mindmap') { window.location.href = '/weekly-mindmap'; return; }
    if (onNavigate) onNavigate(target);
  };

  const sentClass = s => { s = (s || '').toLowerCase(); return s === 'positive' ? 'up' : s === 'negative' ? 'dn' : 'neu'; };
  const sentLabel = s => { s = (s || '').toLowerCase(); if (isChinese) return s === 'positive' ? '利好' : s === 'negative' ? '利空' : '中性'; return s === 'positive' ? 'Bull' : s === 'negative' ? 'Bear' : 'Neutral'; };
  const impLabel = i => { i = (i || '').toLowerCase(); if (isChinese) return (i === 'high' ? '高' : i === 'medium' ? '中等' : '低') + '影响'; return (i === 'high' ? 'High' : i === 'medium' ? 'Med' : 'Low') + ' impact'; };
  const impClass = i => { i = (i || '').toLowerCase(); return i === 'high' ? 'dn' : i === 'medium' ? 'neu' : 'neu'; };

  const clock = ts => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const p = n => String(n).padStart(2, '0');
    return `${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  const displayContent = item => isChinese ? (item.summary_cn || item.summary || item.title) : (item.summary || item.title);
  const fmtNum = n => (n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: n >= 1000 ? 0 : 2 }));
  const chgTxt = c => (c == null ? '' : `${c > 0 ? '+' : c < 0 ? '−' : ''}${Math.abs(c).toFixed(2)}%`);

  return (
    <div className="hd">
      <TopNav onNavigate={onNavigate} activePage="home" />
      <div className="hd-wrap">

        {/* ── Hero: pitch + LIVE market panel ── */}
        <div className="hd-hero">
          <div className="hd-hero__l">
            <p className="hd-eyebrow">{isChinese ? '面向散户的金融资讯平台 · RETAIL INTELLIGENCE' : 'Financial intelligence for retail investors'}</p>
            <h1 className="hd-hero__title">
              {isChinese ? <>万象皆声,<em>唯静者能听</em></> : <>All noise, <em>only the still can hear</em></>}
            </h1>
            <p className="hd-hero__desc">
              {isChinese
                ? '我们为普通投资者提供简洁、及时、不废话的市场资讯与交易参考。AI 摘要精华,每日更新,帮你在噪音中找到信号。'
                : 'Concise, timely market intelligence for everyday investors. AI-powered summaries, daily updates — find the signal in the noise.'}
            </p>
            <div className="hd-hero__cta">
              <a className="hd-btn hd-btn--dark" href={OPEN_ACCOUNT_URL} target="_blank" rel="noopener noreferrer">{isChinese ? '立即开户' : 'Open account'}</a>
              <button className="hd-btn hd-btn--ghost" onClick={() => handleNavigate('guide')}>{isChinese ? '了解更多 →' : 'Learn more →'}</button>
            </div>
          </div>
          <div className="hd-hero__panel">
            <h4>{isChinese ? '今日全球市场 · LIVE' : 'Global markets · LIVE'}</h4>
            {indices.length === 0 ? (
              <p className="hd-empty">{isChinese ? '加载中…' : 'Loading…'}</p>
            ) : indices.map(ix => (
              <div key={ix.code} className="hd-idx">
                <span className="hd-idx__name">{isChinese ? ix.name : ix.short}<span>{ix.short}</span></span>
                <span className="hd-idx__r">
                  <span className="hd-idx__v mono">{fmtNum(ix.last)}</span>
                  <span className={`hd-idx__c mono ${ix.change_pct >= 0 ? 'up' : 'dn'}`}>{chgTxt(ix.change_pct)}</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Features ── */}
        <div className="hd-feats">
          {[
            { icon: <><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 3" /></>, title: isChinese ? '实时资讯' : 'Real-time news', desc: isChinese ? '聚合全球主流财经媒体,AI 自动摘要,第一时间掌握市场动态。' : 'Aggregated global media, auto-summarized by AI.' },
            { icon: <><path d="M3 3v18h18" /><path d="M7 16l4-4 4 4 4-6" /></>, title: isChinese ? '专业分析' : 'Expert analysis', desc: isChinese ? '每周深度复盘,涵盖宏观走势、板块轮动与关键技术位。' : 'Weekly deep-dives on macro, rotation and key technicals.' },
            { icon: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />, title: isChinese ? '合规经营' : 'Regulated', desc: isChinese ? '持牌运营,受监管机构监督,资金安全有保障,费率透明。' : 'Licensed, regulated, transparent fees, fund protection.' },
          ].map(({ icon, title, desc }) => (
            <div key={title} className="hd-feat">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">{icon}</svg>
              <h3>{title}</h3><p>{desc}</p>
            </div>
          ))}
        </div>

        {/* ── News list (dense) + rail (weekly + fortune) ── */}
        <div className="hd-cols">
          <div>
            <div className="hd-sec">
              <span className="hd-sec__l">{isChinese ? '最新新闻 · LATEST' : 'Latest news'}</span>
              <span className="hd-sec__rule" />
              <button className="hd-sec__more" onClick={() => handleNavigate('news')}>{isChinese ? '查看全部 →' : 'View all →'}</button>
            </div>
            {newsLoading ? <div className="hd-empty">{isChinese ? '加载中…' : 'Loading…'}</div>
              : news.length === 0 ? <div className="hd-empty">{isChinese ? '暂无新闻' : 'No news'}</div>
                : news.map(item => (
                  <article key={item.id} className="hd-nitem" onClick={() => item.url && window.open(item.url, '_blank')}>
                    <span className="hd-nitem__t mono">{clock(item.published_at)}</span>
                    <div>
                      <p className="hd-nitem__title">{item.title}</p>
                      <p className="hd-nitem__sum">{displayContent(item)}</p>
                      <div className="hd-nitem__meta">
                        {item.source && <span className="hd-src">{item.source}</span>}
                        {item.sentiment && <span className={`hd-badge hd-badge--${sentClass(item.sentiment)}`}>{sentLabel(item.sentiment)}</span>}
                        {item.impact_level && <span className={`hd-badge hd-badge--${impClass(item.impact_level)}`}>{impLabel(item.impact_level)}</span>}
                      </div>
                    </div>
                    <span />
                  </article>
                ))}
          </div>

          <div>
            <div className="hd-rail">
              <div className="hd-rail__h">
                <h3>{isChinese ? '本周周报' : 'This week'}</h3>
                {weekly && <span className="hd-rail__w mono">{weekly.date}</span>}
              </div>
              {weekly ? (
                <>
                  {(weekly.nodes || []).slice(0, 4).map((node, i) => (
                    <div key={node.id || i} className="hd-bullet"><span className="hd-bullet__d" /><p>{node.title}{node.subtitle ? ` — ${node.subtitle}` : ''}</p></div>
                  ))}
                  <button className="hd-link" onClick={() => handleNavigate('weekly-mindmap')} style={{ marginTop: 10 }}>{isChinese ? '阅读完整周报 →' : 'Read full report →'}</button>
                </>
              ) : <p className="hd-empty" style={{ padding: '8px 0' }}>{isChinese ? '暂无周报' : 'No report yet'}</p>}
            </div>

            {gua && (
              <div className="hd-rail">
                <div className="hd-rail__h"><h3>{isChinese ? '今日一卦' : "Today's fortune"}</h3></div>
                <div className="hd-fortune">
                  <span className="hd-fortune__gua">{gua.char}</span>
                  <div>
                    <span className="hd-fortune__name">{gua.name}</span>
                    <span className={`hd-fortune__tag t-${gua.tag}`}>{gua.tag}</span>
                    <p className="hd-fortune__sub mono">{gua.sub}</p>
                  </div>
                </div>
                <p className="hd-fortune__verdict">{gua.verdict}</p>
                <button className="hd-link" onClick={() => handleNavigate('fortune')} style={{ marginTop: 10 }}>{isChinese ? '查看详情 →' : 'View details →'}</button>
              </div>
            )}
          </div>
        </div>

        {/* ── CTA ── */}
        <div className="hd-cta">
          <div>
            <h3>{isChinese ? '准备好开始交易了吗?' : 'Ready to start trading?'}</h3>
            <p>{isChinese ? '开户流程简单,最快 5 分钟完成,即可访问全球市场。' : 'Simple signup, as fast as 5 minutes, access global markets.'}</p>
          </div>
          <a className="hd-btn" href={OPEN_ACCOUNT_URL} target="_blank" rel="noopener noreferrer">{isChinese ? '立即开户 →' : 'Open account →'}</a>
        </div>

        <div className="hd-footer">
          <span>{isChinese ? '© 2026 临象财经 · 投资有风险,入市需谨慎' : '© 2026 LinXiangFinance · Investment involves risk'}</span>
          <span>{(isChinese ? ['隐私政策', '使用条款', '联系我们'] : ['Privacy', 'Terms', 'Contact']).map(l => <a key={l}>{l}</a>)}</span>
        </div>
      </div>
    </div>
  );
};

export default Home;
