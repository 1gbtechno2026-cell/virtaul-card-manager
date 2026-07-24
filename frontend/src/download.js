import { API_BASE } from './apiBase'

// Fetches an Excel export and saves it via a synthetic click -- not a
// plain <a href>, since the endpoint needs the Bearer token as a header,
// which a browser navigation can't attach. Used both for the Download
// page's manual buttons and for auto-downloading a batch the moment it
// finishes.
export async function downloadCardsExport(token, query, filename, onAuthExpired) {
  const res = await fetch(`${API_BASE}/api/cards/download?${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.status === 401 && onAuthExpired) {
    onAuthExpired()
    return
  }
  if (!res.ok) {
    throw new Error('Download failed.')
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
