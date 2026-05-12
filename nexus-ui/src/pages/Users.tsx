import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip,
} from '@mui/material'

const mockUsers = [
  { email: 'alice@company.com', monthlyTokens: 142_000_000, lastActive: '2026-05-12T10:30:00Z', status: 'active' },
  { email: 'bob@company.com', monthlyTokens: 98_000_000, lastActive: '2026-05-12T09:15:00Z', status: 'active' },
  { email: 'carol@company.com', monthlyTokens: 87_000_000, lastActive: '2026-05-11T16:45:00Z', status: 'active' },
  { email: 'dave@company.com', monthlyTokens: 65_000_000, lastActive: '2026-05-10T14:20:00Z', status: 'active' },
  { email: 'eve@company.com', monthlyTokens: 12_000_000, lastActive: '2026-05-08T11:00:00Z', status: 'blocked' },
]

export function Users() {
  return (
    <Box>
      <Typography variant="h5" gutterBottom>Users</Typography>

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
            {mockUsers.map((user) => (
              <TableRow key={user.email}>
                <TableCell>{user.email}</TableCell>
                <TableCell>{(user.monthlyTokens / 1_000_000).toFixed(1)}M</TableCell>
                <TableCell>{new Date(user.lastActive).toLocaleDateString()}</TableCell>
                <TableCell>
                  <Chip
                    label={user.status}
                    size="small"
                    color={user.status === 'active' ? 'success' : 'error'}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}
