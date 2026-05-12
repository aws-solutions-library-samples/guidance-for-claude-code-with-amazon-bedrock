import { useQuery } from '@tanstack/react-query'
import { Box, Card, CardContent, Grid, Typography, Alert, Button } from '@mui/material'
import { Download } from '@mui/icons-material'
import { useToken } from '../hooks/useToken'
import { api } from '../api/client'

export function Billing() {
  const token = useToken()

  const { data: summary } = useQuery({
    queryKey: ['summary'],
    queryFn: () => api.getSummary(token),
    enabled: !!token,
  })

  const handleExport = () => {
    const apiUrl = import.meta.env.VITE_API_URL || ''
    window.open(`${apiUrl}/api/billing/report`, '_blank')
  }

  const monthlyTokens = summary?.monthlyTokens ?? 0
  // Rough cost estimate: ~$3 per 1M input tokens, ~$15 per 1M output (blended ~$8/M)
  const estimatedCost = (monthlyTokens / 1_000_000) * 8

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5">Billing & Cost Attribution</Typography>
        <Button variant="outlined" startIcon={<Download />} onClick={handleExport}>Export CSV</Button>
      </Box>

      {monthlyTokens === 0 ? (
        <Alert severity="success">✓ API connection works — no billing data yet. Costs will appear here once usage begins.</Alert>
      ) : (
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent>
              <Typography color="text.secondary">Bedrock Base Cost (est.)</Typography>
              <Typography variant="h4">${estimatedCost.toFixed(2)}</Typography>
              <Typography variant="body2" color="text.secondary">This month</Typography>
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent>
              <Typography color="text.secondary">AllCode Nexus Fee (30%)</Typography>
              <Typography variant="h4">${(estimatedCost * 0.3).toFixed(2)}</Typography>
              <Typography variant="body2" color="text.secondary">Via AWS Marketplace</Typography>
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card><CardContent>
              <Typography color="text.secondary">Total Estimated</Typography>
              <Typography variant="h4">${(estimatedCost * 1.3).toFixed(2)}</Typography>
              <Typography variant="body2" color="text.secondary">Bedrock + Nexus fee</Typography>
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12 }}>
            <Card><CardContent>
              <Typography gutterBottom>Cost Breakdown</Typography>
              <Typography variant="body2" color="text.secondary">
                Total tokens this month: {(monthlyTokens / 1_000_000).toFixed(1)}M • 
                Active users: {summary?.activeUsers ?? 0} • 
                Avg cost per user: ${summary?.activeUsers ? (estimatedCost / summary.activeUsers).toFixed(2) : '0.00'}
              </Typography>
            </CardContent></Card>
          </Grid>
        </Grid>
      )}
    </Box>
  )
}
