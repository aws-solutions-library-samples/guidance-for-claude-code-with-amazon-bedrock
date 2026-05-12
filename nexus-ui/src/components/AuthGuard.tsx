import { useAuth } from 'react-oidc-context'
import { Box, Button, CircularProgress, Typography } from '@mui/material'
import { type ReactNode } from 'react'

export function AuthGuard({ children }: { children: ReactNode }) {
  const auth = useAuth()

  if (auth.isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  if (auth.error) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', gap: 2 }}>
        <Typography color="error">Authentication error: {auth.error.message}</Typography>
        <Button variant="contained" onClick={() => auth.signinRedirect()}>Try Again</Button>
      </Box>
    )
  }

  if (!auth.isAuthenticated) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', gap: 3 }}>
        <Typography variant="h4">AllCode Nexus</Typography>
        <Typography color="text.secondary">Sign in to manage your Claude Code deployment</Typography>
        <Button variant="contained" size="large" onClick={() => auth.signinRedirect()}>
          Sign In with SSO
        </Button>
      </Box>
    )
  }

  return <>{children}</>
}
