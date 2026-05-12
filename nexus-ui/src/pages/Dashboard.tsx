import { useQuery } from '@tanstack/react-query'
import { Box, Card, CardContent, Grid, Typography, LinearProgress } from '@mui/material'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { PageWrapper } from '../components/PageWrapper'
import { useToken } from '../hooks/useToken'
import { api } from '../api/client'

export function Dashboard() {
  const token = useToken()

  const { data: summary, isLoading, error } = useQuery({
    queryKey: ['summary'],
    queryFn: () => api.getSummary(token),
    enabled: !!token,
  })

  const activeUsers = summary?.activeUsers ?? 0
  const monthlyTokens = summary?.monthlyTokens ?? 0
  const orgQuotaUsed = summary?.orgQuotaPercent ?? 0
  const topUsers = summary?.topUsers ?? []
  const tokenHistory = summary?.tokenHistory ?? []

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Dashboard</Typography>
      <PageWrapper isLoading={isLoading} error={error} isEmpty={activeUsers === 0 && monthlyTokens === 0} emptyMessage="No usage data yet. Metrics will appear here once developers start using Claude Code.">
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent>
              <Typography color="text.secondary" variant="body2">Active Users</Typography>
              <Typography variant="h3">{activeUsers}</Typography>
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent>
              <Typography color="text.secondary" variant="body2">Monthly Tokens</Typography>
              <Typography variant="h3">{(monthlyTokens / 1_000_000).toFixed(1)}M</Typography>
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent>
              <Typography color="text.secondary" variant="body2">Org Quota Used</Typography>
              <Typography variant="h3">{orgQuotaUsed}%</Typography>
              <LinearProgress variant="determinate" value={orgQuotaUsed} sx={{ mt: 1, height: 6, borderRadius: 3 }} />
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 8 }}>
            <Card><CardContent>
              <Typography variant="body2" color="text.secondary" gutterBottom>Token Usage (30 days)</Typography>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={tokenHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                  <XAxis dataKey="date" stroke="#999" fontSize={12} />
                  <YAxis stroke="#999" fontSize={12} />
                  <Tooltip />
                  <Line type="monotone" dataKey="tokens" stroke="#d32f2f" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent>
              <Typography variant="body2" color="text.secondary" gutterBottom>Top Users (This Month)</Typography>
              {topUsers.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>No usage yet</Typography>
              ) : topUsers.map((u: { email: string; tokens: number }) => (
                <Box key={u.email} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5 }}>
                  <Typography variant="body2" noWrap sx={{ maxWidth: 150 }}>{u.email}</Typography>
                  <Typography variant="body2" color="text.secondary">{(u.tokens / 1_000_000).toFixed(0)}M</Typography>
                </Box>
              ))}
            </CardContent></Card>
          </Grid>
        </Grid>
      </PageWrapper>
    </Box>
  )
}
