import { useAuth } from 'react-oidc-context'

const DEV_MODE = !import.meta.env.VITE_OIDC_AUTHORITY || import.meta.env.VITE_SKIP_AUTH === '1'

export function useToken(): string {
  if (DEV_MODE) return 'dev-token'
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const auth = useAuth()
  return auth.user?.access_token || ''
}
