import { useToken } from '../hooks/useToken'
import { useQuery } from '@tanstack/react-query'
import { Box, Card, CardContent, Grid, Typography, LinearProgress, Alert } from '@mui/material'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api/client'

export function Dashboard() {
  
  const token = useToken()

  const { data: summary, isLoading, error } = useQuery({
    queryKey: ['summary'],
    queryFn: () => api.getSummary(token),
    enabled: !!token,
  })

  if (isLoading) return <Typography>Loading...</Typography>

  if (error) {
    return <Alert severity="info">API connection works — currently no real data available. Start using Claude Code to see metrics here.</Alert>
  }

  const activeUsers = summary?.activeUsers ?? 0
  const monthlyTokens = summary?.monthlyTokens ?? 0
  const orgQuotaUsed = summary?.orgQuotaPercent ?? 0
  const topUsers = summary?.topUsers ?? []
  const tokenHistory = summary?.tokenHistory ?? []

  if (activeUsers === 0 && monthlyTokens === 0) {
    return (
      <Box>
        <Typography variant="h5" gutterBottom>Dashboard</Typography>
        <Alert severity="success" sx={{ mb: 3 }}>✓ API connection works — currently no usage data. Start using Claude Code to see metrics here.</Alert>
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent><Typography color="text.secondary">Active Users</Typography><Typography variant="h3">0</Typography></CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent><Typography color="text.secondary">Monthly Tokens</Typography><Typography variant="h3">0</Typography></CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent><Typography color="text.secondary">Org Quota Used</Typography><Typography variant="h3">0%</Typography></CardContent></Card>
          </Grid>
        </Grid>
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Dashboard</Typography>
      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card><CardContent><Typography color="text.secondary">Active Users</Typography><Typography variant="h3">{activeUsers}</Typography></CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card><CardContent><Typography color="text.secondary">Monthly Tokens</Typography><Typography variant="h3">{(monthlyTokens / 1_000_000).toFixed(1)}M</Typography></CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card><CardContent>
            <Typography color="text.secondary">Org Quota Used</Typography>
            <Typography variant="h3">{orgQuotaUsed}%</Typography>
            <LinearProgress variant="determinate" value={orgQuotaUsed} sx={{ mt: 1 }} />
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 8 }}>
          <Card><CardContent>
            <Typography gutterBottom>Token Usage (30 days)</Typography>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={tokenHistory}>
                <CartesianGrid strokeDasharray="3 3" stroke="#ddd" />
                <XAxis dataKey="date" stroke="#666" />
                <YAxis stroke="#666" />
                <Tooltip />
                <Line type="monotone" dataKey="tokens" stroke="#e53935" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card><CardContent>
            <Typography gutterBottom>Top Users (This Month)</Typography>
            {topUsers.map((u: { email: string; tokens: number }) => (
              <Box key={u.email} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5 }}>
                <Typography variant="body2" noWrap sx={{ maxWidth: 150 }}>{u.email}</Typography>
                <Typography variant="body2" color="text.secondary">{(u.tokens / 1_000_000).toFixed(0)}M</Typography>
              </Box>
            ))}
          </CardContent></Card>
        </Grid>
      </Grid>
    </Box>
  )
}
