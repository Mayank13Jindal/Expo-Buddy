import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, send } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Button, ErrorMessage, Field, Modal } from '../components/ui'
import type { RemovalPreview } from '../api/types'
export function TrashActions({ id }: { id: string }) {
  const { refresh } = useLibrary(),
    toast = useToast(),
    [open, setOpen] = useState(false),
    [confirmation, setConfirmation] = useState(''),
    [error, setError] = useState<unknown>()
  const preview = useQuery({
    queryKey: ['removal-preview', id],
    enabled: open,
    queryFn: () => api<RemovalPreview>(`/documents/${id}/permanent-removal`),
  })
  return (
    <>
      <div className="button-row trash-actions">
        <Button
          variant="secondary"
          onClick={() => {
            void send(`/documents/${id}/restore`, {})
              .then(async () => {
                await refresh()
                toast('Document restored.')
              })
              .catch((error) => toast(error.message))
          }}
        >
          Restore
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            setOpen(true)
            setConfirmation('')
            setError(undefined)
          }}
        >
          Remove originals permanently
        </Button>
      </div>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Remove original files permanently?"
        description="This removes original files from the library drive. Record history is retained."
      >
        <p className="notice">
          {preview.data?.files ?? '…'} files · {((preview.data?.bytes ?? 0) / 1024 ** 2).toFixed(1)}{' '}
          MB. Backups and existing exports can still contain copies.
        </p>
        {(preview.data?.blocked_file_ids.length ?? 0) > 0 && (
          <p className="error">
            Blocked: {preview.data?.blocked_file_ids.length} files are used by another active
            record. Those originals must be kept.
          </p>
        )}
        {preview.data?.files === 0 && (
          <p className="caption">There are no remaining originals to remove.</p>
        )}
        <Field label="Type DELETE to confirm">
          <input
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <ErrorMessage error={error ?? preview.error} />
        <div className="form-actions">
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Keep files
          </Button>
          <Button
            variant="danger"
            disabled={confirmation !== 'DELETE' || !preview.data?.can_remove}
            onClick={() => {
              void send(`/documents/${id}/permanent-removal`, { confirmation })
                .then(async () => {
                  setOpen(false)
                  await refresh()
                  toast('Original-file removal queued.')
                })
                .catch(setError)
            }}
          >
            Remove {preview.data?.files ?? ''} original files
          </Button>
        </div>
      </Modal>
    </>
  )
}
