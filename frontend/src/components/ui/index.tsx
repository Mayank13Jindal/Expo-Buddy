import * as Dialog from '@radix-ui/react-dialog'
import { X, FolderOpen, LoaderCircle } from 'lucide-react'
import {
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
  type ButtonHTMLAttributes,
  type ReactNode,
} from 'react'

export function Button({
  children,
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
}) {
  return (
    <button className={`button ${variant} ${className}`} {...props}>
      {children}
    </button>
  )
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  const id = useId()
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {isValidElement(children)
        ? cloneElement(children as ReactElement<{ id: string; 'aria-describedby'?: string }>, {
            id,
            'aria-describedby': hint ? `${id}-hint` : undefined,
          })
        : children}
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </div>
  )
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <FolderOpen size={30} strokeWidth={1.4} />
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  )
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={22} /> Loading…
    </div>
  )
}
export function ErrorMessage({ error }: { error: unknown }) {
  return error ? (
    <p className="error" role="alert">
      {error instanceof Error ? error.message : 'Something went wrong. Try again.'}
    </p>
  ) : null
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className="modal-content">
          <Dialog.Title>{title}</Dialog.Title>
          {description && <Dialog.Description>{description}</Dialog.Description>}
          <Dialog.Close className="icon-button modal-close" aria-label="Close">
            <X size={20} />
          </Dialog.Close>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
export const stateLabel = (value: string) =>
  (
    ({
      received: 'Saved',
      preparing: 'Making previews',
      reading: 'Reading text',
      waiting_grouping: 'Check groups',
      waiting_ai: 'Waiting for AI',
      indexing: 'Updating search',
      ready: 'Processing complete',
      failed: 'Needs a retry',
      needs_attention: 'Needs attention',
      unreviewed: 'Not checked',
      reviewed: 'Reviewed',
      suggested: 'Check group',
      confirmed: 'Grouping confirmed',
    }) as Record<string, string>
  )[value] ?? value.replaceAll('_', ' ')
export function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function DocumentStatus({ document }: { document: import('../../api/client').Document }) {
  const review = document.review_status ?? document.review_state
  return (
    <div className="badge-row document-status">
      <Badge>{stateLabel(document.processing_state)}</Badge>
      <Badge tone={review === 'reviewed' ? 'green' : 'amber'}>
        Review: {stateLabel(review || 'unreviewed')}
        {document.pending_changes ? ` · ${document.pending_changes} suggestions` : ''}
      </Badge>
    </div>
  )
}
