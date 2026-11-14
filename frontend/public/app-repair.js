const status = document.getElementById('status')
const button = document.getElementById('update')
const parameters = new URLSearchParams(location.search)
async function check() {
  try {
    const response = await fetch('/api/v1/health', { cache: 'no-store', signal: AbortSignal.timeout(10000) })
    if (!response.ok) throw new Error(`Server returned ${response.status}.`)
    const health = await response.json()
    if (health.canonical_url !== location.origin) throw new Error(`Open ${health.canonical_url}/api/v1/app-repair to update this app.`)
    status.textContent = `Server connected at ${location.origin}. Ready to open the current version.`
    button.disabled = false
    if (parameters.get('auto') === '1') button.click()
  } catch (error) {
    status.textContent = `Connection failed: ${error.message} Check that this device can reach your server and trusts its HTTPS certificate, then reload this page.`
  }
}
button.addEventListener('click', async () => {
  button.disabled = true
  status.textContent = 'Updating the app. Your queued captures stay on this device…'
  try {
    if ('serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations()
      for (const registration of registrations) {
        if (registration.scope === `${location.origin}/`) await registration.unregister()
      }
    }
    for (const name of await caches.keys()) {
      if (name.startsWith('workbox-precache-') && name.endsWith(`${location.origin}/`)) await caches.delete(name)
    }
    const destination = parameters.get('next') === 'settings' ? '/settings' : '/'
    location.replace(`${destination}?updated=${Date.now()}${destination === '/settings' ? '#ai' : ''}`)
  } catch (error) {
    status.textContent = `Update failed: ${error.message} Close the other library tabs, then try again.`
    button.disabled = false
  }
})
void check()
