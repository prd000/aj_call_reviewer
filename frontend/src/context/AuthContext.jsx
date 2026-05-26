import { createContext, useContext, useEffect, useState } from 'react'
import {
  getSession,
  signInWithPassword,
  signOut,
  resetPasswordForEmail,
  onAuthStateChange,
} from '../lib/supabaseAuth'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import { getCurrentUserProfile, NoSessionError, SessionUnavailableError } from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  useLoadingWatchdog(loading, setLoading, { timeoutMs: 20_000, label: 'auth-init' })

  async function loadProfile(activeSession) {
    if (!activeSession) {
      setUser(null)
      return
    }
    try {
      const profile = await getCurrentUserProfile(activeSession.access_token)
      setUser({ id: activeSession.user.id, ...profile })
    } catch (err) {
      // SessionUnavailableError = transient Supabase failure — preserve existing user state.
      if (err instanceof SessionUnavailableError) {
        console.warn('loadProfile: transient session-check failure — preserving user state')
        return
      }
      // NoSessionError = Supabase confirmed no session; 401 = backend confirmed token invalid.
      if (err instanceof NoSessionError) { setUser(null); return }
      if (err?.message === 'Session expired. Please log in again.') { setUser(null); return }
      console.error('loadProfile failed (transient):', err)
    }
  }

  useEffect(() => {
    getSession()
      .then(async ({ data: { session: s } }) => {
        setSession(s)
        await loadProfile(s)
      })
      .catch((err) => {
        if (err instanceof SessionUnavailableError) {
          console.warn('Initial getSession transient failure — user can retry')
        } else {
          console.error('Auth session check failed:', err)
        }
      })
      .finally(() => {
        setLoading(false)
      })

    const { data: { subscription } } = onAuthStateChange(
      async (event, s) => {
        setSession(s)
        if (event === 'SIGNED_OUT') {
          try {
            const { data: { session: recheck } } = await getSession()
            if (!recheck) setUser(null)
          } catch (err) {
            if (err instanceof SessionUnavailableError) {
              console.warn('SIGNED_OUT received but session re-check failed transiently; preserving user')
            } else {
              setUser(null)
            }
          }
          return
        }
        // Only fetch the profile when the identity actually changes. TOKEN_REFRESHED
        // and USER_UPDATED fire on a cadence (every ~hour for token refresh, plus
        // tab-visibility events) and the profile hasn't changed — re-fetching on
        // every event multiplies background `/me` traffic and means any transient
        // backend hiccup during idle has many chances to force a logout.
        if (s && (event === 'SIGNED_IN' || event === 'INITIAL_SESSION')) {
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
    const profile = await getCurrentUserProfile(data.session.access_token)
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
