import { type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Box, Drawer, List, ListItemButton, ListItemIcon, ListItemText,
  AppBar, Toolbar, Typography, IconButton, Menu, MenuItem, Chip, Select,
} from '@mui/material'
import { Dashboard as DashboardIcon, People, Policy, Person, Logout, AttachMoney, Memory, Settings as SettingsIcon } from '@mui/icons-material'
import { useState } from 'react'
import { useRole, setDevRole } from '../hooks/useRole'
import { useUserInfo } from '../hooks/useUserInfo'

const DRAWER_WIDTH = 220
const DEV_MODE = !import.meta.env.VITE_OIDC_AUTHORITY || import.meta.env.VITE_SKIP_AUTH === '1'

export function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { isAdmin } = useRole()
  const { email, logout } = useUserInfo()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)

  const navItems = [
    ...(isAdmin ? [
      { path: '/', label: 'Dashboard', icon: <DashboardIcon /> },
      { path: '/users', label: 'Users', icon: <People /> },
      { path: '/quotas', label: 'Quotas', icon: <Policy /> },
      { path: '/billing', label: 'Billing', icon: <AttachMoney /> },
      { path: '/models', label: 'Models', icon: <Memory /> },
      { path: '/settings', label: 'Settings', icon: <SettingsIcon /> },
    ] : []),
    { path: '/me', label: 'My Usage', icon: <Person /> },
  ]

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar>
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>AllCode Nexus</Typography>
          {DEV_MODE && (
            <Select
              size="small"
              value={isAdmin ? 'admin' : 'user'}
              onChange={(e) => setDevRole(e.target.value as 'admin' | 'user')}
              sx={{ mr: 2, minWidth: 100, fontSize: '0.8rem' }}
            >
              <MenuItem value="admin">Admin</MenuItem>
              <MenuItem value="user">User</MenuItem>
            </Select>
          )}
          {isAdmin && <Chip label="Admin" size="small" color="error" sx={{ mr: 2 }} />}
          <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} color="inherit">
            <Person />
          </IconButton>
          <Menu anchorEl={anchorEl} open={!!anchorEl} onClose={() => setAnchorEl(null)}>
            <MenuItem disabled>{email}</MenuItem>
            <MenuItem onClick={() => { logout(); setAnchorEl(null) }}>
              <Logout fontSize="small" sx={{ mr: 1 }} /> Logout
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      <Drawer variant="permanent" sx={{
        width: DRAWER_WIDTH,
        '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' },
      }}>
        <Toolbar />
        <List>
          {navItems.map(({ path, label, icon }) => (
            <ListItemButton key={path} selected={path === '/' ? location.pathname === '/' : location.pathname.startsWith(path)} onClick={() => navigate(path)}>
              <ListItemIcon>{icon}</ListItemIcon>
              <ListItemText primary={label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, p: 3, mt: 8 }}>
        {children}
      </Box>
    </Box>
  )
}
