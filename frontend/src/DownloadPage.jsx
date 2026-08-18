import { useEffect, useState } from 'react'
import { API_BASE } from './apiBase'
import { downloadCardsExport } from './download'
import { formatIndianNumber } from './numberWords'
import ScreenLoader from './ScreenLoader'

const BATCH_STATUS_LABEL = {
  running: 'Running...',
  completed: 'Completed',
  cancelled: 'Cancelled',
  failed: 'Failed',
}

function DownloadPage({ token, onAuthExpired }) {
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [search, setSearch] = useState('')
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState('')
  const [mongoConfigured, setMongoConfigured] = useState(true)
  const [batches, setBatches] = useState([])
  const [downloadingBatchId, setDownloadingBatchId] = useState(null)

  const authHeaders = { Authorization: `Bearer ${token}` }

  const buildQuery = () => {
    const params = new URLSearchParams()
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    if (search) params.set('search', search)
    return params.toString()
  }

  const fetchCards = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/api/cards?${buildQuery()}`, { headers: authHeaders })
      if (res.status === 401) {
        onAuthExpired()
        return
      }
      const body = await res.json()
      if (!res.ok) {
        setMongoConfigured(false)
        setError(body.error || 'Could not load cards.')
        setCards([])
        return
      }
      setMongoConfigured(true)
      setCards(body.cards)
    } catch {
      setError('Could not reach the backend.')
    } finally {
      setLoading(false)
    }
  }

  const fetchBatches = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/batches`, { headers: authHeaders })
      if (res.status === 401) {
        onAuthExpired()
        return
      }
      const body = await res.json()
      if (res.ok) {
        setBatches(body.batches)
      }
    } catch {
      // Non-critical -- the date/search filter section above still works
      // without batch history, so just leave the list empty.
    }
  }

  useEffect(() => {
    fetchCards()
    fetchBatches()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleFilter = (e) => {
    e.preventDefault()
    fetchCards()
  }

  const VISIBLE_LIMIT = 5
  const visibleCards = cards.slice(0, VISIBLE_LIMIT)

  const handleDownload = async () => {
    setDownloading(true)
    setError('')
    try {
      await downloadCardsExport(
        token,
        buildQuery(),
        `cards_export_${Date.now()}.xlsx`,
        onAuthExpired
      )
    } catch {
      setError('Could not reach the backend, or the download failed.')
    } finally {
      setDownloading(false)
    }
  }

  const handleBatchDownload = async (batch) => {
    setDownloadingBatchId(batch.batch_id)
    setError('')
    try {
      await downloadCardsExport(
        token,
        `batch_id=${batch.batch_id}`,
        `batch_${batch.batch_id}.xlsx`,
        onAuthExpired
      )
    } catch {
      setError('Could not reach the backend, or the download failed.')
    } finally {
      setDownloadingBatchId(null)
    }
  }

  return (
    <div className="page">
      {loading && (
        <ScreenLoader message="Loading history..." subtext="Fetching batches and cards from the database." />
      )}
      {(downloading || downloadingBatchId) && !loading && (
        <ScreenLoader message="Preparing Excel..." subtext="Building the download from the database." />
      )}
      <header className="hero">
        <div className="hero-icon">📦</div>
        <div className="hero-text">
          <h1>Card History</h1>
          <p className="hint">
            Filter by date range or card number/alias, then download the matching records as
            an Excel file -- pulled fresh from the database every time.
          </p>
        </div>
      </header>

      <div className="panel">
        <h2 className="panel-title">Batches not the bitch </h2>
        <div className="table-wrap">
          <table className="cards-table">
            <thead>
              <tr>
                <th>Started</th>
                <th>Description</th>
                <th>Cards</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => (
                <tr key={batch.batch_id}>
                  <td>{batch.started_at ? new Date(batch.started_at).toLocaleString() : '—'}</td>
                  <td>{batch.description || '—'}</td>
                  <td>
                    {batch.created_count} / {batch.requested_count}
                  </td>
                  <td>{BATCH_STATUS_LABEL[batch.status] || batch.status}</td>
                  <td>
                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() => handleBatchDownload(batch)}
                      disabled={
                        batch.status === 'running' ||
                        batch.created_count === 0 ||
                        downloadingBatchId === batch.batch_id
                      }
                    >
                      {downloadingBatchId === batch.batch_id ? 'Downloading...' : 'Download'}
                    </button>
                  </td>
                </tr>
              ))}
              {batches.length === 0 && (
                <tr>
                  <td colSpan={5} className="table-empty">
                    No batches yet -- create some cards from the Cards tab first.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <form className="panel filter-panel" onSubmit={handleFilter}>
        <div className="filter-row">
          <div className="row">
            <label htmlFor="date-from">From</label>
            <input
              id="date-from"
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </div>
          <div className="row">
            <label htmlFor="date-to">To</label>
            <input
              id="date-to"
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
          <div className="row filter-search-row">
            <label htmlFor="search">Card number / alias</label>
            <input
              id="search"
              type="text"
              placeholder="Search..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="filter-actions">
            <button type="submit" className="secondary-btn" disabled={loading}>
              {loading ? 'Filtering...' : 'Filter'}
            </button>
            <button
              type="button"
              className="primary-btn"
              onClick={handleDownload}
              disabled={downloading || cards.length === 0}
            >
              {downloading ? 'Downloading...' : `Download Excel (${cards.length})`}
            </button>
          </div>
        </div>
      </form>

      {!mongoConfigured && (
        <div className="notice">
          MongoDB is not configured on the backend (set <code>MONGODB_URI</code> in{' '}
          <code>backend/.env</code>) -- history isn't available until that's set up.
        </div>
      )}
      {error && <div className="error">{error}</div>}

      <div className="panel">
        <h2 className="panel-title">
          {cards.length > VISIBLE_LIMIT
            ? `Showing ${VISIBLE_LIMIT} most recent of ${cards.length} cards`
            : `${cards.length} card${cards.length === 1 ? '' : 's'}`}
        </h2>
        <div className="table-wrap">
          <table className="cards-table">
            <thead>
              <tr>
                <th>Created At</th>
                <th>Created By</th>
                <th>Card Alias</th>
                <th>Card Number</th>
                <th>Amount</th>
                <th>Expiry</th>
                <th>CVC</th>
              </tr>
            </thead>
            <tbody>
              {visibleCards.map((card) => (
                <tr key={card._id}>
                  <td>{card.created_at ? new Date(card.created_at).toLocaleString() : '—'}</td>
                  <td>{card.created_by || '—'}</td>
                  <td>{card.card_alias || '—'}</td>
                  <td className="mono">{card.card_number || '—'}</td>
                  <td>₹{formatIndianNumber(card.card_amount)}</td>
                  <td>{card.expiry || '—'}</td>
                  <td>{card.cvc || '—'}</td>
                </tr>
              ))}
              {cards.length === 0 && !loading && (
                <tr>
                  <td colSpan={7} className="table-empty">
                    No cards found for this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {cards.length > VISIBLE_LIMIT && (
          <p className="table-footnote">
            Only the {VISIBLE_LIMIT} most recent are shown here -- use{' '}
            <strong>Download Excel</strong> to get all {cards.length} matching cards.
          </p>
        )}
      </div>
    </div>
  )
}

export default DownloadPage
