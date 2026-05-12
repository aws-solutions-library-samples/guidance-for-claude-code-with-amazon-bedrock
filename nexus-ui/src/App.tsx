import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from 'react-oidc-context'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material'
import { AuthGuard } from './components/AuthGuard'
import { Layout } from './components/Layout'
import { AdminRoute } from './components/AdminRoute'
import { Dashboard } from './pages/Dashboard'
import { Users } from './pages/Users'
import { Quotas } from './pages/Quotas'
import { Billing } from './pages/Billing'
import { Models } from './pages/Models'
import { Settings } from './pages/Settings'
import { Me } from './pages/Me'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#d32f2f' },
    secondary: { main: '#d32f2f' },
    background: { default: '#ffffff', paper: '#ffffff' },
    text: { primary: '#000000', secondary: '#444444' },
    success: { main: '#2e7d32' },
    error: { main: '#d32f2f' },
    warning: { main: '#f57c00' },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  shape: { borderRadius: 12 },
  components: {
    MuiCard: { styleOverrides: { root: { border: '1px solid #e0e0e0' } } },
    MuiAppBar: { styleOverrides: { root: { backgroundColor: '#ffffff', color: '#000000', borderBottom: '1px solid #e0e0e0', boxShadow: 'none' } } },
    MuiDrawer: { styleOverrides: { paper: { backgroundColor: '#fafafa', color: '#000000', borderRight: '1px solid #e0e0e0' } } },
  },
})

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

const oidcConfig = {
  authority: import.meta.env.VITE_OIDC_AUTHORITY,
  client_id: import.meta.env.VITE_OIDC_CLIENT_ID,
  redirect_uri: window.location.origin,
  post_logout_redirect_uri: window.location.origin,
  scope: 'openid email profile',
  response_type: 'code',
}

const DEV_MODE = !import.meta.env.VITE_OIDC_AUTHORITY || import.meta.env.VITE_SKIP_AUTH === '1'

export default function App() {
  const content = (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<AdminRoute><Dashboard /></AdminRoute>} />
          <Route path="/users" element={<AdminRoute><Users /></AdminRoute>} />
          <Route path="/quotas" element={<AdminRoute><Quotas /></AdminRoute>} />
          <Route path="/billing" element={<AdminRoute><Billing /></AdminRoute>} />
          <Route path="/models" element={<AdminRoute><Models /></AdminRoute>} />
          <Route path="/settings" element={<AdminRoute><Settings /></AdminRoute>} />
          <Route path="/me" element={<Me />} />
          <Route path="*" element={<Navigate to="/me" />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )

  if (DEV_MODE) {
    return (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <QueryClientProvider client={queryClient}>
          {content}
        </QueryClientProvider>
      </ThemeProvider>
    )
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AuthProvider {...oidcConfig}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <AuthGuard>
              <Layout>
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/users" element={<Users />} />
                  <Route path="/quotas" element={<Quotas />} />
                  <Route path="/me" element={<Me />} />
                  <Route path="*" element={<Navigate to="/" />} />
                </Routes>
              </Layout>
            </AuthGuard>
          </BrowserRouter>
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
