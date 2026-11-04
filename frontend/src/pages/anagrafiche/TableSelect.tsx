// Scelta da una tabella (pagamenti, IVA, unità di misura, categorie, marche, listini, categorie clienti) con il tasto
// «Elenco» accanto (anche F4): tutte le voci in ordine alfabetico, ricerca, frecce e Invio, e «Nuovo» per creare la voce
// che manca senza uscire dalla schermata (2026-11-04).

import { ActionIcon, Button, Group, Modal, Paper, ScrollArea, Select, Stack, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core'
import { IconList, IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { notifyError, notifyOk } from '../../components'
import { A, categoryOptions, invalidateLookups } from './shared'
import { DEFS, TableFields, blankRow, parseInstallments } from './Tables'

export type TableKind = 'pagamenti' | 'aliquote-iva' | 'unita-misura' | 'categorie' | 'marche' | 'listini' | 'categorie-clienti'

const LABEL: Record<TableKind, (r: any, all: any[]) => string> = {
  pagamenti: (r) => r.description ?? r.code,
  'aliquote-iva': (r) => r.description ?? r.code,
  'unita-misura': (r) => `${r.code} — ${r.description ?? ''}`,
  categorie: (r, all) => { const p = all.find((x) => x.id === r.parent_id); return p ? `${p.name} › ${r.name}` : r.name },
  marche: (r) => r.name,
  listini: (r) => `${r.code} — ${r.name}`,
  'categorie-clienti': (r) => r.name,
}
const SINGULAR: Record<TableKind, string> = {
  pagamenti: 'pagamento', 'aliquote-iva': 'aliquota IVA', 'unita-misura': 'unità di misura', categorie: 'categoria', marche: 'marca',
  listini: 'listino', 'categorie-clienti': 'categoria clienti',
}

export function TableSelect({ kind, value, onChange, label, description, placeholder, clearable, disabled, size, w, filter, short, valueKey = 'id', required }: {
  kind: TableKind; value: string | null | undefined; onChange: (v: string | null) => void; label?: string; description?: string; placeholder?: string
  clearable?: boolean; disabled?: boolean; size?: 'xs' | 'sm' | 'md'; w?: number | string; filter?: (r: any) => boolean
  short?: boolean; valueKey?: 'id' | 'code'; required?: boolean
}) {
  const [rows, setRows] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const load = () => A(`/tabelle/${kind}`).then(setRows).catch(notifyError)
  useEffect(() => { load() }, [kind])
  const visible = filter ? rows.filter((r) => filter(r) || r[valueKey] === value) : rows
  const data = useMemo(() => (kind === 'categorie' ? categoryOptions(visible) : visible.map((r) => ({ value: r[valueKey], label: short ? r.code : LABEL[kind](r, rows) }))), [visible, rows, short])
  return (
    <Group gap={4} align="flex-end" wrap="nowrap" w={w}>
      <Select label={label} description={description} placeholder={placeholder} data={data} value={value ?? null} onChange={onChange} clearable={clearable} disabled={disabled}
        size={size} searchable required={required} allowDeselect={!!clearable} style={{ flex: 1, minWidth: short ? 70 : 0 }}
        onKeyDown={(e) => { if (e.key === 'F4') { e.preventDefault(); setOpen(true) } }} />
      <Tooltip label={`Elenco (F4): scegli o crea ${SINGULAR[kind]}`}>
        <ActionIcon variant="light" size={size === 'xs' ? 30 : 36} onClick={() => setOpen(true)} disabled={disabled} aria-label={`Elenco ${DEFS[kind].title.toLowerCase()}`}>
          <IconList size={size === 'xs' ? 14 : 18} />
        </ActionIcon>
      </Tooltip>
      {open && <TableLookup kind={kind} rows={visible} all={rows} onClose={() => setOpen(false)}
        onPick={(r) => { setOpen(false); onChange(r[valueKey]) }}
        onCreated={async (r) => { setOpen(false); await load(); onChange(r[valueKey]) }} />}
    </Group>
  )
}

function TableLookup({ kind, rows, all, onClose, onPick, onCreated }: { kind: TableKind; rows: any[]; all: any[]; onClose: () => void; onPick: (r: any) => void; onCreated: (r: any) => void }) {
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const [edit, setEdit] = useState<any>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const label = (r: any) => LABEL[kind](r, all)
  const list = rows.map((r) => ({ r, l: label(r) })).sort((a, b) => a.l.localeCompare(b.l, 'it'))
    .filter(({ r, l }) => !q || `${l} ${r.code ?? ''}`.toLowerCase().includes(q.toLowerCase()))
  useEffect(() => { setActive(0) }, [q])
  useEffect(() => { viewport.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' }) }, [active])
  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(list.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (list[active]) onPick(list[active].r) }
  }
  function startNew() {
    const b: any = blankRow(kind)
    const first = DEFS[kind].cols.find((c) => !c.type || c.type === 'text')
    if (first && q) b[first.key === 'code' ? (DEFS[kind].cols.find((c) => c.key === 'description' || c.key === 'name')?.key ?? 'code') : first.key] = q
    setEdit(b)
  }
  async function save() {
    try {
      const body = { ...edit }
      if (body.installments && typeof body.installments === 'string') body.installments = parseInstallments(body.installments)
      const r = await A(`/tabelle/${kind}`, { body })
      invalidateLookups()
      notifyOk('Voce creata')
      onCreated(r)
    } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} size="lg" title={edit ? `Nuova voce · ${DEFS[kind].title}` : `${DEFS[kind].title} · ${rows.length} in ordine alfabetico`}>
      {edit ? (
        <Stack onKeyDown={(e) => { if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') { e.preventDefault(); save() } }}>
          <TableFields kind={kind} edit={edit} setEdit={setEdit} parentOpts={kind === 'categorie' ? categoryOptions(all.filter((r) => !r.parent_id)) : []} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setEdit(null)}>Torna all'elenco</Button><Button onClick={save}>Salva e scegli</Button></Group>
        </Stack>
      ) : (
        <Stack gap={8}>
          <Paper withBorder radius="sm">
            <ScrollArea h="45vh" viewportRef={viewport}>
              {list.map(({ r, l }, i) => (
                <UnstyledButton key={r.id} data-i={i} w="100%" px="sm" py={7} onClick={() => onPick(r)} onMouseEnter={() => setActive(i)}
                  style={{ display: 'block', background: i === active ? 'var(--mantine-color-blue-light)' : undefined, borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  <Text size="sm" fw={600}>{l}</Text>
                  {r.code && !l.startsWith(r.code) && <Text size="xs" c="dimmed">{r.code}</Text>}
                </UnstyledButton>
              ))}
              {!list.length && <Text c="dimmed" ta="center" py="xl">Nessuna voce{q ? ` per «${q}»` : ''}: creala con «Nuovo»</Text>}
            </ScrollArea>
          </Paper>
          <Group gap="xs" wrap="nowrap">
            <TextInput autoFocus data-autofocus style={{ flex: 1 }} leftSection={<IconSearch size={16} />} placeholder="Cerca" value={q}
              onChange={(e) => setQ(e.currentTarget.value)} onKeyDown={onKey} />
            <Button variant="light" leftSection={<IconPlus size={16} />} onClick={startNew}>Nuovo</Button>
          </Group>
          <Text size="xs" c="dimmed">Frecce per scorrere · Invio per scegliere · clic sulla riga · Esc per chiudere</Text>
        </Stack>
      )}
    </Modal>
  )
}
