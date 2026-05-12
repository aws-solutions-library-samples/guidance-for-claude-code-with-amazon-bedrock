import { Box, Card, CardContent, Grid, Typography, LinearProgress, Chip } from '@mui/material'

export function Me() {
  const monthly = { used: 142_000_000, limit: 300_000_000 }
  const daily = { used: 4_200_000, limit: 11_000_000 }
  const model = 'Claude Sonnet 4 (US cross-region)'
  const status = 'active'
  const monthlyPct = Math.round((monthly.used / monthly.limit) * 100)
  const dailyPct = Math.round((daily.used / daily.limit) * 100)

  return (
    <Box>
      <Typography variant="h5" gutterBottom>My Usage</Typography>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Monthly Usage</Typography>
              <Typography variant="h4">
                {(monthly.used / 1_000_000).toFixed(1)}M / {(monthly.limit / 1_000_000).toFixed(0)}M tokens
              </Typography>
              <LinearProgress
                variant="determinate"
                value={Math.min(monthlyPct, 100)}
                color={monthlyPct > 90 ? 'error' : monthlyPct > 80 ? 'warning' : 'primary'}
                sx={{ mt: 1, height: 8, borderRadius: 4 }}
              />
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{monthlyPct}% used</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Daily Usage</Typography>
              <Typography variant="h4">
                {(daily.used / 1_000_000).toFixed(1)}M / {(daily.limit / 1_000_000).toFixed(0)}M tokens
              </Typography>
              <LinearProgress
                variant="determinate"
                value={Math.min(dailyPct, 100)}
                color={dailyPct > 90 ? 'error' : dailyPct > 80 ? 'warning' : 'primary'}
                sx={{ mt: 1, height: 8, borderRadius: 4 }}
              />
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{dailyPct}% used</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Model</Typography>
              <Typography variant="h6">{model}</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Status</Typography>
              <Chip label={status} color={status === 'active' ? 'success' : 'error'} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  )
}
