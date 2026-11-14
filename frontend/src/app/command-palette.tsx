import { useEffect, useState } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search, Plus, LibraryBig, Settings, CalendarDays } from 'lucide-react'
import { api } from '../api/client'
import { useLibrary } from './providers'

export function CommandPalette() {
  const [open, setOpen] = useState(false),
    [value, setValue] = useState(''),
    [query, setQuery] = useState('')
  const navigate = useNavigate(),
    { activeExpo } = useLibrary()
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])
  useEffect(() => {
    const timer = setTimeout(() => setQuery(value), 300)
    return () => clearTimeout(timer)
  }, [value])
  const results = useQuery({
    queryKey: ['command-search', query, activeExpo?.id],
    enabled: open && query.trim().length > 1,
    queryFn: ({ signal }) =>
      api<{
        results: {
          id: string
          document_id: string | null
          company_id?: string
          title: string
          snippet: string
        }[]
      }>(
        `/search?${new URLSearchParams({ q: query, ...(activeExpo ? { expo_id: activeExpo.id } : {}), limit: '8' })}`,
        { signal },
      ),
  })
  const go = (path: string) => {
    navigate(path)
    setOpen(false)
    setValue('')
  }
  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Find a connection or action"
      shouldFilter={false}
    >
      <div className="command-input">
        <Search size={19} />
        <Command.Input
          value={value}
          onValueChange={setValue}
          placeholder="Find a company, person, note, or action…"
        />
        <kbd>esc</kbd>
      </div>
      <Command.List>
        {query &&
          results.data?.results.map((result) => (
            <Command.Item
              key={result.id}
              onSelect={() =>
                go(
                  result.document_id
                    ? `/documents/${result.document_id}`
                    : result.company_id
                      ? `/companies/${result.company_id}`
                      : '/expos',
                )
              }
            >
              <LibraryBig size={18} />
              <div>
                <strong>{result.title}</strong>
                <small>{result.snippet}</small>
              </div>
            </Command.Item>
          ))}
        {query && !results.isPending && !results.data?.results.length && (
          <Command.Empty>No matching connections yet.</Command.Empty>
        )}
        <Command.Group heading="Go somewhere">
          <Command.Item onSelect={() => go('/capture')}>
            <Plus size={18} />
            Add cards or brochures<kbd>U</kbd>
          </Command.Item>
          <Command.Item
            onSelect={() => go(`/library${value ? `?q=${encodeURIComponent(value)}` : ''}`)}
          >
            <LibraryBig size={18} />
            Open library
          </Command.Item>
          <Command.Item onSelect={() => go('/expos')}>
            <CalendarDays size={18} />
            Manage expos
          </Command.Item>
          <Command.Item onSelect={() => go('/settings')}>
            <Settings size={18} />
            Settings
          </Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  )
}
