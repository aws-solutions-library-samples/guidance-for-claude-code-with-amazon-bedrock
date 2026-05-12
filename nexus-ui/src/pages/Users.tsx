import { useQuery } from '@tanstack/react-query'
import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip,
} from '@mui/material'
import { PageWrapper } from '../components/PageWrapper'
import { useToken } from '../hooks/useToken'
import { api } from '../api/client'

export function Users() {
  const token = useToken()

  const { data, isLoading, error } = useQuery({
    queryKey: ['users'],
    queryFn: () => api.getUsers(token),
    enabled: !!token,
  })

  const users = data?.users ?? []

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Users</Typography>
      <PageWrapper isLoading={isLoading} error={error} isEmpty={users.length === 0} emptyMessage="No users have used Claude Code yet. Usage will appear here once developers start using it.">
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Email</TableCell>
                <TableCell>Monthly Tokens</TableCell>
                <TableCell>Last Active</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((user: { email: string; monthlyTokens: number; lastActive: string; status: string }) => (
                <TableRow key={user.email}>
                  <TableCell>{user.email}</TableCell>
                  <TableCell>{(user.monthlyTokens / 1_000_000).toFixed(1)}M</TableCell>
                  <TableCell>{new Date(user.lastActive).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <Chip label={user.status} size="small" color={user.status === 'active' ? 'success' : 'error'} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </PageWrapper>
    </Box>
  )
}
