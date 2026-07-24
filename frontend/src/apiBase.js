// In production, Flask serves the built frontend itself, so the API is
// same-origin -- an empty base means "relative to this page" and just
// works. In local dev, Vite serves the frontend on its own port (5173+)
// separate from Flask (5000), so VITE_API_BASE (see .env.development)
// points explicitly at the backend.
export const API_BASE = import.meta.env.VITE_API_BASE || ''
