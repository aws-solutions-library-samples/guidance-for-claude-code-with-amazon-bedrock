import { useQuery, useMutation } from '@tanstack/react-query'
import { Box, Card, CardContent, Typography, LinearProgress, Chip, Button } from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { useToken } from '../hooks/useToken'
import { useUserInfo } from '../hooks/useUserInfo'
import { api } from '../api/client'

export function Me() {
  const token = useToken()
  const { email } = useUserInfo()
  const navigate = useNavigate()

  const { data } = useQuery({
    queryKey: ['me'],
    queryFn: () => api.getMe(token),
    enabled: !!token,
  })

  const downloadMutation = useMutation({
    mutationFn: () => api.getDownloadUrl(token),
    onSuccess: (data) => { window.open(data.url, '_blank') },
  })

  const monthly = data?.monthly ?? { used: 0, limit: 225_000_000 }
  const daily = data?.daily ?? { used: 0, limit: 7_500_000 }
  const model = data?.model ?? 'Claude Sonnet 4 (US cross-region)'
  const status = data?.status ?? 'active'
  const monthlyPct = monthly.limit > 0 ? Math.round((monthly.used / monthly.limit) * 100) : 0
  const dailyPct = daily.limit > 0 ? Math.round((daily.used / daily.limit) * 100) : 0

  return (
    <Box sx={{ maxWidth: 600 }}>
      <Typography variant="h5" gutterBottom>{email}</Typography>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>My Usage</Typography>

          <Box sx={{ mb: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="body2">Monthly</Typography>
              <Typography variant="body2">{(monthly.used / 1_000_000).toFixed(1)}M / {(monthly.limit / 1_000_000).toFixed(0)}M tokens</Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={Math.min(monthlyPct, 100)}
              color={monthlyPct > 90 ? 'error' : monthlyPct > 80 ? 'warning' : 'primary'}
              sx={{ height: 10, borderRadius: 5 }}
            />
            <Typography variant="caption" color="text.secondary">{monthlyPct}%</Typography>
          </Box>

          <Box sx={{ mb: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="body2">Daily</Typography>
              <Typography variant="body2">{(daily.used / 1_000_000).toFixed(1)}M / {(daily.limit / 1_000_000).toFixed(0)}M tokens</Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={Math.min(dailyPct, 100)}
              color={dailyPct > 90 ? 'error' : dailyPct > 80 ? 'warning' : 'primary'}
              sx={{ height: 10, borderRadius: 5 }}
            />
            <Typography variant="caption" color="text.secondary">{dailyPct}%</Typography>
          </Box>

          <Typography variant="body2" sx={{ mb: 1 }}>Model: {model}</Typography>
          <Typography variant="body2">Status: <Chip label={status === 'active' ? 'Active ✓' : 'Blocked'} size="small" color={status === 'active' ? 'success' : 'error'} /></Typography>
        </CardContent>
      </Card>

      <Box sx={{ display: 'flex', gap: 2 }}>
        <Button variant="contained" onClick={() => downloadMutation.mutate()} disabled={downloadMutation.isPending}>
          {downloadMutation.isPending ? 'Generating...' : 'Download Installer'}
        </Button>
        <Button variant="outlined" onClick={() => navigate('/activity')}>View Activity Log</Button>
      </Box>
    </Box>
  )
}
