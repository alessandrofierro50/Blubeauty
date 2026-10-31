import { Badge, Button, Group, Paper, SegmentedControl, Select, SimpleGrid, Table, Text, TextInput } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { fmtDate, fmtEuro, isoDate } from '../../api'
import { PageTitle, Stat, notifyError } from '../../components'
import { useItemSearch } from '../anagrafiche/shared'
import { CustomerPicker, S } from './shared'

const n = (v: any) => Number(v).toLocaleString('it-IT', { maximumFractionDigits: 3 })

function Period({ from, to, setFrom, setTo }: { from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void }) {
  const y = new Date().getFullYear()
  const preset = (a: string, b: string) => { setFrom(a); setTo(b) }
  return (
    <Group gap="xs" align="flex-end" wrap="wrap">
      <TextInput type="date" label="Dal" value={from} onChange={(e) => setFrom(e.currentTarget.value)} />
      <TextInput type="date" label="Al" value={to} onChange={(e) => setTo(e.currentTarget.value)} />
      <Button size="xs" variant="subtle" onClick={() => preset(`${y}-01-01`, isoDate(new Date()))}>Anno in corso</Button>
      <Button size="xs" variant="subtle" onClick={() => preset(`${y - 1}-01-01`, `${y - 1}-12-31`)}>Anno scorso</Button>
      <Button size="xs" variant="subtle" onClick={() => preset('', '')}>Sempre</Button>
    </Group>
  )
}

function csv(name: string, header: string[], rows: (string | number | null)[][]) {
  const esc = (v: any) => { const s = v == null ? '' : String(v); return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }
  const body = [header, ...rows].map((r) => r.map(esc).join(';')).join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8' }))
  a.download = name
  a.click()
}

export function ItemHistory() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const itemId = params.get('item')
  const s = useItemSearch()
  const [label, setLabel] = useState<string | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [dir, setDir] = useState('tutti')
  const [data, setData] = useState<any>(null)
  useEffect(() => {
    if (!itemId) { setData(null); return }
    const p = new URLSearchParams({ item_id: itemId })
    if (from) p.set('date_from', from)
    if (to) p.set('date_to', to)
    if (dir !== 'tutti') p.set('direzione', dir)
    S('/storico-articolo?' + p).then((r) => { setData(r); setLabel(`${r.item.code} — ${r.item.description}`) }).catch(notifyError)
  }, [itemId, from, to, dir])
  const options = [...(itemId && label ? [{ value: itemId, label }] : []), ...s.options.filter((o) => o.value !== itemId)]
  const sm = data?.summary
  return (
    <>
      <PageTitle title="Storico articolo" subtitle="Da chi l'hai comprato e a chi l'hai venduto, con quantità e prezzi" />
      <Paper withBorder p="md" mb="md">
        <Group align="flex-end" wrap="wrap">
          <Select label="Articolo" placeholder="Cerca per codice o descrizione" searchable w={360} data={options} value={itemId}
            searchValue={s.q} onSearchChange={s.setQ} filter={({ options: o }) => o} nothingFoundMessage={s.q.length >= 2 ? 'Nessun articolo' : 'Scrivi almeno 2 caratteri'}
            onChange={(v) => v && setParams({ item: v })} />
          <Period from={from} to={to} setFrom={setFrom} setTo={setTo} />
          <SegmentedControl value={dir} onChange={setDir} data={[{ value: 'tutti', label: 'Tutto' }, { value: 'acquisto', label: 'Acquisti' }, { value: 'vendita', label: 'Vendite' }]} />
        </Group>
      </Paper>
      {data && (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
            <Stat label="Acquistato" value={`${n(sm.bought_qty)} ${data.item.unit}`} hint={fmtEuro(sm.bought_amount)} />
            <Stat label="Prezzo medio d'acquisto" value={sm.avg_purchase ? fmtEuro(sm.avg_purchase) : '—'} />
            <Stat label="Venduto" value={`${n(sm.sold_qty)} ${data.item.unit}`} hint={fmtEuro(sm.sold_amount)} />
            <Stat label="Prezzo medio di vendita" value={sm.avg_sale ? fmtEuro(sm.avg_sale) : '—'}
              hint={sm.avg_sale && sm.avg_purchase ? `ricarico ${((Number(sm.avg_sale) / Number(sm.avg_purchase) - 1) * 100).toFixed(1).replace('.', ',')}%` : undefined} />
          </SimpleGrid>
          <Paper withBorder>
            <Group justify="flex-end" p="xs"><Button size="xs" variant="subtle" leftSection={<IconDownload size={14} />} onClick={() => csv(`storico-${data.item.code}.csv`, ['Data', 'Tipo', 'Documento', 'Soggetto', 'Variante', 'Lotto', 'Quantità', 'Prezzo netto', 'Importo'], data.rows.map((r: any) => [r.date, r.direction, `${r.label} ${r.number ?? ''}`, r.party, r.variant, r.lot, r.quantity, r.net_price, r.total]))}>Esporta CSV</Button></Group>
            <Table.ScrollContainer minWidth={760}>
              <Table highlightOnHover verticalSpacing={6}>
                <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Documento</Table.Th><Table.Th>Fornitore / cliente</Table.Th><Table.Th>Variante · lotto</Table.Th><Table.Th ta="right">Q.tà</Table.Th><Table.Th ta="right">Prezzo netto</Table.Th><Table.Th ta="right">Importo</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {data.rows.map((r: any, i: number) => (
                    <Table.Tr key={i} style={{ cursor: 'pointer', opacity: r.counted ? 1 : 0.55 }} onClick={() => nav(`/${r.direction === 'acquisto' ? 'acquisti' : 'vendite'}/${r.document_id}`)}>
                      <Table.Td fz="sm">{fmtDate(r.date)}</Table.Td>
                      <Table.Td><Group gap={6} wrap="nowrap"><Badge size="sm" variant="light" color={r.direction === 'acquisto' ? 'teal' : 'blue'}>{r.direction === 'acquisto' ? 'Acq.' : 'Vend.'}</Badge><Text size="sm">{r.label} {r.number ?? r.external_number ?? ''}</Text></Group></Table.Td>
                      <Table.Td fz="sm">{r.party}</Table.Td>
                      <Table.Td fz="xs">{[r.variant, r.lot && `lotto ${r.lot}`].filter(Boolean).join(' · ')}</Table.Td>
                      <Table.Td ta="right" c={Number(r.quantity) < 0 ? 'red' : undefined}>{n(r.quantity)}</Table.Td>
                      <Table.Td ta="right">{r.net_price ? fmtEuro(r.net_price) : '—'}</Table.Td>
                      <Table.Td ta="right" fw={600}>{fmtEuro(r.total)}</Table.Td>
                    </Table.Tr>
                  ))}
                  {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg">Nessun movimento nel periodo</Text></Table.Td></Table.Tr>}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
            {data.rows.some((r: any) => !r.counted) && <Text size="xs" c="dimmed" p="xs">Le righe più chiare sono fatture di DDT già contati: non entrano nei totali.</Text>}
          </Paper>
        </>
      )}
      {!itemId && <Paper withBorder p="xl"><Text ta="center" c="dimmed">Scegli un articolo per vederne la storia.</Text></Paper>}
    </>
  )
}

export function CustomerPurchases() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const partyId = params.get('party')
  const y = new Date().getFullYear()
  const [from, setFrom] = useState(`${y}-01-01`)
  const [to, setTo] = useState(isoDate(new Date()))
  const [q, setQ] = useState('')
  const [data, setData] = useState<any>(null)
  useEffect(() => {
    if (!partyId) { setData(null); return }
    const p = new URLSearchParams({ party_id: partyId })
    if (from) p.set('date_from', from)
    if (to) p.set('date_to', to)
    S('/acquistato-cliente?' + p).then(setData).catch(notifyError)
  }, [partyId, from, to])
  const rows = data?.rows.filter((r: any) => !q || `${r.code} ${r.description}`.toLowerCase().includes(q.toLowerCase())) ?? []
  return (
    <>
      <PageTitle title="Acquistato per cliente" subtitle="Cosa ha comprato un cliente in un periodo: quantità, importi, ultimo prezzo" />
      <Paper withBorder p="md" mb="md">
        <Group align="flex-end" wrap="wrap">
          <CustomerPicker label="Cliente" value={partyId} onChange={(v) => v && setParams({ party: v })} w={320} />
          <Period from={from} to={to} setFrom={setFrom} setTo={setTo} />
        </Group>
      </Paper>
      {data && (
        <Paper withBorder>
          <Group justify="space-between" p="sm" wrap="wrap">
            <TextInput size="xs" placeholder="Filtra articoli" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={240} />
            <Group gap="md">
              <Text size="sm">{data.rows.length} articoli · totale <b>{fmtEuro(data.total)}</b> + IVA</Text>
              <Button size="xs" variant="subtle" leftSection={<IconDownload size={14} />} onClick={() => csv(`acquistato-${data.party.name}.csv`, ['Codice', 'Descrizione', 'Variante', 'Quantità', 'Importo', 'Documenti', 'Ultimo acquisto', 'Ultimo prezzo'], data.rows.map((r: any) => [r.code, r.description, r.variant, r.quantity, r.amount, r.documents, r.last_date, r.last_price]))}>Esporta CSV</Button>
              <Button size="xs" onClick={() => nav(`/vendite/nuovo?tipo=PRV&cliente=${partyId}`)}>Nuovo preventivo</Button>
            </Group>
          </Group>
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover verticalSpacing={6}>
              <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th ta="right">Quantità</Table.Th><Table.Th ta="right">Importo</Table.Th><Table.Th ta="right">Documenti</Table.Th><Table.Th>Ultimo acquisto</Table.Th><Table.Th ta="right">Ultimo prezzo</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r: any) => (
                  <Table.Tr key={r.item_id + (r.variant ?? '')} style={{ cursor: 'pointer' }} onClick={() => nav(`/vendite/storico-articolo?item=${r.item_id}`)}>
                    <Table.Td><Text size="xs" ff="monospace" c="dimmed">{r.code}{r.variant ? ` · ${r.variant}` : ''}</Text><Text size="sm">{r.description}</Text></Table.Td>
                    <Table.Td ta="right">{n(r.quantity)} {r.unit}</Table.Td>
                    <Table.Td ta="right" fw={600}>{fmtEuro(r.amount)}</Table.Td>
                    <Table.Td ta="right">{r.documents}</Table.Td>
                    <Table.Td fz="sm">{fmtDate(r.last_date)}</Table.Td>
                    <Table.Td ta="right">{r.last_price ? fmtEuro(r.last_price) : '—'}</Table.Td>
                  </Table.Tr>
                ))}
                {rows.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="lg">Nessun acquisto nel periodo</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {!partyId && <Paper withBorder p="xl"><Text ta="center" c="dimmed">Scegli un cliente.</Text></Paper>}
    </>
  )
}

