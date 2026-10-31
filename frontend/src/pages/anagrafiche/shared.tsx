import { Button, FileButton, Group, Menu, Modal, ScrollArea, Select, Stack, Switch, Table, Text } from '@mantine/core'
import { IconDownload, IconUpload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { appApi, tokens } from '../../api'
import { notifyError } from '../../components'

export const A = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/anagrafiche' + path, opts)

export type Lookups = {
  vat: any[]
  payments: any[]
  units: any[]
  categories: any[]
  brands: any[]
  lists: any[]
  customerCategories: any[]
  settings: { field_groups: Record<string, boolean>; custom_fields: any[] }
}

let cache: Lookups | null = null

export async function loadLookups(force = false): Promise<Lookups> {
  if (cache && !force) return cache
  const [vat, payments, units, categories, brands, lists, customerCategories, settings] = await Promise.all([
    A('/tabelle/aliquote-iva'), A('/tabelle/pagamenti'), A('/tabelle/unita-misura'), A('/tabelle/categorie'),
    A('/tabelle/marche'), A('/tabelle/listini'), A('/tabelle/categorie-clienti'), A('/settings'),
  ])
  cache = { vat, payments, units, categories, brands, lists, customerCategories, settings }
  return cache
}

export function invalidateLookups() {
  cache = null
}

export function useLookups() {
  const [l, setL] = useState<Lookups | null>(cache)
  useEffect(() => {
    loadLookups().then(setL).catch(notifyError)
  }, [])
  return l
}

export const opts = (rows: any[], label = (r: any) => r.description ?? r.name) =>
  rows.map((r) => ({ value: r.id, label: label(r) }))

export function categoryOptions(cats: any[]) {
  const byId = Object.fromEntries(cats.map((c) => [c.id, c]))
  return cats
    .map((c) => ({ value: c.id, label: c.parent_id && byId[c.parent_id] ? `${byId[c.parent_id].name} › ${c.name}` : c.name }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

/** Valore numerico per i NumberInput: '' se vuoto. */
export const num = (v: any) => (v === null || v === undefined || v === '' ? '' : Number(v))
/** Valore da inviare al server: null se vuoto. */
export const dec = (v: any) => (v === '' || v === null || v === undefined ? null : String(v))

export async function downloadCsv(path: string, filename: string) {
  try {
    const res = await fetch('/api/anagrafiche' + path, { headers: { Authorization: `Bearer ${tokens.get('user')}` } })
    if (!res.ok) throw new Error('Esportazione non riuscita')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    notifyError(e)
  }
}

export function ImportExport({ kind, onDone, partyKind }: { kind: 'articoli' | 'soggetti'; onDone: () => void; partyKind?: 'clienti' | 'fornitori' }) {
  const [opened, setOpened] = useState(false)
  const base = kind === 'articoli' ? 'articoli' : 'clienti-fornitori'
  return (
    <>
      <Group gap="xs">
        <Menu position="bottom-end">
          <Menu.Target><Button variant="default" leftSection={<IconDownload size={16} />}>Esporta</Button></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => downloadCsv(`/${kind}-export.xlsx`, `${base}.xlsx`)}>Excel (.xlsx)</Menu.Item>
            <Menu.Item onClick={() => downloadCsv(`/${kind}-export.csv`, `${base}.csv`)}>CSV</Menu.Item>
          </Menu.Dropdown>
        </Menu>
        <Button variant="default" leftSection={<IconUpload size={16} />} onClick={() => setOpened(true)}>Importa</Button>
      </Group>
      <ImportWizard opened={opened} onClose={() => setOpened(false)} kind={kind} partyKind={partyKind} onDone={onDone} />
    </>
  )
}

function ImportWizard({ opened, onClose, kind, partyKind, onDone }: { opened: boolean; onClose: () => void; kind: 'articoli' | 'soggetti'; partyKind?: string; onDone: () => void }) {
  const [prev, setPrev] = useState<any>(null)
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [update, setUpdate] = useState(true)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<any>(null)

  function reset() { setPrev(null); setResult(null); setMapping({}) }
  function close() { reset(); onClose() }

  async function pick(file: File | null) {
    if (!file) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`/api/anagrafiche/import/anteprima?tipo=${kind}`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${tokens.get('user')}` } })
      const data = await res.json()
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'File non leggibile')
      setPrev(data)
      setMapping(data.mapping)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  async function run() {
    setBusy(true)
    try {
      const rows = prev.rows.map((r: string[]) => {
        const o: Record<string, string> = {}
        Object.entries(mapping).forEach(([i, f]) => { if (f) o[f] = r[Number(i)] ?? '' })
        return o
      })
      const url = kind === 'articoli' ? '/articoli-import' : `/soggetti-import?tipo=${partyKind ?? 'clienti'}`
      const r = await A(url, { body: { rows, update_existing: update } })
      setResult(r)
      onDone()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  const used = new Set(Object.values(mapping).filter(Boolean))
  const missing = prev?.required.filter((f: string) => !used.has(f)) ?? []
  const title = kind === 'articoli' ? 'Importa articoli' : partyKind === 'fornitori' ? 'Importa fornitori' : 'Importa clienti'

  return (
    <Modal opened={opened} onClose={close} title={title} size={prev && !result ? 'xl' : 'md'}>
      {result ? (
        <Stack>
          <Text><b>{result.created}</b> nuovi, <b>{result.updated}</b> aggiornati{result.errors_total ? <>, <b>{result.errors_total}</b> righe scartate</> : null}.</Text>
          {result.errors?.length > 0 && (
            <ScrollArea.Autosize mah={240}><Stack gap={2}>{result.errors.map((e: string) => <Text key={e} size="xs" c="red">{e}</Text>)}</Stack></ScrollArea.Autosize>
          )}
          <Group justify="flex-end"><Button onClick={close}>Fatto</Button></Group>
        </Stack>
      ) : !prev ? (
        <Stack>
          <Text size="sm">Carica un file <b>Excel</b> (.xlsx, .xls) o <b>CSV</b>. La prima riga deve contenere le intestazioni delle colonne: nel passo successivo le abbini ai campi di BluBeauty.</Text>
          <FileButton onChange={pick} accept=".xlsx,.xls,.xlsm,.csv,.txt">
            {(props) => <Button {...props} loading={busy} leftSection={<IconUpload size={16} />} size="md">Scegli il file</Button>}
          </FileButton>
          <Text size="xs" c="dimmed">Suggerimento: esporta prima in Excel per avere un modello con tutte le colonne.</Text>
        </Stack>
      ) : (
        <Stack>
          <Text size="sm">{prev.total} righe trovate. Controlla l'abbinamento delle colonne (le colonne senza campo vengono ignorate).</Text>
          <ScrollArea.Autosize mah={380}>
            <Table verticalSpacing={6}>
              <Table.Thead><Table.Tr><Table.Th>Colonna del file</Table.Th><Table.Th>Esempi</Table.Th><Table.Th w={240}>Campo BluBeauty</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {prev.headers.map((h: string, i: number) => (
                  <Table.Tr key={i}>
                    <Table.Td fw={500}>{h}</Table.Td>
                    <Table.Td><Text size="xs" c="dimmed" lineClamp={1}>{prev.sample.map((r: string[]) => r[i]).filter(Boolean).slice(0, 3).join(' · ')}</Text></Table.Td>
                    <Table.Td>
                      <Select size="xs" placeholder="— ignora —" clearable value={mapping[String(i)] ?? null}
                        data={prev.fields.map((f: any) => ({ value: f.key, label: f.label, disabled: used.has(f.key) && mapping[String(i)] !== f.key }))}
                        onChange={(v) => setMapping({ ...mapping, [String(i)]: v })} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
          <Switch label="Aggiorna le anagrafiche già presenti (stesso codice o partita IVA)" checked={update} onChange={(e) => setUpdate(e.currentTarget.checked)} />
          {missing.length > 0 && <Text size="sm" c="red">Abbina almeno la colonna: {missing.map((m: string) => prev.fields.find((f: any) => f.key === m)?.label).join(', ')}</Text>}
          <Group justify="space-between">
            <Button variant="subtle" onClick={reset}>Cambia file</Button>
            <Button onClick={run} loading={busy} disabled={missing.length > 0}>Importa {prev.total} righe</Button>
          </Group>
        </Stack>
      )}
    </Modal>
  )
}

/** Ricerca articoli per Select con ricerca remota. */
export function useItemSearch(exclude?: string) {
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  useEffect(() => {
    if (q.length < 2) { setFound([]); return }
    const t = setTimeout(() => A('/articoli?page_size=20&q=' + encodeURIComponent(q)).then((r) => setFound(r.rows.filter((x: any) => x.id !== exclude))).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [q])
  return { q, setQ, found, options: found.map((f) => ({ value: f.id, label: `${f.code} — ${f.description}` })) }
}
