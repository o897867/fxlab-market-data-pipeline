import React, { useState, useEffect, lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import './App.css';
import './index.css';
import Navigation from './components/Navigation.jsx';

// Weekly mindmap module (lazy-loaded, fully isolated)
import { useIsMobile } from './weekly/hooks/useIsMobile';
const TimelineView = lazy(() => import('./weekly/pages/TimelineView.tsx'));
const NodeDetailPage = lazy(() => import('./weekly/pages/NodeDetailPage.tsx'));
const TopicsView = lazy(() => import('./weekly/pages/TopicsView.tsx'));
const GraphView = lazy(() => import('./weekly/pages/GraphView.tsx'));
// Mobile weekly
const MobileApp = lazy(() => import('./weekly/mobile/MobileApp.tsx'));
const MobileNodeDetail = lazy(() => import('./weekly/mobile/MobileNodeDetail.tsx'));
const MobileTopicView = lazy(() => import('./weekly/mobile/MobileTopicView.tsx'));
const MobileErrorBoundary = lazy(() => import('./weekly/mobile/components/MobileErrorBoundary.tsx').then(m => ({ default: m.MobileErrorBoundary })));
import Home from './pages/Home.jsx';
const Fortune = lazy(() => import('./pages/Fortune.jsx'));
const News = lazy(() => import('./pages/News.jsx'));
const OrderBook = lazy(() => import('./pages/OrderBook.jsx'));
const LeverageCalculator = lazy(() => import('./pages/LeverageCalculator.jsx'));
const Guide = lazy(() => import('./pages/Guide.jsx'));
const Analytics = lazy(() => import('./pages/Analytics.jsx'));
const MacroPulse = lazy(() => import('./pages/MacroPulse.jsx'));
import { LanguageProvider } from './hooks/useLanguage.jsx';
import TopNav from './components/TopNav.jsx';


/** Thin wrapper so weekly routes also show the hamburger nav. */
const WeeklyNav = () => {
  const handleSetPage = (id) => {
    if (id === 'weekly-mindmap') return;
    window.location.href = `/#${id}`;
  };
  return <Navigation currentPage="weekly-mindmap" setCurrentPage={handleSetPage} />;
};

/** Viewport-based dispatch for weekly routes */
function WeeklyEntry() {
  const isMobile = useIsMobile();
  return isMobile ? <MobileApp /> : <TimelineView />;
}
function WeeklyNodeEntry() {
  const isMobile = useIsMobile();
  return isMobile ? <MobileNodeDetail /> : <NodeDetailPage />;
}
function WeeklyTopicEntry() {
  const isMobile = useIsMobile();
  return isMobile ? <MobileTopicView /> : <TopicsView />;
}

const App = () => {
  // Initialize page from URL hash or localStorage; fallback to 'home'
  const getInitialPage = () => {
    try {
      const raw = (window.location.hash || '').replace('#', '').trim();
      const hash = raw.split('?')[0];
      const known = ['home','news','fortune','leverage-calculator','guide','analytics','macro-pulse'];
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
    const known = ['home','forum','forum-mod','predictions','news','health','health-token','health-match','trading','orderbook','fortune','leverage-calculator','guide','login','register','withdrawal-rate','liquidity-crisis','analytics','macro-pulse'];
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
      {/* Weekly mindmap module — isolated routes, mobile/desktop dispatch */}
      <Route path="/weekly-mindmap" element={
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <TopNav />
          <WeeklyNav />
          <WeeklyEntry />
        </Suspense>
      } />
      <Route path="/weekly-mindmap/nodes/:id" element={
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <TopNav />
          <WeeklyNav />
          <WeeklyNodeEntry />
        </Suspense>
      } />
      <Route path="/weekly-mindmap/topics" element={
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <TopNav />
          <WeeklyNav />
          <WeeklyTopicEntry />
        </Suspense>
      } />
      <Route path="/weekly-mindmap/topics/:slug" element={
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <TopNav />
          <WeeklyNav />
          <WeeklyTopicEntry />
        </Suspense>
      } />
      <Route path="/weekly-mindmap/graph" element={
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <TopNav />
          <WeeklyNav />
          <GraphView />
        </Suspense>
      } />

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
      ) : currentPage === 'orderbook' ? (
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <OrderBook />
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
