import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { getCurrentUserProfile } from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

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
    supabase.auth.getSession().then(async ({ data: { session: s } }) => {
      setSession(s)
      await loadProfile(s)
      setLoading(false)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
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
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
    const profile = await getCurrentUserProfile()
    setUser({ id: data.user.id, ...profile })
    setSession(data.session)
  }

  async function logout() {
    await supabase.auth.signOut()
    setUser(null)
    setSession(null)
  }

  async function forgotPassword(email) {
    const { error } = await supabase.auth.resetPasswordForEmail(email)
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
