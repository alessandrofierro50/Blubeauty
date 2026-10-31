import { Badge, Paper, Table, Text } from '@mantine/core'
import { useEffect, useState } from 'react'

import { adminApi } from '../../api'
import { Loading, PageTitle, notifyError } from '../../components'

export default function EmailLog() {
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { adminApi('/email-log').then(setRows).catch(notifyError) }, [])
  return (
    <>
      <PageTitle title="Email inviate" subtitle="Registro degli avvisi di scadenza e dei riepiloghi" />
      {!rows ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={720}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Azienda</Table.Th><Table.Th>Oggetto</Table.Th><Table.Th>Destinatari</Table.Th><Table.Th>Esito</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.id}>
                    <Table.Td>{new Date(r.sent_at).toLocaleString('it-IT')}</Table.Td>
                    <Table.Td>{r.tenant ?? '—'}</Table.Td>
                    <Table.Td>{r.subject}</Table.Td>
                    <Table.Td><Text size="xs">{r.recipients}</Text></Table.Td>
                    <Table.Td>{r.success ? <Badge color="green" variant="light">inviata</Badge> : <Badge color="red" variant="light" title={r.error}>errore</Badge>}</Table.Td>
                  </Table.Tr>
                ))}
                {rows.length === 0 && <Table.Tr><Table.Td colSpan={5}><Text c="dimmed" ta="center" py="md">Nessuna email inviata finora</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </>
  )
}
