import { Alert, Anchor, Badge, Button, Checkbox, Group, Paper, SegmentedControl, Table, Text } from '@mantine/core'
import { IconCloudDownload, IconFileImport } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { FE, useModule } from './shared'

export default function Inbox() {
  const nav = useNavigate()
  const enabled = useModule('fatturapa')
  const [stato, setStato] = useState('da_registrare')
  const [data, setData] = useState<any>(null)
  const [sel, setSel] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const load = () => FE(`/ricevute?stato=${stato}`).then(setData).catch(notifyError)
  useEffect(() => { if (enabled) { load(); setSel([]) } }, [stato, enabled])

  if (!enabled) {
    return (
      <>
        <PageTitle title="Fatture ricevute da SDI" />
        <Alert title="Modulo extra non attivo">Con il modulo fatturazione elettronica le fatture dei fornitori arrivano qui da sole. Senza il modulo puoi importarle a mano: <Anchor onClick={() => nav('/acquisti/import-xml')}>importa fatture XML</Anchor>.</Alert>
      </>
    )
  }

  async function sync() {
    setBusy(true)
    try { const r = await FE('/ricevute/sincronizza', { body: {} }); notifyOk(r.received ? `${r.received} nuove fatture` : 'Nessuna nuova fattura'); load() } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function setStatus(id: string, status: string) {
    try { await FE(`/ricevute/${id}/stato`, { body: { status } }); load() } catch (e) { notifyError(e) }
  }
  return (
    <>
      <PageTitle title="Fatture ricevute da SDI" subtitle="Le fatture dei fornitori arrivano qui da sole: registrale negli acquisti con un clic"
        right={<Group>
          <Button variant="default" leftSection={<IconCloudDownload size={16} />} loading={busy} onClick={sync}>Controlla ora</Button>
          <Button leftSection={<IconFileImport size={16} />} disabled={!sel.length} onClick={() => nav(`/acquisti/import-xml?sdi=${sel.join(',')}`)}>Registra {sel.length || ''}</Button>
        </Group>} />
      <SegmentedControl mb="md" value={stato} onChange={setStato} data={[{ value: 'da_registrare', label: 'Da registrare' }, { value: 'registrata', label: 'Registrate' }, { value: 'ignorata', label: 'Ignorate' }, { value: 'tutte', label: 'Tutte' }]} />
      {!data ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead><Table.Tr><Table.Th w={36} /><Table.Th>Fornitore</Table.Th><Table.Th>Documento</Table.Th><Table.Th>Data</Table.Th><Table.Th ta="right">Totale</Table.Th><Table.Th>Ricevuta il</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.rows.map((r: any) => (
                  <Table.Tr key={r.id}>
                    <Table.Td>{r.status === 'da_registrare' && <Checkbox checked={sel.includes(r.id)} onChange={(e) => setSel(e.currentTarget.checked ? [...sel, r.id] : sel.filter((x) => x !== r.id))} />}</Table.Td>
                    <Table.Td><Text size="sm" fw={600}>{r.supplier_name}</Text><Text size="xs" c="dimmed">{r.supplier_vat}</Text></Table.Td>
                    <Table.Td fz="sm">{r.doc_type === 'TD04' ? <Badge size="xs" color="red" variant="light" mr={4}>nota di credito</Badge> : null}n. {r.number}</Table.Td>
                    <Table.Td fz="sm">{fmtDate(r.invoice_date)}</Table.Td>
                    <Table.Td ta="right" fw={600}>{r.total != null ? fmtEuro(r.total) : '—'}</Table.Td>
                    <Table.Td fz="xs" c="dimmed">{new Date(r.received_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
                    <Table.Td>
                      <Group gap={4} justify="flex-end">
                        {r.status === 'da_registrare' && <Button size="compact-xs" variant="light" onClick={() => nav(`/acquisti/import-xml?sdi=${r.id}`)}>Registra</Button>}
                        {r.status === 'da_registrare' && <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setStatus(r.id, 'ignorata')}>Ignora</Button>}
                        {r.status === 'ignorata' && <Button size="compact-xs" variant="subtle" onClick={() => setStatus(r.id, 'da_registrare')}>Ripristina</Button>}
                        {r.document_id && <Button size="compact-xs" variant="subtle" onClick={() => nav(`/acquisti/${r.document_id}`)}>Apri</Button>}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
                {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg">{stato === 'da_registrare' ? 'Nessuna fattura da registrare.' : 'Nessuna fattura.'} Codice destinatario da comunicare ai fornitori: <b>{data.settings.recipient_code}</b></Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </>
  )
}
