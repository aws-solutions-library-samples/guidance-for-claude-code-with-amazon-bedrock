import { useQuery } from '@tanstack/react-query'
import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip,
} from '@mui/material'
import { PageWrapper } from '../components/PageWrapper'
import { useToken } from '../hooks/useToken'
import { api } from '../api/client'

export function Activity() {
  const token = useToken()

  const { data, isLoading, error } = useQuery({
    queryKey: ['activity'],
    queryFn: () => api.getActivity(token),
    enabled: !!token,
  })

  const activities = data?.activities ?? []

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Activity Log</Typography>
      <PageWrapper isLoading={isLoading} error={error} isEmpty={activities.length === 0} emptyMessage="No activity recorded yet. Start using Claude Code to see your sessions here.">
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Tokens</TableCell>
                <TableCell>Model</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {activities.map((a: { timestamp: string; type: string; tokens: number; model: string }, i: number) => (
                <TableRow key={i}>
                  <TableCell>{new Date(a.timestamp).toLocaleString()}</TableCell>
                  <TableCell><Chip label={a.type} size="small" /></TableCell>
                  <TableCell>{(a.tokens / 1_000).toFixed(1)}K</TableCell>
                  <TableCell>{a.model || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </PageWrapper>
    </Box>
  )
}
