import { Box, Card, CardContent, Grid, Typography, Chip } from '@mui/material'

export function Settings() {
  return (
    <Box>
      <Typography variant="h5" gutterBottom>Settings</Typography>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Authentication</Typography>
            <Typography variant="body1">Provider: <Chip label="OIDC (Cognito)" size="small" /></Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>Admin group: claude-code-admins</Typography>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Monitoring</Typography>
            <Typography variant="body1">OTel Collector: <Chip label="Active" size="small" color="success" /></Typography>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Distribution</Typography>
            <Typography variant="body1">Method: <Chip label="Presigned S3" size="small" /></Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>URL expiry: 48 hours</Typography>
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Deployment</Typography>
            <Typography variant="body1">Region: <Chip label={import.meta.env.VITE_AWS_REGION || 'us-east-1'} size="small" /></Typography>
          </CardContent></Card>
        </Grid>
      </Grid>
    </Box>
  )
}
