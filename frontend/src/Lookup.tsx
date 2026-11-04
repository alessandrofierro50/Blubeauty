// Tasto «Elenco» accanto alle caselle di inserimento (2026-11-04): apre una finestra con tutti gli elementi in ordine
// alfabetico e la ricerca in basso (nome, città, partita IVA, telefono, codice fiscale; per gli articoli codice,
// descrizione, codice a barre). Frecce per muoversi, Invio per scegliere, «Nuovo» per inserirlo senza uscire. F4 la apre.
// BluBeauty: «clienti-salone» = clienti dell'agenda (nome e cognome, cellulare, consensi) da /api/agenda/clienti;
// ListModal = stessa finestra per un elenco già caricato (prodotti della cassa, ecc.).

import { ActionIcon, Badge, Button, Checkbox, Group, Modal, Paper, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core'
import { IconList, IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'

import { appApi, fmtEuro } from './api'
import { notifyError, notifyOk } from './components'

export type LookupKind = 'clienti' | 'fornitori' | 'tutti' | 'articoli' | 'clienti-salone'

const TITLE: Record<LookupKind, string> = { clienti: 'Clienti', fornitori: 'Fornitori', tutti: 'Clienti e fornitori', articoli: 'Articoli', 'clienti-salone': 'Clienti' }
const NEW_LABEL: Record<LookupKind, string> = { clienti: 'Nuovo cliente', fornitori: 'Nuovo fornitore', tutti: 'Nuovo soggetto', articoli: 'Nuovo articolo', 'clienti-salone': 'Nuova cliente' }
const PAGE = 100

/** Tasto con l'icona elenco: da mettere accanto a una casella. */
export function LookupButton({ kind, onPick, disabled, size = 36, label }: { kind: LookupKind; onPick: (row: any) => void; disabled?: boolean; size?: number; label?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      {label ? <Button variant="light" size="xl" radius="xl" leftSection={<IconList />} onClick={() => setOpen(true)} disabled={disabled}>{label}</Button> : (
        <Tooltip label={`Elenco ${TITLE[kind].toLowerCase()} (F4)`}>
          <ActionIcon variant="light" size={size} onClick={() => setOpen(true)} disabled={disabled} aria-label={`Elenco ${TITLE[kind].toLowerCase()}`}>
            <IconList size={18} />
          </ActionIcon>
        </Tooltip>
      )}
      {open && <LookupModal kind={kind} onClose={() => setOpen(false)} onPick={(r) => { setOpen(false); onPick(r) }} />}
    </>
  )
}

export function LookupModal({ kind, onClose, onPick }: { kind: LookupKind; onClose: () => void; onPick: (row: any) => void }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [active, setActive] = useState(0)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const items = kind === 'articoli'
  const salon = kind === 'clienti-salone'

  const url = (p: number, text: string) => items
    ? `/api/anagrafiche/articoli?ordine=descrizione&page_size=${PAGE}&page=${p}${text ? '&q=' + encodeURIComponent(text) : ''}`
    : salon ? `/api/agenda/clienti?totale=true&limit=${PAGE}&offset=${(p - 1) * PAGE}${text ? '&q=' + encodeURIComponent(text) : ''}`
    : `/api/anagrafiche/soggetti?tipo=${kind}&page_size=${PAGE}&page=${p}${text ? '&q=' + encodeURIComponent(text) : ''}`

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true)
      appApi<any>(url(1, q.trim())).then((r) => { setRows(r.rows); setTotal(r.total); setPage(1); setActive(0) }).catch(notifyError).finally(() => setLoading(false))
    }, q ? 200 : 0)
    return () => clearTimeout(t)
  }, [q])

  function more() {
    if (loading || rows.length >= total) return
    setLoading(true)
    appApi<any>(url(page + 1, q.trim())).then((r) => { setRows((x) => [...x, ...r.rows]); setPage(page + 1) }).catch(notifyError).finally(() => setLoading(false))
  }
  useEffect(() => { viewport.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' }) }, [active])

  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(rows.length - 1, a + 1)); if (active > rows.length - 5) more() }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'PageDown') { e.preventDefault(); setActive((a) => Math.min(rows.length - 1, a + 10)) }
    else if (e.key === 'PageUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 10)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (rows[active]) onPick(rows[active]) }
  }

  return (
    <Modal opened onClose={onClose} size="xl" title={creating ? NEW_LABEL[kind] : `${TITLE[kind]} · ${total} in ordine alfabetico`}
      styles={{ body: { display: 'flex', flexDirection: 'column', gap: 8 } }}>
      {creating ? (
        items ? <NewItem initial={q} onCancel={() => setCreating(false)} onCreated={(r) => { notifyOk('Articolo creato'); onPick(r) }} />
          : salon ? <NewSalonClient initial={q} onCancel={() => setCreating(false)} onCreated={(r) => { notifyOk('Cliente inserita'); onPick(r) }} />
          : <NewParty kind={kind} initial={q} onCancel={() => setCreating(false)} onCreated={(r) => { notifyOk('Inserito in anagrafica'); onPick(r) }} />
      ) : (
        <>
          <Paper withBorder radius="sm">
            <ScrollArea h="55vh" viewportRef={viewport} onScrollPositionChange={({ y }) => {
              const el = viewport.current; if (el && y + el.clientHeight > el.scrollHeight - 80) more()
            }}>
              {rows.map((r, i) => (
                <UnstyledButton key={r.id} data-i={i} onClick={() => onPick(r)} onMouseEnter={() => setActive(i)} w="100%" px="sm" py={6}
                  style={{ display: 'block', background: i === active ? 'var(--mantine-color-blue-light)' : undefined, borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  {items ? (
                    <Group justify="space-between" wrap="nowrap" gap="xs">
                      <div style={{ minWidth: 0 }}>
                        <Text size="sm" fw={600} truncate>{r.description}</Text>
                        <Text size="xs" c="dimmed" truncate>{[r.code, r.category, r.brand, r.unit].filter(Boolean).join(' · ')}</Text>
                      </div>
                      {r.price != null && <Text size="sm">{fmtEuro(r.price)}</Text>}
                    </Group>
                  ) : (
                    <Group justify="space-between" wrap="nowrap" gap="xs">
                      <div style={{ minWidth: 0 }}>
                        <Text size="sm" fw={600} truncate>{r.name}</Text>
                        <Text size="xs" c="dimmed" truncate>{[r.city && `${r.city}${r.province ? ` (${r.province})` : ''}`, r.vat_number && `P.IVA ${r.vat_number}`,
                          r.tax_code && r.tax_code !== r.vat_number && `CF ${r.tax_code}`, r.phone || r.mobile].filter(Boolean).join(' · ')}</Text>
                      </div>
                      {kind === 'tutti' && <Badge size="xs" variant="light">{r.is_customer && r.is_supplier ? 'cliente e fornitore' : r.is_supplier ? 'fornitore' : 'cliente'}</Badge>}
                    </Group>
                  )}
                </UnstyledButton>
              ))}
              {!rows.length && !loading && <Text c="dimmed" ta="center" py="xl">Nessun risultato{q ? ` per «${q}»` : ''}</Text>}
              {loading && <Text c="dimmed" ta="center" py="xs" size="sm">Caricamento…</Text>}
            </ScrollArea>
          </Paper>
          <Group gap="xs" wrap="nowrap">
            <TextInput ref={searchRef} data-autofocus autoFocus style={{ flex: 1 }} leftSection={<IconSearch size={16} />} value={q} onChange={(e) => setQ(e.currentTarget.value)} onKeyDown={onKey}
              placeholder={items ? 'Cerca per descrizione, codice, codice a barre o codice del fornitore' : salon ? 'Cerca per nome, cellulare, città, partita IVA o codice fiscale' : 'Cerca per nome, città, partita IVA, telefono o codice fiscale'} />
            <Button leftSection={<IconPlus size={16} />} variant="light" onClick={() => setCreating(true)}>{NEW_LABEL[kind]}</Button>
          </Group>
          <Text size="xs" c="dimmed">Frecce per scorrere · Invio per scegliere · clic sulla riga · Esc per chiudere</Text>
        </>
      )}
    </Modal>
  )
}

const PROVINCE = /^[A-Za-z]{2}$/

function NewParty({ kind, initial, onCancel, onCreated }: { kind: LookupKind; initial: string; onCancel: () => void; onCreated: (r: any) => void }) {
  const looksVat = /^\d{11}$/.test(initial.trim())
  const [f, setF] = useState<any>({ person_type: 'azienda', name: looksVat ? '' : initial, first_name: '', last_name: '', vat_number: looksVat ? initial.trim() : '',
    tax_code: '', address: '', zip_code: '', city: '', province: '', phone: '', email: '', sdi_code: '', pec: '', is_supplier: kind === 'fornitori' })
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const privato = f.person_type === 'privato'
  async function save() {
    if (f.province && !PROVINCE.test(f.province)) return notifyError(new Error('Provincia: la sigla di 2 lettere'))
    setBusy(true)
    try {
      const body = { ...f, is_customer: kind !== 'fornitori' || undefined, is_supplier: kind === 'fornitori' || f.is_supplier,
        name: privato ? undefined : f.name, first_name: privato ? f.first_name : undefined, last_name: privato ? f.last_name : undefined }
      Object.keys(body).forEach((k) => { if (body[k] === '' || body[k] === undefined) delete body[k] })
      const r = await appApi<any>('/api/anagrafiche/soggetti', { body })
      onCreated(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Stack gap="xs" onKeyDown={(e) => { if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') { e.preventDefault(); save() } }}>
      <SegmentedControl value={f.person_type} onChange={(v) => set('person_type', v)} data={[{ value: 'azienda', label: 'Azienda' }, { value: 'privato', label: 'Privato' }]} />
      {privato ? (
        <SimpleGrid cols={2}><TextInput autoFocus label="Cognome" value={f.last_name} onChange={(e) => set('last_name', e.currentTarget.value)} required />
          <TextInput label="Nome" value={f.first_name} onChange={(e) => set('first_name', e.currentTarget.value)} required /></SimpleGrid>
      ) : <TextInput autoFocus label="Ragione sociale" value={f.name} onChange={(e) => set('name', e.currentTarget.value)} required />}
      <SimpleGrid cols={2}>
        {!privato && <TextInput label="Partita IVA" value={f.vat_number} onChange={(e) => set('vat_number', e.currentTarget.value)} />}
        <TextInput label="Codice fiscale" value={f.tax_code} onChange={(e) => set('tax_code', e.currentTarget.value.toUpperCase())} />
        <TextInput label="Telefono" value={f.phone} onChange={(e) => set('phone', e.currentTarget.value)} />
        <TextInput label="Email" value={f.email} onChange={(e) => set('email', e.currentTarget.value)} />
      </SimpleGrid>
      <SimpleGrid cols={4}>
        <TextInput label="Indirizzo" value={f.address} onChange={(e) => set('address', e.currentTarget.value)} style={{ gridColumn: 'span 2' }} />
        <TextInput label="CAP" value={f.zip_code} onChange={(e) => set('zip_code', e.currentTarget.value)} />
        <TextInput label="Prov." value={f.province} maxLength={2} onChange={(e) => set('province', e.currentTarget.value.toUpperCase())} />
        <TextInput label="Città" value={f.city} onChange={(e) => set('city', e.currentTarget.value)} style={{ gridColumn: 'span 2' }} />
        {!privato && <TextInput label="Codice SDI" value={f.sdi_code} maxLength={7} onChange={(e) => set('sdi_code', e.currentTarget.value.toUpperCase())} />}
        {!privato && <TextInput label="PEC" value={f.pec} onChange={(e) => set('pec', e.currentTarget.value)} />}
      </SimpleGrid>
      <Text size="xs" c="dimmed">Gli altri dati (pagamento, listino, fido, destinazioni) si completano dopo in Anagrafiche.</Text>
      <Group justify="flex-end"><Button variant="default" onClick={onCancel}>Torna all'elenco</Button><Button onClick={save} loading={busy}>Salva e scegli</Button></Group>
    </Stack>
  )
}

export function NewItem({ initial, onCancel, onCreated }: { initial: string; onCancel: () => void; onCreated: (r: any) => void }) {
  const [f, setF] = useState<any>({ code: '', description: initial, unit: 'PZ', vat_rate_id: null, price: '', item_type: 'articolo' })
  const [vats, setVats] = useState<any[]>([])
  const [list, setList] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  useEffect(() => {
    appApi<any[]>('/api/anagrafiche/tabelle/aliquote-iva').then((v) => {
      const act = v.filter((x) => x.active !== false); setVats(act)
      setF((x: any) => ({ ...x, vat_rate_id: x.vat_rate_id ?? act.find((a) => a.code === '22')?.id ?? act[0]?.id ?? null }))
    }).catch(notifyError)
    appApi<any[]>('/api/anagrafiche/tabelle/listini').then((l) => setList(l.find((x) => x.is_default) ?? l[0] ?? null)).catch(notifyError)
  }, [])
  async function save() {
    setBusy(true)
    try {
      const price = String(f.price).replace(',', '.')
      const body: any = { code: f.code || null, description: f.description, unit: f.unit || 'PZ', vat_rate_id: f.vat_rate_id, item_type: f.item_type,
        stock_managed: f.item_type === 'articolo', prices: list && price ? [{ price_list_id: list.id, price }] : [] }
      const r = await appApi<any>('/api/anagrafiche/articoli', { body })
      onCreated(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Stack gap="xs" onKeyDown={(e) => { if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') { e.preventDefault(); save() } }}>
      <SegmentedControl value={f.item_type} onChange={(v) => set('item_type', v)} data={[{ value: 'articolo', label: 'Articolo (magazzino)' }, { value: 'servizio', label: 'Servizio' }]} />
      <SimpleGrid cols={3}>
        <TextInput label="Codice" placeholder="automatico" value={f.code} onChange={(e) => set('code', e.currentTarget.value.toUpperCase())} />
        <TextInput autoFocus label="Descrizione" required value={f.description} onChange={(e) => set('description', e.currentTarget.value)} style={{ gridColumn: 'span 2' }} />
        <TextInput label="Unità di misura" value={f.unit} onChange={(e) => set('unit', e.currentTarget.value.toUpperCase())} />
        <Select label="IVA" data={vats.map((v) => ({ value: v.id, label: v.description ?? v.code }))} value={f.vat_rate_id} onChange={(v) => set('vat_rate_id', v)} />
        <TextInput label={`Prezzo${list ? ` (${list.name}${list.vat_included ? ', IVA inclusa' : ''})` : ''}`} value={f.price} inputMode="decimal"
          onChange={(e) => set('price', e.currentTarget.value)} />
      </SimpleGrid>
      <Text size="xs" c="dimmed">Fornitori, codici a barre, scorte e foto si completano dopo in Anagrafiche › Articoli.</Text>
      <Group justify="flex-end"><Button variant="default" onClick={onCancel}>Torna all'elenco</Button><Button onClick={save} loading={busy}>Salva e scegli</Button></Group>
    </Stack>
  )
}

/** Cliente nuova del salone: nome, cognome, cellulare (conferme WhatsApp) e consenso alle offerte. */
function NewSalonClient({ initial, onCancel, onCreated }: { initial: string; onCancel: () => void; onCreated: (r: any) => void }) {
  const phone = /^[+\d\s]{6,}$/.test(initial.trim())
  const [first, ...rest] = phone ? [''] : initial.trim().split(/\s+/)
  const [f, setF] = useState({ first_name: first ?? '', last_name: rest.join(' '), mobile: phone ? initial.trim() : '', email: '', marketing: false })
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: any) => setF((x) => ({ ...x, [k]: v }))
  async function save() {
    if (!f.first_name.trim() || !f.last_name.trim()) return notifyError(new Error('Scrivi nome e cognome'))
    setBusy(true)
    try {
      const r = await appApi<any>('/api/agenda/clienti', { body: { ...f, mobile: f.mobile || null, email: f.email || null, privacy: true } })
      onCreated(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Stack gap="xs" onKeyDown={(e) => { if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') { e.preventDefault(); save() } }}>
      <SimpleGrid cols={2}>
        <TextInput autoFocus label="Nome" required value={f.first_name} onChange={(e) => set('first_name', e.currentTarget.value)} />
        <TextInput label="Cognome" required value={f.last_name} onChange={(e) => set('last_name', e.currentTarget.value)} />
        <TextInput label="Cellulare" description="per conferme e promemoria su WhatsApp" inputMode="tel" value={f.mobile} onChange={(e) => set('mobile', e.currentTarget.value)} />
        <TextInput label="Email" value={f.email} onChange={(e) => set('email', e.currentTarget.value)} />
      </SimpleGrid>
      <Checkbox label="Consenso a ricevere offerte su WhatsApp" checked={f.marketing} onChange={(e) => set('marketing', e.currentTarget.checked)} />
      <Text size="xs" c="dimmed">Compleanno, note e dati per la fattura si completano dopo nella scheda della cliente.</Text>
      <Group justify="flex-end"><Button variant="default" onClick={onCancel}>Torna all'elenco</Button><Button onClick={save} loading={busy}>Salva e scegli</Button></Group>
    </Stack>
  )
}

/** Stessa finestra «Elenco» per un elenco già caricato (es. i prodotti del listino della cassa): ordine alfabetico,
 *  ricerca in basso, frecce e Invio; `renderNew` (facoltativo) mostra il modulo «Nuovo». */
export function ListModal<T extends { id: string }>({ title, rows, label, sub, right, onPick, onClose, newLabel, renderNew }: {
  title: string; rows: T[]; label: (r: T) => string; sub?: (r: T) => string | null | undefined; right?: (r: T) => React.ReactNode
  onPick: (r: T) => void; onClose: () => void; newLabel?: string; renderNew?: (initial: string, back: () => void) => React.ReactNode
}) {
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const [creating, setCreating] = useState(false)
  const viewport = useRef<HTMLDivElement>(null)
  const needle = q.trim().toLowerCase()
  const list = [...rows].sort((a, b) => label(a).localeCompare(label(b), 'it'))
    .filter((r) => !needle || `${label(r)} ${sub?.(r) ?? ''}`.toLowerCase().includes(needle))
  useEffect(() => { setActive(0) }, [q])
  useEffect(() => { viewport.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' }) }, [active])
  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(list.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'PageDown') { e.preventDefault(); setActive((a) => Math.min(list.length - 1, a + 10)) }
    else if (e.key === 'PageUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 10)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (list[active]) onPick(list[active]) }
  }
  return (
    <Modal opened onClose={onClose} size="lg" title={creating ? (newLabel ?? 'Nuovo') : `${title} · ${rows.length} in ordine alfabetico`}>
      {creating && renderNew ? renderNew(q, () => setCreating(false)) : (
        <Stack gap={8}>
          <Paper withBorder radius="sm">
            <ScrollArea h="45vh" viewportRef={viewport}>
              {list.map((r, i) => (
                <UnstyledButton key={r.id} data-i={i} w="100%" px="sm" py={7} onClick={() => onPick(r)} onMouseEnter={() => setActive(i)}
                  style={{ display: 'block', background: i === active ? 'var(--mantine-color-blue-light)' : undefined, borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  <Group justify="space-between" wrap="nowrap" gap="xs">
                    <div style={{ minWidth: 0 }}>
                      <Text size="sm" fw={600} truncate>{label(r)}</Text>
                      {sub?.(r) && <Text size="xs" c="dimmed" truncate>{sub(r)}</Text>}
                    </div>
                    {right?.(r)}
                  </Group>
                </UnstyledButton>
              ))}
              {!list.length && <Text c="dimmed" ta="center" py="xl">Nessun risultato{q ? ` per «${q}»` : ''}{renderNew ? ': crealo con «Nuovo»' : ''}</Text>}
            </ScrollArea>
          </Paper>
          <Group gap="xs" wrap="nowrap">
            <TextInput autoFocus data-autofocus style={{ flex: 1 }} leftSection={<IconSearch size={16} />} placeholder="Cerca" value={q}
              onChange={(e) => setQ(e.currentTarget.value)} onKeyDown={onKey} />
            {renderNew && <Button variant="light" leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>{newLabel ?? 'Nuovo'}</Button>}
          </Group>
          <Text size="xs" c="dimmed">Frecce per scorrere · Invio per scegliere · clic sulla riga · Esc per chiudere</Text>
        </Stack>
      )}
    </Modal>
  )
}
