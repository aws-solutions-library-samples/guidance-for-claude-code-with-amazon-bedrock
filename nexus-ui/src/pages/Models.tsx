import { useQuery } from '@tanstack/react-query'
import { Box, Card, CardContent, Grid, Typography, Alert, Chip } from '@mui/material'
import { useToken } from '../hooks/useToken'
import { api } from '../api/client'

export function Models() {
  const token = useToken()

  const { data, error } = useQuery({
    queryKey: ['models'],
    queryFn: () => api.getModels(token),
    enabled: !!token,
  })

  if (error) {
    return (
      <Box>
        <Typography variant="h5" gutterBottom>Model & Region Configuration</Typography>
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card><CardContent>
              <Typography color="text.secondary" gutterBottom>Selected Model</Typography>
              <Typography variant="h6">us.anthropic.claude-sonnet-4-20250514-v1:0</Typography>
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 3 }}>
            <Card><CardContent>
              <Typography color="text.secondary" gutterBottom>Region</Typography>
              <Chip label="us-east-1" />
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12, md: 3 }}>
            <Card><CardContent>
              <Typography color="text.secondary" gutterBottom>Cross-Region Profile</Typography>
              <Chip label="us" color="primary" />
            </CardContent></Card>
          </Grid>
          <Grid size={{ xs: 12 }}>
            <Alert severity="info">Model and region changes are managed via CloudFormation parameters. Use <code>ccwb init</code> to modify.</Alert>
          </Grid>
        </Grid>
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Model & Region Configuration</Typography>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Selected Model</Typography>
            <Typography variant="h6">{data?.selectedModel ?? 'Loading...'}</Typography>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 3 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Region</Typography>
            <Chip label={data?.region ?? '...'} />
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 3 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Cross-Region Profile</Typography>
            <Chip label={data?.crossRegionProfile ?? '...'} color="primary" />
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12 }}>
          <Alert severity="info">Model and region changes are managed via CloudFormation parameters. Use <code>ccwb init</code> to modify.</Alert>
        </Grid>
      </Grid>
    </Box>
  )
}
