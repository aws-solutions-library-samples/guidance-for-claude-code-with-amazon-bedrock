import { Box, Card, CardContent, Grid, Typography, LinearProgress } from '@mui/material'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

export function Dashboard() {
  const mockData = {
    activeUsers: 47,
    monthlyTokens: 2_300_000_000,
    orgQuotaPercent: 78,
    topUsers: [
      { email: 'alice@company.com', tokens: 142_000_000 },
      { email: 'bob@company.com', tokens: 98_000_000 },
      { email: 'carol@company.com', tokens: 87_000_000 },
      { email: 'dave@company.com', tokens: 65_000_000 },
    ],
    tokenHistory: Array.from({ length: 30 }, (_, i) => ({
      date: `May ${i + 1}`,
      tokens: Math.floor(Math.random() * 100_000_000) + 50_000_000,
    })),
  }

  const { activeUsers, monthlyTokens, orgQuotaPercent: orgQuotaUsed, topUsers, tokenHistory } = mockData

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Dashboard</Typography>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Active Users</Typography>
              <Typography variant="h3">{activeUsers}</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Monthly Tokens</Typography>
              <Typography variant="h3">{(monthlyTokens / 1_000_000).toFixed(1)}M</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Org Quota Used</Typography>
              <Typography variant="h3">{orgQuotaUsed}%</Typography>
              <LinearProgress variant="determinate" value={orgQuotaUsed} sx={{ mt: 1 }} />
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }}>
          <Card>
            <CardContent>
              <Typography gutterBottom>Token Usage (30 days)</Typography>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={tokenHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="date" stroke="#888" />
                  <YAxis stroke="#888" />
                  <Tooltip />
                  <Line type="monotone" dataKey="tokens" stroke="#e53935" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography gutterBottom>Top Users (This Month)</Typography>
              {topUsers.map((u: { email: string; tokens: number }) => (
                <Box key={u.email} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5 }}>
                  <Typography variant="body2" noWrap sx={{ maxWidth: 150 }}>{u.email}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {(u.tokens / 1_000_000).toFixed(0)}M
                  </Typography>
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  )
}
