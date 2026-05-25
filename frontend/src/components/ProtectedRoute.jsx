import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) return <div className="auth-loading"><span className="auth-loading__spinner" /></div>
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}
