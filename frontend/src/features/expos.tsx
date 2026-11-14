import { formatTime, formatDate } from '../app/time'
import { useState, type FormEvent } from 'react'
import { CalendarDays, MapPin, Plus, Check } from 'lucide-react'
import { send } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, Empty, ErrorMessage, Field, Modal } from '../components/ui'

export function ExposPage() {
  const { expos, activeExpo, setExpo, refresh } = useLibrary()
  const toast = useToast()
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>()
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    const data = new FormData(event.currentTarget)
    try {
      await send('/expos', {
        name: data.get('name'),
        city: data.get('city'),
        venue: data.get('venue'),
        start_date: data.get('date') || null,
      })
      await refresh()
      setOpen(false)
      toast('Expo created.')
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Your expos</h1>
          <p className="muted">Give every connection a place in your story.</p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus size={18} />
          New expo
        </Button>
      </div>
      {expos.length ? (
        <div className="expo-grid">
          {expos.map((expo) => (
            <article className="panel expo-card" key={expo.id}>
              <div className="expo-card-top">
                <span className="icon-tile">
                  <CalendarDays size={23} />
                </span>
                {expo.id === activeExpo?.id && <Badge tone="green">Active expo</Badge>}
              </div>
              <h2>{expo.name}</h2>
              <p className="muted">
                <MapPin size={15} />
                {[expo.venue, expo.city].filter(Boolean).join(' · ') || 'Location not added'}
              </p>
              {expo.start_date && (
                <p className="caption">{formatDate(expo.start_date, { dateStyle: 'long' })}</p>
              )}
              <Button
                variant="secondary"
                onClick={() => {
                  void setExpo(expo.id)
                    .then(() => toast(`Adding to ${expo.name}`))
                    .catch((error) => toast(error.message))
                }}
                disabled={expo.id === activeExpo?.id}
              >
                {expo.id === activeExpo?.id ? (
                  <>
                    <Check size={16} />
                    Selected
                  </>
                ) : (
                  'Use this expo'
                )}
              </Button>
            </article>
          ))}
        </div>
      ) : (
        <Empty
          title="Where did you make a connection?"
          description="Create an expo, then start collecting cards and brochures."
          action={<Button onClick={() => setOpen(true)}>Create your first expo</Button>}
        />
      )}
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="A new expo"
        description="A name is all you need to get started."
      >
        <form onSubmit={submit}>
          <Field label="Expo name">
            <input name="name" required maxLength={200} placeholder="e.g. Solar Expo 2026" />
          </Field>
          <div className="form-grid">
            <Field label="City">
              <input name="city" maxLength={200} />
            </Field>
            <Field label="Start date">
              <input name="date" type="date" />
            </Field>
          </div>
          <Field label="Venue">
            <input name="venue" maxLength={300} />
          </Field>
          <ErrorMessage error={error} />
          <div className="form-actions">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? 'Creating…' : 'Create expo'}
            </Button>
          </div>
        </form>
      </Modal>
    </>
  )
}
