import { createContext, useContext, useEffect, useState } from 'react'
import {
  getSession,
  refreshSession,
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
    let cancelled = false

    async function bootstrap() {
      async function attempt() {
        const { data: { session: s } } = await getSession()
        if (cancelled) return
        setSession(s)
        await loadProfile(s)
      }

      try {
        await attempt()
      } catch (err) {
        if (err instanceof SessionUnavailableError && !cancelled) {
          // One retry after a short delay for transient supabase-js unavailability
          // (e.g., in-flight token refresh holding the lock on cold start).
          console.warn('[auth] bootstrap getSession transient failure — retrying in 2s')
          await new Promise(r => setTimeout(r, 2000))
          if (!cancelled) {
            try {
              await attempt()
            } catch (retryErr) {
              if (!cancelled) {
                if (retryErr instanceof SessionUnavailableError) {
                  console.warn('[auth] bootstrap getSession persistently unavailable after retry')
                } else {
                  console.error('[auth] Auth session check failed on retry:', retryErr)
                }
              }
            }
          }
        } else if (!cancelled) {
          console.error('[auth] Auth session check failed:', err)
        }
      }

      if (!cancelled) setLoading(false)
    }

    bootstrap()

    const { data: { subscription } } = onAuthStateChange(
      async (event, s) => {
        setSession(s)
        if (event === 'SIGNED_OUT') {
          // supabase-js fires SIGNED_OUT when a background token refresh fails.
          // Attempt one explicit re-refresh before giving up — recovers from
          // transient network errors that caused the initial refresh to fail.
          console.warn('[auth] SIGNED_OUT event received — attempting session recovery')
          try {
            const { data } = await refreshSession()
            if (data?.session) {
              console.warn('[auth] SIGNED_OUT: session recovered via re-refresh — keeping user logged in')
              setSession(data.session)
              return
            }
          } catch {
            // SessionUnavailableError or no refresh token — recovery failed
          }
          // Recovery failed: verify the session is truly gone before clearing user.
          try {
            const { data: { session: recheck } } = await getSession()
            if (!recheck) {
              console.warn('[auth] SIGNED_OUT confirmed — clearing user state')
              setUser(null)
            }
          } catch (err) {
            if (err instanceof SessionUnavailableError) {
              console.warn('[auth] SIGNED_OUT re-check failed transiently; preserving user')
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

    return () => {
      cancelled = true
      subscription.unsubscribe()
    }
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

  async function refreshUser() {
    const { data: { session: s } } = await getSession()
    if (!s) return
    setSession(s)
    await loadProfile(s)
  }

  return (
    <AuthContext.Provider value={{ user, session, loading, login, logout, forgotPassword, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
