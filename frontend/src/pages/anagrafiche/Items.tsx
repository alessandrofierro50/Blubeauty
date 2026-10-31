import { Badge, Button, Group, Pagination, Paper, Select, Switch, Table, Text, TextInput } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError } from '../../components'
import { A, ImportExport, categoryOptions, opts, useLookups } from './shared'

export default function Items() {
  const nav = useNavigate()
  const L = useLookups()
  const [q, setQ] = useState('')
  const [dq] = useDebouncedValue(q, 250)
  const [cat, setCat] = useState<string | null>(null)
  const [brand, setBrand] = useState<string | null>(null)
  const [inactive, setInactive] = useState(false)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)

  const load = () => {
    const p = new URLSearchParams({ page: String(page), page_size: '50' })
    if (dq) p.set('q', dq)
    if (cat) p.set('category_id', cat)
    if (brand) p.set('brand_id', brand)
    p.set('active', inactive ? 'false' : 'true')
    A('/articoli?' + p).then(setData).catch(notifyError)
  }
  useEffect(load, [dq, cat, brand, inactive, page])
  useEffect(() => setPage(1), [dq, cat, brand, inactive])

  return (
    <>
      <PageTitle title="Articoli" subtitle={data ? `${data.total} articoli` : undefined}
        right={<Group><ImportExport kind="articoli" onDone={load} />
          <Button leftSection={<IconPlus size={16} />} onClick={() => nav('/articoli/nuovo')}>Nuovo articolo</Button></Group>} />
      <Group mb="md" wrap="wrap" align="flex-end">
        <TextInput placeholder="Codice, descrizione, codice a barre o codice fornitore" leftSection={<IconSearch size={16} />}
          value={q} onChange={(e) => setQ(e.currentTarget.value)} style={{ flex: 1, minWidth: 240 }} autoFocus />
        {L && <Select placeholder="Categoria" data={categoryOptions(L.categories)} value={cat} onChange={setCat} clearable searchable w={200} />}
        {L && L.brands.length > 0 && <Select placeholder="Marca" data={opts(L.brands)} value={brand} onChange={setBrand} clearable w={160} />}
        <Switch label="Disattivati" checked={inactive} onChange={(e) => setInactive(e.currentTarget.checked)} />
      </Group>
      {!data ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr><Table.Th>Codice</Table.Th><Table.Th>Descrizione</Table.Th><Table.Th>Categoria</Table.Th><Table.Th>UM</Table.Th>
                  <Table.Th ta="right">Costo</Table.Th><Table.Th ta="right">Prezzo ({data.price_list})</Table.Th><Table.Th /></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.rows.map((r: any) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/articoli/${r.id}`)}>
                    <Table.Td ff="monospace" fz="sm">{r.code}</Table.Td>
                    <Table.Td>
                      <Group gap="sm" wrap="nowrap">
                        <div style={{ width: 36, height: 36, borderRadius: 6, flexShrink: 0, background: 'var(--mantine-color-gray-1)', overflow: 'hidden' }}>
                          {r.thumb_url && <img src={r.thumb_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
                        </div>
                        <div><Text size="sm" fw={500}>{r.description}</Text>{r.brand && <Text size="xs" c="dimmed">{r.brand}</Text>}</div>
                      </Group>
                    </Table.Td>
                    <Table.Td>{r.category ?? '—'}</Table.Td>
                    <Table.Td>{r.unit}</Table.Td>
                    <Table.Td ta="right">{r.last_cost != null ? fmtEuro(r.last_cost) : '—'}</Table.Td>
                    <Table.Td ta="right" fw={600}>{r.price != null ? fmtEuro(r.price) : '—'}</Table.Td>
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        {r.item_type === 'servizio' && <Badge size="xs" color="gray">servizio</Badge>}
                        {r.has_variants && <Badge size="xs" color="violet" variant="light">varianti</Badge>}
                        {r.lot_managed && <Badge size="xs" color="orange" variant="light">lotti</Badge>}
                        {r.serial_managed && <Badge size="xs" color="cyan" variant="light">matricole</Badge>}
                        {r.is_kit && <Badge size="xs" color="teal" variant="light">kit</Badge>}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
                {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg">Nessun articolo trovato</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {data && data.total > data.page_size && (
        <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / data.page_size)} value={page} onChange={setPage} /></Group>
      )}
    </>
  )
}
