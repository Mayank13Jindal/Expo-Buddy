import { describe, expect, it } from 'vitest'
import { statusLabel } from '../src/health'

describe('service labels', () => {
  it('shows stalled workers as a problem', () => {
    expect(statusLabel('stale')).toBe('Not responding')
    expect(statusLabel('ready')).toBe('Available')
  })
})
