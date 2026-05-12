import { type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Box, Drawer, List, ListItemButton, ListItemIcon, ListItemText,
  AppBar, Toolbar, Typography, IconButton, Menu, MenuItem,
} from '@mui/material'
import { Dashboard as DashboardIcon, People, Policy, Person, Logout } from '@mui/icons-material'
import { useState } from 'react'

const DRAWER_WIDTH = 220

const navItems = [
  { path: '/', label: 'Dashboard', icon: <DashboardIcon /> },
  { path: '/users', label: 'Users', icon: <People /> },
  { path: '/quotas', label: 'Quotas', icon: <Policy /> },
  { path: '/me', label: 'My Usage', icon: <Person /> },
]

export function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1, bgcolor: 'background.paper' }}>
        <Toolbar>
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>AllCode Nexus</Typography>
          <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} color="inherit">
            <Person />
          </IconButton>
          <Menu anchorEl={anchorEl} open={!!anchorEl} onClose={() => setAnchorEl(null)}>
            <MenuItem disabled>dev@localhost</MenuItem>
            <MenuItem onClick={() => setAnchorEl(null)}>
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
            <ListItemButton key={path} selected={location.pathname === path} onClick={() => navigate(path)}>
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
