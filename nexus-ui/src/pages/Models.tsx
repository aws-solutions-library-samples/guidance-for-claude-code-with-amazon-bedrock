import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Box, Card, CardContent, Grid, Typography, Alert, Chip, Button, Select, MenuItem, FormControl, InputLabel } from '@mui/material'
import { useToken } from '../hooks/useToken'
import { api } from '../api/client'

interface ModelConfig {
  selectedModel: string
  region: string
  crossRegionProfile: string
  availableModels: string[]
}

export function Models() {
  const token = useToken()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [selectedModel, setSelectedModel] = useState('')

  const { data, error } = useQuery<ModelConfig>({
    queryKey: ['models'],
    queryFn: () => api.getModels(token),
    enabled: !!token,
  })

  useEffect(() => {
    if (data?.selectedModel && !selectedModel) setSelectedModel(data.selectedModel)
  }, [data, selectedModel])

  const updateMutation = useMutation({
    mutationFn: () => api.updateModels(token, { selectedModel, region: data?.region, crossRegionProfile: data?.crossRegionProfile }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['models'] }); setEditing(false) },
  })

  if (error) {
    return (
      <Box>
        <Typography variant="h5" gutterBottom>Model & Region Configuration</Typography>
        <Alert severity="info">Model configuration will appear here once the API is connected.</Alert>
      </Box>
    )
  }

  const availableModels = data?.availableModels ?? []

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5">Model & Region Configuration</Typography>
        {!editing ? (
          <Button variant="outlined" onClick={() => { setSelectedModel(data?.selectedModel || ''); setEditing(true) }}>Edit</Button>
        ) : (
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button onClick={() => setEditing(false)}>Cancel</Button>
            <Button variant="contained" onClick={() => updateMutation.mutate()}>Save</Button>
          </Box>
        )}
      </Box>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 8 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Selected Model</Typography>
            {editing ? (
              <FormControl fullWidth>
                <InputLabel>Model</InputLabel>
                <Select value={selectedModel} label="Model" onChange={(e) => setSelectedModel(e.target.value)}>
                  {availableModels.map((m: string) => (
                    <MenuItem key={m} value={m}>{m}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            ) : (
              <Typography variant="h6">{data?.selectedModel ?? 'Loading...'}</Typography>
            )}
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 2 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Region</Typography>
            <Chip label={data?.region ?? '...'} />
          </CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 2 }}>
          <Card><CardContent>
            <Typography color="text.secondary" gutterBottom>Profile</Typography>
            <Chip label={data?.crossRegionProfile ?? '...'} color="primary" />
          </CardContent></Card>
        </Grid>
      </Grid>
    </Box>
  )
}
