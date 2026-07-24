import { useEffect, useRef, useState } from 'react'

const BANKS = [
  { id: 'icici', name: 'ICICI Bank', available: true },
  { id: 'hdfc', name: 'HDFC Bank', available: false },
  { id: 'axis', name: 'Axis Bank', available: false },
  { id: 'sbi', name: 'State Bank of India', available: false },
  { id: 'pnb', name: 'Punjab National Bank', available: false },
]

function Header({ bank, bankLoggedIn, onSelectBank }) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const wrapRef = useRef(null)

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handlePick = (b) => {
    if (!b.available) {
      setError(`Oops! ${b.name} is not available. We're working on it.`)
      return
    }
    setError('')
    setOpen(false)
    onSelectBank(b.name)
  }

  return (
    <header className="top-header">
      <div className="top-header-title">Virtual Card Creator</div>

      <div className="bank-selector" ref={wrapRef}>
        <button type="button" className="bank-selector-btn" onClick={() => setOpen((v) => !v)}>
          <span className="bank-selector-icon">🏦</span>
          {bank || 'Select Bank'}
          {bank && <span className={`bank-status-dot${bankLoggedIn ? ' connected' : ''}`} />}
          <span className="bank-selector-caret">▾</span>
        </button>

        {open && (
          <div className="bank-dropdown">
            {BANKS.map((b) => (
              <button
                key={b.id}
                type="button"
                className={`bank-dropdown-item${!b.available ? ' disabled' : ''}`}
                onClick={() => handlePick(b)}
              >
                <span>{b.name}</span>
                {bank === b.name && bankLoggedIn && (
                  <span className="bank-dropdown-tag connected">Connected</span>
                )}
                {bank === b.name && !bankLoggedIn && (
                  <span className="bank-dropdown-tag">Selected</span>
                )}
                {!b.available && <span className="bank-dropdown-tag">Coming soon</span>}
              </button>
            ))}
            {error && <div className="bank-dropdown-error">{error}</div>}
          </div>
        )}
      </div>
    </header>
  )
}

export default Header
