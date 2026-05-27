import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) return <div className="auth-loading"><span className="auth-loading__spinner" /></div>
  if (!user) return <Navigate to="/login" replace />
  // Force any platform user who hasn't yet chosen their own password through
  // /set-password, regardless of how they landed in the app (invite redirect,
  // direct nav, restored session). Defensive against the Supabase invite
  // redirect_to silently falling back to the Site URL.
  if (user.has_set_password === false) return <Navigate to="/set-password" replace />
  return <Outlet />
}
