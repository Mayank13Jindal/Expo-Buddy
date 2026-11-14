import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Search, UserRound } from 'lucide-react'
import { api } from '../api/client'
import { useLibrary } from '../app/providers'
import { Badge, Empty, ErrorMessage, Loading } from '../components/ui'
import { LibraryTabs } from './library-tabs'

export function PeoplePage() {
  const {activeExpo} = useLibrary(), [all,setAll] = useState(true), [q,setQ] = useState('')
  const query = useQuery({queryKey:['people',all,activeExpo?.id],queryFn:()=>api<any[]>(`/contacts${!all && activeExpo ? `?expo_id=${activeExpo.id}` : ''}`)})
  const rows = query.data?.filter(row=>JSON.stringify([row.full_name,row.company_name,row.designation,row.channels]).toLowerCase().includes(q.toLowerCase()))
  return <><div className="page-heading"><div><h1>People</h1><p className="muted">Every saved person, with company, contact details and source.</p></div><Link className="button secondary" to="/exports">Export contacts</Link></div><LibraryTabs /><div className="library-toolbar"><div className="search-field"><Search size={18}/><input aria-label="Find a person" placeholder="Name, company, email or phone…" value={q} onChange={event=>setQ(event.target.value)}/></div><label className="checkbox-label"><input type="checkbox" checked={all} onChange={event=>setAll(event.target.checked)}/>All expos</label></div><ErrorMessage error={query.error}/>{query.isPending ? <Loading /> : query.isError ? null : rows?.length ? <div className="expo-grid">{rows.map(row=><article className="panel person-card" key={row.id}><UserRound size={24}/><h2>{row.full_name || 'Name needs review'}</h2><Link to={`/companies/${row.company_id}`}>{row.company_name}</Link><p className="muted">{row.designation}</p>{row.review_warning && <p className="contact-review-warning"><Badge tone="amber">{row.review_status === 'needs_attention' ? 'Needs review' : 'Not verified'}</Badge> {row.review_warning}</p>}{row.channels.map((item:any,index:number)=><p className="contact-value" key={index}><small>{item.label || item.kind}</small><span>{item.raw}</span></p>)}{row.source_document_id && <Link className="text-button" to={`/documents/${row.source_document_id}`}>View scanned card ↗</Link>}</article>)}</div> : <Empty title={q.trim() ? 'No people match this search' : 'No people saved yet'} description={q.trim() ? 'Try another name, company, email or phone, or clear the search.' : 'Add a card. Processing extracts its company and people automatically; any uncertain details stay in Review.'}/>}</>
}
