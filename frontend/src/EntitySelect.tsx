// Scelta di magazzini, conti cassa/banca, operatori e servizi dell'agenda con il tasto «Elenco» accanto (anche F4): elenco alfabetico,
// ricerca, frecce e Invio, e «Nuovo» per creare quello che manca senza uscire dalla schermata (2026-11-04).

import { ActionIcon, Button, ColorInput, Group, Modal, MultiSelect, NumberInput, Paper, ScrollArea, Select, SimpleGrid, Stack, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core'
import { IconList, IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'

import { appApi, fmtEuro } from './api'
import { notifyError, notifyOk } from './components'

export type EntityKind = 'magazzini' | 'conti' | 'operatori' | 'servizi'

type Cfg = { title: string; one: string; list: string; create: string; pick: (r: any[]) => any[]; label: (r: any) => string; sub?: (r: any) => string }
const KIND_LABEL: Record<string, string> = { cassa: 'Cassa', banca: 'Banca', carta: 'Carta', altro: 'Altro' }

const CFG: Record<EntityKind, Cfg> = {
  magazzini: { title: 'Magazzini', one: 'magazzino', list: '/api/magazzino/magazzini', create: '/api/magazzino/magazzini', pick: (r: any) => r.rows,
    label: (r) => r.name, sub: (r) => r.code },
  conti: { title: 'Conti cassa e banca', one: 'conto', list: '/api/scadenzario/conti', create: '/api/scadenzario/conti', pick: (r: any) => r,
    label: (r) => r.name, sub: (r) => [KIND_LABEL[r.kind] ?? r.kind, r.iban].filter(Boolean).join(' · ') },
  operatori: { title: 'Operatori', one: 'operatore', list: '/api/agenda/operatori', create: '/api/agenda/operatori', pick: (r: any) => r,
    label: (r) => [r.first_name, r.last_name].filter(Boolean).join(' '), sub: (r) => (r.active === false ? 'non attivo' : '') },
  servizi: { title: 'Servizi', one: 'servizio', list: '/api/agenda/servizi', create: '/api/agenda/servizi', pick: (r: any) => r,
    label: (r) => r.name, sub: (r) => `${r.duration_min} min · ${fmtEuro(r.price)}${r.active === false ? ' · non attivo' : ''}` },
}

export function EntitySelect({ kind, value, onChange, label, description, placeholder, clearable, disabled, required, w, size, filter, optionLabel, newDefaults, testId, extra = [] }: {
  kind: EntityKind; value: string | null | undefined; onChange: (v: string | null, row?: any) => void; label?: string; description?: string; placeholder?: string
  clearable?: boolean; disabled?: boolean; required?: boolean; w?: number | string; size?: 'xs' | 'sm' | 'md'; filter?: (r: any) => boolean
  optionLabel?: (r: any) => string; newDefaults?: Record<string, any>; testId?: string
  extra?: { value: string; label: string }[]  // voci in più che non vengono dall'elenco (es. «Tutto il salone»)
}) {
  const cfg = CFG[kind]
  const [rows, setRows] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const load = () => appApi<any>(cfg.list).then((r) => setRows(cfg.pick(r))).catch(notifyError)
  useEffect(() => { load() }, [kind])
  const visible = filter ? rows.filter((r) => filter(r) || r.id === value) : rows
  const lbl = optionLabel ?? cfg.label
  return (
    <Group gap={4} align="flex-end" wrap="nowrap" w={w}>
      <Select label={label} description={description} placeholder={placeholder} data={[...visible.map((r) => ({ value: r.id, label: lbl(r) })), ...extra]} value={value ?? null}
        onChange={(v) => onChange(v, rows.find((r) => r.id === v))} clearable={clearable} disabled={disabled} required={required} size={size} searchable
        allowDeselect={!!clearable} style={{ flex: 1, minWidth: 0 }} data-testid={testId} onKeyDown={(e) => { if (e.key === 'F4') { e.preventDefault(); setOpen(true) } }} />
      <Tooltip label={`Elenco (F4): scegli o crea un ${cfg.one}`}>
        <ActionIcon variant="light" size={size === 'xs' ? 30 : 36} onClick={() => setOpen(true)} disabled={disabled} aria-label={`Elenco ${cfg.title.toLowerCase()}`}>
          <IconList size={size === 'xs' ? 14 : 18} />
        </ActionIcon>
      </Tooltip>
      {open && <EntityLookup kind={kind} rows={visible} newDefaults={newDefaults} onClose={() => setOpen(false)}
        onPick={(r) => { setOpen(false); onChange(r.id, r) }}
        onCreated={async (r) => { setOpen(false); await load(); onChange(r.id, r) }} />}
    </Group>
  )
}

function EntityLookup({ kind, rows, onClose, onPick, onCreated, newDefaults }: { kind: EntityKind; rows: any[]; onClose: () => void; onPick: (r: any) => void; onCreated: (r: any) => void; newDefaults?: Record<string, any> }) {
  const cfg = CFG[kind]
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const [creating, setCreating] = useState(false)
  const viewport = useRef<HTMLDivElement>(null)
  const list = [...rows].sort((a, b) => cfg.label(a).localeCompare(cfg.label(b), 'it'))
    .filter((r) => !q || `${cfg.label(r)} ${cfg.sub?.(r) ?? ''}`.toLowerCase().includes(q.toLowerCase()))
  useEffect(() => { setActive(0) }, [q])
  useEffect(() => { viewport.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' }) }, [active])
  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(list.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (list[active]) onPick(list[active]) }
  }
  return (
    <Modal opened onClose={onClose} size="lg" title={creating ? `Nuovo ${cfg.one}` : `${cfg.title} · ${rows.length} in ordine alfabetico`}>
      {creating ? <NewEntity kind={kind} initial={q} defaults={newDefaults} onCancel={() => setCreating(false)} onCreated={onCreated} /> : (
        <Stack gap={8}>
          <Paper withBorder radius="sm">
            <ScrollArea h="45vh" viewportRef={viewport}>
              {list.map((r, i) => (
                <UnstyledButton key={r.id} data-i={i} w="100%" px="sm" py={7} onClick={() => onPick(r)} onMouseEnter={() => setActive(i)}
                  style={{ display: 'block', background: i === active ? 'var(--mantine-color-blue-light)' : undefined, borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  <Text size="sm" fw={600}>{cfg.label(r)}</Text>
                  {cfg.sub?.(r) && <Text size="xs" c="dimmed">{cfg.sub(r)}</Text>}
                </UnstyledButton>
              ))}
              {!list.length && <Text c="dimmed" ta="center" py="xl">Nessun {cfg.one}{q ? ` per «${q}»` : ''}: crealo con «Nuovo»</Text>}
            </ScrollArea>
          </Paper>
          <Group gap="xs" wrap="nowrap">
            <TextInput autoFocus data-autofocus style={{ flex: 1 }} leftSection={<IconSearch size={16} />} placeholder="Cerca" value={q}
              onChange={(e) => setQ(e.currentTarget.value)} onKeyDown={onKey} />
            <Button variant="light" leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>Nuovo</Button>
          </Group>
          <Text size="xs" c="dimmed">Frecce per scorrere · Invio per scegliere · clic sulla riga · Esc per chiudere</Text>
        </Stack>
      )}
    </Modal>
  )
}

function NewEntity({ kind, initial, defaults, onCancel, onCreated }: { kind: EntityKind; initial: string; defaults?: Record<string, any>; onCancel: () => void; onCreated: (r: any) => void }) {
  const [f, setF] = useState<any>(() => ({
    magazzini: { code: '', name: initial },
    conti: { name: initial, kind: 'cassa', iban: '', opening_balance: 0 },
    operatori: { first_name: initial, last_name: '', color: '#2340a8' },
    servizi: { name: initial, duration_min: 30, price: '', staff_ids: [] as string[] },
  }[kind]))
  useEffect(() => { if (defaults) setF((x: any) => ({ ...x, ...defaults })) }, [])
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  // servizio nuovo: lo eseguono tutti gli operatori attivi, poi si cambia in Agenda › Servizi
  const [staff, setStaff] = useState<any[]>([])
  useEffect(() => {
    if (kind !== 'servizi') return
    appApi<any[]>('/api/agenda/operatori').then((r) => { const act = r.filter((x) => x.active); setStaff(act); setF((x: any) => ({ ...x, staff_ids: x.staff_ids.length ? x.staff_ids : act.map((a) => a.id) })) }).catch(notifyError)
  }, [])
  async function save() {
    setBusy(true)
    try {
      const body = { ...f }
      Object.keys(body).forEach((k) => { if (body[k] === '') body[k] = null })
      if (kind === 'servizi') body.price = String(body.price ?? '0').replace(',', '.') || '0'
      if (kind === 'operatori' && body.last_name === null) body.last_name = ''
      if (kind === 'magazzini' && !body.code) body.code = (body.name ?? '').replace(/[^A-Za-z0-9]/g, '').slice(0, 6).toUpperCase() || 'MAG'
      const r = await appApi<any>(CFG[kind].create, { body })
      notifyOk(`${CFG[kind].one[0].toUpperCase()}${CFG[kind].one.slice(1)} creato`)
      onCreated(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Stack gap="xs" onKeyDown={(e) => { if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') { e.preventDefault(); save() } }}>
      {kind === 'magazzini' && <SimpleGrid cols={3}>
        <TextInput label="Codice" placeholder="dal nome" value={f.code} onChange={(e) => set('code', e.currentTarget.value.toUpperCase())} maxLength={20} />
        <TextInput autoFocus label="Nome" required value={f.name} onChange={(e) => set('name', e.currentTarget.value)} style={{ gridColumn: 'span 2' }} />
      </SimpleGrid>}
      {kind === 'conti' && <SimpleGrid cols={2}>
        <TextInput autoFocus label="Nome" required value={f.name} onChange={(e) => set('name', e.currentTarget.value)} placeholder="es. Cassa reception" />
        <Select label="Tipo" data={[{ value: 'cassa', label: 'Cassa (contanti, assegni)' }, { value: 'banca', label: 'Banca' }, { value: 'carta', label: 'Carta' }, { value: 'altro', label: 'Altro' }]}
          value={f.kind} onChange={(v) => set('kind', v ?? 'cassa')} allowDeselect={false} />
        {f.kind === 'banca' && <TextInput label="IBAN" value={f.iban} onChange={(e) => set('iban', e.currentTarget.value.toUpperCase())} />}
        <NumberInput label="Saldo iniziale" value={f.opening_balance} onChange={(v) => set('opening_balance', v || 0)} decimalScale={2} decimalSeparator="," suffix=" €" />
      </SimpleGrid>}
      {kind === 'operatori' && <SimpleGrid cols={3}>
        <TextInput autoFocus label="Nome" required value={f.first_name} onChange={(e) => set('first_name', e.currentTarget.value)} />
        <TextInput label="Cognome" value={f.last_name} onChange={(e) => set('last_name', e.currentTarget.value)} />
        <ColorInput label="Colore in agenda" value={f.color} onChange={(v) => set('color', v)} format="hex" />
      </SimpleGrid>}
      {kind === 'servizi' && <SimpleGrid cols={3}>
        <TextInput autoFocus label="Nome" required value={f.name} onChange={(e) => set('name', e.currentTarget.value)} style={{ gridColumn: 'span 3' }} />
        <NumberInput label="Durata (minuti)" required value={f.duration_min} onChange={(v) => set('duration_min', Number(v) || 30)} min={5} max={600} step={5} />
        <TextInput label="Prezzo (€)" required inputMode="decimal" value={f.price} onChange={(e) => set('price', e.currentTarget.value)} />
        <MultiSelect label="Chi lo esegue" data={staff.map((x) => ({ value: x.id, label: x.first_name }))} value={f.staff_ids} onChange={(v) => set('staff_ids', v)} />
      </SimpleGrid>}
      <Text size="xs" c="dimmed">Gli altri dati si completano dopo nella sua pagina.</Text>
      <Group justify="flex-end"><Button variant="default" onClick={onCancel}>Torna all'elenco</Button><Button onClick={save} loading={busy}>Salva e scegli</Button></Group>
    </Stack>
  )
}
