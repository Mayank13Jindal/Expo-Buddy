import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, LibraryBig } from 'lucide-react'
import { api, send } from '../api/client'
import { Button, ErrorMessage, Field, Loading } from '../components/ui'

export function AuthPage({ onSignedIn }: { onSignedIn: () => void }) {
  const status = useQuery({ queryKey: ['account-status'], queryFn: () => api<{ setup_required: boolean }>('/auth/status'), retry: false })
  const queryClient = useQueryClient()
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const setup = status.data?.setup_required
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(undefined)
    try { await send(`/auth/${setup ? 'setup' : 'login'}`, { password }); queryClient.clear(); onSignedIn() }
    catch (error) { setError(error) } finally { setBusy(false) }
  }
  return <div className="auth-layout"><div className="auth-story"><div className="brand"><LibraryBig /> expo<span>library</span></div><div><h1>Every card.<br />Every possibility.</h1><p>Your expos, people, and product discoveries.<br />Collected in one quiet place.</p></div><small>Your library. On your server.</small></div><main className="auth-form"><div className="auth-card">{status.isPending ? <Loading /> : <><h2>{setup ? 'Make yourself at home.' : 'Open your library.'}</h2><p className="muted">{setup ? 'Choose a password for your personal collection.' : 'Sign in to pick up where you left off.'}</p><form onSubmit={submit}><Field label="Password" hint="Use at least 8 characters."><input type="password" autoComplete={setup ? 'new-password' : 'current-password'} required minLength={8} maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></Field><ErrorMessage error={error ?? status.error} /><Button type="submit" disabled={busy}>{busy ? 'Opening…' : setup ? 'Create my library' : 'Sign in'}<ArrowRight size={17} /></Button></form><p className="caption">{setup ? 'One account. All your devices.' : 'Forgot your password? Reset it from your server with make reset-password.'}</p></>}</div></main></div>
}

