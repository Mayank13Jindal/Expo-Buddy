import { formatTime } from '../app/time'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'
import { useSearchParams } from 'react-router-dom'
import { ArrowDown, ArrowUp, Download, Save } from 'lucide-react'
import { api, send } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, ErrorMessage, Field, Loading } from '../components/ui'
import type { ExportPreview, ExportRecord } from '../api/types'

type Selection = {
  allow_unreviewed: boolean
  scope: string
  expo_ids: string[]
  document_ids: string[]
  query: string
  tables: string[]
  fields: Record<string, string[]>
  format: string
  csv_bom: boolean
  csv_safe: boolean
  include_csv: boolean
  include_vcard: boolean
  info_sheet: boolean
}
const defaults: Selection = {
  allow_unreviewed: false,
  scope: 'active',
  expo_ids: [],
  document_ids: [],
  query: '',
  tables: ['contacts'],
  fields: {
    contacts: ['expo', 'company_name', 'full_name', 'designation', 'phones', 'emails'],
    companies: ['expo', 'company_name', 'phones', 'emails', 'products'],
    documents: ['expo', 'title', 'type', 'files'],
  },
  format: 'xlsx',
  csv_bom: true,
  csv_safe: true,
  include_csv: true,
  include_vcard: false,
  info_sheet: true,
}
function PreviewTable({
  rows,
  fields,
  labels,
}: {
  rows: Record<string, string>[]
  fields: string[]
  labels: Record<string, string>
}) {
  const columns = useMemo<ColumnDef<Record<string, string>>[]>(
    () => fields.map((field) => ({ accessorKey: field, header: labels[field] ?? field })),
    [fields, labels],
  )
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() })
  return (
    <div className="table-scroll">
      <table>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id}>
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="muted">No rows in this table for the chosen scope.</p>}
    </div>
  )
}
export function ExportsPage() {
  const { expos, activeExpo, refresh } = useLibrary(),
    toast = useToast(),
    [params] = useSearchParams()
  const [selection, setSelection] = useState<Selection>({
      ...defaults,
      ...(params.get('ids')
        ? { scope: 'selected', document_ids: params.get('ids')!.split(',') }
        : {}),
      ...(params.get('q') ? { scope: 'search', query: params.get('q')! } : {}),
    }),
    [step, setStep] = useState(0),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false),
    [dragged, setDragged] = useState<string>()
  const fields = useQuery({
    queryKey: ['export-fields'],
    queryFn: () => api<Record<string, Record<string, string>>>('/export-fields'),
  })
  const presets = useQuery({
    queryKey: ['export-presets'],
    queryFn: () => api<{ id: string; name: string; selection: Selection }[]>('/export-presets'),
  })
  const exports = useQuery({
    queryKey: ['exports'],
    queryFn: () => api<ExportRecord[]>('/exports'),
    refetchInterval: 3000,
  })
  const body = {
    ...selection,
    expo_ids: selection.scope === 'active' && activeExpo ? [activeExpo.id] : selection.expo_ids,
  }
  const preview = useQuery({
    queryKey: ['export-preview', body],
    enabled: step >= 3,
    queryFn: () => send<ExportPreview>('/exports/preview', body),
    retry: false,
  })
  const update = (values: Partial<Selection>) =>
    setSelection((current) => ({
      ...current,
      ...(Object.keys(values).some((key) =>
        ['scope', 'expo_ids', 'document_ids', 'query', 'tables', 'fields'].includes(key),
      )
        ? { allow_unreviewed: false }
        : {}),
      ...values,
    }))
  const reorder = (table: string, from: number, to: number) => {
    const ordered = [...selection.fields[table]]
    if (to < 0 || to >= ordered.length) return
    const [value] = ordered.splice(from, 1)
    ordered.splice(to, 0, value)
    update({ fields: { ...selection.fields, [table]: ordered } })
  }
  const generate = async () => {
    setBusy(true)
    try {
      await send('/exports', body)
      await refresh()
      toast('Export started. Download it below when ready.')
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>An export, your way.</h1>
          <p className="muted">Choose the records and details you need.</p>
        </div>
      </div>
      <div className="export-steps">
        {['Scope', 'Tables', 'Fields', 'Preview', 'Format'].map((label, index) => (
          <button
            key={label}
            className={step === index ? 'active' : ''}
            onClick={() => setStep(index)}
          >
            <span>{index + 1}</span>
            {label}
          </button>
        ))}
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>
            {
              [
                'Which discoveries?',
                'Choose your tables',
                'Choose and order fields',
                'A look before you export',
                'Choose a format',
              ][step]
            }
          </h2>
          <div className="button-row">
            <select
              aria-label="Export preset"
              value=""
              onChange={(event) => {
                const preset = presets.data?.find((row) => row.id === event.target.value)
                if (preset)
                  setSelection({ ...defaults, ...preset.selection, allow_unreviewed: false })
              }}
            >
              <option value="">Load a preset</option>
              {presets.data?.map((row) => (
                <option value={row.id} key={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
            <Button
              variant="ghost"
              onClick={async () => {
                const name = prompt('Name this export preset')
                if (name) {
                  await send('/export-presets', { name, selection: body })
                  await refresh()
                  toast('Preset saved.')
                }
              }}
            >
              <Save size={16} />
              Save preset
            </Button>
          </div>
        </div>
        {step === 0 && (
          <>
            <Field label="Scope">
              <select
                value={selection.scope}
                onChange={(event) => update({ scope: event.target.value })}
              >
                <option value="active">Active expo · {activeExpo?.name ?? 'choose an expo'}</option>
                <option value="expos">Chosen expos</option>
                <option value="selected">Selected library records</option>
                <option value="search">Search results</option>
                <option value="all">All expos</option>
              </select>
            </Field>
            {selection.scope === 'expos' &&
              expos.map((expo) => (
                <label className="checkbox-label export-check" key={expo.id}>
                  <input
                    type="checkbox"
                    checked={selection.expo_ids.includes(expo.id)}
                    onChange={(event) =>
                      update({
                        expo_ids: event.target.checked
                          ? [...selection.expo_ids, expo.id]
                          : selection.expo_ids.filter((id) => id !== expo.id),
                      })
                    }
                  />
                  {expo.name}
                </label>
              ))}
            {selection.scope === 'selected' && (
              <p className="notice">
                {selection.document_ids.length} documents selected in the library. Use the library
                checkboxes to change this selection.
              </p>
            )}
            {selection.scope === 'search' && (
              <Field
                label="Search query"
                hint="Freezes the visible search results, up to 50 matching documents."
              >
                <input
                  value={selection.query}
                  onChange={(event) => update({ query: event.target.value })}
                />
              </Field>
            )}
            <p className="caption">
              The snapshot freezes when you generate it. Later corrections do not alter an existing
              export.
            </p>
          </>
        )}
        {step === 1 &&
          ['contacts', 'companies', 'documents'].map((table) => (
            <label className="checkbox-label export-check" key={table}>
              <input
                type="checkbox"
                checked={selection.tables.includes(table)}
                onChange={(event) =>
                  update({
                    tables: event.target.checked
                      ? [...selection.tables, table]
                      : selection.tables.filter((item) => item !== table),
                  })
                }
              />
              <span>
                <strong>{table[0].toUpperCase() + table.slice(1)}</strong>
                <small>
                  {table === 'contacts'
                    ? 'One person per expo; company details repeated.'
                    : table === 'companies'
                      ? 'One company per expo, including brochure-only companies.'
                      : 'One card or brochure, with ordered source links.'}
                </small>
              </span>
            </label>
          ))}
        {step === 2 &&
          selection.tables.map((table) => (
            <div className="field-picker" key={table}>
              <h3>{table[0].toUpperCase() + table.slice(1)}</h3>
              <div className="field-picker-columns">
                <div>
                  {Object.entries(fields.data?.[table] ?? {}).map(([key, label]) => (
                    <label className="checkbox-label" key={key}>
                      <input
                        type="checkbox"
                        checked={selection.fields[table]?.includes(key)}
                        onChange={(event) =>
                          update({
                            fields: {
                              ...selection.fields,
                              [table]: event.target.checked
                                ? [...(selection.fields[table] ?? []), key]
                                : selection.fields[table].filter((field) => field !== key),
                            },
                          })
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <ol className="field-order">
                  {selection.fields[table]?.map((field, index) => (
                    <li
                      key={field}
                      draggable
                      onDragStart={() => setDragged(field)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => {
                        if (dragged) reorder(table, selection.fields[table].indexOf(dragged), index)
                      }}
                    >
                      <span>
                        {index + 1}. {fields.data?.[table][field]}
                      </span>
                      <button
                        className="icon-button"
                        disabled={index === 0}
                        aria-label={`Move ${fields.data?.[table][field]} up`}
                        onClick={() => reorder(table, index, index - 1)}
                      >
                        <ArrowUp size={16} />
                      </button>
                      <button
                        className="icon-button"
                        disabled={index === selection.fields[table].length - 1}
                        aria-label={`Move ${fields.data?.[table][field]} down`}
                        onClick={() => reorder(table, index, index + 1)}
                      >
                        <ArrowDown size={16} />
                      </button>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          ))}
        {step >= 3 && (preview.data?.counts?.flagged_rows ?? 0) > 0 && (
          <div className="notice" role="status">
            <strong>{preview.data?.counts.flagged_rows} export rows need review</strong>
            <p>
              These values have not all been checked, contain invalid contact syntax, or have
              unresolved suggestions. Check the Review warning column before using them for
              outreach.
            </p>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={selection.allow_unreviewed}
                onChange={(event) => update({ allow_unreviewed: event.target.checked })}
              />
              Include unreviewed or flagged data in this export
            </label>
          </div>
        )}
        {step === 3 && (
          <>
            {preview.isPending ? (
              <Loading />
            ) : (
              <>
                <p className="caption">
                  {Object.entries(preview.data?.counts ?? {})
                    .filter(([key]) => selection.tables.includes(key))
                    .map(([key, count]) => `${count} ${key}`)
                    .join(' · ')}
                </p>
                {selection.tables.includes('contacts') &&
                  !selection.tables.includes('companies') &&
                  (preview.data?.counts?.brochure_only_companies ?? 0) > 0 && (
                    <p className="notice">
                      Contacts-only leaves out {preview.data?.counts.brochure_only_companies}{' '}
                      brochure-only companies. Include Companies to keep them.
                    </p>
                  )}
                {selection.tables.map((table) => (
                  <div key={table}>
                    <h3>{table}</h3>
                    <p className="caption">
                      Showing {preview.data?.rows?.[table]?.length ?? 0} of{' '}
                      {preview.data?.counts?.[table] ?? 0} rows. Preview sample only; the export
                      contains all selected rows.
                    </p>
                    <PreviewTable
                      rows={preview.data?.rows?.[table] ?? []}
                      fields={preview.data?.fields?.[table] ?? selection.fields[table]}
                      labels={fields.data?.[table] ?? {}}
                    />
                  </div>
                ))}
              </>
            )}
            <ErrorMessage error={preview.error} />
          </>
        )}
        {step === 4 && (
          <>
            <Field label="File format">
              <select
                value={selection.format}
                onChange={(event) => update({ format: event.target.value })}
              >
                <option value="xlsx">Excel (.xlsx)</option>
                <option value="csv">CSV (.csv, one table)</option>
                <option value="vcf">Phone contacts (.vcf)</option>
                <option value="zip">ZIP with originals, text and tables</option>
              </select>
            </Field>
            {['csv', 'zip'].includes(selection.format) && (
              <>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selection.csv_safe}
                    onChange={(event) => update({ csv_safe: event.target.checked })}
                  />
                  Spreadsheet-safe CSV (recommended)
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selection.csv_bom}
                    onChange={(event) => update({ csv_bom: event.target.checked })}
                  />
                  UTF-8 with BOM for Excel
                </label>
              </>
            )}
            {selection.format === 'zip' && (
              <>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selection.include_csv}
                    onChange={(event) => update({ include_csv: event.target.checked })}
                  />
                  Include CSV tables
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selection.include_vcard}
                    onChange={(event) => update({ include_vcard: event.target.checked })}
                  />
                  Include vCards
                </label>
                <p className="notice">
                  Original photos, PDFs and brochure text still contain printed information.
                  Deselecting fields is not redaction. Personal notes appear only when selected.
                </p>
              </>
            )}
            <ErrorMessage error={preview.error} />
            <p className="caption">
              Downloads expire after 7 days. Originals remain in your library.
            </p>
            <Button
              disabled={
                busy ||
                preview.isError ||
                preview.isPending ||
                ((preview.data?.counts?.flagged_rows ?? 0) > 0 && !selection.allow_unreviewed)
              }
              onClick={() => {
                void generate()
              }}
            >
              <Download size={18} />
              {busy ? 'Starting…' : 'Generate export'}
            </Button>
          </>
        )}
        <ErrorMessage error={error} />
        <div className="form-actions export-actions">
          {step > 0 && (
            <Button variant="secondary" onClick={() => setStep(step - 1)}>
              Back
            </Button>
          )}
          {step < 4 && (
            <Button disabled={!selection.tables.length} onClick={() => setStep(step + 1)}>
              Continue
            </Button>
          )}
        </div>
      </section>
      <section className="panel">
        <h2>Your downloads</h2>
        {exports.data?.length ? (
          exports.data.map((row) => (
            <div className="recent-row" key={row.id}>
              <div>
                <strong>{row.format.toUpperCase()} export</strong>
                <small>
                  {formatTime(row.created_at)} · {row.counts.documents_in_scope} documents
                </small>
                {row.error && <p className="error">{row.error}</p>}
              </div>
              <Badge tone={row.state === 'ready' ? 'green' : ''}>{row.state}</Badge>
              {row.state === 'ready' && (
                <a className="button secondary" href={`/api/v1/exports/${row.id}/download`}>
                  <Download size={16} />
                  Download
                </a>
              )}
            </div>
          ))
        ) : (
          <p className="muted">Your generated exports will appear here.</p>
        )}
      </section>
    </>
  )
}
