import { ActionIcon, Badge, Button, Group, Menu, NumberInput, Paper, Select, Table, Text, TextInput } from '@mantine/core'
import { IconChevronDown, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { fmtEuro } from '../../api'
import { Loading, notifyError, notifyOk } from '../../components'
import { A, dec, num, useItemSearch } from './shared'

/** Listino personalizzato del cliente: prezzi netti (IVA esclusa) per articolo, con scaglioni e validità. */
export default function CustomerPrices({ partyId }: { partyId: string }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [dirty, setDirty] = useState(false)
  const search = useItemSearch()
  const [customers, setCustomers] = useState<any[]>([])

  const load = () => A(`/soggetti/${partyId}/prezzi`).then((r) => { setRows(r); setDirty(false) }).catch(notifyError)
  useEffect(() => {
    load()
    A('/soggetti?tipo=clienti&page_size=200').then((r) => setCustomers(r.rows.filter((c: any) => c.id !== partyId))).catch(() => {})
  }, [partyId])
  if (!rows) return <Loading />

  const upd = (i: number, k: string, v: any) => { setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r))); setDirty(true) }

  async function save() {
    try {
      const body = rows!.map((r) => ({ item_id: r.item_id, variant_id: r.variant_id ?? null, min_qty: dec(r.min_qty) ?? '0',
        net_price: dec(r.net_price) ?? '0', valid_from: r.valid_from || null, valid_to: r.valid_to || null, notes: r.notes || null }))
      setRows(await A(`/soggetti/${partyId}/prezzi`, { method: 'PUT', body }))
      setDirty(false)
      notifyOk('Prezzi netti salvati')
    } catch (e) { notifyError(e) }
  }

  async function change() {
    const v = prompt('Variazione percentuale da applicare a tutti i prezzi (es. 5 oppure -3):')
    if (!v) return
    try {
      await A(`/soggetti/${partyId}/prezzi/variazione`, { body: { percent: v.replace(',', '.') } })
      notifyOk('Prezzi aggiornati')
      load()
    } catch (e) { notifyError(e) }
  }

  async function copyFrom(id: string | null) {
    if (!id) return
    try {
      const r = await A(`/soggetti/${partyId}/prezzi/copia-da/${id}`, { method: 'POST' })
      notifyOk(`Copiati ${r.copied} prezzi`)
      load()
    } catch (e) { notifyError(e) }
  }

  return (
    <Paper withBorder>
      <Group justify="space-between" p="sm" wrap="wrap">
        <Select placeholder="Aggiungi un articolo: cerca per nome o codice" searchable searchValue={search.q} onSearchChange={search.setQ}
          data={search.options} value={null} w={380} maw="100%"
          nothingFoundMessage={search.q.length >= 2 ? 'Nessun articolo' : 'Scrivi almeno 2 caratteri'}
          onChange={(v) => {
            const f = search.found.find((x) => x.id === v)
            if (f) { setRows([...rows, { item_id: f.id, item_code: f.code, item_description: f.description, min_qty: 0, net_price: '', list_price: null, last_cost: f.last_cost }]); setDirty(true) }
            search.setQ('')
          }} />
        <Group gap="xs">
          <Menu position="bottom-end">
            <Menu.Target><Button variant="default" rightSection={<IconChevronDown size={14} />}>Strumenti</Button></Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={change} disabled={dirty || !rows.length}>Aumenta o riduci in %</Menu.Item>
              <Menu.Label>Copia i prezzi da</Menu.Label>
              {customers.slice(0, 15).map((c) => <Menu.Item key={c.id} onClick={() => copyFrom(c.id)} disabled={dirty}>{c.name}</Menu.Item>)}
            </Menu.Dropdown>
          </Menu>
          <Button onClick={save} disabled={!dirty}>Salva prezzi</Button>
        </Group>
      </Group>
      <Table.ScrollContainer minWidth={820}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th>Da q.tà</Table.Th><Table.Th>Prezzo netto €</Table.Th><Table.Th>Listino</Table.Th><Table.Th>Sconto</Table.Th><Table.Th>Dal</Table.Th><Table.Th>Al</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r, i) => {
              const lp = r.list_price != null ? Number(r.list_price) : null
              const disc = lp && r.net_price !== '' ? (1 - Number(r.net_price) / lp) * 100 : null
              const under = r.last_cost && r.net_price !== '' && Number(r.net_price) < Number(r.last_cost)
              return (
                <Table.Tr key={i}>
                  <Table.Td><Text size="sm"><Text span ff="monospace" size="xs" c="dimmed">{r.item_code}</Text> {r.item_description}</Text></Table.Td>
                  <Table.Td><NumberInput value={num(r.min_qty)} onChange={(v) => upd(i, 'min_qty', v)} min={0} w={80} /></Table.Td>
                  <Table.Td><NumberInput value={num(r.net_price)} onChange={(v) => upd(i, 'net_price', v)} decimalScale={4} min={0} w={110} error={under ? 'sotto costo' : undefined} /></Table.Td>
                  <Table.Td fz="sm" c="dimmed">{lp != null ? fmtEuro(lp) : '—'}</Table.Td>
                  <Table.Td>{disc != null && <Badge variant="light" color={disc < 0 ? 'orange' : 'blu'}>{disc.toFixed(1)}%</Badge>}</Table.Td>
                  <Table.Td><TextInput type="date" value={r.valid_from ?? ''} onChange={(e) => upd(i, 'valid_from', e.currentTarget.value)} w={140} /></Table.Td>
                  <Table.Td><TextInput type="date" value={r.valid_to ?? ''} onChange={(e) => upd(i, 'valid_to', e.currentTarget.value)} w={140} /></Table.Td>
                  <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => { setRows(rows.filter((_, j) => j !== i)); setDirty(true) }}><IconTrash size={16} /></ActionIcon></Table.Td>
                </Table.Tr>
              )
            })}
            {rows.length === 0 && <Table.Tr><Table.Td colSpan={8}><Text ta="center" c="dimmed" py="lg" size="sm">Nessun prezzo netto: per questo cliente valgono listino, sconti e promozioni.</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group p="sm" gap={6}><IconPlus size={14} color="var(--mantine-color-dimmed)" /><Text size="xs" c="dimmed">Prezzi IVA esclusa. Il prezzo netto ha sempre la precedenza su listino e promozioni.</Text></Group>
    </Paper>
  )
}
