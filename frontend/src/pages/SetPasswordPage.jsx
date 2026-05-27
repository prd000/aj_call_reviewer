import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { updateUser } from '../lib/supabaseAuth'
import { markPasswordSet } from '../services/api'
import './LoginPage.css'
import './SetPasswordPage.css'

export default function SetPasswordPage() {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const { session, loading, refreshUser } = useAuth()
  const navigate = useNavigate()

  if (loading) return <div className="auth-loading"><span className="auth-loading__spinner" /></div>

  if (!session) {
    return (
      <div className="set-password-page">
        <div className="login-card">
          <div className="login-page__brand">Call Reviewer</div>
          <h1 className="login-card__title">Link expired</h1>
          <p className="login-card__subtitle">
            This invite link is invalid or has already been used.
          </p>
          <button className="login-form__forgot" onClick={() => navigate('/login')}>
            Go to login
          </button>
        </div>
      </div>
    )
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setIsLoading(true)
    try {
      const { error: updateError } = await updateUser({ password })
      if (updateError) throw updateError
      try {
        await markPasswordSet()
        await refreshUser()
      } catch (markErr) {
        // The Supabase password write succeeded — don't block redirect on a
        // profile-flag failure. Next /users/me fetch will catch the user up.
        console.warn('markPasswordSet failed; continuing:', markErr)
      }
      setSuccess(true)
      setTimeout(() => navigate('/'), 1500)
    } catch (err) {
      setError(err.message || 'Failed to set password. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="set-password-page">
      <div className="login-card">
        <div className="login-page__brand">Call Reviewer</div>
        <h1 className="login-card__title">Set your password</h1>
        <p className="login-card__subtitle">Choose a password to complete your account setup.</p>

        {error && <span className="upload-form__error login-card__error">{error}</span>}
        {success && <p className="login-form__success">Password set! Redirecting…</p>}

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-form__field">
            <label htmlFor="sp-password" className="upload-form__label">New password</label>
            <input
              id="sp-password"
              type="password"
              className="upload-form__input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading || success}
              autoComplete="new-password"
            />
          </div>
          <div className="login-form__field">
            <label htmlFor="sp-confirm" className="upload-form__label">Confirm password</label>
            <input
              id="sp-confirm"
              type="password"
              className="upload-form__input"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={isLoading || success}
              autoComplete="new-password"
            />
          </div>
          <button
            type="submit"
            className="login-form__submit"
            disabled={isLoading || success}
          >
            {isLoading ? 'Setting password…' : 'Set Password'}
          </button>
        </form>
      </div>
    </div>
  )
}
