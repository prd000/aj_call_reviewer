import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function BdsRepRoute() {
  const { user } = useAuth()
  if (!user || user.role !== 'bds_rep') return <Navigate to="/" replace />
  return <Outlet />
}
