import { Anchor, Badge, Button, Checkbox, Group, Menu, Modal, Pagination, Paper, SegmentedControl, Stack, Switch, Table, Text, TextInput } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconChevronDown, IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { fmtDate, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import ExportXmlButton from '../fatturapa/ExportXml'
import { FE, RESENDABLE, SdiBadge, useModule } from '../fatturapa/shared'
import { CustomerPicker, S, SHORT, StatusBadge, TYPE_COLOR, docNumber } from './shared'

const FILTERS = [
  { value: 'tutti', label: 'Tutti' }, { value: 'PRV', label: 'Preventivi' }, { value: 'ORC', label: 'Ordini' },
  { value: 'DDT', label: 'DDT' }, { value: 'FTI', label: 'Fatture' }, { value: 'NC', label: 'Note credito' },
  { value: 'da_fatturare', label: 'DDT da fatturare' }, { value: 'da_incassare', label: 'Da incassare' },
]

export default function SalesList() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const tipo = params.get('tipo') ?? 'tutti'
  const [q, setQ] = useState('')
  const [dq] = useDebouncedValue(q, 250)
  const [party, setParty] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)
  const [sel, setSel] = useState<string[]>([])
  const [deferred, setDeferred] = useState(false)
  const [invDate, setInvDate] = useState(isoDate(new Date()))
  const [invConfirm, setInvConfirm] = useState(true)
  const [busy, setBusy] = useState(false)
  const fatturapa = useModule('fatturapa')

  const load = () => {
    const p = new URLSearchParams({ page: String(page) })
    if (tipo === 'da_fatturare') p.set('da_fatturare', 'true')
    else if (tipo === 'da_incassare') p.set('da_incassare', 'true')
    else if (tipo !== 'tutti') p.set('tipo', tipo)
    if (dq) p.set('q', dq)
    if (party) p.set('party_id', party)
    S('/documenti?' + p).then(setData).catch(notifyError)
  }
  useEffect(load, [tipo, dq, page, party])
  useEffect(() => { setPage(1); setSel([]) }, [tipo, dq, party])

  async function runDeferred() {
    setBusy(true)
    try {
      const r = await S('/fatturazione-differita', { body: { ddt_ids: sel, doc_date: invDate, confirm: invConfirm } })
      r.warnings?.forEach((w: string) => notifyError(new Error(w)))
      notifyOk(`${r.documents.length} ${r.documents.length === 1 ? 'fattura creata' : 'fatture create'}${invConfirm ? ' ed emesse' : ' in bozza'}`)
      setDeferred(false); setSel([])
      if (r.documents.length === 1) nav(`/vendite/${r.documents[0].id}`)
      else setParams({ tipo: 'FTI' })
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  async function sendSdi() {
    setBusy(true)
    try {
      const r = await FE('/invia-multiplo', { body: { ids: sel } })
      r.results.filter((x: any) => x.status !== 'presa_in_carico').forEach((x: any) => notifyError(new Error(`Fattura ${x.number}: ${x.error}`)))
      if (r.sent) notifyOk(`${r.sent} fatture inviate a SDI`)
      setSel([]); load()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  const sdiSelectable = fatturapa && (tipo === 'FTI' || tipo === 'NC')
  const selectable = tipo === 'da_fatturare' || sdiSelectable
  const selCustomers = new Set(data?.rows.filter((r: any) => sel.includes(r.id)).map((r: any) => r.party_id))
  return (
    <>
      <PageTitle title="Vendite" subtitle="Preventivi, ordini, DDT, fatture e note di credito"
        right={<Group gap="xs">
          {fatturapa && ['FTI', 'NC'].includes(tipo) && <ExportXmlButton />}
          <Menu position="bottom-end">
            <Menu.Target><Button leftSection={<IconPlus size={16} />} rightSection={<IconChevronDown size={14} />}>Nuovo</Button></Menu.Target>
            <Menu.Dropdown>
              {['PRV', 'ORC', 'DDT', 'FTI', 'NC'].map((t) => (
                <Menu.Item key={t} onClick={() => nav(`/vendite/nuovo?tipo=${t}`)}>
                  {({ PRV: 'Preventivo', ORC: 'Ordine cliente', DDT: 'DDT (consegna merce)', FTI: 'Fattura immediata', NC: 'Nota di credito' } as any)[t]}
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
        </Group>} />
      <Group mb="md" wrap="wrap" align="flex-end">
        <SegmentedControl value={tipo} onChange={(v) => setParams(v === 'tutti' ? {} : { tipo: v })} data={FILTERS} />
        <CustomerPicker value={party} onChange={setParty} w={240} />
        {party && <Button variant="subtle" size="xs" onClick={() => setParty(null)}>Tutti i clienti</Button>}
        <TextInput placeholder="Numero o riferimento" leftSection={<IconSearch size={16} />} value={q} onChange={(e) => setQ(e.currentTarget.value)} style={{ flex: 1, minWidth: 180 }} />
      </Group>
      {sdiSelectable && sel.length > 0 && (
        <Paper withBorder p="sm" mb="md" bg="var(--mantine-color-blue-light)">
          <Group justify="space-between"><Text size="sm">{sel.length} fatture selezionate</Text><Button size="xs" loading={busy} onClick={sendSdi}>Invia a SDI</Button></Group>
        </Paper>
      )}
      {tipo === 'da_fatturare' && (
        <Paper withBorder p="sm" mb="md" bg="var(--mantine-color-blue-light)">
          <Group justify="space-between">
            <Text size="sm">Seleziona i DDT da fatturare: verrà creata <b>una fattura per ogni cliente</b> con tutti i suoi DDT. Per la fine del mese c'è <Anchor size="sm" onClick={() => nav('/vendite/fatturazione-ddt')}>Fatturazione DDT di fine mese</Anchor>.</Text>
            <Group>
              <Button variant="default" size="xs" onClick={() => setSel(sel.length ? [] : data?.rows.map((r: any) => r.id) ?? [])}>{sel.length ? 'Deseleziona' : 'Seleziona tutti'}</Button>
              <Button size="xs" disabled={!sel.length} onClick={() => setDeferred(true)}>Fattura {sel.length} DDT</Button>
            </Group>
          </Group>
        </Paper>
      )}
      {!data ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead><Table.Tr>{selectable && <Table.Th w={36} />}<Table.Th>Documento</Table.Th><Table.Th>Data</Table.Th><Table.Th>Cliente</Table.Th><Table.Th>Riferimento</Table.Th><Table.Th ta="right">Totale</Table.Th><Table.Th>Stato</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.rows.map((d: any) => (
                  <Table.Tr key={d.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/vendite/${d.id}`)}>
                    {selectable && <Table.Td onClick={(e) => e.stopPropagation()}>{(!sdiSelectable || (d.sdi_status && RESENDABLE.includes(d.sdi_status))) && <Checkbox checked={sel.includes(d.id)} onChange={(e) => setSel(e.currentTarget.checked ? [...sel, d.id] : sel.filter((x) => x !== d.id))} />}</Table.Td>}
                    <Table.Td><Group gap={6} wrap="nowrap"><Badge variant="light" color={TYPE_COLOR[d.doc_type]}>{SHORT[d.doc_type]}</Badge><Text size="sm" fw={600}>{docNumber(d)}</Text></Group></Table.Td>
                    <Table.Td fz="sm">{fmtDate(d.doc_date)}</Table.Td>
                    <Table.Td fz="sm" fw={500}>{d.party_name}</Table.Td>
                    <Table.Td fz="sm" c="dimmed">{d.reference ?? ''}</Table.Td>
                    <Table.Td ta="right" fw={600} c={d.doc_type === 'NC' ? 'red' : undefined}>{d.doc_type === 'NC' ? '−' : ''}{fmtEuro(d.total)}</Table.Td>
                    <Table.Td><Group gap={4} wrap="nowrap"><StatusBadge d={d} />{fatturapa && d.sdi_status && <SdiBadge status={d.sdi_status} />}</Group></Table.Td>
                  </Table.Tr>
                ))}
                {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg">Nessun documento</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {data.total > 0 && (
            <Group justify="space-between" p="sm" style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}>
              <Text size="sm" c="dimmed">{data.total} documenti</Text>
              <Text size="sm">Imponibile <b>{fmtEuro(data.sum_taxable)}</b> · Totale <b>{fmtEuro(data.sum_total)}</b></Text>
            </Group>
          )}
        </Paper>
      )}
      {data && data.total > data.page_size && <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / data.page_size)} value={page} onChange={setPage} /></Group>}
      <Modal opened={deferred} onClose={() => setDeferred(false)} title="Fatturazione differita">
        <Stack>
          <Text size="sm">{sel.length} DDT di {selCustomers.size} {selCustomers.size === 1 ? 'cliente' : 'clienti'}: {selCustomers.size === 1 ? 'verrà creata una fattura' : `verranno create ${selCustomers.size} fatture`}. Il magazzino non viene movimentato di nuovo.</Text>
          <TextInput type="date" label="Data delle fatture" value={invDate} onChange={(e) => setInvDate(e.currentTarget.value)} />
          <Switch label="Emetti subito (altrimenti restano in bozza da controllare)" checked={invConfirm} onChange={(e) => setInvConfirm(e.currentTarget.checked)} />
          <Group justify="flex-end"><Button onClick={runDeferred} loading={busy}>Crea fatture</Button></Group>
        </Stack>
      </Modal>
    </>
  )
}
