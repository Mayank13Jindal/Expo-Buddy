import { NavLink } from 'react-router-dom'
export function LibraryTabs() {
  return <nav className="collection-tabs" aria-label="Browse scanned records"><NavLink end to="/library">Scans</NavLink><NavLink to="/library/companies">Companies</NavLink><NavLink to="/library/people">People</NavLink><NavLink to="/review">Review</NavLink><NavLink to="/exports">Export</NavLink></nav>
}
