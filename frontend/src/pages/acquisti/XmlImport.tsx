import { Alert, Anchor, Badge, Button, Card, Checkbox, Group, Paper, SegmentedControl, Select, Stack, Switch, Table, TagsInput, Text, TextInput, Title } from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { IconArrowLeft, IconCheck, IconFileInvoice } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { fmtDate, fmtEuro, tokens } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { useItemSearch } from '../anagrafiche/shared'
import { useWarehouses } from '../magazzino/shared'
import { P, useSuppliers } from './Purchases'

function ItemPicker({ value, label, onPick }: { value: string | null; label?: string | null; onPick: (it: any) => void }) {
  const s = useItemSearch()
  const data = [...(value && label ? [{ value, label }] : []), ...s.options.filter((o) => o.value !== value)]
  return (
    <Select size="xs" placeholder="Cerca articolo" searchable searchValue={s.q} onSearchChange={s.setQ} data={data} value={value}
      nothingFoundMessage={s.q.length >= 2 ? 'Nessun articolo' : 'Scrivi almeno 2 caratteri'}
      onChange={(v) => { const f = s.found.find((x) => x.id === v); if (f) onPick(f) }} />
  )
}

function InvoiceCard({ inv, onDone }: { inv: any; onDone: (doc: any) => void }) {
  const whs = useWarehouses()
  const suppliers = useSuppliers()
  const [lines, setLines] = useState<any[]>(inv.lines)
  const [supplierId, setSupplierId] = useState<string | null>(inv.supplier_id)
  const [moves, setMoves] = useState<boolean>(inv.suggest_moves_stock)
  const [linkDdt, setLinkDdt] = useState<string[]>(inv.ddt_loaded.map((x: any) => x.id))
  const [updatePrices, setUpdatePrices] = useState(false)
  const [wh, setWh] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const upd = (i: number, patch: any) => setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const unmatched = lines.filter((l) => l.action === 'abbina' && !l.item_id).length

  async function register() {
    setBusy(true)
    try {
      const r = await P('/import-xml/conferma', { body: {
        file_ref: inv.file_ref, index: inv.index, supplier_id: supplierId, warehouse_id: wh ?? whs?.[0]?.id, moves_stock: moves,
        update_prices: updatePrices, link_ddt_ids: linkDdt, confirm: true,
        lines: lines.map((l) => ({ number: l.number, action: l.action, item_id: l.item_id, variant_id: l.variant_id,
          lot_number: l.lot_number || null, expiry_date: l.expiry_date || null, serials: l.serials ?? [] })),
      } })
      r.warnings?.forEach((w: string) => notifyError(new Error(w)))
      notifyOk(`Fattura ${inv.number} registrata`)
      onDone(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  return (
    <Card withBorder radius="md" padding="md">
      <Group justify="space-between" mb="sm" wrap="wrap">
        <div>
          <Group gap="xs"><IconFileInvoice size={20} /><Text fw={700}>{inv.doc_type === 'NCF' ? 'Nota di credito' : 'Fattura'} n. {inv.number} del {fmtDate(inv.date)}</Text>{inv.duplicate && <Badge color="red">già registrata</Badge>}</Group>
          <Text size="sm" c="dimmed">{inv.supplier.name} · P.IVA {inv.supplier.vat_number} · {inv.file_name}</Text>
        </div>
        <Text fw={800} fz="xl">{fmtEuro(inv.total)}</Text>
      </Group>
      {inv.warnings.map((w: string) => <Alert key={w} color="yellow" mb="xs" py={6}>{w}</Alert>)}
      <Group mb="sm" wrap="wrap" align="flex-end">
        <Select label="Fornitore" w={280} data={[{ value: '', label: `+ Crea "${inv.supplier.name}"` }, ...suppliers.map((s) => ({ value: s.id, label: s.name }))]}
          value={supplierId ?? ''} onChange={(v) => setSupplierId(v || null)} searchable allowDeselect={false} />
        {whs && whs.length > 1 && <Select label="Magazzino" w={200} data={whs.map((w) => ({ value: w.id, label: w.name }))} value={wh ?? whs[0].id} onChange={setWh} />}
        {inv.ddt_loaded.length > 0 && (
          <Checkbox.Group label="Merce già caricata con i DDT" value={linkDdt} onChange={setLinkDdt}>
            <Group gap="xs">{inv.ddt_loaded.map((x: any) => <Checkbox key={x.id} value={x.id} label={`DDT ${x.number} del ${fmtDate(x.date)}`} />)}</Group>
          </Checkbox.Group>
        )}
        {!linkDdt.length && <Switch mb={6} label="Carica il magazzino" checked={moves} onChange={(e) => setMoves(e.currentTarget.checked)} />}
        <Switch mb={6} label="Aggiorna i prezzi di vendita col ricarico del listino" checked={updatePrices} onChange={(e) => setUpdatePrices(e.currentTarget.checked)} />
      </Group>
      <Table.ScrollContainer minWidth={900}>
        <Table verticalSpacing={6}>
          <Table.Thead><Table.Tr><Table.Th>Riga del fornitore</Table.Th><Table.Th ta="right" w={80}>Q.tà</Table.Th><Table.Th ta="right" w={90}>Importo</Table.Th><Table.Th w={210}>Azione</Table.Th><Table.Th w={260}>Articolo BluBeauty</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {lines.map((l, i) => (
              <Table.Tr key={l.number}>
                <Table.Td><Text size="sm">{l.description}</Text><Text size="xs" c="dimmed">{l.codes.join(' · ')}{l.ddt_numbers?.length ? ` · DDT ${l.ddt_numbers.join(', ')}` : ''}</Text></Table.Td>
                <Table.Td ta="right" fz="sm">{Number(l.quantity)} {l.unit ?? ''}</Table.Td>
                <Table.Td ta="right" fz="sm">{fmtEuro(l.total)}</Table.Td>
                <Table.Td>
                  <SegmentedControl size="xs" fullWidth value={l.action} onChange={(v) => upd(i, { action: v })}
                    data={[{ value: 'abbina', label: 'Abbina' }, { value: 'nuovo', label: 'Nuovo' }, { value: 'ignora', label: 'Solo testo' }]} />
                </Table.Td>
                <Table.Td>
                  {l.action === 'abbina' && (
                    <Stack gap={4}>
                      <ItemPicker value={l.item_id} label={l.item_id ? `${l.item_code} — ${l.item_description}` : null}
                        onPick={(it) => upd(i, { item_id: it.id, item_code: it.code, item_description: it.description, lot_managed: it.lot_managed, serial_managed: it.serial_managed, match: 'manuale' })} />
                      {l.match && <Text size="xs" c="green"><IconCheck size={11} /> {l.match}</Text>}
                      {l.lot_managed && moves && <Group gap={4} wrap="nowrap"><TextInput size="xs" placeholder="lotto" value={l.lot_number ?? ''} onChange={(e) => upd(i, { lot_number: e.currentTarget.value })} /><TextInput size="xs" type="date" value={l.expiry_date ?? ''} onChange={(e) => upd(i, { expiry_date: e.currentTarget.value })} /></Group>}
                      {l.serial_managed && moves && <TagsInput size="xs" placeholder="matricole" value={l.serials ?? []} onChange={(v) => upd(i, { serials: v })} />}
                    </Stack>
                  )}
                  {l.action === 'nuovo' && <Text size="xs" c="dimmed">Verrà creato un nuovo articolo con questa descrizione</Text>}
                  {l.action === 'ignora' && <Text size="xs" c="dimmed">Riga senza articolo (spese, note)</Text>}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group justify="space-between" mt="sm">
        <Text size="xs" c="dimmed">Gli abbinamenti vengono ricordati: le prossime fatture di questo fornitore si abbineranno da sole.</Text>
        <Button onClick={register} loading={busy} disabled={unmatched > 0}>{unmatched ? `Abbina ${unmatched} righe` : 'Registra fattura'}</Button>
      </Group>
    </Card>
  )
}

export default function XmlImport() {
  const nav = useNavigate()
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState<any>(null)
  const [done, setDone] = useState<any[]>([])
  const [params] = useSearchParams()
  const sdiIds = params.get('sdi')
  useEffect(() => {
    if (!sdiIds) return
    setBusy(true)
    P('/import-xml/anteprima-sdi', { body: { inbox_ids: sdiIds.split(',') } }).then(setData).catch(notifyError).finally(() => setBusy(false))
  }, [sdiIds])

  async function upload(files: File[]) {
    setBusy(true)
    try {
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f))
      const res = await fetch('/api/acquisti/import-xml/anteprima', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${tokens.get('user')}` } })
      const r = await res.json()
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : 'File non leggibili')
      setData(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  const pending = data?.invoices.filter((i: any) => !done.some((d) => d.key === `${i.file_ref}-${i.index}`)) ?? []
  return (
    <>
      <Anchor size="sm" onClick={() => nav('/acquisti')}><Group gap={4}><IconArrowLeft size={14} />Acquisti</Group></Anchor>
      <PageTitle title="Importa fatture elettroniche" subtitle="File XML, firmati .p7m o archivi .zip scaricati dal cassetto fiscale o dal tuo intermediario" />
      <Dropzone onDrop={upload} loading={busy} accept={['application/xml', 'text/xml', 'application/zip', 'application/pkcs7-mime', 'application/octet-stream', 'application/x-zip-compressed']} mb="lg">
        <Stack align="center" py="lg" gap={4}>
          <IconFileInvoice size={40} color="var(--mantine-color-blu-6)" />
          <Text fw={600}>Trascina qui le fatture o clicca per sceglierle</Text>
          <Text size="sm" c="dimmed">.xml · .p7m · .zip (anche con molte fatture)</Text>
        </Stack>
      </Dropzone>
      {busy && <Loading />}
      {data?.errors?.length > 0 && <Alert color="red" mb="md" title="File non letti">{data.errors.map((e: string) => <div key={e}>{e}</div>)}</Alert>}
      <Stack>
        {pending.map((inv: any) => <InvoiceCard key={`${inv.file_ref}-${inv.index}`} inv={inv} onDone={(doc) => setDone([...done, { key: `${inv.file_ref}-${inv.index}`, doc }])} />)}
      </Stack>
      {done.length > 0 && (
        <Paper withBorder p="md" mt="lg">
          <Title order={5} mb="xs">Registrate</Title>
          {done.map((d) => <Anchor key={d.key} display="block" size="sm" onClick={() => nav(`/acquisti/${d.doc.id}`)}>{d.doc.party_name} · n. {d.doc.external_number} · {fmtEuro(d.doc.total)}</Anchor>)}
        </Paper>
      )}
    </>
  )
}
