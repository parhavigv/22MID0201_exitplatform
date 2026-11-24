import { createClient } from '@supabase/supabase-js'

/**
 * Browser Supabase client. Used for authentication only — all data access goes
 * through the FastAPI backend, so authorisation logic lives in one place rather
 * than being split between the client and the server.
 *
 * The anon key is public by design. RLS is what protects the data.
 */

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!url || !anonKey) {
  throw new Error(
    'VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are missing. ' +
      'Run: python backend/scripts/sync_frontend_env.py',
  )
}

export const supabase = createClient(url, anonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: false,
  },
})
