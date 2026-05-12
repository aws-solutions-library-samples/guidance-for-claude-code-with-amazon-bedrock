import { useAuth } from 'react-oidc-context'
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
    // Register listener for dev role changes
    const fn = () => rerender((n) => n + 1)
    listeners.add(fn)
    return { isAdmin: devRole === 'admin', groups: devRole === 'admin' ? [ADMIN_GROUP] : [] }
  }

  // eslint-disable-next-line react-hooks/rules-of-hooks
  const auth = useAuth()
  const groups: string[] = (auth.user?.profile?.['cognito:groups'] as string[])
    || (auth.user?.profile?.groups as string[])
    || []

  const isAdmin = groups.includes(ADMIN_GROUP)
  return { isAdmin, groups }
}
