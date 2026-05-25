import { supabase } from './supabase'

const AUTH_TIMEOUT_MS = 8000

function withTimeout(promise, ms, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms)
    ),
  ])
}

export async function getSession() {
  try {
    return await withTimeout(supabase.auth.getSession(), AUTH_TIMEOUT_MS, 'getSession')
  } catch (e) {
    console.error('[supabaseAuth] getSession failed:', e)
    return { data: { session: null } }
  }
}

export async function signInWithPassword(credentials) {
  return withTimeout(
    supabase.auth.signInWithPassword(credentials),
    AUTH_TIMEOUT_MS,
    'signInWithPassword'
  )
}

// Fire-and-forget: callers must clear local state synchronously.
// supabase-js holds an internal lock during signOut; if the network call hangs,
// awaiting this would block the caller indefinitely.
export function signOut() {
  withTimeout(supabase.auth.signOut(), AUTH_TIMEOUT_MS, 'signOut').catch((e) => {
    console.error('[supabaseAuth] signOut failed:', e)
  })
}

export async function resetPasswordForEmail(email) {
  return withTimeout(
    supabase.auth.resetPasswordForEmail(email),
    AUTH_TIMEOUT_MS,
    'resetPasswordForEmail'
  )
}

// Pass-through; subscription model can't be wrapped meaningfully.
export function onAuthStateChange(callback) {
  return supabase.auth.onAuthStateChange(callback)
}
