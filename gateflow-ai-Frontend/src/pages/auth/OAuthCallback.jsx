/**
 * OAuthCallback.jsx — Handles the redirect from the backend after Google OAuth.
 *
 * The backend redirects here with:
 *   /auth/callback?access_token=...&refresh_token=...&role=...
 *
 * This page:
 *  1. Reads the tokens from the URL query string
 *  2. Fetches the user profile from /auth/me using the access token
 *  3. Hydrates the auth store (same shape as email/password login)
 *  4. Redirects to the correct dashboard based on role
 *  5. On any error, redirects to /login?error=oauth_failed
 */

import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { env } from '@/config/env'

const ROLE_HOME = {
  ORGANIZER:         '/dashboard',
  RESIDENT:          '/dashboard',
  GUARD:             '/guard/dashboard',
  RESIDENTIAL_GUARD: '/guard/dashboard',
  ADMIN:             '/dashboard',
}

export default function OAuthCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { login } = useAuthStore()
  const handled = useRef(false) // prevent double-run in React StrictMode

  useEffect(() => {
    if (handled.current) return
    handled.current = true

    const accessToken  = searchParams.get('access_token')
    const refreshToken = searchParams.get('refresh_token')
    const role         = searchParams.get('role')

    // If the backend sent an error flag instead of tokens
    if (searchParams.get('error') || !accessToken || !refreshToken || !role) {
      navigate('/login?error=oauth_failed', { replace: true })
      return
    }

    // Fetch the user profile so we have the full user object for the store
    fetch(`${env.API_BASE_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error('Profile fetch failed')
        return res.json()
      })
      .then((user) => {
        login(
          { ...user, role: user.role ?? role },
          accessToken,
          refreshToken,
        )
        navigate(ROLE_HOME[user.role ?? role] ?? '/dashboard', { replace: true })
      })
      .catch(() => {
        navigate('/login?error=oauth_failed', { replace: true })
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-screen items-center justify-center bg-gray-950">
      <div className="flex flex-col items-center gap-4">
        <div
          className="h-10 w-10 animate-spin rounded-full border-4 border-blue-500 border-t-transparent"
          aria-label="Completing sign-in…"
        />
        <p className="text-sm text-slate-400">Completing sign-in…</p>
      </div>
    </div>
  )
}
