import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './LoginPage.css'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [forgotSent, setForgotSent] = useState(false)
  const { login, forgotPassword, user, loading } = useAuth()
  const navigate = useNavigate()

  if (loading) return null
  if (user) return <Navigate to="/" replace />

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setIsLoading(true)
    try {
      await login(email, password)
      navigate('/')
    } catch (err) {
      setError(err.message || 'Login failed. Please check your credentials.')
    } finally {
      setIsLoading(false)
    }
  }

  async function handleForgot() {
    if (!email) {
      setError('Enter your email address above first.')
      return
    }
    setError(null)
    try {
      await forgotPassword(email)
      setForgotSent(true)
    } catch (err) {
      setError(err.message || 'Failed to send reset email.')
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-page__brand">Call Reviewer</div>
        <h1 className="login-card__title">Sign in</h1>
        <p className="login-card__subtitle">Enter your credentials to continue.</p>

        {error && <span className="upload-form__error login-card__error">{error}</span>}

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-form__field">
            <label htmlFor="login-email" className="upload-form__label">Email</label>
            <input
              id="login-email"
              type="email"
              className="upload-form__input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
              autoComplete="email"
            />
          </div>
          <div className="login-form__field">
            <label htmlFor="login-password" className="upload-form__label">Password</label>
            <input
              id="login-password"
              type="password"
              className="upload-form__input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              autoComplete="current-password"
            />
          </div>
          <button type="submit" className="login-form__submit" disabled={isLoading}>
            {isLoading ? 'Signing in…' : 'Sign In'}
          </button>
          {forgotSent ? (
            <p className="login-form__success">Password reset email sent. Check your inbox.</p>
          ) : (
            <button type="button" className="login-form__forgot" onClick={handleForgot}>
              Forgot password?
            </button>
          )}
        </form>
      </div>
    </div>
  )
}
