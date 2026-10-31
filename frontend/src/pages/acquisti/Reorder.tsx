import { Button, Checkbox, Group, NumberInput, Paper, Table, Text, Title } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { qty } from '../magazzino/shared'
import { P } from './Purchases'

export default function Reorder() {
  const nav = useNavigate()
  const [groups, setGroups] = useState<any[] | null>(null)
  const [sel, setSel] = useState<Record<string, boolean>>({})
  const [qtys, setQtys] = useState<Record<string, number | string>>({})
  useEffect(() => {
    P('/proposta-riordino').then((g) => {
      setGroups(g)
      const s: Record<string, boolean> = {}, q: Record<string, number | string> = {}
      g.forEach((x: any) => x.items.forEach((i: any) => { s[i.item_id] = !!x.supplier_id; q[i.item_id] = Number(i.proposed_qty) }))
      setSel(s); setQtys(q)
    }).catch(notifyError)
  }, [])
  if (!groups) return <Loading />

  async function createOrders() {
    try {
      let n = 0
      for (const g of groups!) {
        if (!g.supplier_id) continue
        const lines = g.items.filter((i: any) => sel[i.item_id] && Number(qtys[i.item_id]) > 0)
          .map((i: any) => ({ item_id: i.item_id, quantity: String(qtys[i.item_id]), unit_price: i.unit_price ?? '0', supplier_code: i.supplier_code }))
        if (!lines.length) continue
        await P('/documenti', { body: { doc_type: 'ORF', party_id: g.supplier_id, lines } })
        n++
      }
      notifyOk(`${n} ordini creati in bozza`)
      nav('/acquisti')
    } catch (e) { notifyError(e) }
  }

  return (
    <>
      <PageTitle title="Proposta di riordino" subtitle="Articoli sotto il punto di riordino, già tenendo conto di quanto è in ordine"
        right={<Button onClick={createOrders} disabled={!Object.values(sel).some(Boolean)}>Crea gli ordini ai fornitori</Button>} />
      {groups.length === 0 && <Paper withBorder p="xl"><Text ta="center" c="dimmed">Nessun articolo da riordinare. Imposta scorta minima o punto di riordino negli articoli.</Text></Paper>}
      {groups.map((g) => (
        <Paper key={g.supplier_id ?? 'none'} withBorder mb="md">
          <Group p="sm" justify="space-between"><Title order={5}>{g.supplier_name}</Title>
            {!g.supplier_id && <Text size="xs" c="orange">Indica un fornitore preferito negli articoli per ordinarli</Text>}</Group>
          <Table.ScrollContainer minWidth={720}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th w={36} /><Table.Th>Articolo</Table.Th><Table.Th ta="right">Giacenza</Table.Th><Table.Th ta="right">Impegnata</Table.Th><Table.Th ta="right">In ordine</Table.Th><Table.Th ta="right">Soglia</Table.Th><Table.Th w={120}>Da ordinare</Table.Th><Table.Th ta="right">Prezzo</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {g.items.map((i: any) => (
                  <Table.Tr key={i.item_id}>
                    <Table.Td><Checkbox disabled={!g.supplier_id} checked={!!sel[i.item_id]} onChange={(e) => setSel({ ...sel, [i.item_id]: e.currentTarget.checked })} /></Table.Td>
                    <Table.Td fz="sm"><Text span ff="monospace" size="xs" c="dimmed">{i.code}</Text> {i.description}</Table.Td>
                    <Table.Td ta="right" c={Number(i.on_hand) <= 0 ? 'red' : undefined}>{qty(i.on_hand)}</Table.Td>
                    <Table.Td ta="right">{qty(i.reserved)}</Table.Td><Table.Td ta="right">{qty(i.ordered)}</Table.Td><Table.Td ta="right">{qty(i.threshold)}</Table.Td>
                    <Table.Td><NumberInput size="xs" value={qtys[i.item_id]} onChange={(v) => setQtys({ ...qtys, [i.item_id]: v })} min={0} suffix={` ${i.unit}`} /></Table.Td>
                    <Table.Td ta="right" fz="sm">{i.unit_price ? fmtEuro(i.unit_price) : '—'}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      ))}
    </>
  )
}
