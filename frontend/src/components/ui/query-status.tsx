import { formatTime } from '../../app/time'
import { ApiError } from '../../api/client'
import { Button, ErrorMessage, Loading } from './index'

export function QueryStatus({
  query,
  label,
}: {
  query: {
    isPending: boolean
    isError: boolean
    error: unknown
    dataUpdatedAt: number
    refetch: () => unknown
  }
  label: string
}) {
  if (query.isPending) return <Loading />
  return (
    <div className="query-status">
      {query.isError && (
        <>
          <p className="notice">
            {label} unavailable.
            {query.error instanceof ApiError && query.error.status === 401
              ? ' Sign in again; captures stay on this device.'
              : ''}
          </p>
          <ErrorMessage error={query.error} />
          <Button
            variant="secondary"
            onClick={() => {
              void query.refetch()
            }}
          >
            Retry {label.toLowerCase()}
          </Button>
        </>
      )}
      {query.dataUpdatedAt > 0 && (
        <p className="caption">
          {query.isError ? 'Last successful check' : 'Last checked'}{' '}
          {formatTime(new Date(query.dataUpdatedAt).toISOString())}
          {query.isError ? ' · cached information may be stale' : ''}
        </p>
      )}
    </div>
  )
}
