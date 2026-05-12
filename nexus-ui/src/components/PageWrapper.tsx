import { type ReactNode } from 'react'
import { Box, CircularProgress, Alert, Typography } from '@mui/material'

interface PageWrapperProps {
  isLoading?: boolean
  error?: Error | null
  isEmpty?: boolean
  emptyMessage?: string
  children: ReactNode
}

export function PageWrapper({ isLoading, error, isEmpty, emptyMessage, children }: PageWrapperProps) {
  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', py: 8, gap: 2 }}>
        <CircularProgress color="primary" />
        <Typography color="text.secondary">Loading...</Typography>
      </Box>
    )
  }

  if (error) {
    return <Alert severity="warning" sx={{ mt: 2 }}>Unable to load data. Please try again later.</Alert>
  }

  if (isEmpty) {
    return <Alert severity="success" sx={{ mt: 2 }}>✓ Connected — {emptyMessage || 'No data available yet.'}</Alert>
  }

  return <>{children}</>
}
