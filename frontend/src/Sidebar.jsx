const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'cards', label: 'Cards', icon: '💳' },
  { id: 'download', label: 'Download', icon: '⬇️' },
]

function Sidebar({ activeView, onNavigate, onLogout }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-brand-icon">💳</span>
        <span className="sidebar-brand-text">Virtual Card Creator</span>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`sidebar-nav-item${activeView === item.id ? ' active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            <span className="sidebar-nav-icon">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>

      <button type="button" className="sidebar-logout-btn" onClick={onLogout}>
        Log out
      </button>
    </aside>
  )
}

export default Sidebar
