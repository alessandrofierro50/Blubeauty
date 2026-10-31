import { ActionIcon, Anchor, Badge, Button, FileButton, Group, Paper, Select, Switch, Table, Text, TextInput } from '@mantine/core'
import { IconFileUpload, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { tokens } from '../../api'
import { notifyError } from '../../components'
import { A } from './shared'

const KINDS = [
  { value: 'scheda_tecnica', label: 'Scheda tecnica' }, { value: 'certificato', label: 'Certificato' },
  { value: 'manuale', label: 'Manuale' }, { value: 'sicurezza', label: 'Scheda di sicurezza' }, { value: 'altro', label: 'Altro' },
]

export default function AttachmentsEditor({ itemId }: { itemId?: string }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [kind, setKind] = useState('scheda_tecnica')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (itemId) A(`/articoli/${itemId}/allegati`).then(setRows).catch(notifyError) }, [itemId])
  if (!itemId) return <Text c="dimmed" size="sm">Salva l'articolo per aggiungere schede tecniche e allegati.</Text>

  async function upload(files: File[]) {
    setBusy(true)
    try {
      for (const f of files) {
        const fd = new FormData()
        fd.append('file', f)
        const res = await fetch(`/api/anagrafiche/articoli/${itemId}/allegati?kind=${kind}`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${tokens.get('user')}` } })
        const r = await res.json()
        if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : 'Caricamento non riuscito')
      }
      setRows(await A(`/articoli/${itemId}/allegati`))
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function patch(id: string, body: any) {
    try { const r = await A(`/articoli/${itemId}/allegati/${id}`, { method: 'PATCH', body }); setRows(rows!.map((x) => (x.id === id ? r : x))) } catch (e) { notifyError(e) }
  }
  async function remove(id: string) {
    if (!confirm('Eliminare l\'allegato?')) return
    try { await A(`/articoli/${itemId}/allegati/${id}`, { method: 'DELETE' }); setRows(rows!.filter((x) => x.id !== id)) } catch (e) { notifyError(e) }
  }

  return (
    <Paper withBorder>
      <Group p="sm" justify="space-between" wrap="wrap">
        <Text size="sm" c="dimmed">Documenti da allegare ai preventivi e consultabili dalla scheda articolo.</Text>
        <Group gap="xs">
          <Select size="xs" data={KINDS} value={kind} onChange={(v) => setKind(v ?? 'scheda_tecnica')} w={170} allowDeselect={false} />
          <FileButton onChange={upload} multiple accept=".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.webp">
            {(p) => <Button size="xs" leftSection={<IconFileUpload size={14} />} loading={busy} {...p}>Carica file</Button>}
          </FileButton>
        </Group>
      </Group>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Titolo</Table.Th><Table.Th>Tipo</Table.Th><Table.Th>File</Table.Th><Table.Th>Proponi nei preventivi</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows?.map((a) => (
            <Table.Tr key={a.id}>
              <Table.Td><TextInput size="xs" defaultValue={a.title} onBlur={(e) => e.currentTarget.value !== a.title && patch(a.id, { title: e.currentTarget.value })} /></Table.Td>
              <Table.Td><Badge variant="light">{a.kind_label}</Badge></Table.Td>
              <Table.Td><Anchor href={a.url} target="_blank" size="sm">{a.original_name}</Anchor><Text span size="xs" c="dimmed"> · {(a.size / 1024).toFixed(0)} KB</Text></Table.Td>
              <Table.Td><Switch checked={a.attach_to_quotes} onChange={(e) => patch(a.id, { attach_to_quotes: e.currentTarget.checked })} /></Table.Td>
              <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => remove(a.id)}><IconTrash size={16} /></ActionIcon></Table.Td>
            </Table.Tr>
          ))}
          {rows?.length === 0 && <Table.Tr><Table.Td colSpan={5}><Text size="sm" c="dimmed" ta="center" py="md">Nessun allegato</Text></Table.Td></Table.Tr>}
        </Table.Tbody>
      </Table>
    </Paper>
  )
}
