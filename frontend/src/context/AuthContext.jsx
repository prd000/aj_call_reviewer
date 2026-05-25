import { createContext, useContext, useEffect, useState } from 'react'
import {
  getSession,
  signInWithPassword,
  signOut,
  resetPasswordForEmail,
  onAuthStateChange,
} from '../lib/supabaseAuth'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import { getCurrentUserProfile } from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  useLoadingWatchdog(loading, setLoading, { timeoutMs: 10_000, label: 'auth-init' })

  async function loadProfile(activeSession) {
    if (!activeSession) {
      setUser(null)
      return
    }
    try {
      const profile = await getCurrentUserProfile()
      setUser({ id: activeSession.user.id, ...profile })
    } catch {
      setUser(null)
    }
  }

  useEffect(() => {
    getSession()
      .then(async ({ data: { session: s } }) => {
        setSession(s)
        await loadProfile(s)
      })
      .catch((err) => {
        console.error('Auth session check failed:', err)
      })
      .finally(() => {
        setLoading(false)
      })

    const { data: { subscription } } = onAuthStateChange(
      async (event, s) => {
        setSession(s)
        if (event === 'SIGNED_OUT') {
          setUser(null)
        } else if (s) {
          await loadProfile(s)
        }
      }
    )

    return () => subscription.unsubscribe()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function login(email, password) {
    const { data, error } = await signInWithPassword({ email, password })
    if (error) throw error
    const profile = await getCurrentUserProfile()
    setUser({ id: data.user.id, ...profile })
    setSession(data.session)
  }

  function logout() {
    setUser(null)
    setSession(null)
    signOut()
  }

  async function forgotPassword(email) {
    const { error } = await resetPasswordForEmail(email)
    if (error) throw error
  }

  return (
    <AuthContext.Provider value={{ user, session, loading, login, logout, forgotPassword }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
