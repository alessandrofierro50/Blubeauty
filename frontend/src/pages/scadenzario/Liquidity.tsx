import { CompositeChart } from '@mantine/charts'
import { ActionIcon, Anchor, Badge, Button, Group, Modal, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Tabs, Text, TextInput, Title } from '@mantine/core'
import { IconCamera, IconDownload, IconPrinter, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtDate, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, Stat, notifyError, notifyOk } from '../../components'
import { num } from '../anagrafiche/shared'
import { KIND_LABEL, SC, download, eur0, useAccounts } from './shared'

export default function Liquidity() {
  const [tab, setTab] = useState<string | null>('oggi')
  const [asOf, setAsOf] = useState(isoDate(new Date()))
  const [data, setData] = useState<any>(null)
  const [snaps, setSnaps] = useState<any[]>([])
  const [viewing, setViewing] = useState<any>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState('')
  const [accReload, setAccReload] = useState(0)

  useEffect(() => { setData(null); SC(`/liquidita?as_of=${asOf}`).then(setData).catch(notifyError) }, [asOf, accReload])
  const loadSnaps = () => SC('/fotografie').then(setSnaps).catch(notifyError)
  useEffect(() => { loadSnaps() }, [])

  const today = new Date()
  const lastMonthEnd = isoDate(new Date(today.getFullYear(), today.getMonth(), 0))
  const lastYearEnd = `${today.getFullYear() - 1}-12-31`

  async function saveSnap() {
    try {
      await SC('/fotografie', { body: { name, as_of: asOf } })
      notifyOk('Fotografia salvata')
      setSaveOpen(false); setName(''); loadSnaps()
    } catch (e) { notifyError(e) }
  }
  async function openSnap(id: string) {
    try { setViewing(await SC(`/fotografie/${id}`)) } catch (e) { notifyError(e) }
  }
  async function delSnap(id: string) {
    if (!confirm('Eliminare la fotografia?')) return
    try { await SC(`/fotografie/${id}`, { method: 'DELETE' }); loadSnaps() } catch (e) { notifyError(e) }
  }

  return (
    <>
      <PageTitle title="Liquidità" subtitle="Com'era la situazione a una certa data e come andrà nelle prossime settimane"
        right={<Group className="noprint">
          <Button variant="default" leftSection={<IconPrinter size={16} />} onClick={() => window.print()}>Stampa / PDF</Button>
          <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => download(`/liquidita/excel?as_of=${asOf}`, `liquidita-${asOf}.xlsx`)}>Excel</Button>
          <Button leftSection={<IconCamera size={16} />} onClick={() => { setName(`Situazione al ${fmtDate(asOf)}`); setSaveOpen(true) }}>Salva fotografia</Button>
        </Group>} />
      <style>{'@media print { .noprint, .mantine-AppShell-navbar, .mantine-AppShell-header { display: none !important } .mantine-AppShell-main { padding: 0 !important } }'}</style>
      <Tabs value={tab} onChange={setTab} mb="md" className="noprint">
        <Tabs.List><Tabs.Tab value="oggi">Situazione e previsione</Tabs.Tab><Tabs.Tab value="salvate">Fotografie salvate ({snaps.length})</Tabs.Tab><Tabs.Tab value="conti">Conti cassa e banca</Tabs.Tab></Tabs.List>
      </Tabs>
      {tab === 'oggi' && (
        <>
          <Group mb="md" align="flex-end" className="noprint">
            <TextInput type="date" label="Situazione al" value={asOf} onChange={(e) => e.currentTarget.value && setAsOf(e.currentTarget.value)} />
            <Button size="xs" variant="subtle" onClick={() => setAsOf(isoDate(today))}>Oggi</Button>
            <Button size="xs" variant="subtle" onClick={() => setAsOf(lastMonthEnd)}>Fine mese scorso</Button>
            <Button size="xs" variant="subtle" onClick={() => setAsOf(lastYearEnd)}>Fine anno scorso</Button>
          </Group>
          {!data ? <Loading /> : <SnapshotView data={data} />}
        </>
      )}
      {tab === 'salvate' && (
        <Paper withBorder>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead><Table.Tr><Table.Th>Fotografia</Table.Th><Table.Th>Alla data</Table.Th><Table.Th ta="right">Liquidità</Table.Th><Table.Th ta="right">Posizione netta</Table.Th><Table.Th>Salvata il</Table.Th><Table.Th w={90} /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {snaps.map((x) => (
                <Table.Tr key={x.id} style={{ cursor: 'pointer' }} onClick={() => openSnap(x.id)}>
                  <Table.Td fw={600}>{x.name}</Table.Td><Table.Td>{fmtDate(x.as_of)}</Table.Td>
                  <Table.Td ta="right">{fmtEuro(x.liquidity)}</Table.Td><Table.Td ta="right">{fmtEuro(x.net_position)}</Table.Td>
                  <Table.Td fz="sm" c="dimmed">{new Date(x.created_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
                  <Table.Td onClick={(e) => e.stopPropagation()}><Group gap={2}>
                    <ActionIcon variant="subtle" onClick={() => download(`/fotografie/${x.id}/excel`, `fotografia-${x.as_of}.xlsx`)}><IconDownload size={16} /></ActionIcon>
                    <ActionIcon variant="subtle" color="red" onClick={() => delSnap(x.id)}><IconTrash size={16} /></ActionIcon>
                  </Group></Table.Td>
                </Table.Tr>
              ))}
              {snaps.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="lg">Nessuna fotografia. Salvane una per confrontare la situazione nel tempo (es. a fine mese).</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      {tab === 'conti' && <Accounts onChanged={() => setAccReload((r) => r + 1)} />}

      <Modal opened={saveOpen} onClose={() => setSaveOpen(false)} title="Salva fotografia">
        <Stack>
          <Text size="sm" c="dimmed">I numeri vengono congelati così come sono adesso: potrai riaprirli e confrontarli anche se in seguito registri altri incassi o pagamenti.</Text>
          <TextInput label="Nome" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <Group justify="flex-end"><Button onClick={saveSnap} disabled={!name}>Salva</Button></Group>
        </Stack>
      </Modal>
      <Modal opened={!!viewing} onClose={() => setViewing(null)} size="90%" title={viewing ? `${viewing.name} · situazione al ${fmtDate(viewing.as_of)}` : ''}>
        {viewing && <SnapshotView data={viewing.data} frozen={viewing.created_at} />}
      </Modal>
    </>
  )
}

function SnapshotView({ data, frozen }: { data: any; frozen?: string }) {
  const nav = useNavigate()
  const [mode, setMode] = useState('weeks')
  const rows = data[mode] as any[]
  const chart = rows.map((r) => ({ label: r.label, Entrate: Number(r.in), Uscite: -Number(r.out), Saldo: Number(r.balance) }))
  const r = data.receivables
  const p = data.payables
  return (
    <Stack>
      {frozen && <Badge variant="light" size="lg">Dati congelati il {new Date(frozen).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Badge>}
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Stat label="Liquidità (cassa e banche)" value={fmtEuro(data.liquidity)} />
        <Stat label="Crediti da incassare" value={fmtEuro(r.open)} hint={Number(r.overdue) ? `scaduti ${fmtEuro(r.overdue)} (${r.overdue_count})` : 'nessuno scaduto'} />
        <Stat label="Debiti da pagare" value={fmtEuro(p.open)} hint={Number(p.overdue) ? `scaduti ${fmtEuro(p.overdue)} (${p.overdue_count})` : 'nessuno scaduto'} />
        <Stat label="Posizione netta" value={<Text span fw={700} fz="inherit" c={Number(data.net_position) < 0 ? 'red' : 'green'}>{fmtEuro(data.net_position)}</Text>} hint="liquidità + crediti − debiti" />
      </SimpleGrid>
      <Paper withBorder p="md">
        <Group justify="space-between" mb="sm">
          <Title order={5}>Previsione dei flussi</Title>
          <SegmentedControl size="xs" value={mode} onChange={setMode} data={[{ value: 'weeks', label: 'Per settimana' }, { value: 'months', label: 'Per mese' }]} />
        </Group>
        <CompositeChart h={260} data={chart} dataKey="label" withLegend valueFormatter={(v) => eur0(v)} maxBarWidth={34}
          series={[{ name: 'Entrate', color: 'teal.6', type: 'bar' }, { name: 'Uscite', color: 'red.5', type: 'bar' }, { name: 'Saldo', color: 'blu.7', type: 'line' }]}
          referenceLines={[{ y: 0, color: 'gray.5' }]} />
        <Table mt="md" verticalSpacing={4} fz="sm">
          <Table.Thead><Table.Tr><Table.Th>Periodo</Table.Th><Table.Th ta="right">Entrate</Table.Th><Table.Th ta="right">Uscite</Table.Th><Table.Th ta="right">Saldo del periodo</Table.Th><Table.Th ta="right">Liquidità prevista</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((x) => (
              <Table.Tr key={x.label} bg={x.overdue ? 'var(--mantine-color-red-light)' : undefined}>
                <Table.Td fw={x.overdue ? 600 : undefined}>{x.label}</Table.Td>
                <Table.Td ta="right" c="teal">{Number(x.in) ? fmtEuro(x.in) : '—'}</Table.Td>
                <Table.Td ta="right" c="red">{Number(x.out) ? fmtEuro(x.out) : '—'}</Table.Td>
                <Table.Td ta="right">{fmtEuro(x.net)}</Table.Td>
                <Table.Td ta="right" fw={700} c={Number(x.balance) < 0 ? 'red' : undefined}>{fmtEuro(x.balance)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed" mt="xs">«Già scaduto» comprende crediti e debiti scaduti alla data e non ancora chiusi: la previsione li considera come da incassare/pagare subito.</Text>
      </Paper>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Paper withBorder p="md">
          <Title order={6} mb="xs">Conti alla data</Title>
          {data.accounts.map((a: any) => <Group key={a.id} justify="space-between"><Text size="sm">{a.name} <Text span size="xs" c="dimmed">{KIND_LABEL[a.kind]}</Text></Text><Text size="sm" fw={600} c={Number(a.balance) < 0 ? 'red' : undefined}>{fmtEuro(a.balance)}</Text></Group>)}
          {data.accounts.length === 0 && <Text size="sm" c="dimmed">Nessun conto: aggiungili nella scheda «Conti cassa e banca».</Text>}
        </Paper>
        <Paper withBorder p="md">
          <Title order={6} mb="xs">Incassato e pagato nell'anno</Title>
          {data.ytd.map((m: any) => <Group key={m.month} justify="space-between"><Text size="sm">{m.month}</Text><Text size="sm"><Text span c="teal">+{eur0(m.in)}</Text> <Text span c="red">−{eur0(m.out)}</Text></Text></Group>)}
          <Group justify="space-between" mt={4} pt={4} style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}><Text size="sm" fw={600}>Totale</Text><Text size="sm" fw={600}><Text span c="teal">+{eur0(data.collected_ytd)}</Text> <Text span c="red">−{eur0(data.paid_ytd)}</Text></Text></Group>
        </Paper>
        <Paper withBorder p="md">
          <Title order={6} mb="xs">Clienti con più scaduto</Title>
          {data.top_overdue.map((c: any) => <Group key={c.party_id} justify="space-between"><Anchor size="sm" onClick={() => nav(`/scadenzario?direzione=attiva&stato=scadute&party=${c.party_id}`)}>{c.name}</Anchor><Text size="sm" fw={600} c="red">{fmtEuro(c.amount)}</Text></Group>)}
          {data.top_overdue.length === 0 ? <Text size="sm" c="dimmed">Nessun cliente in ritardo.</Text> : <Anchor size="xs" onClick={() => nav('/scadenzario/solleciti')}>Vai ai solleciti →</Anchor>}
        </Paper>
      </SimpleGrid>
    </Stack>
  )
}

function Accounts({ onChanged }: { onChanged: () => void }) {
  const [reload, setReload] = useState(0)
  const rows = useAccounts(reload)
  const [edit, setEdit] = useState<any>(null)
  async function save() {
    try {
      const body = { ...edit, opening_balance: String(edit.opening_balance || 0), opening_date: edit.opening_date || null, iban: edit.iban || null }
      if (edit.id) await SC(`/conti/${edit.id}`, { method: 'PUT', body })
      else await SC('/conti', { body })
      setEdit(null); setReload((r) => r + 1); onChanged()
    } catch (e) { notifyError(e) }
  }
  async function remove(a: any) {
    if (!confirm(`Eliminare ${a.name}?`)) return
    try { const r = await SC(`/conti/${a.id}`, { method: 'DELETE' }); if (r.deactivated) notifyOk('Il conto ha movimenti: è stato disattivato'); setReload((x) => x + 1); onChanged() } catch (e) { notifyError(e) }
  }
  if (!rows) return <Loading />
  return (
    <>
      <Group justify="flex-end" mb="sm"><Button onClick={() => setEdit({ name: '', kind: 'banca', iban: '', opening_balance: 0, opening_date: isoDate(new Date()), is_default: !rows.length, active: true })}>Nuovo conto</Button></Group>
      <Paper withBorder>
        <Table verticalSpacing="sm" highlightOnHover>
          <Table.Thead><Table.Tr><Table.Th>Conto</Table.Th><Table.Th>Tipo</Table.Th><Table.Th>IBAN</Table.Th><Table.Th ta="right">Saldo iniziale</Table.Th><Table.Th ta="right">Saldo oggi</Table.Th><Table.Th w={50} /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((a) => (
              <Table.Tr key={a.id} style={{ cursor: 'pointer', opacity: a.active ? 1 : 0.5 }} onClick={() => setEdit({ ...a, opening_balance: Number(a.opening_balance) })}>
                <Table.Td fw={600}>{a.name} {a.is_default && <Badge size="xs" variant="light">predefinito</Badge>}</Table.Td>
                <Table.Td>{KIND_LABEL[a.kind]}</Table.Td><Table.Td ff="monospace" fz="xs">{a.iban ?? ''}</Table.Td>
                <Table.Td ta="right">{fmtEuro(a.opening_balance)}{a.opening_date && <Text size="10px" c="dimmed">al {fmtDate(a.opening_date)}</Text>}</Table.Td>
                <Table.Td ta="right" fw={700}>{fmtEuro(a.balance)}</Table.Td>
                <Table.Td onClick={(e) => e.stopPropagation()}><ActionIcon variant="subtle" color="red" onClick={() => remove(a)}><IconTrash size={16} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}
            {rows.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="lg">Aggiungi la cassa e i conti bancari con il loro saldo a una data: da lì in poi BluBeauty calcola i saldi con gli incassi e i pagamenti registrati.</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Paper>
      <Modal opened={!!edit} onClose={() => setEdit(null)} title={edit?.id ? 'Modifica conto' : 'Nuovo conto'}>
        {edit && (
          <Stack>
            <TextInput label="Nome" placeholder="es. Banca Intesa c/c 1234" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.currentTarget.value })} />
            <Select label="Tipo" data={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))} value={edit.kind} onChange={(v) => setEdit({ ...edit, kind: v })} />
            {edit.kind === 'banca' && <TextInput label="IBAN" value={edit.iban ?? ''} onChange={(e) => setEdit({ ...edit, iban: e.currentTarget.value })} />}
            <SimpleGrid cols={2}>
              <NumberInput label="Saldo iniziale" value={num(edit.opening_balance)} onChange={(v) => setEdit({ ...edit, opening_balance: v })} decimalScale={2} prefix="€ " />
              <TextInput type="date" label="alla data" value={edit.opening_date ?? ''} onChange={(e) => setEdit({ ...edit, opening_date: e.currentTarget.value })} />
            </SimpleGrid>
            <Switch label="Conto predefinito per incassi e pagamenti" checked={edit.is_default} onChange={(e) => setEdit({ ...edit, is_default: e.currentTarget.checked })} />
            {edit.id && <Switch label="Attivo" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.currentTarget.checked })} />}
            <Group justify="flex-end"><Button onClick={save} disabled={!edit.name}>Salva</Button></Group>
          </Stack>
        )}
      </Modal>
    </>
  )
}
