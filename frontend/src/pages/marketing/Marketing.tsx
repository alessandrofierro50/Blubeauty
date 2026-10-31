import { Alert, Badge, Button, Grid, Group, Modal, NumberInput, Paper, SimpleGrid, Stack, Switch, Table, Text, TextInput, Textarea, Title, UnstyledButton } from '@mantine/core'
import { IconBrandWhatsapp, IconEdit, IconLock, IconSend } from '@tabler/icons-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'

import { appApi } from '../../api'
import { Loading, PageTitle, Stat, notifyError, notifyOk } from '../../components'
import type { AppCtx } from '../app/AppLayout'
import { KIND_LABEL } from '../agenda/lib'
import { WhatsAppChat } from '../agenda/WhatsAppChat'

const IDEAS = [
  { name: 'Promo martedì e mercoledì', body: 'Ciao {nome}! 💙 Solo martedì e mercoledì da {salone}: piega a 15 €. Posti limitati, prenota dal telefono in 30 secondi 👉 {link}' },
  { name: 'Nuovo trattamento viso', body: 'Ciao {nome}, è arrivato il nuovo trattamento viso illuminante ✨ Per te la prima seduta al 30% di sconto. Prenota qui: {link}' },
  { name: 'Ci manchi', body: 'Ciao {nome}, è un po\' che non ti vediamo 💙 Questo mese per te una piega in omaggio con qualsiasi servizio. Prenota: {link}' },
]

export default function Marketing() {
  const { status } = useOutletContext<AppCtx>()
  const hasMk = status.menu.some((m: any) => m.code === 'marketing' && m.enabled)
  const [sum, setSum] = useState<any>(null)
  const [autos, setAutos] = useState<any[]>([])
  const [segs, setSegs] = useState<any[]>([])
  const [camps, setCamps] = useState<any[]>([])
  const [edit, setEdit] = useState<any>(null)
  const [qr, setQr] = useState('')
  const [c, setC] = useState({ name: '', segment: 'tutti', body: '' })
  const [sending, setSending] = useState(false)
  const nav = useNavigate()
  const load = () => {
    appApi('/api/marketing/riepilogo').then((s) => { setSum(s); QRCode.toDataURL(s.booking_url, { margin: 1, width: 200, color: { dark: '#0b2147', light: '#ffffff' } }).then(setQr) }).catch(notifyError)
    appApi('/api/marketing/automatici').then(setAutos).catch(notifyError)
    if (hasMk) {
      appApi('/api/marketing/segmenti').then(setSegs).catch(() => {})
      appApi('/api/marketing/campagne').then(setCamps).catch(() => {})
    }
  }
  useEffect(load, [])
  if (!sum) return <Loading />
  const saveAuto = async (a: any, patch: any) => {
    try {
      const r = await appApi(`/api/marketing/automatici/${a.id}`, { method: 'PUT', body: { enabled: a.enabled, template: a.template, offset: a.offset, ...patch } })
      setAutos(autos.map((x) => (x.id === a.id ? r : x)))
      return true
    } catch (e) { notifyError(e); return false }
  }
  const send = async () => {
    setSending(true)
    try {
      const r = await appApi('/api/marketing/campagne', { body: c })
      notifyOk(`Campagna inviata a ${r.recipients} clienti su WhatsApp`)
      setC({ name: '', segment: 'tutti', body: '' })
      load()
    } catch (e) { notifyError(e) } finally { setSending(false) }
  }
  const preview = c.body.replace(/\{nome\}/g, 'Laura').replace(/\{salone\}/g, 'il salone').replace(/\{link\}/g, sum.booking_url)
  const count = segs.find((s) => s.code === c.segment)?.count ?? 0
  return (
    <>
      <PageTitle title="Marketing e WhatsApp" subtitle="Messaggi automatici, campagne e prenotazioni dallo smartphone" />
      {sum.mode === 'simulato' && <Alert color="yellow" mb="md" icon={<IconBrandWhatsapp />}>
        WhatsApp in modalità di prova: i messaggi si registrano e si vedono nelle conversazioni, ma non partono. Collega il numero WhatsApp Business del salone da <UnstyledButton c="blu" fw={600} onClick={() => nav('/agenda/impostazioni')}>Impostazioni agenda</UnstyledButton>.
      </Alert>}
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="lg">
        <Stat label="Messaggi (30 giorni)" value={sum.sent_30} />
        <Stat label="Letti" value={sum.sent_30 ? `${Math.round((sum.read_30 / sum.sent_30) * 100)}%` : '—'} />
        <Stat label="Prenotazioni online (30 gg)" value={sum.online_30} />
        <Stat label="Clienti con consenso" value={sum.consent} />
      </SimpleGrid>
      <Grid mb="lg">
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Paper withBorder p="md">
            <Title order={4}>Messaggi automatici</Title>
            <Text size="sm" c="dimmed" mb="sm">Partono da soli su WhatsApp, una sola volta per cliente e occasione.</Text>
            <Stack gap={0}>
              {autos.map((a) => (
                <Group key={a.id} py="sm" wrap="nowrap" align="flex-start" style={{ borderTop: '1px solid var(--mantine-color-gray-2)' }} opacity={a.available ? 1 : 0.55}>
                  <div style={{ flex: 1 }}>
                    <Group gap={6}>
                      <Text fw={600}>{a.label}</Text>
                      {a.offset != null && <Badge size="xs" variant="light">{a.kind === 'promemoria' ? `${a.offset} ore prima` : `${a.offset} giorni`}</Badge>}
                      {!a.available && <Badge size="xs" color="gray" leftSection={<IconLock size={10} />}>pacchetto Salone</Badge>}
                    </Group>
                    <Text size="sm" c="dimmed" lineClamp={2}>{a.template}</Text>
                  </div>
                  <Button size="compact-sm" variant="subtle" leftSection={<IconEdit size={14} />} disabled={!a.available} onClick={() => setEdit({ ...a })}>Testo</Button>
                  <Switch checked={a.enabled} disabled={!a.available} onChange={(e) => saveAuto(a, { enabled: e.currentTarget.checked })} aria-label={a.label} />
                </Group>
              ))}
            </Stack>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Paper withBorder p="md" h="100%">
            <Title order={4}>Prenotazioni dallo smartphone</Title>
            <Text size="sm" c="dimmed" my="xs">I clienti prenotano e disdicono da soli, 24 ore su 24, da Instagram, Google, WhatsApp o dal QR code in vetrina.</Text>
            {qr && <img src={qr} width={170} height={170} alt="QR code" style={{ display: 'block', margin: '0 auto' }} />}
            <Text size="sm" ta="center" mt="xs"><a href={sum.booking_url} target="_blank" rel="noreferrer">{sum.booking_url}</a></Text>
          </Paper>
        </Grid.Col>
      </Grid>

      {hasMk ? (
        <Paper withBorder p="md" mb="lg">
          <Grid>
            <Grid.Col span={{ base: 12, md: 8 }}>
              <Title order={4}>Nuova campagna WhatsApp</Title>
              <Text size="sm" c="dimmed" mb="sm">Solo ai clienti che hanno dato il consenso marketing. Il messaggio si personalizza con il nome di ognuno.</Text>
              <Group gap={6} mb="sm">
                {IDEAS.map((i) => <Button key={i.name} size="compact-sm" variant="light" onClick={() => setC({ ...c, name: i.name, body: i.body })}>💡 {i.name}</Button>)}
              </Group>
              <TextInput label="Nome della campagna" value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} mb="sm" />
              <SimpleGrid cols={2} mb="sm">
                {segs.map((s) => (
                  <Paper key={s.code} withBorder p="sm" style={{ cursor: 'pointer', borderColor: c.segment === s.code ? 'var(--mantine-color-blu-6)' : undefined, background: c.segment === s.code ? 'var(--mantine-color-blu-0)' : undefined }}
                    onClick={() => setC({ ...c, segment: s.code })}>
                    <Text size="sm" fw={600}>{s.label}</Text>
                    <Text size="sm" c="dimmed">{s.count} clienti</Text>
                  </Paper>
                ))}
              </SimpleGrid>
              <Textarea label="Messaggio" autosize minRows={3} value={c.body} onChange={(e) => setC({ ...c, body: e.target.value })}
                description="Segnaposto: {nome} {salone} {link} (link di prenotazione)" />
              <Button mt="sm" leftSection={<IconSend size={16} />} onClick={send} loading={sending} disabled={!c.name || c.body.length < 10 || count === 0}>Invia a {count} clienti</Button>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Text size="xs" c="dimmed" ta="center" tt="uppercase" fw={600} mb={6}>Anteprima</Text>
              <WhatsAppChat title="Il salone" height={300} empty="Scrivi il messaggio" messages={preview ? [{ id: 'p', body: preview, created_at: new Date().toISOString(), inbound: false, status: 'letto', kind: 'campagna' }] : []} />
            </Grid.Col>
          </Grid>
        </Paper>
      ) : (
        <Alert color="blu" mb="lg" icon={<IconLock />}>Campagne WhatsApp, auguri di compleanno, richiami e recupero dei clienti persi sono nel pacchetto <b>Salone</b>.</Alert>
      )}

      <Grid>
        {hasMk && <Grid.Col span={{ base: 12, md: 6 }}>
          <Paper withBorder p="md">
            <Title order={4} mb="sm">Campagne inviate</Title>
            <Table><Table.Tbody>
              {camps.map((x) => <Table.Tr key={x.id}><Table.Td><Text fw={600} size="sm">{x.name}</Text><Text size="xs" c="dimmed">{x.segment_label}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm">{x.recipients} invii</Text><Text size="xs" c="dimmed">{x.sent_at ? new Date(x.sent_at).toLocaleDateString('it-IT') : 'bozza'}</Text></Table.Td></Table.Tr>)}
              {camps.length === 0 && <Table.Tr><Table.Td><Text c="dimmed" size="sm">Nessuna campagna</Text></Table.Td></Table.Tr>}
            </Table.Tbody></Table>
          </Paper>
        </Grid.Col>}
        <Grid.Col span={{ base: 12, md: hasMk ? 6 : 12 }}>
          <Paper withBorder p="md">
            <Title order={4} mb="sm">Ultimi messaggi</Title>
            <Table><Table.Tbody>
              {sum.recent.map((m: any) => (
                <Table.Tr key={m.id} style={{ cursor: m.party_id ? 'pointer' : undefined }} onClick={() => m.party_id && nav(`/agenda/clienti/${m.party_id}`)}>
                  <Table.Td><Text size="sm">{KIND_LABEL[m.kind] ?? m.label}</Text><Text size="xs" c="dimmed">{m.to}</Text></Table.Td>
                  <Table.Td ta="right"><Text size="xs" c="dimmed">{new Date(m.created_at).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })} · {m.status}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody></Table>
          </Paper>
        </Grid.Col>
      </Grid>

      {edit && <Modal opened onClose={() => setEdit(null)} title={edit.label} size="lg">
        <Stack>
          <Textarea autosize minRows={4} value={edit.template} onChange={(e) => setEdit({ ...edit, template: e.target.value })}
            description="Segnaposto: {nome} {salone} {data} {ora} {servizio} {link} {recensione} {giorni}" />
          {edit.offset != null && <NumberInput label={edit.kind === 'promemoria' ? 'Ore prima dell\'appuntamento' : 'Giorni'} value={edit.offset} onChange={(v) => setEdit({ ...edit, offset: Number(v) })} min={0} />}
          <Button onClick={async () => { if (await saveAuto(edit, { template: edit.template, offset: edit.offset })) { setEdit(null); notifyOk('Testo salvato') } }}>Salva</Button>
        </Stack>
      </Modal>}
    </>
  )
}
