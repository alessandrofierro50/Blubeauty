import { Alert, Badge, Button, Group, NumberInput, Paper, SimpleGrid, Stack, Tabs, TagsInput, Text, Textarea, TextInput, Title } from '@mantine/core'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'

import { adminApi } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { ChangePassword } from '../app/Passwords'
import { PaymentSettings } from './Payments'

export default function Settings() {
  return (
    <>
      <PageTitle title="Impostazioni" subtitle="Pacchetti, avvisi di scadenza, modelli email, pagamenti, video di aiuto e il tuo account" />
      <Tabs defaultValue={new URLSearchParams(window.location.search).get('tab') ?? 'pacchetti'}>
        <Tabs.List mb="md">
          <Tabs.Tab value="pacchetti">Pacchetti</Tabs.Tab>
          <Tabs.Tab value="avvisi">Avvisi di scadenza</Tabs.Tab>
          <Tabs.Tab value="modelli">Modelli email</Tabs.Tab>
          <Tabs.Tab value="pagamenti">Pagamenti</Tabs.Tab>
          <Tabs.Tab value="video">Video di aiuto</Tabs.Tab>
          <Tabs.Tab value="account">Il mio account</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="pacchetti"><Plans /></Tabs.Panel>
        <Tabs.Panel value="avvisi"><Rules /></Tabs.Panel>
        <Tabs.Panel value="modelli"><Templates /></Tabs.Panel>
        <Tabs.Panel value="pagamenti"><PaymentSettings /></Tabs.Panel>
        <Tabs.Panel value="video"><HelpVideos /></Tabs.Panel>
        <Tabs.Panel value="account"><Account /></Tabs.Panel>
      </Tabs>
    </>
  )
}

function Plans() {
  const [plans, setPlans] = useState<any[] | null>(null)
  const [modules, setModules] = useState<Record<string, string>>({})
  useEffect(() => {
    adminApi('/plans').then(setPlans).catch(notifyError)
    adminApi('/modules').then((m: any[]) => setModules(Object.fromEntries(m.map((x) => [x.code, x.label])))).catch(() => {})
  }, [])
  if (!plans) return <Loading />
  const upd = (i: number, k: string, v: any) => setPlans(plans.map((p, j) => (j === i ? { ...p, [k]: v } : p)))
  async function save(p: any) {
    try {
      await adminApi(`/plans/${p.code}`, { method: 'PATCH', body: {
        name: p.name, price_month: p.price_month, price_year: p.price_year, max_users: p.max_users,
        max_companies: p.max_companies, max_warehouses: p.max_warehouses, max_pos: p.max_pos } })
      notifyOk(`Pacchetto ${p.code} salvato`)
    } catch (e) { notifyError(e) }
  }
  return (
    <SimpleGrid cols={{ base: 1, lg: 3 }}>
      {plans.map((p, i) => (
        <Paper key={p.code} withBorder p="md">
          <Stack gap="sm">
            <Group justify="space-between"><Title order={4}>{p.code}</Title></Group>
            <TextInput label="Nome" value={p.name} onChange={(e) => upd(i, 'name', e.currentTarget.value)} />
            <SimpleGrid cols={2}>
              <NumberInput label="€ / mese" value={p.price_month} decimalScale={2} onChange={(v) => upd(i, 'price_month', v)} />
              <NumberInput label="€ / anno" value={p.price_year} decimalScale={2} onChange={(v) => upd(i, 'price_year', v)} />
              <NumberInput label="Utenti" value={p.max_users} onChange={(v) => upd(i, 'max_users', v)} />
              <NumberInput label="Ragioni sociali" value={p.max_companies} onChange={(v) => upd(i, 'max_companies', v)} />
              <NumberInput label="Magazzini" value={p.max_warehouses} onChange={(v) => upd(i, 'max_warehouses', v)} />
              <NumberInput label="Postazioni cassa" value={p.max_pos} onChange={(v) => upd(i, 'max_pos', v)} />
            </SimpleGrid>
            <Group gap={4}>{p.modules.map((m: string) => <Badge key={m} variant="light" size="sm">{modules[m] ?? m}</Badge>)}</Group>
            <Button onClick={() => save(p)}>Salva</Button>
          </Stack>
        </Paper>
      ))}
    </SimpleGrid>
  )
}

function Rules() {
  const [days, setDays] = useState<string[] | null>(null)
  const [life, setLife] = useState<any>(null)
  useEffect(() => {
    adminApi('/reminder-rules').then((d: number[]) => setDays(d.map(String))).catch(notifyError)
    adminApi('/lifecycle').then((l: any) => setLife({ ...l, trial_reminder_days: l.trial_reminder_days.map(String) })).catch(notifyError)
  }, [])
  if (!days || !life) return <Loading />
  const nums = (v: string[]) => v.map(Number).filter((n) => !isNaN(n))
  async function save() {
    try {
      const d = await adminApi('/reminder-rules', { method: 'PUT', body: { days: nums(days!) } })
      setDays(d.map(String))
      const l = await adminApi('/lifecycle', { method: 'PUT', body: {
        grace_days: Number(life.grace_days) || 0, readonly_days: Number(life.readonly_days) || 0,
        trial_reminder_days: nums(life.trial_reminder_days) } })
      setLife({ ...l, trial_reminder_days: l.trial_reminder_days.map(String) })
      notifyOk('Avvisi e ciclo di vita salvati')
    } catch (e) { notifyError(e) }
  }
  return (
    <Paper withBorder p="md" maw={640}>
      <Stack>
        <Text size="sm">Gli avvisi partono ogni giorno alle 8:07, per email al cliente (con copia a BluCode) e come banner nel gestionale.
          Ogni avviso parte una sola volta per periodo; se il controllo salta un giorno, parte solo il più vicino.</Text>
        <TagsInput label="Abbonamento: giorni prima della scadenza" description="0 = il giorno stesso. Poi partono in automatico l'avviso a fine tolleranza («da domani sola lettura») e quello di sospensione."
          value={days} onChange={setDays} placeholder="Scrivi un numero e premi Invio" />
        <TagsInput label="Prova gratuita: giorni prima della fine" description="Alla fine della prova l'accesso è sospeso subito, senza tolleranza né sola lettura."
          value={life.trial_reminder_days} onChange={(v) => setLife({ ...life, trial_reminder_days: v })} placeholder="Scrivi un numero e premi Invio" />
        <SimpleGrid cols={2}>
          <NumberInput label="Giorni di tolleranza" description="Accesso completo con banner rosso" min={0} max={365}
            value={life.grace_days} onChange={(v) => setLife({ ...life, grace_days: v })} />
          <NumberInput label="Giorni di sola lettura" description="Poi l'azienda è sospesa" min={0} max={365}
            value={life.readonly_days} onChange={(v) => setLife({ ...life, readonly_days: v })} />
        </SimpleGrid>
        <Text size="xs" c="dimmed">Tolleranza e sola lettura sono valori predefiniti per i nuovi periodi: quelli già inseriti conservano i loro.</Text>
        <Group justify="flex-end"><Button onClick={save}>Salva</Button></Group>
      </Stack>
    </Paper>
  )
}

function Templates() {
  const [tpls, setTpls] = useState<any[] | null>(null)
  useEffect(() => { adminApi('/email-templates').then(setTpls).catch(notifyError) }, [])
  if (!tpls) return <Loading />
  const upd = (i: number, k: string, v: string) => setTpls(tpls.map((t, j) => (j === i ? { ...t, [k]: v } : t)))
  async function save(t: any) {
    try {
      await adminApi(`/email-templates/${t.code}`, { method: 'PUT', body: { subject: t.subject, body: t.body } })
      notifyOk('Modello salvato')
    } catch (e) { notifyError(e) }
  }
  return (
    <Stack>
      <Text size="sm" c="dimmed">Segnaposto degli avvisi: {'{azienda}'} {'{prodotto}'} {'{piano}'} {'{scadenza}'} {'{giorni}'} {'{link_accesso}'} {'{contatti}'} · anche {'{giorni_tolleranza}'} {'{giorni_sola_lettura}'} — per l'attivazione: {'{nome}'} {'{link_attivazione}'}</Text>
      {tpls.map((t, i) => (
        <Paper key={t.code} withBorder p="md">
          <Text fw={600}>{t.description}</Text>
          <TextInput label="Oggetto" mt="sm" value={t.subject} onChange={(e) => upd(i, 'subject', e.currentTarget.value)} />
          <SimpleGrid cols={{ base: 1, md: 2 }} mt="sm">
            <Textarea label="Testo (HTML)" autosize minRows={8} value={t.body} onChange={(e) => upd(i, 'body', e.currentTarget.value)} styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }} />
            <div>
              <Text size="sm" fw={500} mb={4}>Anteprima</Text>
              <Paper withBorder p="xs" bg="white" style={{ color: '#1b2b45' }}><div dangerouslySetInnerHTML={{ __html: t.body }} /></Paper>
            </div>
          </SimpleGrid>
          <Group justify="flex-end" mt="sm"><Button onClick={() => save(t)}>Salva</Button></Group>
        </Paper>
      ))}
    </Stack>
  )
}

function HelpVideos() {
  const [rows, setRows] = useState<{ key: string; title: string; screen: string; url: string | null }[] | null>(null)
  useEffect(() => { adminApi('/video-aiuto').then(setRows).catch(notifyError) }, [])
  if (!rows) return <Loading />
  async function save() {
    try {
      setRows(await adminApi('/video-aiuto', { method: 'PUT', body: { urls: Object.fromEntries(rows!.map((r) => [r.key, r.url || null])) } }))
      notifyOk('Video salvati')
    } catch (e) { notifyError(e) }
  }
  return (
    <Paper withBorder p="md" maw={900}>
      <Stack>
        <Text size="sm">Ogni schermata ha il pulsante «Guarda il video», che apre il tutorial in una finestra sopra la pagina.
          Incolla l'indirizzo del video: YouTube (anche non in elenco), Vimeo o un file .mp4 sul server. Vale per tutte le aziende;
          finché è vuoto il cliente vede «Il video di questa pagina è in preparazione».</Text>
        {rows.map((r, i) => (
          <TextInput key={r.key} label={r.title} description={`Schermata: ${r.screen}`} placeholder="https://youtu.be/…"
            value={r.url ?? ''} onChange={(e) => { const v = e.currentTarget.value; setRows(rows.map((x, j) => (j === i ? { ...x, url: v } : x))) }} />
        ))}
        <Group justify="flex-end"><Button onClick={save}>Salva</Button></Group>
      </Stack>
    </Paper>
  )
}

function Account() {
  const [me, setMe] = useState<any>(null)
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null)
  const [code, setCode] = useState('')
  const load = () => adminApi('/auth/me').then(setMe).catch(notifyError)
  useEffect(() => { load() }, [])
  async function start() {
    try {
      const r = await adminApi('/auth/totp/setup', { method: 'POST' })
      setSetup({ secret: r.secret, qr: await QRCode.toDataURL(r.uri, { margin: 1, width: 200 }) })
    } catch (e) { notifyError(e) }
  }
  async function confirm() {
    try { await adminApi('/auth/totp/confirm', { body: { code } }); notifyOk('Verifica in due passaggi attivata'); setSetup(null); setCode(''); load() } catch (e) { notifyError(e) }
  }
  if (!me) return <Loading />
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} maw={1000}>
      <Paper withBorder p="md">
        <Title order={4} mb={4}>Password</Title>
        <Text size="sm" c="dimmed" mb="md">Accesso al pannello come {me.email}. Se la dimentichi, usa «Password dimenticata?» nella pagina di accesso.</Text>
        <ChangePassword scope="admin" onDone={() => {}} />
      </Paper>
      <Paper withBorder p="md">
        <Group justify="space-between" mb={4}><Title order={4}>Verifica in due passaggi</Title>
          {me.totp_enabled ? <Badge color="teal">attiva</Badge> : <Badge color="orange">non attiva</Badge>}</Group>
        <Text size="sm" c="dimmed" mb="md">Oltre alla password serve il codice a 6 cifre dell'app sul telefono (Google Authenticator, Microsoft Authenticator…).
          Consigliata: il pannello vede i dati di tutte le aziende.</Text>
        {setup ? (
          <Stack>
            <Text size="sm">1. Inquadra il codice con l'app (o inserisci a mano la chiave).</Text>
            <img src={setup.qr} alt="Codice QR" width={200} height={200} />
            <Text size="xs" ff="monospace">{setup.secret}</Text>
            <Text size="sm">2. Scrivi il codice che mostra l'app.</Text>
            <Group><TextInput value={code} onChange={(e) => setCode(e.currentTarget.value)} inputMode="numeric" maxLength={6} w={140} placeholder="123456" />
              <Button onClick={confirm} disabled={code.length !== 6}>Attiva</Button></Group>
            <Alert color="yellow">Finché non confermi il codice, la verifica in due passaggi resta spenta.</Alert>
          </Stack>
        ) : <Button variant={me.totp_enabled ? 'default' : 'filled'} onClick={start}>{me.totp_enabled ? 'Riconfigura su un nuovo telefono' : 'Attiva'}</Button>}
      </Paper>
    </SimpleGrid>
  )
}
