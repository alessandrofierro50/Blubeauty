// Scheda del giro: clienti da visitare, carico del furgone, documenti e incassi dell'agente, rientro con la verifica
// del magazziniere (conta alla cieca, differenze motivate, firme) e quadratura di cassa.

import { ActionIcon, Alert, Anchor, Badge, Button, Divider, Group, NumberInput, Paper, Radio, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, ThemeIcon } from '@mantine/core'
import { IconAlertTriangle, IconArrowDown, IconArrowUp, IconCheck, IconFileTypePdf, IconPlus, IconPrinter, IconSignature, IconTrash, IconTruckDelivery } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { SignaturePad, StatusBadge, TV, emptySignature, openPdf, qtyFmt, signatureReady } from './shared'

export default function TripDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [t, setT] = useState<any>(null)
  const [me, setMe] = useState<any>(null)
  const [tab, setTab] = useState<string | null>(null)
  const load = () => TV(`/giri/${id}`).then((x) => { setT(x); setTab((cur) => cur ?? defaultTab(x)) }).catch(notifyError)
  useEffect(() => { load(); appApi('/api/auth/me').then(setMe).catch(() => {}) }, [id])
  if (!t || !me) return <Loading />
  const s = t.summary
  const open = !['rientro', 'chiuso'].includes(t.status)
  return (
    <>
      <PageTitle title={`Giro di ${t.weekday.toLowerCase()} ${fmtDate(t.trip_date)}`} subtitle={`${t.van} · agente ${t.agent ?? 'non assegnato'} · sezionale /${t.series}`}
        right={<Group>
          <StatusBadge trip={t} />
          {t.status === 'preparazione' && <Button variant="light" onClick={async () => { try { await TV(`/giri/${id}/partenza`, { body: {} }); load() } catch (e) { notifyError(e) } }}>Segna partito</Button>}
          {t.status === 'preparazione' && !t.loads && ['amministratore', 'amministrazione', 'vendite'].includes(me.user.role) &&
            <Button variant="subtle" color="red" onClick={async () => { if (!window.confirm('Eliminare il giro?')) return; try { await TV(`/giri/${id}`, { method: 'DELETE' }); nav('/tentata/giri') } catch (e) { notifyError(e) } }}>Elimina</Button>}
        </Group>} />
      <SimpleGrid cols={{ base: 2, md: 5 }} mb="md">
        <Kpi label="Venduto (imponibile)" value={fmtEuro(s.sold_taxable)} />
        <Kpi label="Visite" value={`${s.visits.visited} di ${s.visits.planned}`} />
        <Kpi label="Documenti" value={Object.values(s.documents).reduce((a: number, d: any) => a + d.count, 0)} />
        <Kpi label="Incassato" value={fmtEuro(s.cash.reduce((a: number, c: any) => a + Number(c.collected), 0))} />
        <Kpi label="Km percorsi" value={s.km ?? (t.km_start ? `partito a ${t.km_start}` : '—')} />
      </SimpleGrid>
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List mb="md">
          <Tabs.Tab value="clienti">Clienti del giro</Tabs.Tab>
          <Tabs.Tab value="carico">Carico</Tabs.Tab>
          <Tabs.Tab value="documenti">Documenti e incassi</Tabs.Tab>
          <Tabs.Tab value="rientro" rightSection={t.status === 'rientro' ? <Badge size="xs" color="orange">da verificare</Badge> : null}>Rientro e quadratura</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="clienti"><Stops t={t} editable={open} onSaved={load} /></Tabs.Panel>
        <Tabs.Panel value="carico">{tab === 'carico' && <Load t={t} onLoaded={load} />}</Tabs.Panel>
        <Tabs.Panel value="documenti"><Docs t={t} /></Tabs.Panel>
        <Tabs.Panel value="rientro">{tab === 'rientro' && <Return t={t} me={me} onDone={load} />}</Tabs.Panel>
      </Tabs>
    </>
  )
}

const defaultTab = (t: any) => (t.status === 'preparazione' ? 'carico' : t.status === 'in_corso' ? 'documenti' : 'rientro')

function Kpi({ label, value }: { label: string; value: any }) {
  return <Paper withBorder p="sm"><Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text><Text fw={800} size="lg">{value}</Text></Paper>
}

// ---------------------------------------------------------------------------------------------------- clienti

function Stops({ t, editable, onSaved }: { t: any; editable: boolean; onSaved: () => void }) {
  const [rows, setRows] = useState<any[]>(t.stops)
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  useEffect(() => setRows(t.stops), [t])
  useEffect(() => {
    if (q.length < 2) { setFound([]); return }
    const h = setTimeout(() => TV(`/clienti?q=${encodeURIComponent(q)}`).then(setFound).catch(() => {}), 250)
    return () => clearTimeout(h)
  }, [q])
  const dirty = JSON.stringify(rows.map((r) => r.party_id)) !== JSON.stringify(t.stops.map((r: any) => r.party_id))
  const move = (i: number, d: number) => setRows((r) => { const x = [...r]; const [a] = x.splice(i, 1); x.splice(i + d, 0, a); return x })
  async function save() {
    try { await TV(`/giri/${t.id}/clienti`, { method: 'PUT', body: { stops: rows.map((r) => ({ party_id: r.party_id, notes: r.notes })) } }); notifyOk('Clienti del giro salvati'); onSaved() } catch (e) { notifyError(e) }
  }
  return (
    <Stack>
      {editable && (
        <Select placeholder="Aggiungi un cliente al giro" searchable searchValue={q} onSearchChange={setQ} value={null}
          data={found.filter((f) => !rows.some((r) => r.party_id === f.id)).map((f) => ({ value: f.id, label: `${f.name}${f.city ? ' · ' + f.city : ''}` }))}
          nothingFoundMessage={q.length < 2 ? 'Scrivi almeno 2 lettere' : 'Nessun cliente'}
          onChange={(v) => { const f = found.find((x) => x.id === v); if (f) setRows([...rows, { party_id: f.id, name: f.name, city: f.city, notes: null, visited: false }]); setQ('') }} />
      )}
      <Paper withBorder>
        <Table fz="sm">
          <Table.Thead><Table.Tr><Table.Th w={40}>#</Table.Th><Table.Th>Cliente</Table.Th><Table.Th>Note</Table.Th><Table.Th>Visita</Table.Th><Table.Th w={110} /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r, i) => (
              <Table.Tr key={r.party_id}>
                <Table.Td>{i + 1}</Table.Td>
                <Table.Td><Text size="sm" fw={600}>{r.name}</Text><Text size="xs" c="dimmed">{r.city}</Text></Table.Td>
                <Table.Td>{r.notes}{r.visit_notes && <Text size="xs" c="dimmed">{r.visit_notes}</Text>}</Table.Td>
                <Table.Td>{r.visited ? <Badge color="teal" variant="light" leftSection={<IconCheck size={12} />}>visitato</Badge> : <Badge color="gray" variant="light">da visitare</Badge>}</Table.Td>
                <Table.Td>{editable && (
                  <Group gap={2} wrap="nowrap">
                    <ActionIcon variant="subtle" disabled={i === 0} onClick={() => move(i, -1)}><IconArrowUp size={15} /></ActionIcon>
                    <ActionIcon variant="subtle" disabled={i === rows.length - 1} onClick={() => move(i, 1)}><IconArrowDown size={15} /></ActionIcon>
                    <ActionIcon variant="subtle" color="red" disabled={r.visited} onClick={() => setRows(rows.filter((_, n) => n !== i))}><IconTrash size={15} /></ActionIcon>
                  </Group>)}
                </Table.Td>
              </Table.Tr>
            ))}
            {!rows.length && <Table.Tr><Table.Td colSpan={5}><Text c="dimmed" ta="center" py="md">Nessun cliente: aggiungili qui o nel giro clienti del furgone</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Paper>
      {editable && dirty && <Group justify="flex-end"><Button onClick={save}>Salva clienti del giro</Button></Group>}
    </Stack>
  )
}

// ---------------------------------------------------------------------------------------------------- carico

function Load({ t, onLoaded }: { t: any; onLoaded: () => void }) {
  const [prop, setProp] = useState<any[] | null>(null)
  const [loaded, setLoaded] = useState<any>(null)
  const [rows, setRows] = useState<any[]>([])
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  const canLoad = ['preparazione', 'in_corso'].includes(t.status)
  const reload = () => {
    TV(`/giri/${t.id}/carico`).then(setLoaded).catch(notifyError)
    if (canLoad) TV(`/giri/${t.id}/proposta-carico`).then((p) => { setProp(p); setRows(p.map((r: any) => ({ ...r, qty: Number(r.proposed) || 0, lot: '', serials: '' }))) }).catch(notifyError)
  }
  useEffect(reload, [t.id])
  useEffect(() => {
    if (q.length < 2) { setFound([]); return }
    const h = setTimeout(() => appApi(`/api/anagrafiche/articoli?q=${encodeURIComponent(q)}&page_size=20`).then((r) => setFound(r.rows.filter((i: any) => i.item_type !== 'servizio' && !i.is_kit))).catch(() => {}), 250)
    return () => clearTimeout(h)
  }, [q])
  function add(it: any) {
    appApi(`/api/anagrafiche/articoli/${it.id}`).then((a) => {
      const base = { item_id: a.id, code: a.code, description: a.description, unit: a.unit, orders: '0', avg_sold: '0', on_van: '—', available: '—',
        lot_managed: a.lot_managed, serial_managed: a.serial_managed, qty: 1, lot: '', serials: '' }
      const extra = a.has_variants && a.variants?.length
        ? a.variants.map((v: any) => ({ ...base, variant_id: v.id, variant: [v.size, v.color, v.format].filter(Boolean).join(' · ') || v.code, qty: 0 }))
        : [{ ...base, variant_id: null, variant: null }]
      setRows((r) => [...r, ...extra])
    }).catch(notifyError)
    setQ('')
  }
  async function doLoad() {
    const lines = rows.filter((r) => Number(r.qty) > 0).map((r) => ({
      item_id: r.item_id, variant_id: r.variant_id, quantity: String(r.serial_managed ? r.serials.split(/[\s,;]+/).filter(Boolean).length : r.qty),
      lot_number: r.lot || null, serials: r.serial_managed ? r.serials.split(/[\s,;]+/).filter(Boolean) : null }))
    if (!lines.length) return
    setBusy(true)
    try {
      await TV(`/giri/${t.id}/carico`, { body: { lines } })
      notifyOk(`${lines.length} righe caricate sul furgone`)
      onLoaded()
      reload()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  const total = rows.reduce((a, r) => a + (Number(r.qty) > 0 ? 1 : 0), 0)
  return (
    <Stack>
      {canLoad && (
        <Paper withBorder p="md">
          <Group justify="space-between" mb="xs">
            <div>
              <Text fw={700}>Proposta di carico</Text>
              <Text size="xs" c="dimmed">Il più alto tra ordini da consegnare ai clienti del giro e media venduta negli ultimi giri, meno quanto è già sul furgone.
                Lotti: vuoto = prima quelli che scadono prima.</Text>
            </div>
            <Button leftSection={<IconTruckDelivery size={16} />} onClick={doLoad} loading={busy} disabled={!total}>Carica sul furgone ({total})</Button>
          </Group>
          <Select mb="sm" placeholder="Aggiungi un articolo da caricare" searchable searchValue={q} onSearchChange={setQ} value={null}
            data={found.map((i) => ({ value: i.id, label: `${i.code} · ${i.description}` }))} nothingFoundMessage={q.length < 2 ? 'Scrivi almeno 2 lettere' : 'Nessun articolo'}
            onChange={(v) => { const f = found.find((x) => x.id === v); if (f) add(f) }} />
          {!prop ? <Loading /> : (
            <Table fz="sm" striped>
              <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th ta="right">Ordini</Table.Th><Table.Th ta="right">Media giri</Table.Th>
                <Table.Th ta="right">Già a bordo</Table.Th><Table.Th ta="right">In magazzino</Table.Th><Table.Th w={110}>Da caricare</Table.Th><Table.Th w={170}>Lotto / matricole</Table.Th><Table.Th w={30} /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>{r.code} · {r.description}{r.variant && <Text span c="dimmed"> · {r.variant}</Text>}</Table.Td>
                    <Table.Td ta="right">{qtyFmt(r.orders)}</Table.Td><Table.Td ta="right">{r.avg_sold}</Table.Td>
                    <Table.Td ta="right">{qtyFmt(r.on_van)}</Table.Td><Table.Td ta="right">{qtyFmt(r.available)}</Table.Td>
                    <Table.Td>{r.serial_managed ? <Text size="xs" c="dimmed">dalle matricole</Text> :
                      <NumberInput size="xs" min={0} value={r.qty} onChange={(v) => setRows(rows.map((x, n) => (n === i ? { ...x, qty: v } : x)))} />}</Table.Td>
                    <Table.Td>{r.serial_managed ? <TextInput size="xs" placeholder="matricole separate da spazio" value={r.serials}
                      onChange={(e) => { const v = e.currentTarget.value; setRows(rows.map((x, n) => (n === i ? { ...x, serials: v, qty: v.split(/[\s,;]+/).filter(Boolean).length } : x))) }} />
                      : r.lot_managed ? <TextInput size="xs" placeholder="FEFO" value={r.lot} onChange={(e) => { const v = e.currentTarget.value.toUpperCase(); setRows(rows.map((x, n) => (n === i ? { ...x, lot: v } : x))) }} /> : null}</Table.Td>
                    <Table.Td><ActionIcon size="sm" variant="subtle" color="red" onClick={() => setRows(rows.filter((_, n) => n !== i))}><IconTrash size={14} /></ActionIcon></Table.Td>
                  </Table.Tr>
                ))}
                {!rows.length && <Table.Tr><Table.Td colSpan={8}><Text c="dimmed" ta="center" py="md">Nessuna proposta (niente ordini né storico): aggiungi gli articoli a mano</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          )}
        </Paper>
      )}
      <Paper withBorder p="md">
        <Group justify="space-between" mb="xs">
          <Text fw={700}>Caricato in questo giro</Text>
          <Button size="xs" variant="light" leftSection={<IconPrinter size={14} />} disabled={!loaded?.lines.length}
            onClick={() => window.open(`/stampa/giro/${t.id}/carico`, '_blank')}>Documento di carico</Button>
        </Group>
        {!loaded ? <Loading /> : <QtyTable rows={loaded.lines} empty="Ancora niente caricato" />}
        {loaded && loaded.on_van.length > 0 && <>
          <Divider my="sm" label="Merce a bordo adesso" labelPosition="left" />
          <QtyTable rows={loaded.on_van} empty="" />
        </>}
      </Paper>
    </Stack>
  )
}

function QtyTable({ rows, empty }: { rows: any[]; empty: string }) {
  if (!rows.length) return <Text c="dimmed" size="sm">{empty}</Text>
  return (
    <Table fz="sm">
      <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th>Lotto</Table.Th><Table.Th ta="right">Quantità</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{rows.map((r, i) => (
        <Table.Tr key={i}><Table.Td>{r.code} · {r.description}{r.variant && <Text span c="dimmed"> · {r.variant}</Text>}</Table.Td>
          <Table.Td>{r.lot_number ?? ''}{r.expiry_date && <Text span size="xs" c="dimmed"> scad. {fmtDate(r.expiry_date)}</Text>}</Table.Td>
          <Table.Td ta="right">{qtyFmt(r.quantity)} {r.unit}</Table.Td></Table.Tr>))}
      </Table.Tbody>
    </Table>
  )
}

// ---------------------------------------------------------------------------------------------------- documenti

function Docs({ t }: { t: any }) {
  const nav = useNavigate()
  return (
    <Stack>
      <Paper withBorder>
        <Table fz="sm" highlightOnHover>
          <Table.Thead><Table.Tr><Table.Th>Documento</Table.Th><Table.Th>Cliente</Table.Th><Table.Th>Firma</Table.Th><Table.Th>Inviato</Table.Th>
            <Table.Th ta="right">Totale</Table.Th><Table.Th w={40} /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {t.documents.map((d: any) => (
              <Table.Tr key={d.id}>
                <Table.Td><Anchor size="sm" onClick={() => nav(`/vendite/${d.id}`)}>{d.label}</Anchor>
                  {d.credit_warning && <Text size="xs" c="orange"><IconAlertTriangle size={11} /> {d.credit_warning}</Text>}</Table.Td>
                <Table.Td>{d.party}</Table.Td>
                <Table.Td>{d.signed ? <Group gap={6} wrap="nowrap"><img src={d.signature_url} alt="" style={{ height: 26, maxWidth: 90, objectFit: 'contain' }} /><Text size="xs">{d.signer_name}</Text></Group>
                  : <Text size="xs" c="dimmed">—</Text>}</Table.Td>
                <Table.Td>{d.sent.map((x: any, i: number) => <Badge key={i} size="xs" variant="light" color={x.channel === 'email' ? 'blue' : 'green'} mr={4}>{x.channel}</Badge>)}</Table.Td>
                <Table.Td ta="right">{fmtEuro(d.doc_type === 'NC' ? -Number(d.total) : d.total)}</Table.Td>
                <Table.Td><ActionIcon variant="subtle" onClick={() => openPdf(d.id).catch(notifyError)} title="PDF firmato"><IconFileTypePdf size={16} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}
            {!t.documents.length && <Table.Tr><Table.Td colSpan={6}><Text c="dimmed" ta="center" py="md">Nessun documento ancora arrivato dall'agente</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Paper>
      <Text fw={700}>Incassi sul posto</Text>
      <Paper withBorder>
        <Table fz="sm">
          <Table.Thead><Table.Tr><Table.Th>Cliente</Table.Th><Table.Th>Metodo</Table.Th><Table.Th>Riferimento</Table.Th><Table.Th ta="right">Importo</Table.Th><Table.Th ta="right">Da abbinare</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {t.collections.map((c: any) => (
              <Table.Tr key={c.id}><Table.Td>{c.party}</Table.Td><Table.Td>{c.method_label}{c.check_info && <Text size="xs" c="dimmed">{c.check_info}</Text>}</Table.Td>
                <Table.Td>{c.document ?? 'Scadenze più vecchie'}</Table.Td><Table.Td ta="right">{fmtEuro(c.amount)}</Table.Td>
                <Table.Td ta="right">{Number(c.unallocated) ? <Text c="orange" size="sm">{fmtEuro(c.unallocated)}</Text> : ''}</Table.Td></Table.Tr>
            ))}
            {!t.collections.length && <Table.Tr><Table.Td colSpan={5}><Text c="dimmed" ta="center" py="md">Nessun incasso</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Paper>
      <Text size="xs" c="dimmed">«Da abbinare»: acconti su DDT o senza scadenze aperte, da collegare alla fattura in ufficio.</Text>
    </Stack>
  )
}

// ---------------------------------------------------------------------------------------------------- rientro e verifica

function Return({ t, me, onDone }: { t: any; me: any; onDone: () => void }) {
  const [sheet, setSheet] = useState<any>(null)
  const [counts, setCounts] = useState<Record<string, { counted: number | string; reason: string | null; notes: string }>>({})
  const [diffs, setDiffs] = useState<Record<string, { expected: string; counted: string }>>({})
  const [extra, setExtra] = useState<any[]>([])
  const [remaining, setRemaining] = useState('rientra')
  const [sigAgent, setSigAgent] = useState(emptySignature(t.agent ?? ''))
  const [sigWh, setSigWh] = useState(emptySignature(me.user.full_name))
  const [opts, setOpts] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  const warehouseRole = ['amministratore', 'amministrazione', 'magazzino'].includes(me.user.role)
  useEffect(() => {
    TV(`/giri/${t.id}/rientro`).then((s) => {
      setSheet(s)
      setCounts(Object.fromEntries(s.rows.map((r: any) => [r.id, { counted: '', reason: null, notes: '' }])))
    }).catch(notifyError)
    TV('/opzioni').then(setOpts).catch(() => {})
  }, [t.id, t.status])
  useEffect(() => {
    if (q.length < 2) { setFound([]); return }
    const h = setTimeout(() => appApi(`/api/anagrafiche/articoli?q=${encodeURIComponent(q)}&page_size=20`).then((r) => setFound(r.rows)).catch(() => {}), 250)
    return () => clearTimeout(h)
  }, [q])
  const reasons = useMemo(() => opts?.reasons ?? [], [opts])
  if (!sheet || !opts) return <Loading />

  if (t.status === 'preparazione' || t.status === 'in_corso') {
    return <OfficeReturn t={t} onDone={onDone} />
  }
  if (t.status === 'chiuso') {
    return (
      <Stack>
        <Group justify="space-between">
          <Alert color="teal" icon={<IconCheck />} style={{ flex: 1 }}>
            Rientro verificato da {t.checked_by} il {new Date(t.checked_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}.
            {t.remaining === 'rientra' ? ' La merce è rientrata in magazzino.' : ' La merce è rimasta sul furgone per il giro successivo.'}
          </Alert>
          <Button leftSection={<IconPrinter size={16} />} onClick={() => window.open(`/stampa/giro/${t.id}/rientro`, '_blank')}>Documento di rientro</Button>
        </Group>
        <Paper withBorder>
          <Table fz="sm">
            <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th>Lotto</Table.Th><Table.Th ta="right">Atteso</Table.Th><Table.Th ta="right">Contato</Table.Th>
              <Table.Th ta="right">Differenza</Table.Th><Table.Th>Motivo</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{sheet.rows.map((r: any) => (
              <Table.Tr key={r.id} bg={Number(r.difference) ? 'var(--mantine-color-orange-0)' : undefined}>
                <Table.Td>{r.code} · {r.description}{r.variant && <Text span c="dimmed"> · {r.variant}</Text>}</Table.Td><Table.Td>{r.lot_number ?? ''}</Table.Td>
                <Table.Td ta="right">{qtyFmt(r.expected)}</Table.Td><Table.Td ta="right">{qtyFmt(r.counted)}</Table.Td>
                <Table.Td ta="right" fw={Number(r.difference) ? 700 : undefined} c={Number(r.difference) < 0 ? 'red' : Number(r.difference) > 0 ? 'teal' : undefined}>{Number(r.difference) > 0 ? '+' : ''}{qtyFmt(r.difference)}</Table.Td>
                <Table.Td>{r.reason_label}{r.notes && <Text size="xs" c="dimmed">{r.notes}</Text>}</Table.Td>
              </Table.Tr>))}
            </Table.Tbody>
          </Table>
        </Paper>
        <Cash t={t} />
        <SimpleGrid cols={2}>
          {(['agente', 'magazziniere'] as const).map((k) => t.signatures[k] && (
            <Paper key={k} withBorder p="sm"><Text size="xs" c="dimmed" tt="uppercase" fw={600}>Firma {k}</Text>
              {t.signatures[k].url && <img src={t.signatures[k].url} alt="" style={{ height: 60, maxWidth: '100%', objectFit: 'contain' }} />}
              <Text size="sm">{t.signatures[k].signer_name}</Text></Paper>))}
        </SimpleGrid>
      </Stack>
    )
  }

  // status === 'rientro': verifica del magazziniere
  const blind = !sheet.revealed
  const allCounted = sheet.rows.every((r: any) => counts[r.id]?.counted !== '' && counts[r.id]?.counted !== undefined)
  const needReason = (id: string) => !!diffs[id] || (!blind && sheet.rows.find((r: any) => r.id === id) && Number(counts[id]?.counted) !== Number(sheet.rows.find((r: any) => r.id === id).expected) && counts[id]?.counted !== '')
  async function confirm() {
    setBusy(true)
    try {
      const body = {
        counts: sheet.rows.map((r: any) => ({ id: r.id, counted: String(counts[r.id].counted), reason: counts[r.id].reason, notes: counts[r.id].notes || null })),
        extra: extra.filter((x) => Number(x.counted) > 0).map((x) => ({ item_id: x.item_id, variant_id: x.variant_id, lot_number: x.lot_number || null, counted: String(x.counted), reason: x.reason, notes: x.notes || null })),
        remaining,
        signatures: { ...(t.signatures.agente ? {} : { agente: sigAgent }), magazziniere: sigWh },
      }
      const r = await TV(`/giri/${t.id}/verifica`, { body })
      notifyOk(r.differences ? `Rientro chiuso con ${r.differences} differenze registrate` : 'Rientro chiuso: tutto torna')
      onDone()
    } catch (e: any) {
      if (e.code === 'differenze_da_motivare') {
        const list = e.detail?.differences ?? []
        setDiffs(Object.fromEntries(list.filter((d: any) => d.id).map((d: any) => [d.id, { expected: d.expected, counted: d.counted }])))
        notifyError(new Error(`${e.message}. Ricontale e scegli il motivo.`))
      } else notifyError(e)
    } finally { setBusy(false) }
  }
  const missingReasons = Object.keys(diffs).some((id) => !counts[id]?.reason) || extra.some((x) => Number(x.counted) > 0 && !x.reason)
  const sigOk = signatureReady(sigWh) && (t.signatures.agente || signatureReady(sigAgent))
  return (
    <Stack>
      {!warehouseRole && <Alert color="gray">La verifica del rientro la fa il magazzino.</Alert>}
      <Group justify="space-between" align="flex-start">
        <Alert color={blind ? 'blue' : 'gray'} icon={<IconSignature />} style={{ flex: 1 }} title={blind ? 'Conta alla cieca' : 'Conta del rientro'}>
          {blind ? 'Conta la merce sul furgone senza vedere le quantità attese. Alla conferma BluBeauty ti mostra solo le righe che non tornano: ricontale e indica il motivo.'
            : 'Conta la merce sul furgone e indica il motivo delle differenze.'}
          {t.return_notes && <Text size="sm" mt={4}>Note dell'agente: {t.return_notes}</Text>}
        </Alert>
        <Button variant="light" leftSection={<IconPrinter size={16} />} onClick={() => window.open(`/stampa/giro/${t.id}/conta`, '_blank')}>Foglio di conta</Button>
      </Group>
      <Paper withBorder>
        <Table fz="sm">
          <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th>Lotto</Table.Th>{!blind && <Table.Th ta="right">Atteso</Table.Th>}
            <Table.Th w={120}>Contato</Table.Th><Table.Th w={220}>Motivo della differenza</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {sheet.rows.map((r: any) => {
              const c = counts[r.id]
              const d = diffs[r.id]
              return (
                <Table.Tr key={r.id} bg={d ? 'var(--mantine-color-orange-0)' : undefined}>
                  <Table.Td>{r.code} · {r.description}{r.variant && <Text span c="dimmed"> · {r.variant}</Text>}
                    {d && <Text size="xs" c="orange.8" fw={600}>Atteso {qtyFmt(d.expected)}, contato {qtyFmt(d.counted)}: ricontrolla</Text>}</Table.Td>
                  <Table.Td>{r.lot_number ?? ''}{r.expiry_date && <Text span size="xs" c="dimmed"> {fmtDate(r.expiry_date)}</Text>}</Table.Td>
                  {!blind && <Table.Td ta="right">{qtyFmt(r.expected)}</Table.Td>}
                  <Table.Td><NumberInput size="xs" min={0} value={c?.counted} onChange={(v) => { setCounts({ ...counts, [r.id]: { ...c, counted: v } }); if (d) setDiffs(({ [r.id]: _x, ...rest }) => rest) }} disabled={!warehouseRole} /></Table.Td>
                  <Table.Td>{needReason(r.id) && <Select size="xs" placeholder="Motivo" data={reasons} value={c?.reason} onChange={(v) => setCounts({ ...counts, [r.id]: { ...c, reason: v } })} error={!c?.reason} />}</Table.Td>
                </Table.Tr>
              )
            })}
            {extra.map((x, i) => (
              <Table.Tr key={'x' + i} bg="var(--mantine-color-teal-0)">
                <Table.Td>{x.code} · {x.description} <Badge size="xs" color="teal">in più</Badge></Table.Td>
                <Table.Td>{x.lot_managed && <TextInput size="xs" placeholder="Lotto" value={x.lot_number} onChange={(e) => { const v = e.currentTarget.value.toUpperCase(); setExtra(extra.map((y, n) => (n === i ? { ...y, lot_number: v } : y))) }} />}</Table.Td>
                {!blind && <Table.Td ta="right">0</Table.Td>}
                <Table.Td><NumberInput size="xs" min={0} value={x.counted} onChange={(v) => setExtra(extra.map((y, n) => (n === i ? { ...y, counted: v } : y)))} /></Table.Td>
                <Table.Td><Group gap={4} wrap="nowrap"><Select size="xs" placeholder="Motivo" data={reasons} value={x.reason} onChange={(v) => setExtra(extra.map((y, n) => (n === i ? { ...y, reason: v } : y)))} error={!x.reason} style={{ flex: 1 }} />
                  <ActionIcon size="sm" variant="subtle" color="red" onClick={() => setExtra(extra.filter((_, n) => n !== i))}><IconTrash size={14} /></ActionIcon></Group></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
      {warehouseRole && (
        <Select placeholder="Merce trovata sul furgone ma non in elenco: cerca l'articolo" searchable searchValue={q} onSearchChange={setQ} value={null} leftSection={<IconPlus size={14} />}
          data={found.map((i) => ({ value: i.id, label: `${i.code} · ${i.description}` }))} nothingFoundMessage={q.length < 2 ? 'Scrivi almeno 2 lettere' : 'Nessun articolo'}
          onChange={(v) => { const f = found.find((x) => x.id === v); if (f) setExtra([...extra, { item_id: f.id, code: f.code, description: f.description, lot_managed: f.lot_managed, variant_id: null, lot_number: '', counted: 1, reason: null }]); setQ('') }} />
      )}
      <Cash t={t} />
      <Paper withBorder p="md">
        <Radio.Group label="La merce contata" value={remaining} onChange={setRemaining}>
          <Group mt="xs"><Radio value="rientra" label="rientra in magazzino" /><Radio value="resta" label="resta sul furgone per il giro successivo" /></Group>
        </Radio.Group>
      </Paper>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {t.signatures.agente ? (
          <Paper withBorder p="md"><Text size="sm" fw={500}>Firma dell'agente (al rientro)</Text>
            <img src={t.signatures.agente.url} alt="" style={{ height: 80, objectFit: 'contain' }} /><Text size="sm">{t.signatures.agente.signer_name}</Text></Paper>
        ) : <Paper withBorder p="md"><SignaturePad label="Firma dell'agente" value={sigAgent} onChange={setSigAgent} height={150} /></Paper>}
        <Paper withBorder p="md"><SignaturePad label="Firma del magazziniere" value={sigWh} onChange={setSigWh} height={150} /></Paper>
      </SimpleGrid>
      <Group justify="flex-end">
        {!allCounted && <Text size="sm" c="dimmed">Conta tutte le righe (0 se l'articolo non c'è)</Text>}
        <Button size="md" leftSection={<IconCheck size={18} />} onClick={confirm} loading={busy} disabled={!warehouseRole || !allCounted || missingReasons || !sigOk}>
          Conferma il rientro
        </Button>
      </Group>
    </Stack>
  )
}

function Cash({ t }: { t: any }) {
  const rows = t.summary.cash
  if (!rows.length) return null
  return (
    <Paper withBorder p="md">
      <Text fw={700} mb="xs">Quadratura di cassa</Text>
      <Table fz="sm">
        <Table.Thead><Table.Tr><Table.Th>Metodo</Table.Th><Table.Th ta="right">Incassato nei documenti</Table.Th><Table.Th ta="right">Consegnato dall'agente</Table.Th><Table.Th ta="right">Differenza</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>{rows.map((c: any) => (
          <Table.Tr key={c.method}><Table.Td>{c.label}{c.to_deposit ? '' : <Text span size="xs" c="dimmed"> (già in banca)</Text>}</Table.Td>
            <Table.Td ta="right">{fmtEuro(c.collected)}</Table.Td><Table.Td ta="right">{c.declared !== null ? fmtEuro(c.declared) : '—'}</Table.Td>
            <Table.Td ta="right" c={Number(c.difference) < 0 ? 'red' : Number(c.difference) > 0 ? 'teal' : undefined} fw={Number(c.difference) ? 700 : undefined}>{c.difference !== null ? fmtEuro(c.difference) : ''}</Table.Td></Table.Tr>))}
        </Table.Tbody>
      </Table>
    </Paper>
  )
}

/** Rientro dichiarato dall'ufficio (agente senza dispositivo o dispositivo guasto). */
function OfficeReturn({ t, onDone }: { t: any; onDone: () => void }) {
  const [km, setKm] = useState<number | string>('')
  const [cash, setCash] = useState<Record<string, number | string>>({ contanti: '', assegno: '' })
  if (t.status === 'preparazione') return <Alert color="gray">Il giro non è ancora partito.</Alert>
  return (
    <Stack>
      <Alert color="blue" icon={<ThemeIcon variant="light" size="sm"><IconTruckDelivery size={14} /></ThemeIcon>}>
        Il furgone è in giro. Al rientro l'agente lo dichiara dal suo dispositivo (km, contanti e assegni); se non può, puoi farlo qui.
      </Alert>
      <Paper withBorder p="md" maw={520}>
        <SimpleGrid cols={3}>
          <NumberInput label="Km al rientro" value={km} onChange={setKm} min={0} />
          <NumberInput label="Contanti" value={cash.contanti} onChange={(v) => setCash({ ...cash, contanti: v })} decimalScale={2} min={0} />
          <NumberInput label="Assegni" value={cash.assegno} onChange={(v) => setCash({ ...cash, assegno: v })} decimalScale={2} min={0} />
        </SimpleGrid>
        <Group justify="flex-end" mt="md">
          <Button variant="light" onClick={async () => {
            try {
              await TV(`/giri/${t.id}/rientro`, { body: { km_end: km === '' ? null : Number(km), cash: Object.fromEntries(Object.entries(cash).filter(([, v]) => v !== '').map(([k, v]) => [k, String(v)])) } })
              notifyOk('Rientro registrato: ora il magazziniere verifica la merce')
              onDone()
            } catch (e) { notifyError(e) }
          }}>Registra il rientro</Button>
        </Group>
      </Paper>
    </Stack>
  )
}
