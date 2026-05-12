import { type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useRole } from '../hooks/useRole'

export function AdminRoute({ children }: { children: ReactNode }) {
  const { isAdmin } = useRole()
  if (!isAdmin) return <Navigate to="/me" />
  return <>{children}</>
}
