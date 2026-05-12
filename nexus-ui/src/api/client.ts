const API_BASE = import.meta.env.VITE_API_URL || ''

async function fetchWithAuth(path: string, token: string) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export const api = {
  // Dashboard
  getSummary: (token: string) => fetchWithAuth('/api/metrics/summary', token),

  // Users
  getUsers: (token: string) => fetchWithAuth('/api/users', token),
  getUser: (token: string, id: string) => fetchWithAuth(`/api/users/${id}`, token),
  getMe: (token: string) => fetchWithAuth('/api/users/me', token),

  // Quotas
  getQuotas: (token: string) => fetchWithAuth('/api/quotas', token),

  // Metrics
  getUserMetrics: (token: string, id: string) => fetchWithAuth(`/api/metrics/users/${id}`, token),

  // Config
  getModels: (token: string) => fetchWithAuth('/api/config/models', token),
}
