/**
 * Shared authenticated fetch for Sovereign Command (admin SPA).
 * All /api/admin and swarm tab calls must use this so Bearer tokens are sent.
 */

const API_BASE = process.env.REACT_APP_API_BASE_URL || '';

export function getAuthHeaders(extra = {}) {
  const h = { ...extra };
  const token = sessionStorage.getItem('token');
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

/**
 * JSON-oriented helper matching legacy SovereignCommand behavior:
 * redirects to index.html on 401, returns null on other errors.
 */
export async function apiFetch(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers = {
    ...getAuthHeaders(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...options.headers,
  };
  if (isFormData) delete headers['Content-Type'];
  try {
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      window.location.href = 'index.html';
      return null;
    }
    if (res.status === 204 || res.status === 205) return null;
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) return await res.json();
    return await res.text();
  } catch (err) {
    console.warn(`apiFetch ${path}:`, err);
    return null;
  }
}

/**
 * Low-level fetch with Authorization. Does not swallow errors.
 * Caller must check res.ok. Still redirects on 401.
 */
export async function authFetch(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers = {
    ...getAuthHeaders(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...options.headers,
  };
  if (isFormData) delete headers['Content-Type'];
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    window.location.href = 'index.html';
  }
  return res;
}

/**
 * For mutations that need FastAPI error bodies (detail) when res.ok is false.
 */
export async function apiFetchWithStatus(path, options = {}) {
  const res = await authFetch(path, options);
  const ct = res.headers.get('content-type') || '';
  let data = null;
  if (ct.includes('application/json')) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  } else {
    data = await res.text().catch(() => null);
  }
  return { ok: res.ok, status: res.status, data };
}
