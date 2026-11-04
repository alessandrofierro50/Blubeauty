import { Alert, Badge, Button, Grid, Group, Modal, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Textarea, Title, UnstyledButton } from '@mantine/core'
import { IconBrandWhatsapp, IconEdit, IconGift, IconLock, IconPlus, IconSend } from '@tabler/icons-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'

import { appApi } from '../../api'
import { Loading, PageTitle, Stat, notifyError, notifyOk } from '../../components'
import type { AppCtx } from '../app/AppLayout'
import { KIND_LABEL } from '../agenda/lib'
import { WhatsAppChat } from '../agenda/WhatsAppChat'
import { EntitySelect } from '../../EntitySelect'

const IDEAS = [
  { name: 'Promo martedì e mercoledì', body: 'Ciao {nome}! 💙 Solo martedì e mercoledì da {salone}: piega a 15 €. Posti limitati, prenota dal telefono in 30 secondi 👉 {link}' },
  { name: 'Nuovo trattamento viso', body: 'Ciao {nome}, è arrivato il nuovo trattamento viso illuminante ✨ Per te la prima seduta al 30% di sconto. Prenota qui: {link}' },
  { name: 'Ci manchi', body: 'Ciao {nome}, è un po\' che non ti vediamo 💙 Questo mese per te una piega in omaggio con qualsiasi servizio. Prenota: {link}' },
]

// segnaposto dei messaggi di buoni regalo e pacchetti (app/prepagati/service.py: voucher_values, package_values)
const PLACEHOLDERS: Record<string, string> = {
  buono_ricevuto: '{codice} {importo} {scadenza} {buono} (pagina del buono) {regalato_da}',
  buono_saldo: '{codice} {usato} {residuo} {scadenza} {buono}',
  pacchetto_acquistato: '{pacchetto} {sedute} {scadenza}',
  pacchetto_seduta: '{pacchetto} {seduta} {totale} {restano} {rimaste} {scadenza}',
  prepagato_scadenza: '{cosa} {data} {resta}',
}

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
                      {a.offset != null && <Badge size="xs" variant="light">{a.kind === 'promemoria' ? `${a.offset} ore prima` : a.kind === 'prepagato_scadenza' ? `${a.offset} giorni prima` : `${a.offset} giorni`}</Badge>}
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

      {hasMk && <LoyaltySettings />}
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
            description={`Segnaposto: {nome} {salone} {link} ${PLACEHOLDERS[edit.kind] ?? '{data} {ora} {servizio} {recensione} {giorni}'}`} />
          {edit.offset != null && <NumberInput label={edit.kind === 'promemoria' ? 'Ore prima dell\'appuntamento' : 'Giorni'} value={edit.offset} onChange={(v) => setEdit({ ...edit, offset: Number(v) })} min={0} />}
          <Button onClick={async () => { if (await saveAuto(edit, { template: edit.template, offset: edit.offset })) { setEdit(null); notifyOk('Testo salvato') } }}>Salva</Button>
        </Stack>
      </Modal>}
    </>
  )
}


const KIND: Record<string, string> = { sconto_euro: 'Sconto in euro', sconto_percento: 'Sconto in percentuale', servizio: 'Servizio in omaggio' }

/** Regole della raccolta punti e premi (come i programmi fedeltà dei software del settore). */
function LoyaltySettings() {
  const [f, setF] = useState<any>(null)
  const [services, setServices] = useState<any[]>([])
  const [edit, setEdit] = useState<any>(null)
  const load = () => appApi('/api/marketing/fidelity').then(setF).catch(notifyError)
  useEffect(() => { load(); appApi('/api/agenda/servizi').then(setServices).catch(() => {}) }, [])
  if (!f) return null
  const save = async (patch: any) => {
    try { setF(await appApi('/api/marketing/fidelity', { method: 'PUT', body: { enabled: f.enabled, points_per_euro: f.points_per_euro, welcome_points: f.welcome_points, referral_points: f.referral_points, card_prefix: f.card_prefix, ...patch } })) } catch (e) { notifyError(e) }
  }
  const saveReward = async () => {
    const body = { name: edit.name, points: Number(edit.points), kind: edit.kind, value: Number(edit.value || 0), service_id: edit.service_id || null, active: edit.active ?? true }
    try { await appApi(edit.id ? `/api/marketing/fidelity/premi/${edit.id}` : '/api/marketing/fidelity/premi', { method: edit.id ? 'PUT' : 'POST', body }); setEdit(null); load(); notifyOk('Premio salvato') } catch (e) { notifyError(e) }
  }
  return (
    <Paper withBorder p="md" mb="lg">
      <Group justify="space-between" mb="sm">
        <Group gap={8}><IconGift /><Title order={4}>Raccolta punti e tessere fedeltà</Title></Group>
        <Switch size="md" label={f.enabled ? 'Attiva' : 'Spenta'} checked={f.enabled} onChange={(e) => save({ enabled: e.currentTarget.checked })} />
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 3 }} mb="md">
        <NumberInput label="Punti per ogni euro speso" value={f.points_per_euro} min={0} onChange={(v) => setF({ ...f, points_per_euro: Number(v) })} onBlur={() => save({})} />
        <NumberInput label="Punti di benvenuto con la tessera" value={f.welcome_points} min={0} onChange={(v) => setF({ ...f, welcome_points: Number(v) })} onBlur={() => save({})} />
        <NumberInput label="Punti a chi presenta un'amica" value={f.referral_points} min={0} onChange={(v) => setF({ ...f, referral_points: Number(v) })} onBlur={() => save({})} />
      </SimpleGrid>
      <Group justify="space-between" mb={6}><Text fw={600}>Premi</Text><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setEdit({ kind: 'sconto_euro', points: 100, value: 5, name: '' })}>Nuovo premio</Button></Group>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        {f.rewards.map((r: any) => (
          <Paper key={r.id} withBorder p="sm" style={{ cursor: 'pointer' }} opacity={r.active ? 1 : 0.5} onClick={() => setEdit(r)}>
            <Text fw={700}>🎁 {r.name}</Text><Text size="sm" c="dimmed">{r.points} punti · {KIND[r.kind]}</Text>
          </Paper>
        ))}
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt="sm">I punti si accumulano a ogni incasso e il premio si usa in cassa con un tocco. Quando una cliente raggiunge un premio le arriva un messaggio WhatsApp.</Text>
      {edit && <Modal opened onClose={() => setEdit(null)} title={edit.id ? 'Modifica premio' : 'Nuovo premio'}>
        <Stack>
          <TextInput label="Nome del premio" placeholder="Es. Piega in omaggio" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
          <NumberInput label="Punti necessari" value={edit.points} min={1} onChange={(v) => setEdit({ ...edit, points: v })} />
          <Select label="Tipo" data={Object.entries(KIND).map(([value, label]) => ({ value, label }))} value={edit.kind} onChange={(v) => setEdit({ ...edit, kind: v })} />
          {edit.kind === 'servizio' ? <EntitySelect kind="servizi" label="Servizio in omaggio" filter={(x) => x.active} value={edit.service_id} onChange={(v) => setEdit({ ...edit, service_id: v })} />
            : <NumberInput label={edit.kind === 'sconto_percento' ? 'Percentuale di sconto' : 'Sconto in euro'} value={edit.value} min={0} onChange={(v) => setEdit({ ...edit, value: v })} />}
          <Switch label="Attivo" checked={edit.active ?? true} onChange={(e) => setEdit({ ...edit, active: e.currentTarget.checked })} />
          <Button onClick={saveReward} disabled={!edit.name}>Salva</Button>
        </Stack>
      </Modal>}
    </Paper>
  )
}
