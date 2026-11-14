import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Home, LibraryBig, Plus, ScanLine, ClipboardCheck, Settings, CalendarDays, Activity, Search, MoreHorizontal, ArrowUpRight, Sun, Moon, Users, Building2, Download } from 'lucide-react'
import { useCaptures } from '../pwa/hooks'
import { InstallHint } from '../pwa/install'
import { AppUpdateHint } from '../pwa/update'
import { CommandPalette } from './command-palette'
import { useLibrary, useToast } from './providers'
import { isServerReachable, send } from '../api/client'
import { Button } from '../components/ui'

const links = [{ to: '/', label: 'Overview', icon: Home }, { to: '/capture', label: 'Capture', icon: ScanLine }, { to: '/library', label: 'Library', icon: LibraryBig }, { to: '/library/companies', label: 'Companies', icon: Building2 }, { to: '/library/people', label: 'People', icon: Users }, { to: '/review', label: 'Review', icon: ClipboardCheck }, { to: '/expos', label: 'Expos', icon: CalendarDays }, { to: '/exports', label: 'Exports', icon: Download }]
export function Layout() {
  const { expos, activeExpo, setExpo, preferences, refresh } = useLibrary()
  const queued = useCaptures().filter(item => item.state !== 'saved' && item.kind === 'file').length
  const toast = useToast()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  useEffect(() => { const main = document.getElementById('main-content'); if (!main) return; const update = () => { const heading = main.querySelector('h1')?.textContent?.trim(); document.title = `${pathname === '/' ? 'Overview' : heading || 'Library'} · Expo Buddy` }; const observer = new MutationObserver(update); observer.observe(main, {childList:true,subtree:true,characterData:true}); update(); return () => observer.disconnect() }, [pathname])
  const [offline, setOffline] = useState(!navigator.onLine)
  const [reachable, setReachable] = useState(isServerReachable)
  useEffect(() => {
    const online = () => setOffline(false), offline = () => setOffline(true)
    window.addEventListener('online', online); window.addEventListener('offline', offline)
    const reachability = (event: Event) => setReachable((event as CustomEvent<boolean>).detail)
    window.addEventListener('server-reachability', reachability)
    const keyboard = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement).matches('input,textarea,select,[contenteditable=true]')) return
      if (event.key === 'u' || event.key === 'U') navigate('/capture')
      if (event.key.toLowerCase() === 'e') { const title = document.getElementById('document-title'); if (title) title.focus(); else document.querySelector<HTMLButtonElement>('button[aria-label="Edit company"]')?.click() }
      if (event.key === '/') { event.preventDefault(); document.getElementById('global-search')?.focus() }
    }
    window.addEventListener('keydown', keyboard)
    return () => { window.removeEventListener('online', online); window.removeEventListener('offline', offline); window.removeEventListener('server-reachability', reachability); window.removeEventListener('keydown', keyboard) }
  }, [navigate])
  return <div className="app-layout"><a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="sidebar"><NavLink to="/" className="brand"><span className="brand-icon"><LibraryBig size={23} /></span><span>Expo<span className="brand-light"> Buddy</span></span></NavLink><p className="nav-label">Workspace</p><nav>{links.map(({ to, label, icon: Icon }) => <NavLink end={to === '/' || to === '/library'} key={to} to={to}><Icon size={19} />{label}{to === '/library' && <kbd>L</kbd>}</NavLink>)}</nav><div className="sidebar-bottom"><div className="privacy-note"><span className="status-dot" />Stored on your server</div><NavLink to="/health"><Activity size={18} />System health</NavLink><NavLink to="/settings"><Settings size={18} />Settings</NavLink></div></aside>
    <CommandPalette /><div className="workspace"><header className="topbar"><form className="global-search" onSubmit={event => { event.preventDefault(); navigate(`/library?q=${encodeURIComponent(new FormData(event.currentTarget).get('q') as string)}`) }}><Search size={18} /><input id="global-search" name="q" placeholder="Search your library…" aria-label="Search your library" /><kbd>/</kbd></form><div className="top-actions"><button className="icon-button" aria-label="Switch colour theme" onClick={async () => { await send('/preferences', { theme: preferences?.theme === 'dark' ? 'light' : 'dark' }, 'PATCH'); await refresh() }}>{preferences?.theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}</button><NavLink className="text-button" to="/exports" aria-label="Export library"><Download size={18} /><span>Export</span></NavLink><NavLink className="text-button" to="/settings#ai">AI & ChatGPT</NavLink></div></header>
      <div className="expo-bar"><div><CalendarDays size={17} /><span>Adding to</span><select aria-label="Active expo" value={activeExpo?.id ?? ''} onChange={event => { void setExpo(event.target.value).catch(error => toast(error.message)) }}><option value="" disabled>Choose an expo</option>{expos.filter(expo => !expo.archived || expo.id === activeExpo?.id).map(expo => <option key={expo.id} value={expo.id}>{expo.name}</option>)}</select></div><button className="text-button" onClick={() => navigate('/expos')}>Manage expos<ArrowUpRight size={14} /></button></div>
      {(offline || !reachable) && <div className="offline-banner" role="status">{offline ? 'Offline — captures will upload later.' : 'Server unreachable — captures stay on this device until reconnected.'}</div>}
      <main id="main-content" className="content"><AppUpdateHint />{pathname !== '/capture' && <InstallHint />}<Outlet /></main>
    </div>
    <nav className="mobile-nav" aria-label="Main navigation"><NavLink to="/" end><Home size={21} /><span>Home</span></NavLink><NavLink to="/library"><LibraryBig size={21} /><span>Library</span></NavLink><NavLink className="capture-tab" to="/capture"><span><ScanLine size={24} /></span><small>Capture</small>{queued > 0 && <b className="queue-badge">{queued}</b>}</NavLink><NavLink to="/review"><ClipboardCheck size={21} /><span>Review</span></NavLink><NavLink to="/settings"><MoreHorizontal size={21} /><span>More</span></NavLink></nav>
  </div>
}

