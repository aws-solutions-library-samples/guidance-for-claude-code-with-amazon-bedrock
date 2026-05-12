import { useAuth } from 'react-oidc-context'

const DEV_MODE = !import.meta.env.VITE_OIDC_AUTHORITY || import.meta.env.VITE_SKIP_AUTH === '1'

export function useUserInfo() {
  if (DEV_MODE) {
    return {
      email: 'dev@localhost',
      logout: () => { window.location.href = '/' },
    }
  }

  // eslint-disable-next-line react-hooks/rules-of-hooks
  const auth = useAuth()
  return {
    email: (auth.user?.profile?.email as string) || (auth.user?.profile?.preferred_username as string) || 'User',
    logout: () => {
      auth.removeUser()
      window.location.href = '/'
    },
  }
}
