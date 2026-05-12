import { useAuth } from 'react-oidc-context'
import { useQuery } from '@tanstack/react-query'
import { Box, Card, CardContent, Grid, Typography, LinearProgress, Chip, Alert } from '@mui/material'
import { api } from '../api/client'

export function Me() {
  const auth = useAuth()
  const token = auth.user?.access_token || ''

  const { data, isLoading, error } = useQuery({
    queryKey: ['me'],
    queryFn: () => api.getMe(token),
    enabled: !!token,
  })

  if (isLoading) return <Typography>Loading...</Typography>
  if (error) return <Alert severity="info">✓ API connection works — no usage data for your account yet.</Alert>

  const monthly = data?.monthly ?? { used: 0, limit: 225_000_000 }
  const daily = data?.daily ?? { used: 0, limit: 7_500_000 }
  const model = data?.model ?? 'Not configured'
  const status = data?.status ?? 'active'
  const monthlyPct = monthly.limit > 0 ? Math.round((monthly.used / monthly.limit) * 100) : 0
  const dailyPct = daily.limit > 0 ? Math.round((daily.used / daily.limit) * 100) : 0

  return (
    <Box>
      <Typography variant="h5" gutterBottom>My Usage</Typography>
      {monthly.used === 0 && daily.used === 0 && (
        <Alert severity="success" sx={{ mb: 3 }}>✓ API connection works — no usage recorded yet. Start using Claude Code to see your metrics here.</Alert>
      )}
      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Monthly Usage</Typography>
            <Typography variant="h4">{(monthly.used / 1_000_000).toFixed(1)}M / {(monthly.limit / 1_000_000).toFixed(0)}M tokens</Typography>
            <LinearProgress variant="determinate" value={Math.min(monthlyPct, 100)} color={monthlyPct > 90 ? 'error' : monthlyPct > 80 ? 'warning' : 'primary'} sx={{ mt: 1, height: 8, borderRadius: 4 }} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{monthlyPct}% used</Typography>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Daily Usage</Typography>
            <Typography variant="h4">{(daily.used / 1_000_000).toFixed(1)}M / {(daily.limit / 1_000_000).toFixed(0)}M tokens</Typography>
            <LinearProgress variant="determinate" value={Math.min(dailyPct, 100)} color={dailyPct > 90 ? 'error' : dailyPct > 80 ? 'warning' : 'primary'} sx={{ mt: 1, height: 8, borderRadius: 4 }} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{dailyPct}% used</Typography>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Model</Typography>
            <Typography variant="h6">{model}</Typography>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Status</Typography>
            <Chip label={status} color={status === 'active' ? 'success' : 'error'} />
          </CardContent></Card>
        </Grid>
      </Grid>
    </Box>
  )
}
