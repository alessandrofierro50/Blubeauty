import { ActionIcon, Badge, Box, Button, Card, Center, Chip, Group, Loader, NumberInput, Paper, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconCamera, IconCheck, IconCloudOff, IconCloudUpload, IconMinus, IconPlus, IconSearch, IconX } from '@tabler/icons-react'
import { BrowserMultiFormatReader, type IScannerControls } from '@zxing/browser'
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import { Logo } from '../../components'
import { W } from './shared'

type Pending = {
  client_uuid: string
  item_id: string
  variant_id: string | null
  quantity: string
  lot_number: string | null
  expiry_date: string | null
  serial_number: string | null
  counted_at: string
  label: string
}

const storeKey = (id: string) => `blubeauty_inventario_${id}`
function loadQueue(id: string): Pending[] {
  try { return JSON.parse(localStorage.getItem(storeKey(id)) || '[]') } catch { return [] }
}
function saveQueue(id: string, q: Pending[]) {
  try { localStorage.setItem(storeKey(id), JSON.stringify(q)) } catch { /* memoria non disponibile: resta in RAM */ }
}

export function beep(ok = true) {
  try {
    const ctx = new AudioContext()
    const o = ctx.createOscillator()
    o.frequency.value = ok ? 1200 : 300
    o.connect(ctx.destination)
    o.start()
    o.stop(ctx.currentTime + 0.08)
  } catch { /* audio non disponibile */ }
  try { navigator.vibrate?.(ok ? 60 : [80, 60, 80]) } catch { /* nessuna vibrazione */ }
}

/** Fotocamera: legge QR e codici a barre (EAN, Code128…) e restituisce il testo letto. */
export function CameraScanner({ onCode, onClose }: { onCode: (c: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let controls: IScannerControls | undefined
    let last = ''
    const reader = new BrowserMultiFormatReader()
    reader.decodeFromConstraints({ video: { facingMode: 'environment' } }, video.current!, (res) => {
      if (res && res.getText() !== last) { last = res.getText(); onCode(last) }
    }).then((c) => { controls = c }).catch(() => setError('Fotocamera non disponibile: consenti l\'accesso alla fotocamera nelle impostazioni del browser.'))
    return () => controls?.stop()
  }, [])
  return (
    <Box pos="fixed" inset={0} bg="black" style={{ zIndex: 300 }}>
      <video ref={video} style={{ width: '100%', height: '100%', objectFit: 'cover' }} muted playsInline />
      <Box pos="absolute" top="35%" left="10%" w="80%" h="22%" style={{ border: '3px solid #6ec1e4', borderRadius: 12, boxShadow: '0 0 0 2000px rgba(0,0,0,.35)' }} />
      <Text pos="absolute" top="20%" w="100%" ta="center" c="white" fw={600}>Inquadra il codice a barre o il QR</Text>
      {error && <Paper pos="absolute" bottom={120} left={16} right={16} p="md"><Text c="red" size="sm">{error}</Text></Paper>}
      <Center pos="absolute" bottom={40} w="100%"><Button size="lg" radius="xl" color="gray" leftSection={<IconX size={18} />} onClick={onClose}>Chiudi</Button></Center>
    </Box>
  )
}

export default function MobileCount() {
  const { id } = useParams()
  const [session, setSession] = useState<any>(null)
  const [queue, setQueue] = useState<Pending[]>(() => loadQueue(id!))
  const [done, setDone] = useState<Pending[]>([])
  const [online, setOnline] = useState(navigator.onLine)
  const [camera, setCamera] = useState<false | 'item' | 'serial'>(false)
  const [q, setQ] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [item, setItem] = useState<any>(null)
  const [variant, setVariant] = useState<string | null>(null)
  const [count, setCount] = useState<number | string>(1)
  const [lot, setLot] = useState('')
  const [expiry, setExpiry] = useState('')
  const [serial, setSerial] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    W(`/inventari`).then((rows) => setSession(rows.find((r: any) => r.id === id) ?? { error: true })).catch(() => setSession({ error: true }))
    const on = () => setOnline(true), off = () => setOnline(false)
    window.addEventListener('online', on); window.addEventListener('offline', off)
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off) }
  }, [id])

  // invio dei conteggi in coda (anche dopo un periodo senza rete)
  useEffect(() => {
    saveQueue(id!, queue)
    if (!queue.length || !online) return
    const t = setTimeout(async () => {
      const batch = queue.slice(0, 50)
      try {
        await W(`/inventari/${id}/conteggi`, { body: batch.map(({ label: _l, ...c }) => c) })
        setQueue((cur) => cur.filter((c) => !batch.some((b) => b.client_uuid === c.client_uuid)))
        setDone((d) => [...batch, ...d].slice(0, 30))
      } catch (e: any) {
        if (e?.status === 409) setMsg({ ok: false, text: 'Inventario chiuso: i conteggi non sono più accettati' })
      }
    }, 800)
    return () => clearTimeout(t)
  }, [queue, online])

  function pick(it: any) {
    setItem(it)
    setVariant(it.variant_id ?? (it.variants.length === 1 ? it.variants[0].id : null))
    setCount(it.serial_managed ? 1 : 1)
    setLot(''); setExpiry(''); setSerial('')
    setResults([]); setQ('')
  }

  async function lookup(code: string) {
    const c = code.trim()
    if (!c) return
    try {
      const r = await W('/cerca?code=' + encodeURIComponent(c))
      if (r.length === 1) { pick(r[0]); beep(true) } else if (!r.length) { beep(false); setMsg({ ok: false, text: `Nessun articolo per «${c}»` }) } else setResults(r)
    } catch { beep(false); setMsg({ ok: false, text: online ? 'Errore di ricerca' : 'Senza rete non posso cercare nuovi articoli' }) }
  }

  function onCamera(code: string) {
    if (camera === 'serial') { setSerial(code.toUpperCase()); setCamera(false); beep(true); return }
    setCamera(false)
    lookup(code)
  }

  function confirm() {
    if (!item) return
    if (item.variants.length && !variant) return setMsg({ ok: false, text: 'Scegli taglia e colore' })
    if (item.lot_managed && !lot.trim()) return setMsg({ ok: false, text: 'Indica il lotto' })
    if (item.serial_managed && !serial.trim()) return setMsg({ ok: false, text: 'Leggi la matricola' })
    const v = item.variants.find((x: any) => x.id === variant)
    const p: Pending = {
      client_uuid: crypto.randomUUID(), item_id: item.id, variant_id: variant, quantity: String(item.serial_managed ? 1 : count || 0),
      lot_number: item.lot_managed ? lot.trim().toUpperCase() : null, expiry_date: item.lot_managed && expiry ? expiry : null,
      serial_number: item.serial_managed ? serial.trim().toUpperCase() : null, counted_at: new Date().toISOString(),
      label: `${item.description}${v ? ` ${[v.color, v.size].filter(Boolean).join(' ')}` : ''}${item.lot_managed ? ` · lotto ${lot.toUpperCase()}` : ''}${item.serial_managed ? ` · ${serial.toUpperCase()}` : ''}`,
    }
    setQueue((cur) => [...cur, p])
    beep(true)
    setMsg({ ok: true, text: `${p.label}: ${item.serial_managed ? '1 pezzo' : `${count} ${item.unit}`}` })
    if (item.serial_managed) { setSerial(''); return }  // matricole: resto sullo stesso articolo e leggo la successiva
    setItem(null)
    setTimeout(() => searchRef.current?.focus(), 50)
  }

  if (!session) return <Center h="100vh"><Loader /></Center>
  if (session.error) return <Center h="100vh" p="md"><Text>Inventario non trovato o non hai accesso.</Text></Center>
  const closed = session.status !== 'aperto'
  const colors = item ? [...new Set(item.variants.map((v: any) => v.color || '—'))] as string[] : []
  const selected = item?.variants.find((v: any) => v.id === variant)

  return (
    <Box maw={520} mx="auto" p="sm" pb={120} mih="100vh" bg="var(--mantine-color-body)">
      <Group justify="space-between" mb="sm">
        <Logo size={28} />
        <Badge size="lg" variant="light" color={online ? (queue.length ? 'orange' : 'green') : 'red'}
          leftSection={online ? <IconCloudUpload size={14} /> : <IconCloudOff size={14} />}>
          {online ? (queue.length ? `${queue.length} da inviare` : 'sincronizzato') : `offline · ${queue.length} in coda`}
        </Badge>
      </Group>
      <Title order={4}>{session.name}</Title>
      <Text size="sm" c="dimmed" mb="md">{session.warehouse}</Text>
      {closed && <Paper withBorder p="md" mb="md" bg="var(--mantine-color-red-0)"><Text c="red">Questo inventario è {session.status}.</Text></Paper>}

      {!item && !closed && (
        <Stack>
          <Button size="xl" radius="md" h={90} leftSection={<IconCamera size={30} />} onClick={() => setCamera('item')}>Inquadra il codice</Button>
          <TextInput ref={searchRef} size="lg" placeholder="Oppure cerca per nome o codice" leftSection={<IconSearch size={18} />} value={q}
            onChange={(e) => setQ(e.currentTarget.value)} onKeyDown={(e) => e.key === 'Enter' && lookup(q)}
            rightSection={<ActionIcon size="lg" onClick={() => lookup(q)}><IconSearch size={18} /></ActionIcon>} />
          {results.map((r) => (
            <Card key={r.id} withBorder padding="sm" onClick={() => pick(r)} style={{ cursor: 'pointer' }}>
              <Text fw={600}>{r.description}</Text><Text size="xs" c="dimmed" ff="monospace">{r.code}{r.location ? ` · ${r.location}` : ''}</Text>
            </Card>
          ))}
        </Stack>
      )}

      {item && !closed && (
        <Card withBorder radius="md" padding="md">
          <Group wrap="nowrap" mb="sm">
            {item.image && <img src={item.image} alt="" width={56} height={56} style={{ objectFit: 'cover', borderRadius: 8 }} />}
            <div style={{ flex: 1 }}><Text fw={700}>{item.description}</Text><Text size="xs" c="dimmed" ff="monospace">{item.code}{item.location ? ` · ubicazione ${item.location}` : ''}</Text></div>
            <ActionIcon variant="subtle" color="gray" onClick={() => setItem(null)}><IconX size={18} /></ActionIcon>
          </Group>

          {item.variants.length > 0 && (
            <Stack gap="xs" mb="md">
              {colors.map((c) => (
                <div key={c}>
                  {c !== '—' && <Text size="xs" c="dimmed" mb={2}>{c}</Text>}
                  <Chip.Group value={variant ?? ''} onChange={(v) => setVariant(v as string)}>
                    <Group gap={6}>{item.variants.filter((v: any) => (v.color || '—') === c).map((v: any) => <Chip key={v.id} value={v.id} size="md">{v.size || v.code}</Chip>)}</Group>
                  </Chip.Group>
                </div>
              ))}
            </Stack>
          )}

          {item.lot_managed && (
            <Group grow mb="md">
              <TextInput size="md" label="Lotto" value={lot} onChange={(e) => setLot(e.currentTarget.value)} />
              <TextInput size="md" type="date" label="Scadenza" value={expiry} onChange={(e) => setExpiry(e.currentTarget.value)} />
            </Group>
          )}

          {item.serial_managed ? (
            <Group align="flex-end" mb="md" wrap="nowrap">
              <TextInput style={{ flex: 1 }} size="lg" label="Matricola" value={serial} onChange={(e) => setSerial(e.currentTarget.value)} onKeyDown={(e) => e.key === 'Enter' && confirm()} autoFocus />
              <ActionIcon size={50} variant="light" onClick={() => setCamera('serial')}><IconCamera size={24} /></ActionIcon>
            </Group>
          ) : (
            <Group justify="center" mb="md" wrap="nowrap">
              <ActionIcon size={64} radius="xl" variant="light" onClick={() => setCount(Math.max(0, Number(count || 0) - 1))}><IconMinus size={28} /></ActionIcon>
              <NumberInput value={count} onChange={setCount} min={0} hideControls size="xl" w={140} styles={{ input: { textAlign: 'center', fontSize: 32, fontWeight: 800, height: 64 } }}
                onKeyDown={(e) => e.key === 'Enter' && confirm()} autoFocus={!item.variants.length} decimalScale={3} />
              <ActionIcon size={64} radius="xl" variant="light" onClick={() => setCount(Number(count || 0) + 1)}><IconPlus size={28} /></ActionIcon>
            </Group>
          )}
          <Text ta="center" size="sm" c="dimmed" mb="sm">{item.unit}{selected ? ` · ${[selected.color, selected.size].filter(Boolean).join(' ')}` : ''}</Text>
          <Button size="xl" fullWidth leftSection={<IconCheck size={24} />} onClick={confirm}>Conferma</Button>
        </Card>
      )}

      {msg && (
        <Paper mt="md" p="sm" withBorder bg={msg.ok ? 'var(--mantine-color-green-0)' : 'var(--mantine-color-red-0)'} onClick={() => setMsg(null)}>
          <Text size="sm" c={msg.ok ? 'green.8' : 'red.8'} fw={600}>{msg.text}</Text>
        </Paper>
      )}

      {(queue.length > 0 || done.length > 0) && (
        <Stack gap={4} mt="lg">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Ultimi conteggi</Text>
          {[...queue].reverse().map((c) => <Text key={c.client_uuid} size="sm">⏳ {c.label} — {c.quantity}</Text>)}
          {done.slice(0, 10).map((c) => <Text key={c.client_uuid} size="sm" c="dimmed">✓ {c.label} — {c.quantity}</Text>)}
        </Stack>
      )}

      {camera && <CameraScanner onCode={onCamera} onClose={() => setCamera(false)} />}
    </Box>
  )
}
