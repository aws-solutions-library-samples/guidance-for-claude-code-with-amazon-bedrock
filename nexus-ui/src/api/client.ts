const API_BASE = import.meta.env.VITE_API_URL || ''

async function fetchWithAuth(path: string, token: string, options?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export const api = {
  getSummary: (token: string) => fetchWithAuth('/api/metrics/summary', token),
  getUsers: (token: string) => fetchWithAuth('/api/users', token),
  getUser: (token: string, id: string) => fetchWithAuth(`/api/users/${id}`, token),
  getMe: (token: string) => fetchWithAuth('/api/users/me', token),
  getQuotas: (token: string) => fetchWithAuth('/api/quotas', token),
  getUserMetrics: (token: string, id: string) => fetchWithAuth(`/api/metrics/users/${id}`, token),
  getModels: (token: string) => fetchWithAuth('/api/config/models', token),

  updateModels: (token: string, data: { selectedModel: string; region?: string; crossRegionProfile?: string }) =>
    fetchWithAuth('/api/config/models', token, { method: 'PUT', body: JSON.stringify(data) }),

  // Download
  getDownloadUrl: (token: string) => fetchWithAuth('/api/download', token),

  // Activity
  getActivity: (token: string) => fetchWithAuth('/api/users/me/activity', token),

  // Quota write operations
  createQuota: (token: string, data: { type: string; target: string; monthlyLimit: number; dailyLimit: number; enforcement: string }) =>
    fetchWithAuth('/api/quotas', token, { method: 'POST', body: JSON.stringify(data) }),

  updateQuota: (token: string, id: string, data: { monthlyLimit?: number; dailyLimit?: number; enforcement?: string }) =>
    fetchWithAuth(`/api/quotas/${encodeURIComponent(id)}`, token, { method: 'PUT', body: JSON.stringify(data) }),

  deleteQuota: (token: string, id: string) =>
    fetchWithAuth(`/api/quotas/${encodeURIComponent(id)}`, token, { method: 'DELETE' }),
}
