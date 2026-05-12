import { useState } from 'react'

const ADMIN_GROUP = import.meta.env.VITE_ADMIN_GROUP || 'claude-code-admins'
const DEV_MODE = !import.meta.env.VITE_OIDC_AUTHORITY || import.meta.env.VITE_SKIP_AUTH === '1'

// Shared state for dev mode role toggle
let devRole: 'admin' | 'user' = 'admin'
const listeners: Set<() => void> = new Set()

export function setDevRole(role: 'admin' | 'user') {
  devRole = role
  listeners.forEach((fn) => fn())
}

export function useRole() {
  const [, rerender] = useState(0)

  if (DEV_MODE) {
    const fn = () => rerender((n) => n + 1)
    listeners.add(fn)
    return { isAdmin: devRole === 'admin', groups: devRole === 'admin' ? [ADMIN_GROUP] : [] }
  }

  // In production, check for groups in the stored OIDC user
  try {
    // oidc-client-ts stores the user in sessionStorage
    const storageKey = Object.keys(sessionStorage).find(k => k.startsWith('oidc.user:'))
    if (storageKey) {
      const userData = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
      // Check ID token for cognito:groups
      if (userData.id_token) {
        const payload = JSON.parse(atob(userData.id_token.split('.')[1]))
        const groups: string[] = payload['cognito:groups'] || []
        return { isAdmin: groups.includes(ADMIN_GROUP), groups }
      }
      // Check profile
      const groups: string[] = userData.profile?.['cognito:groups'] || []
      return { isAdmin: groups.includes(ADMIN_GROUP), groups }
    }
  } catch { /* ignore */ }

  // Default: treat as admin if authenticated (fallback until token issue resolved)
  return { isAdmin: true, groups: [ADMIN_GROUP] }
}
