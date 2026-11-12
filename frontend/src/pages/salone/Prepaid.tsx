// Buoni regalo e pacchetti di sedute: vendita (buono multiuso: ricevuta non fiscale, scontrino all'utilizzo; pacchetti: scontrino), elenchi con credito residuo e sedute rimaste, listino pacchetti.
import { ActionIcon, Alert, Badge, Button, Group, Modal, NumberInput, Paper, Progress, SegmentedControl, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Textarea, ThemeIcon } from '@mantine/core'
import { IconBrandWhatsapp, IconCash, IconCheck, IconCreditCard, IconDeviceDesktop, IconEdit, IconGift, IconPackage, IconPlus, IconPrinter, IconSearch, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'

import { ApiError, appApi, fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import type { AppCtx } from '../app/AppLayout'

const PP = '/api/prepagati'
const BIG = { size: 'xl', radius: 'lg', h: 64, fz: 18 } as const
const fmtDate = (s?: string | null) => (s ? new Date(s + (s.length === 10 ? 'T12:00' : '')).toLocaleDateString('it-IT') : '—')
const STATUS: Record<string, [string, string]> = { attivo: ['Attivo', 'green'], esaurito: ['Esaurito', 'gray'], scaduto: ['Scaduto', 'orange'], annullato: ['Annullato', 'red'] }
const uuid = () => (crypto as any).randomUUID?.() ?? `${Date.now()}-${Math.random()}`.replace(/\./g, '')

/** Vende passando dalla cassa: se è chiusa la apre (fondo 0) e riprova, come l'incasso degli appuntamenti. */
export async function sellWithRegister(path: string, body: any) {
  try {
    return await appApi(path, { body })
  } catch (e) {
    if (e instanceof ApiError && e.status === 409 && /cassa non è aperta|già chiusa/.test(e.message)) {
      const s = await appApi('/api/agenda/impostazioni')
      const regs = await appApi('/api/pos/casse').catch(() => [])
      const id = s.register_id ?? regs.find((r: any) => r.active)?.id
      if (id) { await appApi(`/api/pos/casse/${id}/apri`, { body: { opening_float: '0' } }); return await appApi(path, { body }) }
    }
    throw e
  }
}

export function waVoucherLink(v: any, salon = '') {
  const text = `Ciao${v.beneficiary_name ? ' ' + v.beneficiary_name : ''}! 🎁 Hai ricevuto un buono regalo${salon ? ' da ' + salon : ''}` +
    `${v.service ? ` per «${v.service}»` : ` di ${fmtEuro(v.initial_amount)}`}.${v.message ? `\n«${v.message}»` : ''}\nCodice ${v.code}` +
    `${v.expires_on ? `, valido fino al ${fmtDate(v.expires_on)}` : ''}.\nEccolo qui: ${v.public_url}`
  return `https://wa.me/?text=${encodeURIComponent(text)}`
}

export default function Prepaid() {
  const { me } = useOutletContext<AppCtx>()
  const admin = me.user.role === 'amministratore'
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'buoni'
  const [sell, setSell] = useState<'buono' | 'pacchetto' | null>(null)
  const [stamp, setStamp] = useState(0)
  return (
    <>
      <PageTitle title="Buoni regalo e pacchetti" video="buoni_abbonamenti" subtitle="Buono regalo: ricevuta non fiscale alla vendita, scontrino quando si usa. Pacchetti: scontrino alla vendita, sedute scalate a ogni incasso"
        right={<Group>
          <Button size="md" leftSection={<IconGift size={18} />} onClick={() => setSell('buono')} data-testid="nuovo-buono">Nuovo buono regalo</Button>
          <Button size="md" variant="light" leftSection={<IconPackage size={18} />} onClick={() => setSell('pacchetto')}>Vendi un pacchetto</Button>
        </Group>} />
      <Tabs value={tab} onChange={(v) => setParams({ tab: v ?? 'buoni' })} keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="buoni" leftSection={<IconGift size={16} />}>Buoni regalo</Tabs.Tab>
          <Tabs.Tab value="venduti" leftSection={<IconPackage size={16} />}>Pacchetti delle clienti</Tabs.Tab>
          <Tabs.Tab value="listino">Listino pacchetti</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="buoni"><Vouchers key={stamp} admin={admin} /></Tabs.Panel>
        <Tabs.Panel value="venduti"><SoldPackages key={stamp} admin={admin} /></Tabs.Panel>
        <Tabs.Panel value="listino"><PackageCatalog admin={admin} /></Tabs.Panel>
      </Tabs>
      {sell === 'buono' && <SellVoucher onClose={() => setSell(null)} onDone={() => setStamp(Date.now())} />}
      {sell === 'pacchetto' && <SellPackage onClose={() => setSell(null)} onDone={() => { setStamp(Date.now()); setParams({ tab: 'venduti' }) }} />}
    </>
  )
}

// ------------------------------------------------------------------------------------------------------------ buoni
function Vouchers({ admin }: { admin: boolean }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<any>(null)
  const load = () => appApi(`${PP}/buoni${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`).then(setRows).catch(notifyError)
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [q])
  if (!rows) return <Loading />
  return (
    <>
      {admin && <VoucherMode />}
      <TextInput size="md" mb="sm" leftSection={<IconSearch size={18} />} placeholder="Cerca per codice, per chi è o chi l'ha comprato" value={q}
        onChange={(e) => setQ(e.currentTarget.value)} maw={520} />
      {rows.length === 0 ? <Paper withBorder p="xl" ta="center"><Text c="dimmed">Nessun buono regalo{q ? ' trovato' : ' venduto finora'}.</Text></Paper> : (
        <Paper withBorder>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead><Table.Tr><Table.Th>Codice</Table.Th><Table.Th>Per</Table.Th><Table.Th>Comprato da</Table.Th><Table.Th ta="right">Valore</Table.Th>
              <Table.Th ta="right">Credito residuo</Table.Th><Table.Th>Scadenza</Table.Th><Table.Th>Stato</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((v) => (
                <Table.Tr key={v.id} style={{ cursor: 'pointer' }} onClick={() => appApi(`${PP}/buoni/${v.id}`).then(setOpen).catch(notifyError)}>
                  <Table.Td ff="monospace" fw={700}>{v.code}</Table.Td>
                  <Table.Td>{v.beneficiary_name ?? '—'}{v.service && <Text size="xs" c="dimmed">{v.service}</Text>}</Table.Td>
                  <Table.Td>{v.purchaser ?? '—'}</Table.Td>
                  <Table.Td ta="right">{fmtEuro(v.initial_amount)}</Table.Td>
                  <Table.Td ta="right" fw={700}>{fmtEuro(v.balance)}</Table.Td>
                  <Table.Td>{fmtDate(v.expires_on)}</Table.Td>
                  <Table.Td><Badge color={STATUS[v.status]?.[1]} variant="light">{STATUS[v.status]?.[0] ?? v.status}</Badge></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      {open && <VoucherDetail v={open} admin={admin} onClose={() => setOpen(null)} onChanged={(v) => { setOpen(v); load() }} />}
    </>
  )
}

/** Buono multiuso (predefinito) o monouso: vale per i buoni venduti da ora in poi. */
function VoucherMode() {
  const [mode, setMode] = useState<string | null>(null)
  useEffect(() => { appApi(`${PP}/impostazioni`).then((s) => setMode(s.voucher_mode)).catch(() => {}) }, [])
  if (!mode) return null
  const save = (m: string) => appApi(`${PP}/impostazioni`, { method: 'PUT', body: { voucher_mode: m } }).then((s) => { setMode(s.voucher_mode); notifyOk('Impostazione salvata') }).catch(notifyError)
  return (
    <Paper withBorder p="sm" mb="md" radius="md">
      <Group justify="space-between" wrap="wrap">
        <div><Text fw={600}>Come si emettono i buoni regalo</Text>
          <Text size="xs" c="dimmed" maw={560}>{mode === 'multiuso'
            ? 'Multiuso: alla vendita ricevuta non fiscale con il codice; lo scontrino si emette quando il buono si usa, pagato «con buono regalo» (non è un nuovo incasso).'
            : 'Monouso: scontrino alla vendita; quando il buono si usa, ricevuta non fiscale (o scontrino solo della differenza).'} Vale per i buoni venduti da ora: chiedi conferma al commercialista.</Text></div>
        <SegmentedControl value={mode} onChange={save} data={[{ value: 'multiuso', label: 'Multiuso' }, { value: 'monouso', label: 'Monouso' }]} data-testid="modo-buoni" />
      </Group>
    </Paper>
  )
}

export function VoucherActions({ v }: { v: any }) {
  const printThermal = async () => {
    try { const r = await appApi(`${PP}/buoni/${v.id}/stampa`, { body: {} }); notifyOk(`Buono inviato a «${r.device}»`) } catch (e) { notifyError(e) }
  }
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
      <Button variant="light" leftSection={<IconDeviceDesktop size={18} />} onClick={() => window.open(`/stampa/buono/${v.id}`, '_blank')}>Stampa il biglietto</Button>
      <Button variant="light" leftSection={<IconPrinter size={18} />} onClick={printThermal}>Stampante 80 mm</Button>
      <Button color="green" leftSection={<IconBrandWhatsapp size={18} />} component="a" href={waVoucherLink(v)} target="_blank">Manda su WhatsApp</Button>
    </SimpleGrid>
  )
}

function VoucherDetail({ v, admin, onClose, onChanged }: { v: any; admin: boolean; onClose: () => void; onChanged: (v: any) => void }) {
  const cancel = async () => {
    if (!window.confirm(`Annullare il buono ${v.code}? Il credito residuo (${fmtEuro(v.balance)}) non sarà più utilizzabile.`)) return
    try { onChanged(await appApi(`${PP}/buoni/${v.id}/annulla`, { body: { note: 'Annullato dal salone' } })) } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title={<Text fw={700}>Buono regalo {v.code}</Text>} size="lg">
      <Group justify="space-between" align="flex-start">
        <div>
          <Text c="dimmed" size="sm">{v.service ? `Per «${v.service}»` : 'Buono a importo'}{v.beneficiary_name ? ` · per ${v.beneficiary_name}` : ''}</Text>
          <Text fz={34} fw={800}>{fmtEuro(v.balance)}</Text>
          <Text size="sm">credito residuo su {fmtEuro(v.initial_amount)} · valido fino al {fmtDate(v.expires_on)}</Text>
        </div>
        <Badge size="lg" color={STATUS[v.status]?.[1]}>{STATUS[v.status]?.[0]}</Badge>
      </Group>
      {v.message && <Text mt="sm" fs="italic">«{v.message}»</Text>}
      <Text fw={600} mt="md" mb={4}>Movimenti</Text>
      <Table>
        <Table.Tbody>
          {(v.moves ?? []).map((m: any, i: number) => (
            <Table.Tr key={i}><Table.Td>{new Date(m.created_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
              <Table.Td>{m.kind === 'emissione' ? 'Venduto' : m.kind === 'utilizzo' ? 'Usato' : 'Annullato'}</Table.Td>
              <Table.Td ta="right" c={Number(m.amount) < 0 ? 'red' : 'green'}>{Number(m.amount) > 0 ? '+' : ''}{fmtEuro(m.amount)}</Table.Td>
              <Table.Td ta="right" c="dimmed">resta {fmtEuro(m.balance_after)}</Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Stack mt="md" gap="xs">
        <VoucherActions v={v} />
        {admin && v.status === 'attivo' && <Button variant="subtle" color="red" onClick={cancel}>Annulla il buono</Button>}
      </Stack>
    </Modal>
  )
}

function PayButtons({ busy, onPay, disabled }: { busy: string | null; onPay: (m: string) => void; disabled?: boolean }) {
  return (
    <SimpleGrid cols={3}>
      <Button {...BIG} color="green" leftSection={<IconCash size={24} />} loading={busy === 'contanti'} disabled={disabled || !!busy} onClick={() => onPay('contanti')}>Contanti</Button>
      <Button {...BIG} leftSection={<IconCreditCard size={24} />} loading={busy === 'carta'} disabled={disabled || !!busy} onClick={() => onPay('carta')}>Carta</Button>
      <Button {...BIG} variant="light" leftSection={<IconCreditCard size={24} />} loading={busy === 'bancomat'} disabled={disabled || !!busy} onClick={() => onPay('bancomat')}>Bancomat</Button>
    </SimpleGrid>
  )
}

function ClientPicker({ value, onChange, label, placeholder }: { value: any; onChange: (c: any) => void; label: string; placeholder?: string }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => {
    if (q.trim().length < 2) { setRows([]); return }
    const t = setTimeout(() => appApi(`/api/agenda/clienti?q=${encodeURIComponent(q.trim())}`).then((r) => setRows(r.slice(0, 6))).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [q])
  if (value) return (
    <div><Text size="sm" fw={500}>{label}</Text>
      <Group gap="xs"><Badge size="lg" variant="light">{value.name}</Badge><Button size="xs" variant="subtle" onClick={() => onChange(null)}>Cambia</Button></Group></div>
  )
  return (
    <div>
      <TextInput size="md" label={label} placeholder={placeholder ?? 'Scrivi nome o telefono'} value={q} onChange={(e) => setQ(e.currentTarget.value)} leftSection={<IconSearch size={16} />} />
      {rows.length > 0 && <Paper withBorder mt={4}>{rows.map((c) => (
        <Button key={c.id} fullWidth variant="subtle" justify="flex-start" onClick={() => { onChange(c); setQ('') }}>{c.name}{c.mobile ? ` · ${c.mobile}` : ''}</Button>
      ))}</Paper>}
    </div>
  )
}

function Done({ title, sub, children, onClose }: { title: string; sub: string; children?: any; onClose: () => void }) {
  return (
    <Stack align="center" ta="center" py="md">
      <ThemeIcon size={80} radius={80} color="green" variant="light"><IconCheck size={44} /></ThemeIcon>
      <Text fz={24} fw={800}>{title}</Text>
      <Text c="dimmed">{sub}</Text>
      {children}
      <Button size="lg" variant="subtle" onClick={onClose}>Chiudi</Button>
    </Stack>
  )
}

export function SellVoucher({ onClose, onDone, purchaser, registerId }: { onClose: () => void; onDone?: () => void; purchaser?: any; registerId?: string }) {
  const [kind, setKind] = useState<'importo' | 'servizio'>('importo')
  const [amount, setAmount] = useState<number | ''>(50)
  const [services, setServices] = useState<any[]>([])
  const [serviceId, setServiceId] = useState<string | null>(null)
  const [buyer, setBuyer] = useState<any>(purchaser ?? null)
  const [forClient, setForClient] = useState<any>(null)  // chi lo riceve, se è già cliente: il buono va nella sua scheda
  const [forName, setForName] = useState('')
  const [mode, setMode] = useState('multiuso')
  useEffect(() => { appApi(`${PP}/impostazioni`).then((s) => setMode(s.voucher_mode)).catch(() => {}) }, [])
  const [message, setMessage] = useState('')
  const [months, setMonths] = useState('12')
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<any>(null)
  const [cu] = useState(uuid())
  useEffect(() => { appApi('/api/agenda/servizi').then((s) => setServices(s.filter((x: any) => x.active))).catch(() => {}) }, [])
  const svc = services.find((s) => s.id === serviceId)
  const value = kind === 'servizio' ? Number(svc?.price ?? 0) : Number(amount || 0)
  const pay = async (method: string) => {
    setBusy(method)
    try {
      const r = await sellWithRegister(`${PP}/buoni`, {
        client_uuid: cu, register_id: registerId ?? null, kind, amount: kind === 'importo' ? value.toFixed(2) : null, service_id: kind === 'servizio' ? serviceId : null,
        purchaser_id: buyer?.id ?? null, beneficiary_id: forClient?.id ?? null, beneficiary_name: forClient ? null : forName || null, message: message || null, months: months === '0' ? null : Number(months),
        payments: [{ method, amount: value.toFixed(2) }],
      })
      setDone(r); onDone?.()
    } catch (e) { notifyError(e) } finally { setBusy(null) }
  }
  return (
    <Modal opened onClose={onClose} title={<Text fw={700} fz="lg">Nuovo buono regalo</Text>} size="lg" radius="lg">
      {done ? (
        <Done title={`Buono ${done.voucher.code}`} sub={`Valore ${fmtEuro(done.voucher.initial_amount)} · ${done.receipt.fiscal?.nonfiscal ? 'ricevuta non fiscale' : 'scontrino'} ${done.receipt.number}${done.voucher.beneficiary_id ? ` · nella scheda di ${done.voucher.beneficiary_name}` : ''}${Number(done.change) > 0 ? ` · resto ${fmtEuro(done.change)}` : ''}`} onClose={onClose}>
          <VoucherActions v={done.voucher} />
        </Done>
      ) : (
        <Stack>
          <SegmentedControl size="md" value={kind} onChange={(v) => setKind(v as any)} data={[{ value: 'importo', label: 'Un importo' }, { value: 'servizio', label: 'Un servizio' }]} />
          {kind === 'importo' ? (
            <Group align="flex-end">
              {[25, 50, 100, 150].map((n) => <Button key={n} size="md" variant={amount === n ? 'filled' : 'light'} onClick={() => setAmount(n)}>{n} €</Button>)}
              <NumberInput size="md" w={140} label="Altro importo" value={amount} onChange={(v) => setAmount(v === '' ? '' : Number(v))} min={1} max={5000} decimalScale={2} decimalSeparator="," suffix=" €" />
            </Group>
          ) : (
            <Select size="md" label="Servizio regalato" searchable data={services.map((s) => ({ value: s.id, label: `${s.name} · ${fmtEuro(s.price)}` }))} value={serviceId} onChange={setServiceId} />
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {forClient ? <ClientPicker label="Per chi è" value={forClient} onChange={setForClient} />
              : <TextInput size="md" label="Per chi è (facoltativo)" placeholder="es. Giulia" value={forName} onChange={(e) => setForName(e.currentTarget.value)} />}
            <Select size="md" label="Valido per" value={months} onChange={(v) => setMonths(v ?? '12')} allowDeselect={false}
              data={[{ value: '6', label: '6 mesi' }, { value: '12', label: '12 mesi' }, { value: '24', label: '24 mesi' }, { value: '0', label: 'Senza scadenza' }]} />
          </SimpleGrid>
          <Textarea label="Dedica (facoltativa)" placeholder="es. Buon compleanno!" maxLength={300} autosize minRows={2} value={message} onChange={(e) => setMessage(e.currentTarget.value)} />
          {!forClient && <ClientPicker label="È già cliente? Cercala: il buono va nella sua scheda" placeholder="Nome o telefono di chi lo riceve" value={null} onChange={(c) => { setForClient(c); if (c) setForName('') }} />}
          <ClientPicker label="Chi lo compra (facoltativo)" value={buyer} onChange={setBuyer} />
          <Paper withBorder p="sm" radius="md" bg="var(--mantine-color-blu-light)">
            <Group justify="space-between"><Text fw={600}>{mode === 'multiuso' ? 'Da pagare (ricevuta non fiscale con il codice)' : 'Da pagare (con scontrino)'}</Text><Text fz={26} fw={800}>{fmtEuro(value)}</Text></Group>
            {mode === 'multiuso' && <Text size="xs" c="dimmed">Lo scontrino fiscale si emette quando il buono viene usato.</Text>}
          </Paper>
          <PayButtons busy={busy} onPay={pay} disabled={!(value > 0)} />
        </Stack>
      )}
    </Modal>
  )
}

// --------------------------------------------------------------------------------------------------------- pacchetti
export function SellPackage({ onClose, onDone, client, registerId }: { onClose: () => void; onDone?: () => void; client?: any; registerId?: string }) {
  const [pkgs, setPkgs] = useState<any[] | null>(null)
  const [who, setWho] = useState<any>(client ?? null)
  const [pid, setPid] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<any>(null)
  const [cu] = useState(uuid())
  useEffect(() => { appApi(`${PP}/pacchetti`).then((p) => setPkgs(p.filter((x: any) => x.active))).catch(notifyError) }, [])
  const p = pkgs?.find((x) => x.id === pid)
  const pay = async (method: string) => {
    if (!p || !who) return
    setBusy(method)
    try {
      const r = await sellWithRegister(`${PP}/pacchetti/${p.id}/vendi`, { client_uuid: cu, register_id: registerId ?? null, party_id: who.id, payments: [{ method, amount: p.price }] })
      setDone(r); onDone?.()
    } catch (e) { notifyError(e) } finally { setBusy(null) }
  }
  return (
    <Modal opened onClose={onClose} title={<Text fw={700} fz="lg">Vendi un pacchetto</Text>} size="lg" radius="lg">
      {done ? <Done title={done.package.name} sub={`Venduto a ${done.package.client} · ${done.package.sessions} sedute${done.package.expires_on ? `, valide fino al ${fmtDate(done.package.expires_on)}` : ''}`} onClose={onClose} />
        : !pkgs ? <Loading /> : pkgs.length === 0 ? <Alert color="yellow">Non ci sono pacchetti a listino: creali in «Listino pacchetti».</Alert> : (
        <Stack>
          <ClientPicker label="Per quale cliente?" value={who} onChange={setWho} />
          <Text size="sm" fw={500}>Quale pacchetto?</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {pkgs.map((x) => (
              <Paper key={x.id} withBorder p="md" radius="lg" style={{ cursor: 'pointer', borderColor: pid === x.id ? 'var(--mantine-color-blu-6)' : undefined, borderWidth: pid === x.id ? 2 : 1 }}
                onClick={() => setPid(x.id)}>
                <Text fw={700}>{x.name}</Text>
                <Text size="sm" c="dimmed">{x.items.map((i: any) => `${i.sessions} × ${i.name}`).join(' · ')}</Text>
                <Group justify="space-between" mt={6}><Text fz="lg" fw={800}>{fmtEuro(x.price)}</Text>
                  {Number(x.saving) > 0 && <Badge color="green" variant="light">risparmia {fmtEuro(x.saving)}</Badge>}</Group>
              </Paper>
            ))}
          </SimpleGrid>
          <PayButtons busy={busy} onPay={pay} disabled={!p || !who} />
        </Stack>
      )}
    </Modal>
  )
}

export function PackageProgress({ cp }: { cp: any }) {
  return (
    <Stack gap={4}>
      {cp.items.map((i: any) => (
        <div key={i.service_id}>
          <Group justify="space-between"><Text size="sm">{i.name}</Text><Text size="sm" fw={600}>{i.remaining} di {i.sessions} rimaste</Text></Group>
          <Progress value={(i.used / i.sessions) * 100} size="sm" color={i.remaining ? 'blu' : 'gray'} />
        </div>
      ))}
    </Stack>
  )
}

function SoldPackages({ admin }: { admin: boolean }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [stato, setStato] = useState<string>('attivo')
  const load = () => appApi(`${PP}/venduti${stato ? `?stato=${stato}` : ''}`).then(setRows).catch(notifyError)
  useEffect(() => { load() }, [stato])
  const cancel = async (cp: any) => {
    if (!window.confirm(`Annullare il pacchetto «${cp.name}» di ${cp.client}? Le sedute rimaste non saranno più utilizzabili.`)) return
    try { await appApi(`${PP}/venduti/${cp.id}/annulla`, { body: {} }); load() } catch (e) { notifyError(e) }
  }
  if (!rows) return <Loading />
  return (
    <>
      <SegmentedControl mb="sm" value={stato} onChange={setStato} data={[{ value: 'attivo', label: 'In corso' }, { value: 'esaurito', label: 'Finiti' }, { value: 'scaduto', label: 'Scaduti' }, { value: '', label: 'Tutti' }]} />
      {rows.length === 0 ? <Paper withBorder p="xl" ta="center"><Text c="dimmed">Nessun pacchetto.</Text></Paper> : (
        <SimpleGrid cols={{ base: 1, md: 2, lg: 3 }}>
          {rows.map((cp) => (
            <Paper key={cp.id} withBorder p="md" radius="lg">
              <Group justify="space-between" align="flex-start" mb={6}>
                <div><Text fw={700}>{cp.client}</Text><Text size="sm" c="dimmed">{cp.name}</Text></div>
                <Badge color={STATUS[cp.status]?.[1]} variant="light">{STATUS[cp.status]?.[0]}</Badge>
              </Group>
              <PackageProgress cp={cp} />
              <Group justify="space-between" mt="sm">
                <Text size="xs" c="dimmed">{cp.expires_on ? `Scade il ${fmtDate(cp.expires_on)}` : 'Senza scadenza'}{cp.last_use ? ` · ultima seduta ${fmtDate(cp.last_use.slice(0, 10))}` : ''}</Text>
                {admin && cp.status === 'attivo' && <ActionIcon variant="subtle" color="red" onClick={() => cancel(cp)} aria-label="Annulla"><IconTrash size={16} /></ActionIcon>}
              </Group>
            </Paper>
          ))}
        </SimpleGrid>
      )}
    </>
  )
}

function PackageCatalog({ admin }: { admin: boolean }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [edit, setEdit] = useState<any>(null)
  const load = () => appApi(`${PP}/pacchetti`).then(setRows).catch(notifyError)
  useEffect(() => { load() }, [])
  if (!rows) return <Loading />
  return (
    <>
      {admin && <Button mb="sm" leftSection={<IconPlus size={16} />} onClick={() => setEdit({ name: '', price: '', items: [{ service_id: null, sessions: 5 }], validity_days: 180, active: true })}>Nuovo pacchetto</Button>}
      {rows.length === 0 ? <Paper withBorder p="xl" ta="center"><Text c="dimmed">Nessun pacchetto a listino. Esempi: «10 pressoterapie», «5 pieghe», «Percorso viso 6 sedute».</Text></Paper> : (
        <Paper withBorder>
          <Table verticalSpacing="sm">
            <Table.Thead><Table.Tr><Table.Th>Pacchetto</Table.Th><Table.Th>Contiene</Table.Th><Table.Th ta="right">Prezzo</Table.Th><Table.Th>Durata</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((p) => (
                <Table.Tr key={p.id} opacity={p.active ? 1 : 0.5}>
                  <Table.Td fw={700}>{p.name}</Table.Td>
                  <Table.Td>{p.items.map((i: any) => `${i.sessions} × ${i.name}`).join(' · ')}</Table.Td>
                  <Table.Td ta="right">{fmtEuro(p.price)}{Number(p.saving) > 0 && <Text size="xs" c="green">invece di {fmtEuro(p.list_value)}</Text>}</Table.Td>
                  <Table.Td>{p.validity_days ? `${p.validity_days} giorni` : 'senza scadenza'}</Table.Td>
                  <Table.Td>{admin && <ActionIcon variant="subtle" onClick={() => setEdit(p)}><IconEdit size={16} /></ActionIcon>}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      {edit && <PackageEditor p={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load() }} />}
    </>
  )
}

function PackageEditor({ p, onClose, onSaved }: { p: any; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<any>({ ...p, items: p.items.map((i: any) => ({ service_id: i.service_id, sessions: i.sessions })) })
  const [services, setServices] = useState<any[]>([])
  useEffect(() => { appApi('/api/agenda/servizi').then((s) => setServices(s.filter((x: any) => x.active))).catch(() => {}) }, [])
  const listed = f.items.reduce((s: number, i: any) => s + Number(services.find((x) => x.id === i.service_id)?.price ?? 0) * (i.sessions || 0), 0)
  const save = async () => {
    const body = { name: f.name, price: Number(f.price || 0).toFixed(2), items: f.items.filter((i: any) => i.service_id), validity_days: f.validity_days || null,
      min_days: f.min_days || null, description: f.description || null, active: f.active, sort_order: f.sort_order ?? 0 }
    try { await appApi(p.id ? `${PP}/pacchetti/${p.id}` : `${PP}/pacchetti`, { method: p.id ? 'PUT' : 'POST', body }); notifyOk('Pacchetto salvato'); onSaved() } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title={p.id ? 'Modifica pacchetto' : 'Nuovo pacchetto'} size="lg">
      <Stack>
        <TextInput label="Nome" placeholder="es. 10 pressoterapie" value={f.name} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
        <Text size="sm" fw={500}>Servizi e sedute</Text>
        {f.items.map((it: any, i: number) => (
          <Group key={i} align="flex-end" wrap="nowrap">
            <Select style={{ flex: 1 }} searchable placeholder="Servizio" data={services.map((s) => ({ value: s.id, label: `${s.name} · ${fmtEuro(s.price)}` }))}
              value={it.service_id} onChange={(v) => setF({ ...f, items: f.items.map((x: any, j: number) => (j === i ? { ...x, service_id: v } : x)) })} />
            <NumberInput w={110} label={i === 0 ? 'Sedute' : undefined} min={1} max={100} value={it.sessions}
              onChange={(v) => setF({ ...f, items: f.items.map((x: any, j: number) => (j === i ? { ...x, sessions: Number(v) || 1 } : x)) })} />
            {f.items.length > 1 && <ActionIcon variant="subtle" color="red" mb={6} onClick={() => setF({ ...f, items: f.items.filter((_: any, j: number) => j !== i) })}><IconTrash size={16} /></ActionIcon>}
          </Group>
        ))}
        <Button variant="subtle" size="xs" w="fit-content" onClick={() => setF({ ...f, items: [...f.items, { service_id: null, sessions: 1 }] })}>+ aggiungi un servizio</Button>
        <SimpleGrid cols={3}>
          <NumberInput label="Prezzo del pacchetto" description={listed ? `A listino: ${fmtEuro(listed)}` : undefined} min={1} decimalScale={2} decimalSeparator="," suffix=" €"
            value={f.price} onChange={(v) => setF({ ...f, price: v })} />
          <NumberInput label="Valido per (giorni)" description="vuoto = senza scadenza" min={1} max={1100} value={f.validity_days ?? ''} onChange={(v) => setF({ ...f, validity_days: v === '' ? null : Number(v) })} />
          <NumberInput label="Giorni tra le sedute" description="consigliati (facoltativo)" min={1} max={120} value={f.min_days ?? ''} onChange={(v) => setF({ ...f, min_days: v === '' ? null : Number(v) })} />
        </SimpleGrid>
        <SegmentedControl value={f.active ? 'si' : 'no'} onChange={(v) => setF({ ...f, active: v === 'si' })} data={[{ value: 'si', label: 'In vendita' }, { value: 'no', label: 'Non più in vendita' }]} />
        <Button onClick={save} disabled={!f.name || !Number(f.price) || !f.items.some((i: any) => i.service_id)}>Salva</Button>
      </Stack>
    </Modal>
  )
}


