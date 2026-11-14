export interface Health {
  status: 'ready' | 'unavailable'
  stage: number
  release_ready: boolean
  services: Record<string, string>
  storage: { name: string; status: string; message: string; warning: boolean }[]
  canonical_url: string
  message: string
}

export function statusLabel(status: string): string {
  return (
    (
      {
        ready: 'Available',
        unavailable: 'Unavailable',
        paused: 'Paused',
        stale: 'Not responding',
        migration_needed: 'Update needed',
      } as Record<string, string>
    )[status] ?? 'Checking'
  )
}
