import { useEffect, useRef, useState } from 'react'
import './App.css'
import AnalyticsPage from './AnalyticsPage'
import { API_BASE } from './apiBase'
import DownloadPage from './DownloadPage'
import { downloadCardsExport } from './download'
import Header from './Header'
import { formatIndianNumber, numberToIndianWords } from './numberWords'
import ScreenLoader from './ScreenLoader'
import Sidebar from './Sidebar'

const AMOUNT_FIELDS = new Set(['min_transaction_amount', 'max_transaction_amount', 'cumulative_limit'])

const PHASE_LABEL = {
  idle: 'Create Cards',
  launching: 'Starting browser...',
  'waiting-login': 'Waiting for login...',
  creating: 'Creating...',
}

const BANKS = [
  { id: 'icici', name: 'ICICI Bank', available: true },
  { id: 'hdfc', name: 'HDFC Bank', available: false },
  { id: 'axis', name: 'Axis Bank', available: false },
  { id: 'sbi', name: 'State Bank of India', available: false },
  { id: 'pnb', name: 'Punjab National Bank', available: false },
]

function AmountHint({ value }) {
  const num = Number(value)
  if (!value || !Number.isFinite(num) || num <= 0) return null
  return (
    <div className="amount-hint">
      ₹{formatIndianNumber(num)} &middot; {numberToIndianWords(num)}
    </div>
  )
}

function CardsTable({ cards }) {
  return (
    <div className="table-wrap">
      <table className="cards-table">
        <thead>
          <tr>
            <th>Card Alias</th>
            <th>Card Number</th>
            <th>Amount</th>
            <th>Expiry</th>
            <th>CVC</th>
            <th>Card Holder</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card, i) => (
            <tr key={i}>
              <td>{card.card_alias || '—'}</td>
              <td className="mono">{card.card_number || '—'}</td>
              <td>₹{formatIndianNumber(card.card_amount)}</td>
              <td>{card.expiry || '—'}</td>
              <td>{card.cvc || '—'}</td>
              <td>{card.billing_name || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ConfirmModal({ fields, values, count, onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Please confirm the details</h2>
        <p className="modal-subtitle">
          Double-check everything below before the first card is created.
        </p>
        <div className="modal-list">
          {fields.map(([key, label]) => (
            <div className="modal-row" key={key}>
              <span className="modal-label">{label}</span>
              <span className="modal-value">
                {values[key] || '—'}
                {AMOUNT_FIELDS.has(key) && values[key] ? (
                  <span className="modal-amount-hint">
                    {' '}
                    (₹{formatIndianNumber(values[key])} &middot; {numberToIndianWords(values[key])})
                  </span>
                ) : null}
              </span>
            </div>
          ))}
          <div className="modal-row">
            <span className="modal-label">Number of cards</span>
            <span className="modal-value">{count}</span>
          </div>
        </div>
        <div className="modal-actions">
          <button className="secondary-btn" onClick={onCancel}>
            Go back and edit
          </button>
          <button className="primary-btn" onClick={onConfirm}>
            Confirm & Create
          </button>
        </div>
      </div>
    </div>
  )
}

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const res = await fetch(`${API_BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const body = await res.json()
      if (!res.ok) {
        setError(body.error || 'Login failed.')
        return
      }
      onLogin(body.token)
    } catch {
      setError('Could not reach the backend at ' + API_BASE)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="hero-icon login-icon">💳</div>
        <h1>Virtual Card Creator</h1>
        <p className="hint">Log in to continue</p>

        <div className="row">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="row">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button type="submit" className="primary-btn login-btn" disabled={submitting}>
          {submitting ? 'Checking...' : 'Log In'}
        </button>

        {error && <div className="error">{error}</div>}
      </form>
      {submitting && (
        <ScreenLoader message="Signing in..." subtext="Checking your credentials." />
      )}
    </div>
  )
}

function IciciLoginPage({ token, onLoggedIn, onAuthExpired }) {
  // checking-browser | form | submitting | otp | submitting-otp | restarting-login
  const ICICI_LOADER = {
    'checking-browser': ['Starting browser...', 'Getting the Smart Data login page ready.'],
    submitting: ['Signing in to Smart Data...', 'Filling User ID and password on the bank page.'],
    'submitting-otp': ['Verifying OTP...', 'Checking the code with Smart Data.'],
    'restarting-login': ['Signing in again...', 'Requesting a new OTP. Please wait.'],
  }
  const [phase, setPhase] = useState('checking-browser')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [error, setError] = useState('')
  const browserPollRef = useRef(null)
  const authHeaders = { Authorization: `Bearer ${token}` }

  // Resolves once the browser is reachable, launching it first if needed.
  // Does NOT decide phase/navigation -- callers do that with the data.
  const ensureBrowserReady = () => {
    return new Promise((resolve, reject) => {
      fetch(`${API_BASE}/launch-browser`, { method: 'POST', headers: authHeaders })

      browserPollRef.current = setInterval(async () => {
        const res = await fetch(`${API_BASE}/browser-status`, { headers: authHeaders })
        if (res.status === 401) {
          clearInterval(browserPollRef.current)
          onAuthExpired()
          reject(new Error('auth expired'))
          return
        }
        const data = await res.json()
        if (data.reachable) {
          clearInterval(browserPollRef.current)
          resolve(data)
        }
      }, 1500)
    })
  }

  const checkBrowserAndSetPhase = async () => {
    setPhase('checking-browser')
    try {
      const data = await ensureBrowserReady()
      if (data.logged_in) {
        onLoggedIn()
      } else if ((data.url || '').includes('one-time-passcode')) {
        setPhase('otp')
      } else {
        setPhase('form')
      }
    } catch {
      // auth expired -- onAuthExpired() already handled it
    }
  }

  useEffect(() => {
    checkBrowserAndSetPhase()
    return () => clearInterval(browserPollRef.current)
  }, [])

  const requestOtpFromCredentials = async () => {
    const res = await fetch(`${API_BASE}/icici-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ username, password }),
    })
    if (res.status === 401) {
      onAuthExpired()
      return null
    }
    const body = await res.json()
    if (!res.ok) {
      setError(body.error || 'Login failed.')
      setPhase('form')
      return null
    }
    if (body.status === 'logged_in') {
      onLoggedIn()
      return body
    }
    if (body.status === 'otp_required') {
      setPhase('otp')
      return body
    }
    setError('Could not confirm login -- check the browser window.')
    setPhase('form')
    return null
  }

  const restartLoginForNewOtp = async (reason) => {
    if (!username || !password) {
      setError(reason || 'OTP screen is gone. Sign in with User ID and password again.')
      setPhase('form')
      return
    }
    setOtp('')
    setError(reason || 'OTP was rejected. Signing in again to send a new OTP...')
    setPhase('restarting-login')
    try {
      const body = await requestOtpFromCredentials()
      if (!body) return
      if (body.status === 'otp_required') {
        setError('Signed in again. Enter the new OTP sent to you.')
        setPhase('otp')
      }
    } catch {
      setError('Could not sign in again. Enter User ID and password.')
      setPhase('form')
    }
  }

  const handleLoginSubmit = async (e) => {
    e.preventDefault()
    setError('')

    // The browser can die between page load and clicking Sign In --
    // make sure it's actually there before attempting to fill anything.
    const quickCheck = await fetch(`${API_BASE}/browser-status`, { headers: authHeaders })
    if (quickCheck.status === 401) {
      onAuthExpired()
      return
    }
    const quickData = await quickCheck.json()
    if (!quickData.reachable) {
      setPhase('checking-browser')
      try {
        await ensureBrowserReady()
      } catch {
        return
      }
    }

    setPhase('submitting')

    try {
      await requestOtpFromCredentials()
    } catch {
      setError('Something went wrong talking to the backend. Please try again.')
      setPhase('form')
    }
  }

  const handleOtpSubmit = async (e) => {
    e.preventDefault()
    setError('')

    const quickCheck = await fetch(`${API_BASE}/browser-status`, { headers: authHeaders })
    if (quickCheck.status === 401) {
      onAuthExpired()
      return
    }
    const quickData = await quickCheck.json()
    if (!quickData.reachable) {
      setError('The browser closed -- please start over from the login step.')
      setPhase('form')
      return
    }

    setPhase('submitting-otp')

    try {
      const res = await fetch(`${API_BASE}/icici-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ otp }),
      })
      if (res.status === 401) {
        onAuthExpired()
        return
      }
      const body = await res.json()

      if (!res.ok) {
        setError(body.error || 'OTP submission failed.')
        setPhase('otp')
        return
      }
      if (body.status === 'logged_in') {
        onLoggedIn()
        return
      }
      if (body.status === 'otp_invalid') {
        setOtp('')
        setError(body.message || 'That OTP was not accepted. Enter a new 6-digit code.')
        setPhase('otp')
        return
      }
      // OTP screen gone and main screen never appeared -- re-run User ID + password.
      await restartLoginForNewOtp(body.message)
    } catch {
      setError('Something went wrong talking to the backend. Please try again.')
      setPhase('otp')
    }
  }

  if (phase === 'otp' || phase === 'submitting-otp' || phase === 'restarting-login') {
    const busy = phase === 'submitting-otp' || phase === 'restarting-login'
    const loader = ICICI_LOADER[phase]
    return (
      <div className="login-page">
        <form className="login-card" onSubmit={handleOtpSubmit}>
          <div className="hero-icon login-icon">🔐</div>
          <h1>Enter OTP</h1>
          <p className="hint">A 6-digit code has been sent to you -- enter it below.</p>

          <div className="row">
            <label htmlFor="otp">6-digit OTP</label>
            <input
              id="otp"
              type="text"
              inputMode="numeric"
              maxLength={6}
              autoFocus
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
              className="otp-input-field"
              disabled={busy}
            />
          </div>

          <button
            type="submit"
            className="primary-btn login-btn"
            disabled={busy || otp.length !== 6}
          >
            {phase === 'submitting-otp' ? 'Verifying...' : 'Verify OTP'}
          </button>

          <button
            type="button"
            className="secondary-btn login-btn"
            disabled={busy}
            onClick={() => restartLoginForNewOtp('Signing in again to send a new OTP...')}
          >
            OTP wrong? Sign in again
          </button>

          {error && <div className="error">{error}</div>}
        </form>
        {loader && <ScreenLoader message={loader[0]} subtext={loader[1]} />}
      </div>
    )
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleLoginSubmit}>
        <div className="hero-icon login-icon">🏦</div>
        <h1>ICICI Bank Login</h1>
        <p className="hint">Log in to Mastercard Smart Data to continue.</p>

        <div className="row">
          <label htmlFor="icici-username">User ID</label>
          <input
            id="icici-username"
            type="text"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="row">
          <label htmlFor="icici-password">Password</label>
          <input
            id="icici-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button type="submit" className="primary-btn login-btn" disabled={phase === 'submitting'}>
          {phase === 'submitting' ? 'Signing in...' : 'Sign In'}
        </button>

        {error && <div className="error">{error}</div>}
      </form>
      {phase === 'submitting' && (
        <ScreenLoader
          message={ICICI_LOADER.submitting[0]}
          subtext={ICICI_LOADER.submitting[1]}
        />
      )}
      {phase === 'checking-browser' && (
        <ScreenLoader
          message={ICICI_LOADER['checking-browser'][0]}
          subtext={ICICI_LOADER['checking-browser'][1]}
        />
      )}
    </div>
  )
}

function BankSelectPage({ onSelect }) {
  const [error, setError] = useState('')

  const handleClick = (bank) => {
    if (bank.available) {
      setError('')
      onSelect(bank.name)
    } else {
      setError(`Oops! ${bank.name} is not available. We're working on it.`)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card bank-card">
        <div className="hero-icon login-icon">🏦</div>
        <h1>Choose a Bank</h1>
        <p className="hint">Which bank do you want to create a virtual card for?</p>

        <div className="bank-grid">
          {BANKS.map((bank) => (
            <button
              key={bank.id}
              type="button"
              className={`bank-option${bank.available ? '' : ' bank-option-disabled'}`}
              onClick={() => handleClick(bank)}
            >
              {bank.name}
            </button>
          ))}
        </div>

        {error && <div className="error">{error}</div>}
      </div>
    </div>
  )
}

function Dashboard({ token, bank, onAuthExpired, onBankSessionLost }) {
  const [fields, setFields] = useState([])
  const [values, setValues] = useState({})
  const [count, setCount] = useState(1)
  const [phase, setPhase] = useState('idle') // idle | launching | waiting-login | creating
  const [log, setLog] = useState([])
  const [results, setResults] = useState([])
  // How many cards the *running* batch actually asked for -- tracked
  // separately from `count` (the live "Number of cards" input) so
  // editing that field mid-batch, or navigating away and back, can't
  // desync the progress display's denominator from what's actually
  // running server-side.
  const [requestedCount, setRequestedCount] = useState(0)
  const [error, setError] = useState('')
  const [showConfirm, setShowConfirm] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [configLoading, setConfigLoading] = useState(true)
  const statusPollRef = useRef(null)
  const browserPollRef = useRef(null)
  const logBoxRef = useRef(null)
  const hasConfirmedOnceRef = useRef(false)
  const autoDownloadedBatchRef = useRef(null)

  const authHeaders = { Authorization: `Bearer ${token}` }

  useEffect(() => {
    // "Logged in" from a previous visit is saved in localStorage, but the
    // actual browser session may have died since then (closed, machine
    // restarted, etc.) -- verify it's genuinely still true before trusting it.
    fetch(`${API_BASE}/browser-status`, { headers: authHeaders })
      .then((res) => {
        if (res.status === 401) {
          onAuthExpired()
          return null
        }
        return res.json()
      })
      .then((data) => {
        if (!data) return
        if (!data.reachable || !data.logged_in) {
          onBankSessionLost()
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetch(`${API_BASE}/api/config`, { headers: authHeaders })
      .then((res) => {
        if (res.status === 401) {
          onAuthExpired()
          return null
        }
        return res.json()
      })
      .then((data) => {
        if (!data) return
        setFields(data.fields)
        setValues(data.values)
      })
      .catch(() => setError('Could not reach the backend at ' + API_BASE))
      .finally(() => setConfigLoading(false))

    return () => {
      clearInterval(statusPollRef.current)
      clearInterval(browserPollRef.current)
    }
  }, [])

  useEffect(() => {
    // A batch keeps running server-side even if you navigate away from
    // this tab -- switching tabs unmounts this component, which wipes
    // its local log/results state and kills the poll interval below.
    // Reattach to whatever's actually happening on the server instead of
    // showing a blank slate when you come back mid-batch.
    fetch(`${API_BASE}/status`, { headers: authHeaders })
      .then((res) => {
        if (res.status === 401) {
          onAuthExpired()
          return null
        }
        return res.json()
      })
      .then((data) => {
        if (!data || !data.running) return
        setPhase('creating')
        setLog(data.log)
        setResults(data.results)
        setRequestedCount(data.requested_count)
        statusPollRef.current = setInterval(pollStatus, 1000)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight
    }
  }, [log])

  const handleChange = (key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }))
  }

  const pollStatus = () => {
    fetch(`${API_BASE}/status`, { headers: authHeaders })
      .then((res) => {
        if (res.status === 401) {
          clearInterval(statusPollRef.current)
          onAuthExpired()
          return null
        }
        return res.json()
      })
      .then((data) => {
        if (!data) return
        setLog(data.log)
        setResults(data.results)
        setRequestedCount(data.requested_count)
        if (!data.running) {
          clearInterval(statusPollRef.current)
          setPhase('idle')
          setCancelling(false)

          // Auto-download the batch's Excel export the moment it finishes
          // -- no click needed. Guarded by the ref so a batch that
          // created at least one card only triggers this once, even if
          // this poll response is seen more than once before the
          // interval actually clears.
          if (
            data.batch_id &&
            data.results.length > 0 &&
            autoDownloadedBatchRef.current !== data.batch_id
          ) {
            autoDownloadedBatchRef.current = data.batch_id
            downloadCardsExport(
              token,
              `batch_id=${data.batch_id}`,
              `batch_${data.batch_id}.xlsx`,
              onAuthExpired
            ).catch(() => {
              setError(
                'Batch finished, but the automatic download failed -- use the Download page to get it manually.'
              )
            })
          }
        }
      })
  }

  // Launches launch_browser.py if it's not already running, then waits
  // (polling) until you've logged in there before resolving.
  const ensureBrowserReady = () => {
    return new Promise((resolve) => {
      setPhase('launching')
      fetch(`${API_BASE}/launch-browser`, { method: 'POST', headers: authHeaders })

      browserPollRef.current = setInterval(async () => {
        const res = await fetch(`${API_BASE}/browser-status`, { headers: authHeaders })
        if (res.status === 401) {
          clearInterval(browserPollRef.current)
          onAuthExpired()
          return
        }
        const data = await res.json()
        if (data.reachable && data.logged_in) {
          clearInterval(browserPollRef.current)
          resolve()
        } else if (data.reachable) {
          setPhase('waiting-login')
        } else {
          setPhase('launching')
        }
      }, 1500)
    })
  }

  const submitCreate = async () => {
    setError('')
    setLog([])
    setResults([])
    setCancelling(false)

    await ensureBrowserReady()
    setPhase('creating')
    // Snapshot now, before the "Number of cards" field can be edited out
    // from under the batch that's about to start.
    setRequestedCount(Number(count))

    const res = await fetch(`${API_BASE}/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ ...values, count }),
    })
    if (res.status === 401) {
      setPhase('idle')
      onAuthExpired()
      return
    }
    const body = await res.json()

    if (!res.ok) {
      setError(body.error || 'Something went wrong.')
      setPhase('idle')
      return
    }

    statusPollRef.current = setInterval(pollStatus, 1000)
  }

  const handleFormSubmit = (e) => {
    e.preventDefault()
    if (!hasConfirmedOnceRef.current) {
      setShowConfirm(true)
      return
    }
    submitCreate()
  }

  const handleCancel = async () => {
    setCancelling(true)
    try {
      await fetch(`${API_BASE}/cancel`, { method: 'POST', headers: authHeaders })
    } catch {
      // the status poll will keep running regardless; nothing else to do here
    }
  }

  const handleConfirm = () => {
    hasConfirmedOnceRef.current = true
    setShowConfirm(false)
    submitCreate()
  }

  const isBusy = phase !== 'idle'
  const completedCount = log.filter((l) => l.startsWith('  ->')).length
  const progressPct =
    requestedCount > 0 ? Math.min(100, (completedCount / requestedCount) * 100) : 0

  const blockingLoader =
    configLoading
      ? ['Loading form...', 'Fetching saved card details.']
      : phase === 'launching'
        ? ['Starting browser...', 'Connecting to the Smart Data session.']
        : phase === 'waiting-login'
          ? ['Waiting for bank login...', 'Finish signing in so card creation can start.']
          : null

  return (
    <div className="page">
      {blockingLoader && (
        <ScreenLoader message={blockingLoader[0]} subtext={blockingLoader[1]} />
      )}
      <header className="hero">
        <div className="hero-icon">💳</div>
        <div className="hero-text">
          <h1>
            Virtual Card Creator <span className="bank-badge">{bank}</span>
          </h1>
          <p className="hint">
            Fill in the details once, choose how many cards you need, and click Create --
            it will start the browser, wait for you to log in, then create every card.
          </p>
        </div>
      </header>

      <div className="layout">
        <form className="panel form-panel" onSubmit={handleFormSubmit}>
          <h2 className="panel-title">Card Details</h2>
          <div className="grid">
            {fields.map(([key, label]) => (
              <div
                className={`row${key === 'description' || key === 'user_email' ? ' row-full' : ''}`}
                key={key}
              >
                <label htmlFor={key}>{label}</label>
                <input
                  id={key}
                  type="text"
                  value={values[key] || ''}
                  onChange={(e) => handleChange(key, e.target.value)}
                />
                {AMOUNT_FIELDS.has(key) && <AmountHint value={values[key]} />}
              </div>
            ))}
          </div>

          <div className="count-row">
            <div className="row">
              <label htmlFor="count">Number of cards</label>
              <input
                id="count"
                type="number"
                min="1"
                value={count}
                onChange={(e) => setCount(e.target.value)}
              />
            </div>
            <button type="submit" className="primary-btn" disabled={isBusy}>
              {isBusy ? (
                <>
                  <span className="spinner" /> {PHASE_LABEL[phase]}
                </>
              ) : (
                'Create Cards'
              )}
            </button>
          </div>

          {phase === 'waiting-login' && (
            <div className="notice">
              A Chrome window has opened. Please log in to Mastercard Smart Data there --
              creation will continue automatically once you're logged in.
            </div>
          )}

          {phase === 'creating' && (
            <div className="progress-wrap">
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${progressPct}%` }} />
              </div>
              <span className="progress-text">
                {completedCount} cards created out of {requestedCount}
              </span>
              <button
                type="button"
                className="cancel-btn"
                onClick={handleCancel}
                disabled={cancelling}
              >
                {cancelling ? 'Cancelling...' : 'Cancel'}
              </button>
            </div>
          )}

          {error && <div className="error">{error}</div>}
        </form>

        <div className="panel log-panel">
          <h2 className="panel-title">Activity Log</h2>
          <div className="log" ref={logBoxRef}>
            {log.length === 0 ? (
              <span className="log-placeholder">Log output will appear here...</span>
            ) : (
              log.map((line, i) => (
                <div
                  key={i}
                  className={
                    line.startsWith('  ->')
                      ? 'log-line log-success'
                      : line.startsWith('Failed') || line.startsWith('Error')
                      ? 'log-line log-error'
                      : 'log-line'
                  }
                >
                  {line}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {results.length > 0 && (
        <div className="results-section">
          <h2 className="panel-title">Created Cards</h2>
          <CardsTable cards={results} />
        </div>
      )}

      {showConfirm && (
        <ConfirmModal
          fields={fields}
          values={values}
          count={count}
          onConfirm={handleConfirm}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  )
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('vcc_token'))
  const [bank, setBank] = useState(() => localStorage.getItem('vcc_bank'))
  const [bankLoggedIn, setBankLoggedIn] = useState(
    () => localStorage.getItem('vcc_bankLoggedIn') === 'true'
  )

  const handleLogin = (t) => {
    localStorage.setItem('vcc_token', t)
    setToken(t)
  }

  // Switching to a different bank invalidates any previous bank login;
  // re-picking the same (already logged-in) bank is a no-op.
  const handleBankSelect = (b) => {
    setBank((prevBank) => {
      if (prevBank !== b) {
        localStorage.removeItem('vcc_bankLoggedIn')
        setBankLoggedIn(false)
      }
      return b
    })
    localStorage.setItem('vcc_bank', b)
  }

  const handleBankLoggedIn = () => {
    localStorage.setItem('vcc_bankLoggedIn', 'true')
    setBankLoggedIn(true)
  }

  // The saved "logged in" flag turned out to be stale (browser session
  // died) -- send back to the ICICI login step, but keep the app login
  // and bank choice intact.
  const handleBankSessionLost = () => {
    localStorage.removeItem('vcc_bankLoggedIn')
    setBankLoggedIn(false)
  }

  // Called on logout AND when the backend rejects our token (e.g. it
  // restarted and forgot every session) -- either way, start clean.
  const handleLogout = () => {
    localStorage.removeItem('vcc_token')
    localStorage.removeItem('vcc_bank')
    localStorage.removeItem('vcc_bankLoggedIn')
    setToken(null)
    setBank(null)
    setBankLoggedIn(false)
  }

  if (!token) {
    return <LoginPage onLogin={handleLogin} />
  }

  // Bank selection/ICICI login is no longer a full-app gate -- Dashboard
  // and Download don't need it at all, and Cards only asks for it inline,
  // when you actually open that tab.
  return (
    <AppShell
      token={token}
      bank={bank}
      bankLoggedIn={bankLoggedIn}
      onBankSelect={handleBankSelect}
      onBankLoggedIn={handleBankLoggedIn}
      onBankSessionLost={handleBankSessionLost}
      onLogout={handleLogout}
      onAuthExpired={handleLogout}
    />
  )
}

function AppShell({
  token,
  bank,
  bankLoggedIn,
  onBankSelect,
  onBankLoggedIn,
  onBankSessionLost,
  onLogout,
  onAuthExpired,
}) {
  const [activeView, setActiveView] = useState('dashboard')

  const renderCardsView = () => {
    if (!bank) {
      return <BankSelectPage onSelect={onBankSelect} />
    }
    if (!bankLoggedIn) {
      return (
        <IciciLoginPage token={token} onLoggedIn={onBankLoggedIn} onAuthExpired={onAuthExpired} />
      )
    }
    return (
      <Dashboard
        token={token}
        bank={bank}
        onAuthExpired={onAuthExpired}
        onBankSessionLost={onBankSessionLost}
      />
    )
  }

  return (
    <div className="app-shell">
      <Sidebar activeView={activeView} onNavigate={setActiveView} onLogout={onLogout} />
      <div className="app-content">
        <Header bank={bank} bankLoggedIn={bankLoggedIn} onSelectBank={(b) => {
          onBankSelect(b)
          setActiveView('cards')
        }} />

        {activeView === 'dashboard' && (
          <AnalyticsPage token={token} onAuthExpired={onAuthExpired} />
        )}
        {activeView === 'cards' && renderCardsView()}
        {activeView === 'download' && (
          <DownloadPage token={token} onAuthExpired={onAuthExpired} />
        )}
      </div>
    </div>
  )
}

export default App
