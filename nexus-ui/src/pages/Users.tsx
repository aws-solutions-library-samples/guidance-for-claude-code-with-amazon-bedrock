import { useAuth } from 'react-oidc-context'
import { useQuery } from '@tanstack/react-query'
import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip, Alert,
} from '@mui/material'
import { api } from '../api/client'

export function Users() {
  const auth = useAuth()
  const token = auth.user?.access_token || ''

  const { data, isLoading, error } = useQuery({
    queryKey: ['users'],
    queryFn: () => api.getUsers(token),
    enabled: !!token,
  })

  if (isLoading) return <Typography>Loading...</Typography>
  if (error) return <Alert severity="info">✓ API connection works — currently no user data available.</Alert>

  const users = data?.users ?? []

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Users</Typography>
      {users.length === 0 ? (
        <Alert severity="success">✓ API connection works — no users have used Claude Code yet. Usage will appear here once developers start using it.</Alert>
      ) : (
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
      )}
    </Box>
  )
}
