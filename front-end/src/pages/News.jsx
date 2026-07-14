import React, { useState, useEffect, useCallback, useRef } from 'react';
import TopNav from '../components/TopNav.jsx';
import { useLanguage } from '../hooks/useLanguage.jsx';
import './News.css';

const CATEGORIES = [
  { key: '', label_cn: '全部', label_en: 'All' },
  { key: 'crypto', label_cn: '加密', label_en: 'Crypto' },
  { key: 'monetary_policy', label_cn: '政策', label_en: 'Policy' },
  { key: 'market_indices', label_cn: '指数', label_en: 'Indices' },
  { key: 'forex', label_cn: '外汇', label_en: 'Forex' },
  { key: 'precious_metals', label_cn: '大宗', label_en: 'Commodities' },
  { key: 'tech_stocks', label_cn: '个股', label_en: 'Equities' },
];

const API = () => import.meta.env.VITE_API_URL || '';

const News = ({ onNavigate }) => {
  const { currentLanguage } = useLanguage();
  const isChinese = currentLanguage === 'zh-CN';

  const [news, setNews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState('');
  const [sentiment, setSentiment] = useState('');
  const [impact, setImpact] = useState('');
  const [search, setSearch] = useState('');
  const [clock, setClock] = useState('');
  const searchDebounce = useRef(null);

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const p = n => String(n).padStart(2, '0');
      setClock(`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const fetchNews = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ important_limit: '20', others_limit: '30' });
      if (category) params.set('category', category);
      if (sentiment) params.set('sentiment', sentiment);
      if (impact) params.set('impact', impact);
      if (search.trim()) params.set('search', search.trim());
      const res = await fetch(`${API()}/api/news/latest?${params}`);
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      setNews(data.news || []);
    } catch (e) { console.warn('news:', e); setNews([]); }
    finally { setLoading(false); }
  }, [category, sentiment, impact, search]);

  useEffect(() => { fetchNews(); }, [fetchNews]);

  const handleSearch = val => {
    clearTimeout(searchDebounce.current);
    searchDebounce.current = setTimeout(() => setSearch(val), 300);
  };

  const sentClass = s => { s = (s || '').toLowerCase(); return s === 'positive' ? 'up' : s === 'negative' ? 'dn' : 'neu'; };
  const sentLabel = s => { s = (s || '').toLowerCase(); if (isChinese) return s === 'positive' ? '积极' : s === 'negative' ? '消极' : '中性'; return s === 'positive' ? 'Positive' : s === 'negative' ? 'Negative' : 'Neutral'; };
  const impClass = i => { i = (i || '').toLowerCase(); return i === 'high' ? 'dn' : 'neu'; };
  const impLabel = i => { i = (i || '').toLowerCase(); if (isChinese) return (i === 'high' ? '高' : i === 'medium' ? '中等' : '低') + '影响'; return i === 'high' ? 'High' : i === 'medium' ? 'Medium' : 'Low'; };
  const hhmm = ts => { if (!ts) return ''; const d = new Date(ts * 1000); const p = n => String(n).padStart(2, '0'); return `${p(d.getHours())}:${p(d.getMinutes())}`; };
  const dispTitle = item => item.title_cn || item.title || '';
  const dispSum = item => item.summary_cn || item.summary || '';

  const dateStr = new Date().toLocaleDateString(isChinese ? 'zh-CN' : 'en-US', {
    year: 'numeric', month: isChinese ? 'long' : 'short', day: 'numeric', weekday: 'long',
  });

  const featured = news[0] || null;
  const rest = news.slice(1);
  const mostRead = news.slice(0, 6);

  return (
    <div className="nd">
      <TopNav onNavigate={onNavigate} activePage="news" />
      <div className="nd-wrap">
        {/* masthead */}
        <div className="nd-mast">
          <h1 className="nd-mast__title">{isChinese ? '市场速览' : 'Market Brief'}<span className="lt"> · {isChinese ? '临象财经' : 'LinXiang'}</span></h1>
          <div className="nd-mast__meta">
            <span className="nd-time">{dateStr}</span>
            <span className="nd-live"><span className="nd-live__dot" />Live · {clock}</span>
          </div>
        </div>

        {/* categories */}
        <nav className="nd-cats">
          {CATEGORIES.map(cat => (
            <button key={cat.key} className={`nd-cat${category === cat.key ? ' on' : ''}`} onClick={() => setCategory(cat.key)}>
              {isChinese ? cat.label_cn : cat.label_en}
            </button>
          ))}
        </nav>

        {/* filters */}
        <div className="nd-filters">
          <input className="nd-input nd-search" type="search" defaultValue={search}
            placeholder={isChinese ? '搜索新闻 / Search…' : 'Search news…'} onChange={e => handleSearch(e.target.value)} />
          <select className="nd-input nd-select" value={sentiment} onChange={e => setSentiment(e.target.value)}>
            <option value="">{isChinese ? '所有情绪' : 'All sentiment'}</option>
            <option value="positive">{isChinese ? '积极' : 'Positive'}</option>
            <option value="neutral">{isChinese ? '中性' : 'Neutral'}</option>
            <option value="negative">{isChinese ? '消极' : 'Negative'}</option>
          </select>
          <select className="nd-input nd-select" value={impact} onChange={e => setImpact(e.target.value)}>
            <option value="">{isChinese ? '所有影响' : 'All impact'}</option>
            <option value="high">{isChinese ? '高影响' : 'High'}</option>
            <option value="medium">{isChinese ? '中等' : 'Medium'}</option>
            <option value="low">{isChinese ? '低影响' : 'Low'}</option>
          </select>
        </div>

        {loading ? <div className="nd-empty">{isChinese ? '加载中…' : 'Loading…'}</div>
          : news.length === 0 ? <div className="nd-empty">{isChinese ? '暂无新闻' : 'No news found'}</div>
            : (
              <div className="nd-grid">
                <div>
                  {featured && (
                    <article className="nd-lead" style={{ cursor: featured.url ? 'pointer' : 'default' }} onClick={() => featured.url && window.open(featured.url, '_blank')}>
                      <div className="nd-lead__meta">
                        {featured.source && <span className="nd-src">{featured.source}</span>}
                        <span className="nd-time">{hhmm(featured.published_at)}</span>
                        {featured.sentiment && <span className={`nd-badge nd-badge--${sentClass(featured.sentiment)}`}>{sentLabel(featured.sentiment)}</span>}
                        {featured.impact_level && <span className={`nd-badge nd-badge--${impClass(featured.impact_level)}`}>{impLabel(featured.impact_level)}</span>}
                      </div>
                      <h2 className="nd-lead__t">{dispTitle(featured)}</h2>
                      <p className="nd-lead__body">{dispSum(featured)}</p>
                    </article>
                  )}
                  <div className="nd-stories">
                    {rest.map(item => (
                      <article key={item.id} className="nd-story" onClick={() => item.url && window.open(item.url, '_blank')}>
                        <div className="nd-lead__meta">
                          {item.source && <span className="nd-src">{item.source}</span>}
                          <span className="nd-time">{hhmm(item.published_at)}</span>
                          {item.sentiment && <span className={`nd-badge nd-badge--${sentClass(item.sentiment)}`}>{sentLabel(item.sentiment)}</span>}
                        </div>
                        <h3 className="nd-story__t">{dispTitle(item)}</h3>
                        <p className="nd-story__s">{dispSum(item)}</p>
                      </article>
                    ))}
                  </div>
                </div>

                <aside>
                  <p className="nd-rail-h">{isChinese ? '今日重点 · MOST READ' : 'Top stories · MOST READ'}</p>
                  {mostRead.map((item, i) => (
                    <div key={item.id} className="nd-most" onClick={() => item.url && window.open(item.url, '_blank')}>
                      <span className="nd-most__n">{i + 1}</span>
                      <div>
                        <p className="nd-most__t">{dispTitle(item)}</p>
                        <span className="nd-src">{item.source || ''}{item.source ? ' · ' : ''}{hhmm(item.published_at)}</span>
                      </div>
                    </div>
                  ))}
                </aside>
              </div>
            )}

        <div className="nd-footer">
          <span>{isChinese ? '© 2026 临象财经 · 由 AI 摘要,内容仅供参考' : '© 2026 LinXiang · AI-summarized, for reference only'}</span>
          <span>{(isChinese ? ['数据说明', '联系我们'] : ['About', 'Contact']).map(l => <a key={l}>{l}</a>)}</span>
        </div>
      </div>
    </div>
  );
};

export default News;
