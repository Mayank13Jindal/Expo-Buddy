export function timeZone() {
  return localStorage.getItem('expo-timezone') ?? 'UTC'
}
export function formatTime(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not available'
  return new Date(value).toLocaleString('en-IN', {
    timeZone: timeZone(),
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}
export function formatDate(
  value: string,
  options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' },
) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not available'
  return new Date(value).toLocaleDateString('en-IN', {
    ...options,
    timeZone: /^\d{4}-\d\d-\d\d$/.test(value) ? 'UTC' : timeZone(),
  })
}
