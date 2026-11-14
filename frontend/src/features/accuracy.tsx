import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, send } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Button, ErrorMessage, Modal } from '../components/ui'

export function CheckedExample({id,reviewed}:{id:string;reviewed:boolean}) {
  const [open,setOpen]=useState(false), [checked,setChecked]=useState<string[]>(['company_name','people','phones','emails']),[error,setError]=useState<unknown>(),{refresh}=useLibrary(),toast=useToast()
  return <><Button variant="ghost" disabled={!reviewed} onClick={()=>setOpen(true)}>Use as a checked accuracy example</Button><Modal open={open} onOpenChange={setOpen} title="Save hand-checked example" description="Only do this after comparing these corrected fields with the original photo. This is the expected answer for future model comparisons.">{['company_name','people','phones','emails'].map(field=><label className="checkbox-label" key={field}><input type="checkbox" checked={checked.includes(field)} onChange={event=>setChecked(rows=>event.target.checked?[...rows,field]:rows.filter(row=>row!==field))}/>{field.replace('_',' ')}</label>)}<p className="notice">Raw AI output will be scored against this snapshot. Later AI reprocessing cannot change the expected answer. Replace it only after another manual check.</p><ErrorMessage error={error}/><Button disabled={!checked.length} onClick={async()=>{try{await send(`/accuracy/examples/${id}`,{confirmed:true,checked_fields:checked});await refresh();setOpen(false);toast('Hand-checked example saved. See Accuracy in Settings.')}catch(error){setError(error)}}}>I checked these fields against the photo</Button></Modal></>
}
export function AccuracyPanel(){
  const query=useQuery({queryKey:['accuracy'],queryFn:()=>api<any>('/accuracy')})
  return <section className="panel"><h2>Accuracy on your checked cards</h2><ErrorMessage error={query.error}/>{query.data && <><p>{query.data.examples.length} hand-checked examples · {query.data.measured_field_groups ? `${query.data.correct_field_groups}/${query.data.measured_field_groups} exact field-group matches (${query.data.exact_match_percent}%)` : 'No measured accuracy yet'}</p><p className="caption">{query.data.policy}</p>{query.data.examples.map((row:any)=><div className="history-row" key={row.document_id}><Link to={`/documents/${row.document_id}`}>{row.title}</Link><p>{row.model ?? 'Waiting for extraction'} · {row.matches ? Object.entries(row.matches).map(([field,match])=>`${field}: ${match?'match':'differs'}`).join(' · ') : 'No raw AI output to compare'}</p></div>)}</>}<p className="caption">Correct a scan, mark it reviewed, then choose “Use as a checked accuracy example”. Include 30–50 varied cards before judging a model change.</p></section>
}
