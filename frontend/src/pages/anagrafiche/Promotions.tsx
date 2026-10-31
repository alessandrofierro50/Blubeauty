import { ActionIcon, Anchor, Badge, Button, Group, MultiSelect, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Text, Textarea, TextInput, Title } from '@mantine/core'
import { IconArrowLeft, IconPlus, IconTrash, IconX } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { fmtDate, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { A, categoryOptions, dec, num, opts, useItemSearch, useLookups } from './shared'
import { promoLabel } from '../pos/promos'

const STATE_COLOR: Record<string, string> = { attiva: 'green', futura: 'blue', scaduta: 'gray', sospesa: 'orange' }

function describe(p: any, L: any) {
  const what = p.item_scope === 'tutti' ? 'Tutti gli articoli'
    : p.item_scope === 'categorie' ? p.category_ids.map((id: string) => L?.categories.find((c: any) => c.id === id)?.name).filter(Boolean).join(', ')
      : `${p.item_ids.length} articoli`
  const who = p.customer_scope === 'tutti' ? 'tutti i clienti'
    : p.customer_scope === 'categorie' ? p.customer_category_ids.map((id: string) => L?.customerCategories.find((c: any) => c.id === id)?.name).filter(Boolean).join(', ')
      : `${p.party_ids.length} clienti`
  const how = p.mechanic && p.mechanic !== 'prezzo' ? `${promoLabel(p)} · in cassa`
    : p.price_type === 'sconto' ? `−${Number(p.value)}%` : p.price_type === 'importo' ? `−${Number(p.value).toFixed(2)} €` : `prezzo ${Number(p.value).toFixed(2)} €`
  return { what, who, how }
}

export function PromotionsList() {
  const nav = useNavigate()
  const L = useLookups()
  const [state, setState] = useState('attiva')
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { A('/promozioni?stato=' + state).then(setRows).catch(notifyError) }, [state])
  return (
    <>
      <PageTitle title="Promozioni" subtitle="Prezzi speciali per periodo, articoli e clienti"
        right={<Button leftSection={<IconPlus size={16} />} onClick={() => nav('/promozioni/nuova')}>Nuova promozione</Button>} />
      <SegmentedControl mb="md" value={state} onChange={setState}
        data={[{ value: 'attiva', label: 'In corso' }, { value: 'futura', label: 'Programmate' }, { value: 'scaduta', label: 'Concluse' }, { value: 'tutte', label: 'Tutte' }]} />
      {!rows ? <Loading /> : rows.length === 0 ? (
        <Paper withBorder p="xl"><Text ta="center" c="dimmed">Nessuna promozione {state === 'attiva' ? 'in corso' : state === 'futura' ? 'programmata' : state === 'scaduta' ? 'conclusa' : ''}.</Text></Paper>
      ) : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={700}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead><Table.Tr><Table.Th>Promozione</Table.Th><Table.Th>Periodo</Table.Th><Table.Th>Articoli</Table.Th><Table.Th>Clienti</Table.Th><Table.Th>Prezzo</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((p) => {
                  const d = describe(p, L)
                  return (
                    <Table.Tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/promozioni/${p.id}`)}>
                      <Table.Td fw={600}>{p.name}</Table.Td>
                      <Table.Td fz="sm">{fmtDate(p.date_from)} → {fmtDate(p.date_to)}</Table.Td>
                      <Table.Td fz="sm">{d.what}</Table.Td>
                      <Table.Td fz="sm">{d.who}</Table.Td>
                      <Table.Td><Badge variant="light" size="lg">{d.how}</Badge></Table.Td>
                      <Table.Td><Badge color={STATE_COLOR[p.state]} variant="dot">{p.state}</Badge></Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </>
  )
}

const today = () => isoDate(new Date())

export function PromotionEditor() {
  const { id } = useParams()
  const isNew = id === 'nuova'
  const nav = useNavigate()
  const L = useLookups()
  const search = useItemSearch()
  const [customers, setCustomers] = useState<any[]>([])
  const [p, setP] = useState<any>(isNew ? {
    name: '', date_from: today(), date_to: today(), active: true, item_scope: 'categorie', category_ids: [], item_ids: [], items: [],
    customer_scope: 'tutti', customer_category_ids: [], party_ids: [], price_type: 'sconto', value: 10, vat_included: true, min_qty: 0, notes: '',
    mechanic: 'prezzo', buy_qty: null, pay_qty: null, threshold: null,
  } : null)

  useEffect(() => {
    A('/soggetti?tipo=clienti&page_size=200').then((r) => setCustomers(r.rows)).catch(() => {})
    if (!isNew) A(`/promozioni/${id}`).then((r) => setP({ ...r, items: r.items ?? [] })).catch(notifyError)
  }, [id])
  if (!p || !L) return <Loading />
  const set = (k: string, v: any) => setP({ ...p, [k]: v })

  async function save() {
    try {
      const body = { ...p, value: dec(p.value) ?? '0', min_qty: dec(p.min_qty) ?? '0', notes: p.notes || null, item_ids: p.items.map((i: any) => i.id),
        buy_qty: p.buy_qty ? Number(p.buy_qty) : null, pay_qty: p.pay_qty ? Number(p.pay_qty) : null, threshold: dec(p.threshold) ?? null }
      if (p.mechanic !== 'prezzo') body.customer_scope = 'tutti'
      for (const k of ['id', 'state', 'items', 'parties']) delete body[k]
      const r = isNew ? await A('/promozioni', { body }) : await A(`/promozioni/${id}`, { method: 'PUT', body })
      notifyOk('Promozione salvata')
      if (isNew) nav(`/promozioni/${r.id}`, { replace: true })
      else setP({ ...r, items: r.items ?? [] })
    } catch (e) { notifyError(e) }
  }

  async function remove() {
    if (!confirm('Eliminare la promozione?')) return
    try { await A(`/promozioni/${id}`, { method: 'DELETE' }); nav('/promozioni') } catch (e) { notifyError(e) }
  }

  return (
    <>
      <Anchor size="sm" onClick={() => nav('/promozioni')}><Group gap={4}><IconArrowLeft size={14} />Promozioni</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md">
        <Group gap="xs"><Title order={2}>{isNew ? 'Nuova promozione' : p.name}</Title>{p.state && <Badge color={STATE_COLOR[p.state]} variant="dot">{p.state}</Badge>}</Group>
        <Group>
          {!isNew && <ActionIcon variant="subtle" color="red" size="lg" onClick={remove}><IconTrash size={18} /></ActionIcon>}
          <Button onClick={save}>Salva</Button>
        </Group>
      </Group>

      <Stack maw={900}>
        <Paper withBorder p="md">
          <Text fw={700} mb="sm">1 · Nome e periodo</Text>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <TextInput label="Nome" placeholder="es. Saldi invernali" value={p.name} onChange={(e) => set('name', e.currentTarget.value)} />
            <TextInput type="date" label="Dal" value={p.date_from} onChange={(e) => set('date_from', e.currentTarget.value)} />
            <TextInput type="date" label="Al" value={p.date_to} onChange={(e) => set('date_to', e.currentTarget.value)} />
          </SimpleGrid>
          <Switch mt="md" label="Promozione attiva" checked={p.active} onChange={(e) => set('active', e.currentTarget.checked)} />
        </Paper>

        <Paper withBorder p="md">
          <Text fw={700} mb="sm">2 · Quali articoli</Text>
          <SegmentedControl value={p.item_scope} onChange={(v) => set('item_scope', v)} mb="sm"
            data={[{ value: 'tutti', label: 'Tutti' }, { value: 'categorie', label: 'Categorie' }, { value: 'articoli', label: 'Articoli scelti' }]} />
          {p.item_scope === 'categorie' && (
            <MultiSelect placeholder="Scegli le categorie" data={categoryOptions(L.categories)} value={p.category_ids} onChange={(v) => set('category_ids', v)} searchable
              description="Una categoria include anche le sue sottocategorie" />
          )}
          {p.item_scope === 'articoli' && (
            <>
              <Select placeholder="Cerca e aggiungi articoli" searchable searchValue={search.q} onSearchChange={search.setQ} data={search.options} value={null}
                nothingFoundMessage={search.q.length >= 2 ? 'Nessun articolo' : 'Scrivi almeno 2 caratteri'}
                onChange={(v) => { const f = search.found.find((x) => x.id === v); if (f && !p.items.some((i: any) => i.id === v)) set('items', [...p.items, f]); search.setQ('') }} />
              <Group gap={6} mt="sm">
                {p.items.map((i: any) => (
                  <Badge key={i.id} size="lg" variant="light" rightSection={<IconX size={12} style={{ cursor: 'pointer' }} onClick={() => set('items', p.items.filter((x: any) => x.id !== i.id))} />}>
                    {i.code} {i.description}
                  </Badge>
                ))}
              </Group>
            </>
          )}
        </Paper>

        <Paper withBorder p="md">
          <Text fw={700} mb="sm">3 · Per quali clienti</Text>
          {p.mechanic !== 'prezzo' ? <Text size="sm" c="dimmed">Le promozioni di cassa valgono per tutti i clienti al banco.</Text> : <>
          <SegmentedControl value={p.customer_scope} onChange={(v) => set('customer_scope', v)} mb="sm"
            data={[{ value: 'tutti', label: 'Tutti' }, { value: 'categorie', label: 'Categorie di clienti' }, { value: 'clienti', label: 'Clienti scelti' }]} />
          {p.customer_scope === 'categorie' && (
            L.customerCategories.length
              ? <MultiSelect placeholder="Scegli le categorie di clienti" data={opts(L.customerCategories)} value={p.customer_category_ids} onChange={(v) => set('customer_category_ids', v)} />
              : <Text size="sm" c="dimmed">Non hai ancora categorie clienti: creale in Tabelle → Categorie clienti.</Text>
          )}
          {p.customer_scope === 'clienti' && (
            <MultiSelect placeholder="Scegli i clienti" data={opts(customers, (c) => c.name)} value={p.party_ids} onChange={(v) => set('party_ids', v)} searchable />
          )}
          </>}
        </Paper>

        <Paper withBorder p="md">
          <Text fw={700} mb="sm">4 · Tipo di promozione</Text>
          <SegmentedControl mb="md" fullWidth value={p.mechanic} onChange={(v) => setP({ ...p, mechanic: v, price_type: v === 'nesimo' ? 'sconto' : v === 'soglia' && p.price_type === 'prezzo' ? 'sconto' : p.price_type,
            buy_qty: v === 'nxm' ? (p.buy_qty ?? 3) : v === 'nesimo' ? (p.buy_qty ?? 2) : null, pay_qty: v === 'nxm' ? (p.pay_qty ?? 2) : null,
            value: v === 'nesimo' ? (p.mechanic === 'nesimo' ? p.value : 50) : v === 'nxm' ? 0 : p.value, threshold: v === 'soglia' ? (p.threshold ?? 50) : null })}
            data={[{ value: 'prezzo', label: 'Prezzo o sconto' }, { value: 'nxm', label: 'Prendi N paghi M' }, { value: 'nesimo', label: 'N-esimo pezzo scontato' }, { value: 'soglia', label: 'Sconto a soglia di spesa' }]} />
          {p.mechanic === 'prezzo' && (
            <>
              <Group align="flex-end" wrap="wrap">
                <SegmentedControl value={p.price_type} onChange={(v) => set('price_type', v)}
                  data={[{ value: 'sconto', label: 'Sconto %' }, { value: 'importo', label: 'Sconto in €' }, { value: 'prezzo', label: 'Prezzo fisso' }]} />
                <NumberInput label={p.price_type === 'sconto' ? 'Percentuale' : 'Importo €'} value={num(p.value)} onChange={(v) => set('value', v)} decimalScale={2} min={0} w={140} suffix={p.price_type === 'sconto' ? ' %' : undefined} />
                {p.price_type !== 'sconto' && <Switch label="IVA inclusa" checked={p.vat_included} onChange={(e) => set('vat_included', e.currentTarget.checked)} mb={8} />}
                <NumberInput label="Quantità minima" value={num(p.min_qty)} onChange={(v) => set('min_qty', v)} min={0} w={140} />
              </Group>
              <Text size="xs" c="dimmed" mt="sm">Lo sconto si calcola sul listino del cliente. Se il cliente ha un prezzo netto concordato, vale quello. Tra listino e promozione si applica il prezzo più basso. Vale in cassa e nei documenti di vendita.</Text>
            </>
          )}
          {p.mechanic === 'nxm' && (
            <Group align="flex-end">
              <NumberInput label="Prendi (pezzi)" value={p.buy_qty ?? ''} onChange={(v) => set('buy_qty', v)} min={2} max={99} w={140} />
              <NumberInput label="Paghi (pezzi)" value={p.pay_qty ?? ''} onChange={(v) => set('pay_qty', v)} min={1} max={98} w={140} />
              <Badge size="xl" variant="light" color="orange" mb={4}>{p.buy_qty && p.pay_qty ? `${p.buy_qty}x${p.pay_qty}` : '—'}</Badge>
            </Group>
          )}
          {p.mechanic === 'nesimo' && (
            <Group align="flex-end">
              <NumberInput label="Ogni quanti pezzi" description="2 = il secondo pezzo" value={p.buy_qty ?? ''} onChange={(v) => set('buy_qty', v)} min={2} max={99} w={160} />
              <NumberInput label="Sconto sul pezzo" value={num(p.value)} onChange={(v) => set('value', v)} min={1} max={100} suffix=" %" w={160} />
            </Group>
          )}
          {p.mechanic === 'soglia' && (
            <Group align="flex-end">
              <NumberInput label="Spesa minima (IVA inclusa)" value={num(p.threshold)} onChange={(v) => set('threshold', v)} min={0} decimalScale={2} suffix=" €" w={200} />
              <SegmentedControl value={p.price_type === 'importo' ? 'importo' : 'sconto'} onChange={(v) => set('price_type', v)} data={[{ value: 'sconto', label: 'Sconto %' }, { value: 'importo', label: 'Sconto in €' }]} />
              <NumberInput label={p.price_type === 'importo' ? 'Importo €' : 'Percentuale'} value={num(p.value)} onChange={(v) => set('value', v)} min={0} decimalScale={2} w={140} suffix={p.price_type === 'importo' ? ' €' : ' %'} />
            </Group>
          )}
          {p.mechanic !== 'prezzo' && (
            <Text size="xs" c="dimmed" mt="sm">
              Promozione di cassa: si applica da sola nella vendita al banco. {p.mechanic === 'soglia'
                ? 'La spesa si conta sugli articoli scelti al punto 2, già scontati dalle altre promozioni; se più soglie sono raggiunte vale la più conveniente.'
                : 'Gli articoli del punto 2 si possono mescolare: in ogni gruppo è scontato il meno caro. Non vale sulle righe già scontate a mano né sugli articoli a peso.'}
            </Text>
          )}
          <Textarea label="Note" mt="md" autosize value={p.notes ?? ''} onChange={(e) => set('notes', e.currentTarget.value)} />
        </Paper>
      </Stack>
    </>
  )
}
