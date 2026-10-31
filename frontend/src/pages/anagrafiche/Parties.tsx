import { Badge, Button, Group, Pagination, Paper, Switch, Table, Text, TextInput } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Loading, PageTitle, notifyError } from '../../components'
import { A, ImportExport } from './shared'

export default function Parties({ kind }: { kind: 'clienti' | 'fornitori' }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [dq] = useDebouncedValue(q, 250)
  const [inactive, setInactive] = useState(false)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)

  const load = () => {
    const p = new URLSearchParams({ tipo: kind, page: String(page), active: inactive ? 'false' : 'true' })
    if (dq) p.set('q', dq)
    A('/soggetti?' + p).then(setData).catch(notifyError)
  }
  useEffect(load, [kind, dq, inactive, page])
  useEffect(() => { setPage(1); setData(null) }, [kind])

  const title = kind === 'clienti' ? 'Clienti' : 'Fornitori'
  return (
    <>
      <PageTitle title={title} subtitle={data ? `${data.total} anagrafiche` : undefined}
        right={<Group><ImportExport kind="soggetti" partyKind={kind} onDone={load} />
          <Button leftSection={<IconPlus size={16} />} onClick={() => nav(`/soggetti/nuovo?tipo=${kind}`)}>{kind === 'clienti' ? 'Nuovo cliente' : 'Nuovo fornitore'}</Button></Group>} />
      <Group mb="md">
        <TextInput placeholder="Nome, codice, partita IVA, codice fiscale, città o email" leftSection={<IconSearch size={16} />}
          value={q} onChange={(e) => setQ(e.currentTarget.value)} style={{ flex: 1 }} autoFocus />
        <Switch label="Disattivati" checked={inactive} onChange={(e) => setInactive(e.currentTarget.checked)} />
      </Group>
      {!data ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={720}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead><Table.Tr><Table.Th>Codice</Table.Th><Table.Th>Nome</Table.Th><Table.Th>P. IVA / C.F.</Table.Th><Table.Th>Località</Table.Th><Table.Th>Contatti</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.rows.map((r: any) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/soggetti/${r.id}`)}>
                    <Table.Td ff="monospace" fz="sm">{r.code}</Table.Td>
                    <Table.Td fw={500}>{r.name}</Table.Td>
                    <Table.Td fz="sm">{r.vat_number || r.tax_code || '—'}</Table.Td>
                    <Table.Td fz="sm">{r.city ? `${r.city}${r.province ? ` (${r.province})` : ''}` : '—'}</Table.Td>
                    <Table.Td><Text size="xs">{r.phone}</Text><Text size="xs" c="dimmed">{r.email}</Text></Table.Td>
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        {r.person_type === 'pa' && <Badge size="xs" color="grape" variant="light">PA</Badge>}
                        {r.person_type === 'privato' && <Badge size="xs" color="gray" variant="light">privato</Badge>}
                        {r.is_customer && r.is_supplier && <Badge size="xs" variant="light">cliente e fornitore</Badge>}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
                {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="lg">Nessuna anagrafica</Text></Table.Td></Table.Tr>}
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
