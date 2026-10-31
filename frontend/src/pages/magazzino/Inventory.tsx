import { ActionIcon, Alert, Anchor, Badge, Button, Checkbox, Collapse, FileButton, Group, Modal, MultiSelect, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title, Tooltip } from '@mantine/core'
import { IconArrowLeft, IconChevronDown, IconChevronRight, IconDeviceMobile, IconPlus, IconUpload } from '@tabler/icons-react'
import QRCode from 'qrcode'
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { fmtDate, fmtEuro, tokens } from '../../api'
import { Loading, PageTitle, Stat, notifyError, notifyOk } from '../../components'
import { categoryOptions, useLookups } from '../anagrafiche/shared'
import { W, qty, useWarehouses } from './shared'

const STATUS: Record<string, string> = { aperto: 'green', chiuso: 'gray', annullato: 'red' }

export function InventoryList() {
  const nav = useNavigate()
  const whs = useWarehouses()
  const L = useLookups()
  const [rows, setRows] = useState<any[] | null>(null)
  const [opened, setOpened] = useState(false)
  const [f, setF] = useState<any>({ name: '', warehouse_id: null, category_ids: [], location_prefix: '', zero_uncounted: false })
  useEffect(() => { W('/inventari').then(setRows).catch(notifyError) }, [])
  useEffect(() => { if (whs?.length && !f.warehouse_id) setF((x: any) => ({ ...x, warehouse_id: whs[0].id, name: `Inventario ${new Date().toLocaleDateString('it-IT')}` })) }, [whs])

  async function create() {
    try {
      const r = await W('/inventari', { body: { ...f, location_prefix: f.location_prefix || null } })
      nav(`/magazzino/inventari/${r.id}`)
    } catch (e) { notifyError(e) }
  }

  return (
    <>
      <PageTitle title="Inventari" subtitle="Conta con lo smartphone, controlla da qui e conferma le rettifiche"
        right={<Button leftSection={<IconPlus size={16} />} onClick={() => setOpened(true)}>Nuovo inventario</Button>} />
      {!rows ? <Loading /> : (
        <Paper withBorder>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead><Table.Tr><Table.Th>Inventario</Table.Th><Table.Th>Magazzino</Table.Th><Table.Th>Aperto il</Table.Th><Table.Th ta="right">Conteggi</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/magazzino/inventari/${r.id}`)}>
                  <Table.Td fw={600}>{r.name}</Table.Td><Table.Td>{r.warehouse}</Table.Td><Table.Td>{fmtDate(r.opened_at.slice(0, 10))}</Table.Td>
                  <Table.Td ta="right">{r.counts}</Table.Td><Table.Td><Badge color={STATUS[r.status]} variant="light">{r.status}</Badge></Table.Td>
                </Table.Tr>
              ))}
              {rows.length === 0 && <Table.Tr><Table.Td colSpan={5}><Text ta="center" c="dimmed" py="lg">Nessun inventario</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      <Modal opened={opened} onClose={() => setOpened(false)} title="Nuovo inventario">
        <Stack>
          <TextInput label="Nome" value={f.name} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
          {whs && <Select label="Magazzino" data={whs.map((w) => ({ value: w.id, label: w.name }))} value={f.warehouse_id} onChange={(v) => setF({ ...f, warehouse_id: v })} allowDeselect={false} />}
          {L && <MultiSelect label="Solo queste categorie" placeholder="tutte" data={categoryOptions(L.categories)} value={f.category_ids} onChange={(v) => setF({ ...f, category_ids: v })} searchable clearable />}
          <TextInput label="Solo ubicazioni che iniziano con" placeholder="es. A- (vuoto = tutte)" value={f.location_prefix} onChange={(e) => setF({ ...f, location_prefix: e.currentTarget.value })} />
          <Group justify="flex-end"><Button onClick={create} disabled={!f.name || !f.warehouse_id}>Crea</Button></Group>
        </Stack>
      </Modal>
    </>
  )
}

export function InventoryReview() {
  const { id } = useParams()
  const nav = useNavigate()
  const [d, setD] = useState<any>(null)
  const [show, setShow] = useState('contati')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [edits, setEdits] = useState<Record<string, number | string>>({})
  const [qr, setQr] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [zeroChoice, setZeroChoice] = useState<'si' | 'no' | null>(null)
  const load = () => W(`/inventari/${id}`).then((r) => { setD(r); setEdits({}) }).catch(notifyError)
  const editsRef = useRef(edits)
  editsRef.current = edits
  useEffect(() => {
    load()
    // aggiornamento automatico mentre gli operatori contano (sospeso se stai correggendo)
    const t = setInterval(() => { if (!Object.keys(editsRef.current).length) W(`/inventari/${id}`).then(setD).catch(() => {}) }, 15000)
    return () => clearInterval(t)
  }, [id])
  const mobileUrl = `${window.location.origin}/conta/${id}`
  useEffect(() => { QRCode.toDataURL(mobileUrl, { margin: 1, width: 220 }).then(setQr).catch(() => {}) }, [mobileUrl])

  const key = (r: any) => `${r.item_id}|${r.variant_id ?? ''}|${r.lot_number ?? ''}`
  const rows = useMemo(() => {
    if (!d) return []
    let rs = d.rows
    if (show === 'contati') rs = rs.filter((r: any) => r.counted !== null)
    if (show === 'differenze') rs = rs.filter((r: any) => r.difference !== null && Number(r.difference) !== 0)
    if (show === 'non_contati') rs = rs.filter((r: any) => r.counted === null)
    if (q) { const s = q.toLowerCase(); rs = rs.filter((r: any) => `${r.code} ${r.description} ${r.variant_code ?? ''}`.toLowerCase().includes(s)) }
    return rs
  }, [d, show, q])

  if (!d) return <Loading />
  const isOpen = d.status === 'aperto'

  async function saveEdits() {
    const body = Object.entries(edits).filter(([, v]) => v !== '').map(([k, v]) => {
      const [item_id, variant_id, lot_number] = k.split('|')
      const r = d.rows.find((x: any) => key(x) === k)
      return { item_id, variant_id: variant_id || null, lot_number: lot_number || null, expiry_date: r?.expiry_date ?? null, quantity: String(v) }
    })
    try { setD(await W(`/inventari/${id}/quantita`, { method: 'PUT', body })); setEdits({}); notifyOk('Quantità salvate') } catch (e) { notifyError(e) }
  }
  async function accept(countIds: string[], accepted: boolean) {
    try { setD(await W(`/inventari/${id}/accetta`, { body: { count_ids: countIds, accepted } })) } catch (e) { notifyError(e) }
  }
  async function importFile(file: File | null) {
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await fetch(`/api/magazzino/inventari/${id}/import`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${tokens.get('user')}` } })
      const r = await res.json()
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : 'Import non riuscito')
      notifyOk(`Importati ${r.added} conteggi${r.errors.length ? `, ${r.errors.length} righe scartate` : ''}`)
      load()
    } catch (e) { notifyError(e) }
  }
  async function close() {
    try { const r = await W(`/inventari/${id}/chiudi`, { body: { zero_uncounted: zeroChoice === 'si' } }); notifyOk(`Inventario chiuso: ${r.adjusted_rows} rettifiche`); setConfirm(false); load() } catch (e) { notifyError(e) }
  }
  async function cancel() {
    if (!window.confirm('Annullare l\'inventario? I conteggi non verranno applicati.')) return
    try { await W(`/inventari/${id}/annulla`, { method: 'POST' }); load() } catch (e) { notifyError(e) }
  }

  const t = d.totals
  return (
    <>
      <Anchor size="sm" onClick={() => nav('/magazzino/inventari')}><Group gap={4}><IconArrowLeft size={14} />Inventari</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <Group gap="xs"><Title order={2}>{d.name}</Title><Badge color={STATUS[d.status]} variant="light">{d.status}</Badge></Group>
        {isOpen && (
          <Group>
            <FileButton onChange={importFile} accept=".xlsx,.xls,.csv">{(p) => <Button variant="default" leftSection={<IconUpload size={16} />} {...p}>Importa conteggi</Button>}</FileButton>
            <Button variant="subtle" color="red" onClick={cancel}>Annulla</Button>
            <Button onClick={() => setConfirm(true)}>Chiudi e applica</Button>
          </Group>
        )}
      </Group>

      <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
        <Stat label="Righe contate" value={`${t.rows_counted} / ${t.rows_in_scope}`} hint={`${t.items_counted} articoli su ${t.items_in_scope}`} />
        <Stat label="Righe con differenza" value={t.rows_with_difference} />
        <Stat label="Valore differenze" value={fmtEuro(t.value_difference)} hint="al costo medio" />
        <Stat label="Conteggi ricevuti" value={t.counts_total} hint={t.counts_rejected ? `${t.counts_rejected} scartati` : undefined} />
      </SimpleGrid>

      {isOpen && (
        <Paper withBorder p="md" mb="md">
          <Group wrap="nowrap" align="center">
            {qr && <img src={qr} alt="QR per contare con lo smartphone" width={110} height={110} />}
            <div>
              <Group gap={6}><IconDeviceMobile size={18} /><Text fw={600}>Conta con lo smartphone</Text></Group>
              <Text size="sm" c="dimmed">Inquadra il QR con il telefono (accesso con le tue credenziali) oppure apri <Anchor href={mobileUrl} target="_blank">{mobileUrl}</Anchor>. Più persone possono contare insieme: i conteggi arrivano qui in tempo reale.</Text>
            </div>
          </Group>
        </Paper>
      )}

      <Group mb="sm" wrap="wrap" justify="space-between">
        <Group>
          <SegmentedControl value={show} onChange={setShow} data={[{ value: 'contati', label: 'Contati' }, { value: 'differenze', label: 'Con differenze' }, { value: 'non_contati', label: 'Non contati' }, { value: 'tutti', label: 'Tutti' }]} />
          <TextInput placeholder="Filtra" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={200} />
        </Group>
        {Object.keys(edits).length > 0 && <Button onClick={saveEdits}>Salva {Object.keys(edits).length} correzioni</Button>}
      </Group>

      <Text size="xs" c="dimmed" mb={6}>Il pallino verde indica le righe già contate. Le righe senza pallino non vengono toccate finché non chiudi l'inventario: solo allora scegli se azzerarle. Scrivere una quantità sostituisce i conteggi di quella riga.</Text>
      <Paper withBorder>
        <Table.ScrollContainer minWidth={820}>
          <Table verticalSpacing="xs">
            <Table.Thead><Table.Tr><Table.Th w={54} /><Table.Th>Articolo</Table.Th><Table.Th>Variante / lotto</Table.Th><Table.Th>Ubic.</Table.Th>
              <Table.Th ta="right">Teorica</Table.Th><Table.Th ta="right" w={140}>Contata</Table.Th><Table.Th ta="right">Differenza</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((r: any) => {
                const k = key(r)
                const diff = r.difference !== null ? Number(r.difference) : null
                return (
                  <Fragment key={k}>
                    <Table.Tr>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          <Tooltip label={r.is_counted ? 'Contato' : 'Non ancora contato'}>
                            <div style={{ width: 10, height: 10, borderRadius: 10, background: r.is_counted ? 'var(--mantine-color-green-6)' : 'transparent', border: r.is_counted ? 'none' : '1px solid var(--mantine-color-gray-4)' }} />
                          </Tooltip>
                          {r.counts.length > 0 && <ActionIcon variant="subtle" size="sm" onClick={() => setOpen({ ...open, [k]: !open[k] })}>{open[k] ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}</ActionIcon>}
                        </Group>
                      </Table.Td>
                      <Table.Td><Text size="sm"><Text span ff="monospace" size="xs" c="dimmed">{r.code}</Text> {r.description}</Text></Table.Td>
                      <Table.Td fz="sm">{[r.color, r.size].filter(Boolean).join(' ') || r.variant_code || ''}{r.lot_number && <>lotto <b>{r.lot_number}</b>{r.expiry_date ? ` · scad. ${fmtDate(r.expiry_date)}` : ''}</>}
                        {r.serial_managed && r.serials_expected && <Text size="xs" c="dimmed">attese: {r.serials_expected.join(', ') || '—'}{r.serials_missing?.length ? ` · non lette: ${r.serials_missing.join(', ')}` : ''}{r.serials_extra?.length ? ` · nuove: ${r.serials_extra.join(', ')}` : ''}</Text>}</Table.Td>
                      <Table.Td fz="xs" c="dimmed">{r.location ?? ''}</Table.Td>
                      <Table.Td ta="right">{qty(r.theoretical)}</Table.Td>
                      <Table.Td ta="right">
                        {isOpen && !r.serial_managed ? (
                          <NumberInput size="xs" hideControls min={0} placeholder="—" value={edits[k] ?? (r.counted === null ? '' : Number(r.counted))}
                            onChange={(v) => setEdits({ ...edits, [k]: v })} styles={{ input: { textAlign: 'right', fontWeight: edits[k] !== undefined ? 700 : 400 } }} />
                        ) : r.counted === null ? <Text c="dimmed">—</Text> : qty(r.counted)}
                      </Table.Td>
                      <Table.Td ta="right" fw={700} c={diff === null ? 'dimmed' : diff < 0 ? 'red' : diff > 0 ? 'green' : undefined}>{diff === null ? '' : `${diff > 0 ? '+' : ''}${qty(diff)}`}</Table.Td>
                    </Table.Tr>
                    {r.counts.length > 0 && (
                      <Table.Tr style={{ display: open[k] ? undefined : 'none' }}>
                        <Table.Td />
                        <Table.Td colSpan={6} bg="var(--mantine-color-gray-0)">
                          <Collapse in={!!open[k]}>
                            <Stack gap={4} py={4}>
                              {r.counts.map((c: any) => (
                                <Group key={c.id} gap="sm">
                                  <Checkbox size="xs" checked={c.accepted} disabled={!isOpen} onChange={(e) => accept([c.id], e.currentTarget.checked)} label={c.accepted ? 'accettato' : 'scartato'} />
                                  <Badge size="xs" variant="outline">{c.source}</Badge>
                                  <Text size="xs">{c.serial_number ? `matricola ${c.serial_number}` : `${qty(c.quantity)} ${r.unit}`}</Text>
                                  <Text size="xs" c="dimmed">{new Date(c.counted_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Text>
                                </Group>
                              ))}
                            </Stack>
                          </Collapse>
                        </Table.Td>
                      </Table.Tr>
                    )}
                  </Fragment>
                )
              })}
              {rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg" size="sm">Nessuna riga</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>

      <Modal opened={confirm} onClose={() => setConfirm(false)} title="Chiudere l'inventario?" size="lg">
        <Stack>
          <Text size="sm">Verranno rettificate le <b>{t.rows_with_difference}</b> righe contate con differenza (valore {fmtEuro(t.value_difference)}).</Text>
          {t.rows_uncounted > 0 ? (
            <>
              <Text size="sm">Ci sono <b>{t.rows_uncounted}</b> righe con giacenza che <b>non sono state contate</b> (valore {fmtEuro(t.value_uncounted)}). Cosa vuoi farne?</Text>
              <SegmentedControl orientation="vertical" fullWidth value={zeroChoice ?? ''} onChange={(v) => setZeroChoice(v as any)}
                data={[{ value: 'no', label: 'Lasciale invariate (inventario parziale o interrotto)' }, { value: 'si', label: 'Azzerale (inventario concluso: ciò che non è stato contato non c\'è)' }]} />
            </>
          ) : <Text size="sm" c="dimmed">Tutte le righe con giacenza sono state contate.</Text>}
          {Object.keys(edits).length > 0 && <Alert color="yellow">Hai correzioni non salvate: salvale prima di chiudere.</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirm(false)}>Annulla</Button>
            <Button onClick={close} color={zeroChoice === 'si' ? 'red' : undefined}
              disabled={Object.keys(edits).length > 0 || (t.rows_uncounted > 0 && !zeroChoice)}>
              {zeroChoice === 'si' ? 'Chiudi e azzera i non contati' : 'Chiudi e applica'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}

export function Lots() {
  const [days, setDays] = useState<string>('30')
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { W(`/lotti${days === 'tutti' ? '' : `?entro_giorni=${days}`}`).then(setRows).catch(notifyError) }, [days])
  return (
    <>
      <PageTitle title="Lotti e scadenze" subtitle="Lotti con giacenza, dal primo in scadenza" />
      <SegmentedControl mb="md" value={days} onChange={setDays} data={[{ value: '7', label: 'Entro 7 giorni' }, { value: '30', label: 'Entro 30 giorni' }, { value: '90', label: 'Entro 90 giorni' }, { value: 'tutti', label: 'Tutti' }]} />
      {!rows ? <Loading /> : (
        <Paper withBorder><Table.ScrollContainer minWidth={640}><Table verticalSpacing="xs">
          <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th>Lotto</Table.Th><Table.Th>Scadenza</Table.Th><Table.Th>Magazzino</Table.Th><Table.Th ta="right">Quantità</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r, i) => (
              <Table.Tr key={i}>
                <Table.Td fz="sm"><Text span ff="monospace" size="xs" c="dimmed">{r.code}</Text> {r.description}</Table.Td>
                <Table.Td ff="monospace">{r.lot_number}</Table.Td>
                <Table.Td>{fmtDate(r.expiry_date)} {r.state && r.state !== 'ok' && <Badge size="xs" color={r.state === 'scaduto' ? 'red' : 'orange'}>{r.state === 'scaduto' ? 'scaduto' : `${r.days_left} gg`}</Badge>}</Table.Td>
                <Table.Td fz="sm">{r.warehouse}</Table.Td><Table.Td ta="right" fw={600}>{qty(r.on_hand, r.unit)}</Table.Td>
              </Table.Tr>
            ))}
            {rows.length === 0 && <Table.Tr><Table.Td colSpan={5}><Text ta="center" c="dimmed" py="lg">Nessun lotto in scadenza</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table></Table.ScrollContainer></Paper>
      )}
    </>
  )
}

export function Serials() {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<any[] | null>(null)
  async function search() {
    if (q.trim().length < 2) return
    try { setRows(await W('/matricole?q=' + encodeURIComponent(q.trim()))) } catch (e) { notifyError(e) }
  }
  return (
    <>
      <PageTitle title="Matricole" subtitle="Storia di ogni pezzo: acquisto, vendita, garanzia" />
      <TextInput placeholder="Leggi o scrivi una matricola e premi Invio" value={q} onChange={(e) => setQ(e.currentTarget.value)} onKeyDown={(e) => e.key === 'Enter' && search()} size="md" mb="md" autoFocus />
      <Stack>
        {rows?.map((r) => (
          <Paper key={r.serial_number + r.code} withBorder p="md">
            <Group justify="space-between" mb={6}>
              <div><Text fw={700} ff="monospace">{r.serial_number}</Text><Text size="sm">{r.code} — {r.description}</Text></div>
              <Group gap={6}><Badge variant="light" color={r.status === 'disponibile' ? 'green' : r.status === 'venduto' ? 'blue' : 'gray'}>{r.status}</Badge>
                {r.warranty_until && <Badge variant="light" color={r.in_warranty ? 'green' : 'red'}>{r.in_warranty ? `in garanzia fino al ${fmtDate(r.warranty_until)}` : `garanzia scaduta il ${fmtDate(r.warranty_until)}`}</Badge>}</Group>
            </Group>
            <SimpleGrid cols={{ base: 1, sm: 3 }} mb="xs">
              <Text size="sm"><Text span c="dimmed">Fornitore: </Text>{r.supplier ?? '—'}{r.purchase_date ? ` (${fmtDate(r.purchase_date)})` : ''}</Text>
              <Text size="sm"><Text span c="dimmed">Cliente: </Text>{r.customer ?? '—'}{r.sale_date ? ` (${fmtDate(r.sale_date)})` : ''}</Text>
              <Text size="sm"><Text span c="dimmed">Magazzino: </Text>{r.warehouse ?? '—'}</Text>
            </SimpleGrid>
            <Group gap={6}>{r.history.map((h: any, i: number) => <Badge key={i} variant="outline" size="sm">{fmtDate(h.moved_at.slice(0, 10))} {h.reason}</Badge>)}</Group>
          </Paper>
        ))}
        {rows && rows.length === 0 && <Text c="dimmed" ta="center">Nessuna matricola trovata</Text>}
      </Stack>
    </>
  )
}

export function Places() {
  const whs = useWarehouses()
  const [stores, setStores] = useState<any[] | null>(null)
  const [maxWh, setMaxWh] = useState(1)
  const [whRows, setWhRows] = useState<any[]>([])
  const [editStore, setEditStore] = useState<any>(null)
  const [newWh, setNewWh] = useState<any>(null)
  const [policy, setPolicy] = useState<boolean | null>(null)
  const load = () => {
    W('/punti-vendita').then(setStores).catch(notifyError)
    W('/magazzini').then((r) => { setWhRows(r.rows); setMaxWh(r.max_warehouses) }).catch(notifyError)
    W('/impostazioni').then((r) => setPolicy(r.allow_negative)).catch(() => {})
  }
  useEffect(load, [])
  if (!stores || !whs) return <Loading />

  async function saveStore() {
    try {
      const body = { ...editStore, warehouse_id: editStore.warehouse_id === 'nuovo' ? null : editStore.warehouse_id }
      if (editStore.id) await W(`/punti-vendita/${editStore.id}`, { method: 'PUT', body })
      else await W('/punti-vendita', { body })
      setEditStore(null)
      load()
    } catch (e) { notifyError(e) }
  }
  async function saveWh() {
    try { await W('/magazzini', { body: newWh }); setNewWh(null); load() } catch (e) { notifyError(e) }
  }
  async function togglePolicy(v: boolean) {
    try { await W('/impostazioni', { method: 'PUT', body: { allow_negative: v } }); setPolicy(v) } catch (e) { notifyError(e) }
  }

  return (
    <>
      <PageTitle title="Punti vendita e magazzini" subtitle="Ogni punto vendita scarica dal suo magazzino o da uno comune" />
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Paper withBorder>
          <Group justify="space-between" p="sm"><Text fw={600}>Punti vendita</Text>
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditStore({ code: '', name: '', city: '', address: '', warehouse_id: whs[0]?.id, active: true })}>Nuovo</Button></Group>
          <Table>
            <Table.Tbody>
              {stores.map((s) => (
                <Table.Tr key={s.id} style={{ cursor: 'pointer' }} onClick={() => setEditStore(s)}>
                  <Table.Td><Text fw={600} size="sm">{s.name}</Text><Text size="xs" c="dimmed">{s.code}{s.city ? ` · ${s.city}` : ''}</Text></Table.Td>
                  <Table.Td><Text size="sm">{s.warehouse_name}</Text>{s.shared_warehouse && <Badge size="xs" variant="light">magazzino comune</Badge>}</Table.Td>
                </Table.Tr>
              ))}
              {stores.length === 0 && <Table.Tr><Table.Td><Text size="sm" c="dimmed" p="sm">Nessun punto vendita: se hai un solo negozio non serve crearne.</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Paper>
        <Paper withBorder>
          <Group justify="space-between" p="sm"><Text fw={600}>Magazzini <Text span size="xs" c="dimmed">({whRows.length} di {maxWh})</Text></Text>
            <Tooltip label={whRows.length >= maxWh ? 'Limite del pacchetto raggiunto' : ''} disabled={whRows.length < maxWh}>
              <Button size="xs" leftSection={<IconPlus size={14} />} disabled={whRows.length >= maxWh} onClick={() => setNewWh({ code: '', name: '' })}>Nuovo</Button>
            </Tooltip></Group>
          <Table>
            <Table.Tbody>
              {whRows.map((w) => (
                <Table.Tr key={w.id}><Table.Td><Text fw={600} size="sm">{w.name}</Text><Text size="xs" c="dimmed">{w.code}</Text></Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{w.stores.length ? `Usato da: ${w.stores.join(', ')}` : ''}</Text></Table.Td></Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {policy !== null && (
            <Switch m="sm" label="Consenti giacenze negative" description="Utile al banco per non bloccare le vendite; per lotti e matricole il controllo resta sempre attivo"
              checked={policy} onChange={(e) => togglePolicy(e.currentTarget.checked)} />
          )}
        </Paper>
      </SimpleGrid>

      <Modal opened={!!editStore} onClose={() => setEditStore(null)} title={editStore?.id ? 'Punto vendita' : 'Nuovo punto vendita'}>
        {editStore && (
          <Stack>
            <Group grow><TextInput label="Codice" value={editStore.code} onChange={(e) => setEditStore({ ...editStore, code: e.currentTarget.value })} />
              <TextInput label="Nome" value={editStore.name} onChange={(e) => setEditStore({ ...editStore, name: e.currentTarget.value })} /></Group>
            <TextInput label="Indirizzo" value={editStore.address ?? ''} onChange={(e) => setEditStore({ ...editStore, address: e.currentTarget.value })} />
            <Group grow><TextInput label="Città" value={editStore.city ?? ''} onChange={(e) => setEditStore({ ...editStore, city: e.currentTarget.value })} />
              <TextInput label="Telefono" value={editStore.phone ?? ''} onChange={(e) => setEditStore({ ...editStore, phone: e.currentTarget.value })} /></Group>
            <Select label="Magazzino da cui scarica" description="Scegli un magazzino esistente (comune) o creane uno dedicato"
              data={[...(editStore.id ? [] : [{ value: 'nuovo', label: '+ Crea un magazzino dedicato' }]), ...whs.map((w) => ({ value: w.id, label: w.name }))]}
              value={editStore.warehouse_id} onChange={(v) => setEditStore({ ...editStore, warehouse_id: v })} allowDeselect={false} />
            <Group justify="flex-end"><Button onClick={saveStore} disabled={!editStore.code || !editStore.name}>Salva</Button></Group>
          </Stack>
        )}
      </Modal>
      <Modal opened={!!newWh} onClose={() => setNewWh(null)} title="Nuovo magazzino">
        {newWh && (
          <Stack>
            <TextInput label="Codice" value={newWh.code} onChange={(e) => setNewWh({ ...newWh, code: e.currentTarget.value })} />
            <TextInput label="Nome" value={newWh.name} onChange={(e) => setNewWh({ ...newWh, name: e.currentTarget.value })} />
            <Group justify="flex-end"><Button onClick={saveWh} disabled={!newWh.code || !newWh.name}>Crea</Button></Group>
          </Stack>
        )}
      </Modal>
    </>
  )
}
