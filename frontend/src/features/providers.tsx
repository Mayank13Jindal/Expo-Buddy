import { QueryStatus } from '../components/ui/query-status'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Cloud, RefreshCw } from 'lucide-react'
import { api, send } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, ErrorMessage, Field, Modal } from '../components/ui'

type Model = { id: string; name: string; digest?: string }
type Provider = {
  provider: string
  enabled: boolean
  order: number
  model: string
  base_url: string
  has_secret: boolean
  state: string
  spent: string
  spending_cap: string
  remote: boolean
  timeout_seconds: number
  pinned_digest: string
  active_account?: string
  accounts: { id: string; label: string; connected: boolean; plan_enabled: boolean }[]
}
export function ProviderSettings() {
  const dirty = useRef(false)
  const query = useQuery({
    queryKey: ['providers'],
    queryFn: () => api<{ providers: Provider[]; cloud_fallback: boolean }>('/settings/providers'),
    retry: false,
    refetchInterval: 10000,
  })
  const [cloud, setCloud] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(),
    [connect, setConnect] = useState(false)
  const [enabled, setEnabled] = useState<Record<string, boolean>>({})
  const [signingIn, setSigningIn] = useState(false),
    [authorizationUrl, setAuthorizationUrl] = useState('')
  const signIn = useQuery({
    queryKey: ['chatgpt-sign-in'],
    queryFn: () => api<{ state: string; message: string }>('/settings/providers/chatgpt/sign-in'),
    refetchInterval: signingIn ? 2000 : false,
  })
  const [models, setModels] = useState<Record<string, Model[]>>({}),
    [chosen, setChosen] = useState<Record<string, string>>({}),
    [pins, setPins] = useState<Record<string, string>>({})
  const { refresh } = useLibrary(),
    toast = useToast()
  useEffect(() => {
    if (query.data && !dirty.current) {
      setCloud(query.data.cloud_fallback)
      setEnabled(Object.fromEntries(query.data.providers.map((row) => [row.provider, row.enabled])))
      setChosen(Object.fromEntries(query.data.providers.map((row) => [row.provider, row.model])))
      setPins(
        Object.fromEntries(query.data.providers.map((row) => [row.provider, row.pinned_digest])),
      )
    }
  }, [query.data])
  useEffect(() => {
    if (!signIn.data) return
    if (!signingIn && signIn.data.state === 'waiting') {
      setSigningIn(true)
      return
    }
    if (!signingIn) return
    if (signIn.data.state === 'connected') {
      setSigningIn(false)
      setAuthorizationUrl('')
      void refresh()
      toast(signIn.data.message)
    }
    if (signIn.data.state === 'idle') {
      setSigningIn(false)
      setAuthorizationUrl('')
      return
    }
    if (signIn.data.state === 'failed') {
      setSigningIn(false)
      setAuthorizationUrl('')
      setError(new Error(signIn.data.message || 'The sign-in session ended. Start a new attempt.'))
    }
  }, [signingIn, signIn.data, refresh, toast])
  const startSignIn = async (newAccount = false) => {
    const popup = window.open('about:blank', '_blank')
    setBusy(true)
    setError(undefined)
    try {
      const value = await send<{ authorization_url: string }>(
        `/settings/providers/chatgpt/sign-in?new_account=${newAccount}`,
        {},
      )
      setAuthorizationUrl(value.authorization_url)
      await signIn.refetch()
      setSigningIn(true)
      if (popup) {
        popup.opener = null
        popup.location.href = value.authorization_url
      }
    } catch (error) {
      popup?.close()
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  const run = async (task: () => Promise<unknown>) => {
    setBusy(true)
    setError(undefined)
    try {
      await task()
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    await run(async () => {
      await send(
        '/settings/providers',
        {
          cloud_fallback: cloud,
          providers: query.data?.providers.map((row) => ({
            provider: row.provider,
            enabled: enabled[row.provider] ?? row.enabled,
            model: chosen[row.provider] ?? row.model,
            pinned_digest: pins[row.provider] ?? '',
            base_url: data.get(`${row.provider}-url`) || null,
            secret: data.get(`${row.provider}-secret`) || null,
            spending_cap: Number(data.get(`${row.provider}-cap`) || 0),
            timeout_seconds: Number(data.get(`${row.provider}-timeout`) || 600),
          })),
        },
        'PUT',
      )
      dirty.current = false
      await refresh()
      toast('Connection and model choices saved.')
    })
  }
  const load = (name: string) =>
    run(async () => {
      const result = await api<{ models: Model[] }>(`/settings/providers/${name}/models`)
      setModels((value) => ({ ...value, [name]: result.models }))
      toast('Available models loaded.')
    })
  if (query.isPending || query.isError)
    return (
      <section className="panel" aria-label="AI connections">
        <h2>AI connections & models</h2>
        <QueryStatus query={query} label="AI connections" />
      </section>
    )
  return (
    <section className="panel provider-settings" id="ai">
      <div className="panel-heading">
        <div>
          <h2>AI connections & models</h2>
          <p>Choose where card processing runs. Your selected model stays saved.</p>
        </div>
        <Cloud size={19} />
      </div>
      <form
        onSubmit={save}
        onChangeCapture={() => {
          dirty.current = true
        }}
      >
        <label className="checkbox-label cloud-choice">
          <input
            type="checkbox"
            checked={cloud}
            onChange={(event) => setCloud(event.target.checked)}
          />
          Allow cloud processing with my connected providers
        </label>
        <p className="caption">
          Printed text and the note explicitly added at capture/reprocessing can be sent. Existing
          personal notes stay private. Optional image checks use local Ollama only.
        </p>
        <div className="provider-grid">
          {query.data?.providers.map((row) => {
            const account = row.accounts?.find((item) => item.id === row.active_account)
            return (
              <div className="provider-card" key={row.provider}>
                <div className="panel-heading">
                  <h3>
                    {row.order}.{' '}
                    {row.provider === 'chatgpt'
                      ? 'ChatGPT plan'
                      : row.provider === 'ollama'
                        ? 'Local Ollama'
                        : 'OpenRouter'}
                  </h3>
                  <Badge
                    tone={
                      (row.provider === 'chatgpt' ? account?.connected : row.state === 'online')
                        ? 'green'
                        : ''
                    }
                  >
                    {row.provider === 'chatgpt'
                      ? account?.connected
                        ? account.plan_enabled
                          ? 'Connected'
                          : 'Permission needed'
                        : 'Signed out'
                      : row.state.replaceAll('_', ' ')}
                  </Badge>
                </div>
                {row.provider === 'chatgpt' && (
                  <>
                    <p>
                      {account?.connected
                        ? `Account connected. Card processing is ${row.enabled && cloud ? 'enabled' : 'off'}.`
                        : 'Sign in to connect your ChatGPT plan. Signing out keeps your saved model choice.'}
                    </p>
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={busy || signingIn}
                      data-oai-siwc-button
                      onClick={() => {
                        void startSignIn()
                      }}
                    >
                      {signingIn
                        ? 'Waiting for OpenAI…'
                        : account?.connected
                          ? 'Sign in again'
                          : 'Sign in on server PC'}
                    </Button>
                    <p className="caption">
                      Use this button in a browser on the computer running Expo Buddy. On another
                      computer, use the protected helper below.
                    </p>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => {
                        setError(undefined)
                        setConnect(true)
                      }}
                    >
                      Connect from another PC
                    </Button>
                    {signingIn && (
                      <p role="status">
                        Complete OpenAI sign-in in the other tab.{' '}
                        {authorizationUrl && (
                          <a
                            className="text-button"
                            href={authorizationUrl}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open OpenAI sign-in
                          </a>
                        )}
                        <Button
                          type="button"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => {
                            void run(async () => {
                              await api('/settings/providers/chatgpt/sign-in', { method: 'DELETE' })
                              await signIn.refetch()
                            })
                          }}
                        >
                          Cancel sign-in
                        </Button>
                      </p>
                    )}
                    {row.accounts?.length > 0 && (
                      <>
                        <Field label="ChatGPT account">
                          <select
                            value={row.active_account ?? ''}
                            onChange={(event) => {
                              void run(async () => {
                                await send('/settings/providers/chatgpt/account', {
                                  account_id: event.target.value,
                                })
                                setModels((value) => ({ ...value, chatgpt: [] }))
                                await refresh()
                              })
                            }}
                          >
                            {row.accounts.map((account) => (
                              <option key={account.id} value={account.id}>
                                {account.label} · {account.id.slice(0, 6)} ·{' '}
                                {account.connected
                                  ? account.plan_enabled
                                    ? 'plan enabled'
                                    : 'permission needed'
                                  : 'signed out'}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <a
                          className="text-button"
                          href="https://chatgpt.com/settings/usage"
                          target="_blank"
                          rel="noreferrer"
                        >
                          Manage ChatGPT usage ↗
                        </a>
                        <Button
                          type="button"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => {
                            void startSignIn(true)
                          }}
                        >
                          Use another ChatGPT account
                        </Button>
                        {account?.connected && (
                          <Button
                            type="button"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => {
                              void run(async () => {
                                const value = await send<{ remote_revocation_confirmed: boolean }>(
                                  '/settings/providers/chatgpt/disconnect',
                                  {},
                                )
                                await refresh()
                                toast(
                                  value.remote_revocation_confirmed
                                    ? 'ChatGPT signed out.'
                                    : 'Signed out locally. Remote revocation was not confirmed; disconnect in ChatGPT Settings too.',
                                )
                              })
                            }}
                          >
                            Sign out of ChatGPT
                          </Button>
                        )}
                      </>
                    )}
                  </>
                )}
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    name={`${row.provider}-enabled`}
                    checked={enabled[row.provider] ?? row.enabled}
                    onChange={(event) =>
                      setEnabled((value) => ({ ...value, [row.provider]: event.target.checked }))
                    }
                  />
                  Use{' '}
                  {row.provider === 'chatgpt'
                    ? 'my ChatGPT plan'
                    : row.provider === 'ollama'
                      ? 'Ollama'
                      : 'OpenRouter'}
                </label>
                {row.provider === 'ollama' && (
                  <Field label="Ollama address">
                    <input
                      name="ollama-url"
                      type="url"
                      defaultValue={row.base_url}
                      placeholder="http://host.docker.internal:11434"
                    />
                  </Field>
                )}
                <Field
                  label={`${row.provider === 'chatgpt' ? 'ChatGPT model' : 'Exact model name'} (saved)`}
                >
                  <input
                    list={`${row.provider}-models`}
                    value={chosen[row.provider] ?? row.model}
                    onChange={(event) => {
                      setChosen((value) => ({ ...value, [row.provider]: event.target.value }))
                      setPins((value) => ({ ...value, [row.provider]: '' }))
                    }}
                    maxLength={200}
                    placeholder="Load models or enter an exact model ID"
                  />
                  <datalist id={`${row.provider}-models`}>
                    {models[row.provider]?.map((model) => (
                      <option value={model.id} key={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </datalist>
                </Field>
                {row.provider !== 'openrouter' && (
                  <Button
                    variant="ghost"
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      void load(row.provider)
                    }}
                  >
                    <RefreshCw size={14} />
                    Load available models
                  </Button>
                )}
                {models[row.provider]?.length ? (
                  <Field label="Choose an available model">
                    <select
                      value={chosen[row.provider] ?? ''}
                      onChange={(event) => {
                        const id = event.target.value
                        setChosen((value) => ({ ...value, [row.provider]: id }))
                        setPins((value) => ({
                          ...value,
                          [row.provider]:
                            models[row.provider].find((model) => model.id === id)?.digest ?? '',
                        }))
                      }}
                    >
                      <option value="">Choose…</option>
                      {models[row.provider].map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                ) : null}
                {row.provider === 'ollama' && (
                  <>
                    <Field label="Extraction timeout (seconds)">
                      <input
                        name="ollama-timeout"
                        type="number"
                        min={30}
                        max={1800}
                        defaultValue={row.timeout_seconds ?? 600}
                      />
                    </Field>
                    <p className="caption">
                      {pins.ollama
                        ? `Version pinned: ${pins.ollama.slice(0, 16)}… Processing stops if this tag changes.`
                        : 'Choose an installed model from the list to pin its digest.'}
                    </p>
                  </>
                )}
                {row.provider === 'openrouter' && (
                  <>
                    <Field
                      label="OpenRouter key"
                      hint={
                        row.has_secret ? 'Leave empty to keep the saved key.' : 'Stored encrypted.'
                      }
                    >
                      <input name="openrouter-secret" type="password" autoComplete="off" />
                    </Field>
                    <Field label="Monthly spending limit (USD)">
                      <input
                        name="openrouter-cap"
                        type="number"
                        min="0"
                        max="100000"
                        step="0.01"
                        defaultValue={row.spending_cap}
                      />
                    </Field>
                    <p className="caption">${Number(row.spent).toFixed(2)} used this month.</p>
                  </>
                )}
                <Button
                  variant="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    void run(async () => {
                      await send(`/settings/providers/${row.provider}/test`, {})
                      await refresh()
                      toast('Actual extraction test succeeded with the saved model.')
                    })
                  }}
                >
                  Test saved connection
                </Button>
              </div>
            )
          })}
        </div>
        <ErrorMessage error={connect ? undefined : (error ?? query.error)} />
        <div className="form-actions">
          <Button disabled={busy}>{busy ? 'Working…' : 'Save connections & models'}</Button>
        </div>
      </form>
      <Modal
        open={connect}
        onOpenChange={(value) => {
          setConnect(value)
          setError(undefined)
        }}
        title="Continue with ChatGPT"
        description="Complete OpenAI sign-in on your PC, then import the protected connection."
      >
        <ol className="connect-steps">
          <li>
            <a className="button secondary" href="/api/v1/settings/providers/chatgpt/helper">
              Download PC sign-in helper
            </a>
            <p>
              Extract the ZIP. Follow README.txt to install its Python dependencies, then run{' '}
              <code>python connect_helper.py</code>. Sign in only on OpenAI’s page. If it does not
              open, use the link printed by the helper on that same PC.
            </p>
            <a
              className="text-button"
              href="/api/v1/settings/providers/chatgpt/helper?new_account=true"
            >
              Use a different ChatGPT account
            </a>
          </li>
          <li>
            <Field label="Import protected connection file">
              <input
                type="file"
                accept=".expo,application/json"
                disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file)
                    void run(async () => {
                      if (file.size > 128000)
                        throw new Error(
                          'Choose the protected connection file created by the helper.',
                        )
                      const value = await send<{ plan_enabled: boolean }>(
                        '/settings/providers/chatgpt/import',
                        JSON.parse(await file.text()),
                      )
                      await refresh()
                      setConnect(false)
                      toast(
                        value.plan_enabled
                          ? 'ChatGPT connected. Load models, choose one, enable cloud processing, then test.'
                          : 'Signed in. Reconnect and grant ChatGPT plan usage to enable processing.',
                      )
                    })
                }}
              />
            </Field>
            <p>
              The file is encrypted for this server. Credentials stay encrypted and are excluded
              from backups. Delete the transfer file after import.
            </p>
          </li>
        </ol>
        <ErrorMessage error={error} />
        <p className="notice">
          OpenAI’s loopback callback reaches the computer running the browser, so server sign-in
          uses this helper. Transferred sessions do not support independent per-host revocation;
          disconnecting may revoke the shared session.
        </p>
      </Modal>
    </section>
  )
}
