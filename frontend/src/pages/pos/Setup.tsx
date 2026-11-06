// Configurazione della vendita al banco: casse (con tasti rapidi), reparti, codici della bilancia.

import {
  ActionIcon, Alert, Badge, Button, Group, Modal, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table,
  Tabs, TagsInput, Text, TextInput,
} from '@mantine/core'
import { IconArrowDown, IconArrowUp, IconCash, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { P } from './shared'

const COLORS = ['blue', 'teal', 'green', 'lime', 'yellow', 'orange', 'red', 'pink', 'grape', 'violet', 'indigo', 'cyan', 'gray']

export default function Setup() {
  const { tab } = useParams()
  const nav = useNavigate()
  return (
    <>
      <PageTitle title="Casse e reparti" subtitle="Postazioni di vendita al banco, tasti rapidi, reparti e bilance"
        right={<Button leftSection={<IconCash size={16} />} onClick={() => nav('/cassa')}>Apri la cassa</Button>} />
      <Tabs value={tab ?? 'casse'} onChange={(v) => nav(v === 'casse' ? '/pos/casse' : `/pos/casse/${v}`)} mb="md">
        <Tabs.List><Tabs.Tab value="casse">Casse</Tabs.Tab><Tabs.Tab value="reparti">Reparti</Tabs.Tab><Tabs.Tab value="bilancia">Bilancia e opzioni</Tabs.Tab></Tabs.List>
      </Tabs>
      {tab === 'reparti' ? <Departments /> : tab === 'bilancia' ? <ScaleSettings /> : <Registers />}
    </>
  )
}

// ====================================================================== casse

function Registers() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [edit, setEdit] = useState<any>(null)
  const load = () => P('/casse').then(setRows).catch(notifyError)
  useEffect(() => { load() }, [])
  if (!rows) return <Loading />
  return (
    <Paper withBorder>
      <Group justify="space-between" p="sm"><Text c="dimmed" size="sm">Ogni cassa scarica il magazzino indicato e incassa sui conti scelti (contanti e carte).</Text>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEdit({})}>Nuova cassa</Button></Group>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Codice</Table.Th><Table.Th>Nome</Table.Th><Table.Th>Punto vendita / magazzino</Table.Th><Table.Th>Modalità</Table.Th><Table.Th>Stato</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.id} opacity={r.active ? 1 : 0.5}>
              <Table.Td ff="monospace">{r.code}</Table.Td>
              <Table.Td fw={500}>{r.name}</Table.Td>
              <Table.Td>{r.store_name ?? '—'} · {r.warehouse_name}</Table.Td>
              <Table.Td><Badge variant="light" color={r.mode === 'supermercato' ? 'orange' : 'blue'}>{r.mode === 'supermercato' ? 'supermercato (tastiera)' : 'negozio (touch)'}</Badge></Table.Td>
              <Table.Td>{!r.active ? <Badge color="gray">disattivata</Badge> : r.session ? <Badge color="green">aperta da {r.session.opened_by}</Badge> : <Badge color="gray" variant="light">chiusa</Badge>}</Table.Td>
              <Table.Td ta="right"><ActionIcon variant="subtle" onClick={() => setEdit(r)}><IconPencil size={16} /></ActionIcon></Table.Td>
            </Table.Tr>
          ))}
          {!rows.length && <Table.Tr><Table.Td colSpan={6}><Text c="dimmed" ta="center" py="lg">Nessuna cassa: creane una per iniziare a vendere al banco.</Text></Table.Td></Table.Tr>}
        </Table.Tbody>
      </Table>
      {edit && <RegisterEditor reg={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load() }} />}
    </Paper>
  )
}

function RegisterEditor({ reg, onClose, onSaved }: { reg: any; onClose: () => void; onSaved: () => void }) {
  const isNew = !reg.id
  const [r, setR] = useState<any>({ code: '', name: '', store_id: null, warehouse_id: null, price_list_id: null, mode: 'negozio', cash_account_id: null,
    card_account_id: null, quick_keys: [], settings: {}, devices: {}, active: true, ...reg })
  const [L, setL] = useState<any>(null)
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    Promise.all([appApi('/api/magazzino/magazzini'), appApi('/api/magazzino/punti-vendita'), appApi('/api/anagrafiche/tabelle/listini'),
      appApi('/api/scadenzario/conti').catch(() => []), P('/reparti'), appApi('/api/periferiche/dispositivi').catch(() => null)])
      .then(([w, st, pl, acc, deps, devs]) => {
        setL({ whs: w.rows, stores: st, lists: pl, accounts: acc.filter((a: any) => a.active), deps, devs })
        if (isNew && w.rows.length) setR((x: any) => ({ ...x, warehouse_id: x.warehouse_id ?? w.rows[0].id }))
      }).catch(notifyError)
  }, [])
  useEffect(() => {
    if (q.trim().length < 2) { setFound([]); return }
    const t = setTimeout(() => appApi(`/api/anagrafiche/articoli?q=${encodeURIComponent(q)}&page_size=10`).then((x) => setFound(x.rows)).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [q])
  if (!L) return <Modal opened onClose={onClose} title="Cassa"><Loading /></Modal>
  const set = (k: string, v: any) => setR({ ...r, [k]: v })
  const keys: any[] = r.quick_keys
  const move = (i: number, d: number) => { const k = [...keys]; const [x] = k.splice(i, 1); k.splice(i + d, 0, x); set('quick_keys', k) }
  const addKey = (k: any) => { if (!keys.some((x) => x.type === k.type && x.id === k.id)) set('quick_keys', [...keys, k]); setQ('') }
  async function save() {
    setBusy(true)
    try {
      const body = { ...r, code: r.code.trim(), quick_keys: keys.map((k) => ({ type: k.type, id: k.id, label: k.label, color: k.color || null })) }
      for (const k of ['id', 'session', 'store_name', 'warehouse_name']) delete body[k]
      body.devices = Object.fromEntries(Object.entries(r.devices || {}).filter(([, v]) => v))
      await (isNew ? P('/casse', { body }) : P(`/casse/${r.id}`, { method: 'PUT', body }))
      notifyOk('Cassa salvata')
      onSaved()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function remove() {
    if (!window.confirm('Eliminare la cassa? Se ha già venduto viene solo disattivata.')) return
    try { await P(`/casse/${r.id}`, { method: 'DELETE' }); onSaved() } catch (e) { notifyError(e) }
  }
  const accOpts = (kinds: string[]) => L.accounts.filter((a: any) => kinds.includes(a.kind)).map((a: any) => ({ value: a.id, label: a.name }))
  return (
    <Modal opened onClose={onClose} title={isNew ? 'Nuova cassa' : `Cassa ${reg.code}`} size="xl">
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <TextInput label="Codice" required maxLength={10} value={r.code} onChange={(e) => set('code', e.currentTarget.value.toUpperCase())} />
        <TextInput label="Nome" required value={r.name} onChange={(e) => set('name', e.currentTarget.value)} placeholder="es. Cassa 1" />
        <Select label="Punto vendita" data={L.stores.map((s: any) => ({ value: s.id, label: s.name }))} value={r.store_id} clearable
          onChange={(v) => { const st = L.stores.find((s: any) => s.id === v); setR({ ...r, store_id: v, warehouse_id: st?.warehouse_id ?? r.warehouse_id }) }} />
        <Select label="Magazzino da scaricare" required data={L.whs.map((w: any) => ({ value: w.id, label: w.name }))} value={r.warehouse_id} onChange={(v) => set('warehouse_id', v)} allowDeselect={false} />
        <Select label="Listino" description="Vuoto: il listino predefinito" data={L.lists.map((p: any) => ({ value: p.id, label: `${p.name}${p.vat_included ? ' (IVA incl.)' : ''}` }))} value={r.price_list_id} onChange={(v) => set('price_list_id', v)} clearable />
        <div>
          <Text size="sm" fw={500} mb={4}>Modalità</Text>
          <SegmentedControl fullWidth value={r.mode} onChange={(v) => set('mode', v)} data={[{ value: 'negozio', label: 'Negozio (touch)' }, { value: 'supermercato', label: 'Supermercato' }]} />
        </div>
        <Select label="Conto per i contanti" description="Vuoto: la cassa predefinita" data={accOpts(['cassa'])} value={r.cash_account_id} onChange={(v) => set('cash_account_id', v)} clearable />
        <Select label="Conto per carte e POS" description="Vuoto: la banca predefinita" data={accOpts(['banca', 'carta', 'altro'])} value={r.card_account_id} onChange={(v) => set('card_account_id', v)} clearable />
        <Stack gap={6} mt="lg">
          <Switch label="Stampa la ricevuta di cortesia a ogni vendita" checked={!!r.settings.auto_print} onChange={(e) => set('settings', { ...r.settings, auto_print: e.currentTarget.checked })} />
          <Switch label="Consenti la ricevuta non fiscale al posto dello scontrino" checked={r.settings.nonfiscal_allowed !== false}
            onChange={(e) => set('settings', { ...r.settings, nonfiscal_allowed: e.currentTarget.checked })} />
          <Switch label="Cassa attiva" checked={r.active} onChange={(e) => set('active', e.currentTarget.checked)} />
        </Stack>
      </SimpleGrid>
      {L.devs && (
        <>
          <Text fw={600} mt="lg" mb="xs">Periferiche</Text>
          {L.devs.length === 0 ? <Text size="sm" c="dimmed">Nessuna periferica: si collegano in «Computer e periferiche».</Text> : (
            <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
              {([['rt', 'rt', 'Registratore telematico'], ['printer', 'stampante', 'Stampante di ricevute'], ['scale', 'bilancia', 'Bilancia'], ['cash', 'cassa_auto', 'Cassa automatica']] as const).map(([role, kind, label]) => (
                <Select key={role} label={label} clearable value={r.devices?.[role] ?? null} placeholder="Nessuno"
                  data={L.devs.filter((d: any) => d.kind === kind).map((d: any) => ({ value: d.id, label: `${d.name} · ${d.agent_name}` }))}
                  onChange={(v) => set('devices', { ...(r.devices || {}), [role]: v })} />
              ))}
            </SimpleGrid>
          )}
          {r.devices?.rt && <Switch mt="sm" label="Alla chiusura di cassa esegui la chiusura giornaliera (Z) sul registratore" checked={r.settings.z_on_close !== false}
            onChange={(e) => set('settings', { ...r.settings, z_on_close: e.currentTarget.checked })} />}
        </>
      )}
      {r.mode === 'supermercato' && <Alert mt="md" color="blue" variant="light">In modalità supermercato il campo codice resta sempre attivo per il lettore; «3*» moltiplica, gli importi dei reparti si possono digitare in centesimi (250 = 2,50 €) e i tasti F2–F12 richiamano le funzioni.</Alert>}

      <Text fw={600} mt="lg" mb="xs">Tasti rapidi</Text>
      <Stack gap="sm">
        <Stack gap={6}>
          <TextInput placeholder="Cerca un articolo da aggiungere" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
          {found.map((it) => <Button key={it.id} variant="subtle" justify="flex-start" size="xs" onClick={() => addKey({ type: 'item', id: it.id, label: it.description.slice(0, 30) })}>{it.code} · {it.description}</Button>)}
          <Group gap={6}>{L.deps.filter((d: any) => d.active).map((d: any) => <Button key={d.id} size="xs" variant="light" color={d.color || 'gray'} onClick={() => addKey({ type: 'department', id: d.id, label: d.name, color: d.color })}>+ reparto {d.name}</Button>)}</Group>
        </Stack>
        <Table verticalSpacing={4}>
          <Table.Tbody>
            {keys.map((k, i) => (
              <Table.Tr key={k.type + k.id}>
                <Table.Td w={100}><Badge size="sm" variant="light" color={k.type === 'item' ? 'blue' : 'grape'}>{k.type === 'item' ? 'articolo' : 'reparto'}</Badge></Table.Td>
                <Table.Td><TextInput size="xs" value={k.label} maxLength={30} onChange={(e) => set('quick_keys', keys.map((x, n) => (n === i ? { ...x, label: e.currentTarget.value } : x)))} /></Table.Td>
                <Table.Td w={140}><Select size="xs" data={COLORS} value={k.color ?? null} placeholder="colore" clearable onChange={(v) => set('quick_keys', keys.map((x, n) => (n === i ? { ...x, color: v } : x)))} /></Table.Td>
                <Table.Td w={90}>
                  <Group gap={0} wrap="nowrap">
                    <ActionIcon size="sm" variant="subtle" disabled={i === 0} onClick={() => move(i, -1)}><IconArrowUp size={14} /></ActionIcon>
                    <ActionIcon size="sm" variant="subtle" disabled={i === keys.length - 1} onClick={() => move(i, 1)}><IconArrowDown size={14} /></ActionIcon>
                    <ActionIcon size="sm" variant="subtle" color="red" onClick={() => set('quick_keys', keys.filter((_, n) => n !== i))}><IconTrash size={14} /></ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
            {!keys.length && <Table.Tr><Table.Td><Text size="sm" c="dimmed">Nessun tasto: aggiungi articoli o reparti</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Stack>
      <Group justify="space-between" mt="xl">
        {!isNew ? <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} onClick={remove}>Elimina</Button> : <span />}
        <Group><Button variant="default" onClick={onClose}>Annulla</Button><Button loading={busy} disabled={!r.code || !r.name || !r.warehouse_id} onClick={save}>Salva</Button></Group>
      </Group>
    </Modal>
  )
}

// ====================================================================== reparti

function Departments() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [vats, setVats] = useState<any[]>([])
  const [edit, setEdit] = useState<any>(null)
  const load = () => P('/reparti').then(setRows).catch(notifyError)
  useEffect(() => { load(); appApi('/api/anagrafiche/tabelle/aliquote-iva').then((v) => setVats(v.filter((x: any) => x.active))).catch(() => {}) }, [])
  async function save() {
    try {
      const body = { code: edit.code, name: edit.name, vat_rate_id: edit.vat_rate_id, rt_department: edit.rt_department || null, color: edit.color || null,
        sort_order: Number(edit.sort_order || 0), active: edit.active !== false }
      await (edit.id ? P(`/reparti/${edit.id}`, { method: 'PUT', body }) : P('/reparti', { body }))
      setEdit(null); load()
    } catch (e) { notifyError(e) }
  }
  async function remove(d: any) {
    try { await P(`/reparti/${d.id}`, { method: 'DELETE' }); load() } catch (e) { notifyError(e) }
  }
  if (!rows) return <Loading />
  return (
    <Paper withBorder>
      <Group justify="space-between" p="sm">
        <Text c="dimmed" size="sm">I reparti servono per vendere a importo libero (es. ortofrutta) e per raggruppare i corrispettivi sul registratore telematico.</Text>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEdit({ code: '', name: '', vat_rate_id: vats.find((v) => v.code === '22')?.id ?? null, sort_order: (rows.length + 1) * 10, active: true })}>Nuovo reparto</Button>
      </Group>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Codice</Table.Th><Table.Th>Nome</Table.Th><Table.Th>IVA</Table.Th><Table.Th>Reparto RT</Table.Th><Table.Th>Colore</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((d) => (
            <Table.Tr key={d.id} opacity={d.active ? 1 : 0.5}>
              <Table.Td ff="monospace">{d.code}</Table.Td><Table.Td fw={500}>{d.name}{!d.active && <Badge ml="xs" size="xs" color="gray">disattivato</Badge>}</Table.Td>
              <Table.Td>{d.vat_label ?? '—'}</Table.Td><Table.Td>{d.rt_department ?? '—'}</Table.Td>
              <Table.Td>{d.color && <Badge color={d.color} variant="light">{d.color}</Badge>}</Table.Td>
              <Table.Td ta="right">
                <ActionIcon variant="subtle" onClick={() => setEdit(d)}><IconPencil size={16} /></ActionIcon>
                <ActionIcon variant="subtle" color="red" onClick={() => remove(d)}><IconTrash size={16} /></ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
          {!rows.length && <Table.Tr><Table.Td colSpan={6}><Text c="dimmed" ta="center" py="lg">Nessun reparto</Text></Table.Td></Table.Tr>}
        </Table.Tbody>
      </Table>
      {edit && (
        <Modal opened onClose={() => setEdit(null)} title={edit.id ? `Reparto ${edit.code}` : 'Nuovo reparto'}>
          <Stack>
            <Group grow>
              <TextInput label="Codice" maxLength={10} value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.currentTarget.value.toUpperCase() })} />
              <NumberInput label="N. reparto sul registratore" min={1} max={99} value={edit.rt_department ?? ''} onChange={(v) => setEdit({ ...edit, rt_department: v })} />
            </Group>
            <TextInput label="Nome" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.currentTarget.value })} />
            <Select label="Aliquota IVA" data={vats.map((v) => ({ value: v.id, label: v.description }))} value={edit.vat_rate_id} onChange={(v) => setEdit({ ...edit, vat_rate_id: v })} />
            <Group grow>
              <Select label="Colore del tasto" data={COLORS} value={edit.color ?? null} onChange={(v) => setEdit({ ...edit, color: v })} clearable />
              <NumberInput label="Ordine" value={edit.sort_order} onChange={(v) => setEdit({ ...edit, sort_order: v })} />
            </Group>
            <Switch label="Attivo" checked={edit.active !== false} onChange={(e) => setEdit({ ...edit, active: e.currentTarget.checked })} />
            <Group justify="flex-end"><Button variant="default" onClick={() => setEdit(null)}>Annulla</Button><Button disabled={!edit.code || !edit.name} onClick={save}>Salva</Button></Group>
          </Stack>
        </Modal>
      )}
    </Paper>
  )
}

// ====================================================================== bilancia e opzioni

function ScaleSettings() {
  const [s, setS] = useState<any>(null)
  const [test, setTest] = useState('')
  useEffect(() => { P('/impostazioni').then(setS).catch(notifyError) }, [])
  if (!s) return <Loading />
  const sc = s.scale_barcode
  const setSc = (k: string, v: any) => setS({ ...s, scale_barcode: { ...sc, [k]: v } })
  async function save() {
    try { setS(await P('/impostazioni', { method: 'PUT', body: s })); notifyOk('Impostazioni salvate') } catch (e) { notifyError(e) }
  }
  const pd = Number(sc.plu_digits), vd = Number(sc.value_digits)
  const example = `${sc.prefixes?.[0] ?? '21'}${'1'.padStart(pd, '0')}${'1250'.padStart(vd, '0')}`.padEnd(13, '0').slice(0, 13)
  let parsed: string | null = null
  if (/^\d{13}$/.test(test)) {
    const ok = (sc.prefixes || []).some((p: string) => test.startsWith(p))
    if (!ok) parsed = 'Il prefisso non è tra quelli delle bilance: verrà cercato come codice a barre normale'
    else {
      const plu = test.slice(2, 2 + pd).replace(/^0+/, '') || '0'
      const val = Number(test.slice(2 + pd, 2 + pd + vd))
      parsed = `PLU ${plu} · ${sc.value === 'prezzo' ? `importo ${(val / 100).toFixed(2).replace('.', ',')} €` : `peso ${(val / 1000).toLocaleString('it-IT')} kg`}`
    }
  }
  return (
    <Paper withBorder p="md" maw={760}>
      <Text fw={600} mb={4}>Etichette delle bilance (EAN-13 a peso o prezzo variabile)</Text>
      <Text size="sm" c="dimmed" mb="md">Struttura: prefisso (2 cifre) + PLU dell'articolo + peso in grammi o importo in centesimi + cifra di controllo. Il PLU si imposta nella scheda articolo.</Text>
      <Switch label="Leggi i codici delle bilance" checked={sc.enabled} onChange={(e) => setSc('enabled', e.currentTarget.checked)} mb="md" />
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <TagsInput label="Prefissi" description="Di solito 20-29" value={sc.prefixes} onChange={(v) => setSc('prefixes', v.filter((x) => /^\d{2}$/.test(x)))} />
        <div>
          <Text size="sm" fw={500} mb={4}>Il codice contiene</Text>
          <SegmentedControl fullWidth value={sc.value} onChange={(v) => setSc('value', v)} data={[{ value: 'peso', label: 'il peso' }, { value: 'prezzo', label: "l'importo" }]} />
        </div>
        <NumberInput label="Cifre del PLU" min={4} max={6} value={sc.plu_digits} onChange={(v) => setSc('plu_digits', Number(v))} />
        <NumberInput label={sc.value === 'prezzo' ? "Cifre dell'importo" : 'Cifre del peso'} min={4} max={6} value={sc.value_digits} onChange={(v) => setSc('value_digits', Number(v))} />
      </SimpleGrid>
      {pd + vd !== 10 && <Alert color="yellow" mt="sm">PLU e valore devono occupare insieme 10 cifre (13 meno prefisso e controllo).</Alert>}
      <Group mt="md" align="flex-end">
        <TextInput label="Prova un codice" placeholder={example} value={test} onChange={(e) => setTest(e.currentTarget.value.trim())} w={220} />
        {parsed && <Text size="sm" mb={8}>{parsed}</Text>}
      </Group>
      <Text fw={600} mt="xl" mb="xs">Altre opzioni</Text>
      <Switch label="Chiedi il codice lotteria degli scontrini" checked={!!s.lottery} onChange={(e) => setS({ ...s, lottery: e.currentTarget.checked })} />
      <Group justify="flex-end" mt="lg"><Button onClick={save} disabled={pd + vd !== 10}>Salva</Button></Group>
    </Paper>
  )
}
