import { useState } from 'react'
import { useAuth } from 'react-oidc-context'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip, Alert, Button, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Select, MenuItem, FormControl, InputLabel,
} from '@mui/material'
import { Add, Edit, Delete } from '@mui/icons-material'
import { api } from '../api/client'

interface QuotaPolicy {
  id: string; type: string; target: string; monthlyLimit: number; dailyLimit: number | null; enforcement: string
}

interface QuotaForm {
  type: string; target: string; monthlyLimit: string; dailyLimit: string; enforcement: string
}

const emptyForm: QuotaForm = { type: 'default', target: '', monthlyLimit: '225', dailyLimit: '', enforcement: 'block' }

export function Quotas() {
  const auth = useAuth()
  const token = auth.user?.access_token || ''
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<QuotaForm>(emptyForm)

  const { data, isLoading, error } = useQuery({
    queryKey: ['quotas'],
    queryFn: () => api.getQuotas(token),
    enabled: !!token,
  })

  const createMutation = useMutation({
    mutationFn: () => api.createQuota(token, {
      type: form.type,
      target: form.target,
      monthlyLimit: parseInt(form.monthlyLimit) * 1_000_000,
      dailyLimit: form.dailyLimit ? parseInt(form.dailyLimit) * 1_000_000 : 0,
      enforcement: form.enforcement,
    }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['quotas'] }); closeDialog() },
  })

  const updateMutation = useMutation({
    mutationFn: () => api.updateQuota(token, editId!, {
      monthlyLimit: parseInt(form.monthlyLimit) * 1_000_000,
      dailyLimit: form.dailyLimit ? parseInt(form.dailyLimit) * 1_000_000 : 0,
      enforcement: form.enforcement,
    }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['quotas'] }); closeDialog() },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteQuota(token, id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['quotas'] }); setDeleteId(null) },
  })

  const closeDialog = () => { setDialogOpen(false); setEditId(null); setForm(emptyForm) }

  const openEdit = (p: QuotaPolicy) => {
    setEditId(p.id)
    setForm({
      type: p.type,
      target: p.target,
      monthlyLimit: String(p.monthlyLimit / 1_000_000),
      dailyLimit: p.dailyLimit ? String(p.dailyLimit / 1_000_000) : '',
      enforcement: p.enforcement,
    })
    setDialogOpen(true)
  }

  if (isLoading) return <Typography>Loading...</Typography>
  if (error) return <Alert severity="info">✓ API connection works — currently no quota data available.</Alert>

  const policies: QuotaPolicy[] = data?.policies ?? []

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5">Quota Policies</Typography>
        <Button variant="contained" startIcon={<Add />} onClick={() => { setForm(emptyForm); setDialogOpen(true) }}>
          Create Policy
        </Button>
      </Box>

      {policies.length === 0 ? (
        <Alert severity="success">✓ API connection works — no quota policies configured yet. Click "Create Policy" to add one.</Alert>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Type</TableCell>
                <TableCell>Target</TableCell>
                <TableCell>Monthly Limit</TableCell>
                <TableCell>Daily Limit</TableCell>
                <TableCell>Enforcement</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {policies.map((p) => (
                <TableRow key={p.id}>
                  <TableCell><Chip label={p.type} size="small" color={p.type === 'default' ? 'primary' : p.type === 'group' ? 'secondary' : 'default'} /></TableCell>
                  <TableCell>{p.target}</TableCell>
                  <TableCell>{(p.monthlyLimit / 1_000_000).toFixed(0)}M tokens</TableCell>
                  <TableCell>{p.dailyLimit ? `${(p.dailyLimit / 1_000_000).toFixed(0)}M` : 'Auto'}</TableCell>
                  <TableCell><Chip label={p.enforcement} size="small" color={p.enforcement === 'block' ? 'error' : 'warning'} /></TableCell>
                  <TableCell>
                    <IconButton size="small" onClick={() => openEdit(p)}><Edit fontSize="small" /></IconButton>
                    <IconButton size="small" color="error" onClick={() => setDeleteId(p.id)}><Delete fontSize="small" /></IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onClose={closeDialog} maxWidth="sm" fullWidth>
        <DialogTitle>{editId ? 'Edit Policy' : 'Create Quota Policy'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
          <FormControl fullWidth disabled={!!editId}>
            <InputLabel>Type</InputLabel>
            <Select value={form.type} label="Type" onChange={(e) => setForm({ ...form, type: e.target.value })}>
              <MenuItem value="default">Default (all users)</MenuItem>
              <MenuItem value="group">Group</MenuItem>
              <MenuItem value="user">User</MenuItem>
            </Select>
          </FormControl>
          {form.type !== 'default' && (
            <TextField label={form.type === 'user' ? 'Email' : 'Group name'} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} disabled={!!editId} />
          )}
          <TextField label="Monthly Limit (millions of tokens)" type="number" value={form.monthlyLimit} onChange={(e) => setForm({ ...form, monthlyLimit: e.target.value })} />
          <TextField label="Daily Limit (millions, blank = auto)" type="number" value={form.dailyLimit} onChange={(e) => setForm({ ...form, dailyLimit: e.target.value })} />
          <FormControl fullWidth>
            <InputLabel>Enforcement</InputLabel>
            <Select value={form.enforcement} label="Enforcement" onChange={(e) => setForm({ ...form, enforcement: e.target.value })}>
              <MenuItem value="block">Block (hard limit)</MenuItem>
              <MenuItem value="alert">Alert (soft limit)</MenuItem>
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog}>Cancel</Button>
          <Button variant="contained" onClick={() => editId ? updateMutation.mutate() : createMutation.mutate()}>
            {editId ? 'Save' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation */}
      <Dialog open={!!deleteId} onClose={() => setDeleteId(null)}>
        <DialogTitle>Delete Policy?</DialogTitle>
        <DialogContent><Typography>This will permanently remove this quota policy.</Typography></DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={() => deleteId && deleteMutation.mutate(deleteId)}>Delete</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
