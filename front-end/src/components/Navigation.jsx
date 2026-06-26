import React, { useState } from 'react';
import { useLanguage } from '../hooks/useLanguage.jsx';
import { t } from '../translations/index';

const Navigation = ({ currentPage, setCurrentPage, currentUser, onLogout }) => {
  const [isOpen, setIsOpen] = useState(false);
  const { currentLanguage } = useLanguage();
  const translate = (key) => t(key, currentLanguage);

  const navGroups = [
    {
      title: translate('nav.groups.explore'),
      items: [
        { id: 'home', label: translate('nav.home'), badge: 'recommended' },
        { id: 'guide', label: translate('nav.guide'), badge: 'new' },
        { id: 'fortune', label: translate('nav.fortune'), badge: 'new' }
      ]
    },
    // 健康相关功能暂时隐藏
    // {
    //   title: translate('nav.groups.health'),
    //   items: [
    //     { id: 'health-token', label: translate('nav.healthToken'), badge: 'key' },
    //     { id: 'health', label: translate('nav.health'), badge: 'new' },
    //     { id: 'health-match', label: translate('nav.healthMatch') }
    //   ]
    // },
    {
      title: translate('nav.groups.community'),
      items: [
        { id: 'orderbook', label: translate('orderbook.hero.badge') },
        { id: 'leverage-calculator', label: translate('nav.leverage') },
        { id: 'news', label: translate('nav.news'), badge: 'new' },
        { id: 'analytics', label: currentLanguage === 'zh-CN' ? '数据分析' : 'Analytics', badge: 'new' },
        { id: 'macro-pulse', label: currentLanguage === 'zh-CN' ? '央行鹰鸽' : 'MacroPulse', badge: 'new' },
        { id: 'option-lens', label: currentLanguage === 'zh-CN' ? '期权透镜' : 'OptionLens', badge: 'new' },
        { id: 'weekly-mindmap', label: currentLanguage === 'zh-CN' ? '周报导图' : 'Weekly Mindmap', badge: 'new' },
        ...(currentLanguage === 'cn' ? [
          { id: 'withdrawal-rate', label: '出金汇率', badge: 'new' },
          { id: 'liquidity-crisis', label: '流动性危机图', badge: 'new' }
        ] : [])
      ]
    }
  ];

  const handleSelect = (id) => {
    if (id === 'weekly-mindmap') {
      window.location.href = '/weekly-mindmap';
      return;
    }
    setCurrentPage(id);
    setIsOpen(false);
  };

  return (
    <>
      {/* Toggle button fixed at top-left */}
      <button
        className={`nav-toggle ${isOpen ? 'open' : ''}`}
        aria-label="Toggle navigation"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((v) => !v)}
      >
        {/* Hamburger / close icon */}
        <svg
          className="nav-toggle-icon"
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          {isOpen ? (
            <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          ) : (
            <>
              <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </>
          )}
        </svg>
      </button>

      {/* Slide-out drawer */}
      <div className={`nav-drawer ${isOpen ? 'open' : ''}`} role="menu">
        {currentUser && (
          <div className="badge published" style={{ marginBottom: 8 }}>
            {translate('forum.common.loggedIn').replace('{{name}}', currentUser.username || currentUser.display_name)}
          </div>
        )}
        {navGroups.map((group, groupIndex) => (
          <div key={groupIndex} className="nav-group">
            <div className="nav-group-title">{group.title}</div>
            {group.items.map((item) => (
              <button
                key={item.id}
                role="menuitem"
                onClick={() => handleSelect(item.id)}
                className={`nav-item ${currentPage === item.id ? 'active' : ''}`}
              >
                {item.label}
                {item.badge === 'recommended' && (
                  <span className="nav-badge">{translate('nav.badges.recommended')}</span>
                )}
                {item.badge === 'new' && (
                  <span className="nav-badge new">{translate('nav.badges.new')}</span>
                )}
                {item.badge === 'key' && (
                  <span className="nav-badge key">🔑</span>
                )}
              </button>
            ))}
          </div>
        ))}
        {currentUser && (
          <button
            className="nav-item nav-item-logout"
            onClick={() => { onLogout && onLogout(); setIsOpen(false); }}
          >
            {translate('nav.logout')}
          </button>
        )}
      </div>
    </>
  );
};

export default Navigation;
