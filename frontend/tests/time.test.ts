import { expect, it, vi } from 'vitest'
import { formatDate, formatTime } from '../src/app/time'
it('missing or malformed timestamps never display Invalid Date', () => {
  vi.stubGlobal('localStorage', {getItem: ()=>'UTC'})
  expect(formatTime(undefined)).toBe('Not available')
  expect(formatTime(null)).toBe('Not available')
  expect(formatTime('bad-date')).toBe('Not available')
  expect(formatDate('')).toBe('Not available')
  expect(formatTime('2026-11-14T00:00:00Z')).not.toContain('Invalid Date')
  vi.unstubAllGlobals()
})
