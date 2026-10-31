// Esporta in un file ZIP gli XML delle fatture elettroniche emesse in un periodo (per il commercialista o l'archivio).

import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core'
import { IconFileZip } from '@tabler/icons-react'
import { useState } from 'react'

import { isoDate, tokens } from '../../api'
import { notifyError, notifyOk } from '../../components'

const monthRange = (offset: number) => {
  const n = new Date()
  const from = new Date(n.getFullYear(), n.getMonth() + offset, 1)
  const to = offset === 0 ? n : new Date(n.getFullYear(), n.getMonth() + offset + 1, 0)
  return [isoDate(from), isoDate(to)]
}

export async function downloadXml(url: string, fallbackName: string) {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${tokens.get('user')}` } })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'XML non disponibile')
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? fallbackName
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await res.blob())
  a.download = name
  a.click()
  return res
}

export default function ExportXmlButton({ size = 'sm' }: { size?: string }) {
  const [open, setOpen] = useState(false)
  const [[from, to], setRange] = useState(monthRange(-1))
  const [busy, setBusy] = useState(false)
  async function run() {
    setBusy(true)
    try {
      const r = await downloadXml(`/api/fatturapa/esporta?dal=${from}&al=${to}`, `fatture-xml-${from}_${to}.zip`)
      const errors = Number(r.headers.get('X-Errori') || 0)
      notifyOk(`Esportate ${r.headers.get('X-Esportate') ?? ''} fatture${errors ? ` · ${errors} con errori: vedi ERRORI.txt nello ZIP` : ''}`)
      setOpen(false)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <>
      <Button size={size} variant="default" leftSection={<IconFileZip size={16} />} onClick={() => setOpen(true)}>Esporta XML</Button>
      <Modal opened={open} onClose={() => setOpen(false)} title="Esporta XML delle fatture elettroniche">
        <Stack>
          <Text size="sm" c="dimmed">Scarica uno ZIP con l'XML FatturaPA di ogni fattura e nota di credito emessa nel periodo: quello trasmesso a SDI se la fattura è già stata inviata, altrimenti quello generato adesso.</Text>
          <Group gap="xs">
            <Button size="compact-xs" variant="light" onClick={() => setRange(monthRange(-1))}>Mese scorso</Button>
            <Button size="compact-xs" variant="light" onClick={() => setRange(monthRange(0))}>Questo mese</Button>
            <Button size="compact-xs" variant="light" onClick={() => setRange([`${new Date().getFullYear()}-01-01`, isoDate(new Date())])}>Dall'inizio dell'anno</Button>
          </Group>
          <Group grow>
            <TextInput type="date" label="Dal" value={from} onChange={(e) => setRange([e.currentTarget.value, to])} />
            <TextInput type="date" label="Al" value={to} onChange={(e) => setRange([from, e.currentTarget.value])} />
          </Group>
          <Group justify="flex-end"><Button leftSection={<IconFileZip size={16} />} loading={busy} disabled={!from || !to} onClick={run}>Scarica ZIP</Button></Group>
        </Stack>
      </Modal>
    </>
  )
}
