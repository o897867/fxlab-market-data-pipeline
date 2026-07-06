import React, { useState, useEffect, lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import './App.css';
import './index.css';
import Navigation from './components/Navigation.jsx';

// 周报导图(Weekly mindmap) 已隐去：前端路由与导航移除（后端路由保留，不占资源）
import Home from './pages/Home.jsx';
const Fortune = lazy(() => import('./pages/Fortune.jsx'));
const News = lazy(() => import('./pages/News.jsx'));
// 盘口放大镜(OrderBook) 已隐去：XAUUSD 数据源暂停，前端路由移除（页面文件保留）
const LeverageCalculator = lazy(() => import('./pages/LeverageCalculator.jsx'));
const Guide = lazy(() => import('./pages/Guide.jsx'));
const Analytics = lazy(() => import('./pages/Analytics.jsx'));
const MacroPulse = lazy(() => import('./pages/MacroPulse.jsx'));
const OptionLens = lazy(() => import('./pages/OptionLens.jsx'));
import { LanguageProvider } from './hooks/useLanguage.jsx';


const App = () => {
  // Initialize page from URL hash or localStorage; fallback to 'home'
  const getInitialPage = () => {
    try {
      const raw = (window.location.hash || '').replace('#', '').trim();
      const hash = raw.split('?')[0];
      const known = ['home','news','fortune','leverage-calculator','guide','analytics','macro-pulse','option-lens'];
      if (hash && known.includes(hash)) return hash;
      const saved = localStorage.getItem('currentPage');
      if (saved && known.includes(saved)) return saved;
    } catch (e) { /* ignore */ }
    return 'home';
  };
  const [currentPage, setCurrentPage] = useState(getInitialPage);
  

  // Persist page selection and reflect in URL hash
  useEffect(() => {
    try {
      localStorage.setItem('currentPage', currentPage);
      const currentHash = (window.location.hash || '').replace('#','');
      if (currentHash !== currentPage) {
        window.location.hash = currentPage;
      }
    } catch (e) { /* ignore */ }
  }, [currentPage]);

  // Listen for external hash changes (e.g. TopNav without onNavigate)
  useEffect(() => {
    const known = ['home','forum','forum-mod','predictions','news','health','health-token','health-match','trading','fortune','leverage-calculator','guide','login','register','withdrawal-rate','liquidity-crisis','analytics','macro-pulse','option-lens'];
    const onHashChange = () => {
      const hash = (window.location.hash || '').replace('#', '').split('?')[0];
      if (hash && known.includes(hash) && hash !== currentPage) {
        setCurrentPage(hash);
      }
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [currentPage]);



  return (
    <Routes>
      {/* 周报导图(weekly-mindmap) 路由已隐去 */}

      {/* Existing hash-based app — catch-all */}
      <Route path="*" element={
        <HashApp
          currentPage={currentPage}
          setCurrentPage={setCurrentPage}
        />
      } />
    </Routes>
  );
};

/** Original hash-based app, extracted so Routes can render it as a fallback. */
const HashApp = ({ currentPage, setCurrentPage }) => {
  return (
    <div className="app">
      {/* 全局导航 - 始终显示 */}
      <Navigation currentPage={currentPage} setCurrentPage={setCurrentPage} />

      {currentPage === 'home' ? (
        <Home onNavigate={setCurrentPage} />
      ) : currentPage === 'news' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <News onNavigate={setCurrentPage} />
        </Suspense>
      ) : currentPage === 'fortune' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <Fortune onNavigate={setCurrentPage} />
        </Suspense>
      ) : currentPage === 'leverage-calculator' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <LeverageCalculator />
        </Suspense>
      ) : currentPage === 'guide' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <Guide onNavigate={setCurrentPage} />
        </Suspense>
      ) : currentPage === 'analytics' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <Analytics onNavigate={setCurrentPage} />
        </Suspense>
      ) : currentPage === 'macro-pulse' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <MacroPulse onNavigate={setCurrentPage} />
        </Suspense>
      ) : currentPage === 'option-lens' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <OptionLens onNavigate={setCurrentPage} />
        </Suspense>
      ) : null}
    </div>
  );
};


export default function AppWithLanguage() {
  return (
    <LanguageProvider>
      <App />
    </LanguageProvider>
  );
}
