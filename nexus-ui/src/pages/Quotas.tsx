import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip,
} from '@mui/material'

const mockPolicies = [
  { id: '1', type: 'default', target: 'All Users', monthlyLimit: 225_000_000, dailyLimit: null, enforcement: 'block' },
  { id: '2', type: 'group', target: 'engineering', monthlyLimit: 400_000_000, dailyLimit: 15_000_000, enforcement: 'alert' },
  { id: '3', type: 'user', target: 'alice@company.com', monthlyLimit: 500_000_000, dailyLimit: null, enforcement: 'block' },
]

export function Quotas() {
  return (
    <Box>
      <Typography variant="h5" gutterBottom>Quota Policies</Typography>
      <Typography color="text.secondary" gutterBottom>
        Read-only view of configured quota policies. Use the CLI to modify.
      </Typography>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Type</TableCell>
              <TableCell>Target</TableCell>
              <TableCell>Monthly Limit</TableCell>
              <TableCell>Daily Limit</TableCell>
              <TableCell>Enforcement</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {mockPolicies.map((p) => (
              <TableRow key={p.id}>
                <TableCell>
                  <Chip label={p.type} size="small" color={p.type === 'default' ? 'primary' : p.type === 'group' ? 'secondary' : 'default'} />
                </TableCell>
                <TableCell>{p.target}</TableCell>
                <TableCell>{(p.monthlyLimit / 1_000_000).toFixed(0)}M tokens</TableCell>
                <TableCell>{p.dailyLimit ? `${(p.dailyLimit / 1_000_000).toFixed(0)}M` : 'Auto'}</TableCell>
                <TableCell>
                  <Chip label={p.enforcement} size="small" color={p.enforcement === 'block' ? 'error' : 'warning'} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}
