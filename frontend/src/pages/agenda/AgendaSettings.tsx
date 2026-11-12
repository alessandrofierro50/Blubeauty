import { ActionIcon, Anchor, Button, Checkbox, Grid, Group, NumberInput, Paper, PasswordInput, SegmentedControl, Select, Stack, Text, TextInput, Textarea, Title } from '@mantine/core'
import { IconCopy, IconPlus, IconTrash } from '@tabler/icons-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'

import { appApi } from '../../api'
import { Loading, PageTitle, VideoButton, notifyError, notifyOk } from '../../components'
import type { AppCtx } from '../app/AppLayout'
import { DAYS } from './lib'

type Hours = Record<string, string[][]>

/** Orari settimanali: più fasce per giorno (es. 9-13 e 15-19:30); giorno senza fasce = chiuso. */
export function HoursEditor({ value, onChange }: { value: Hours; onChange: (h: Hours) => void }) {
  const set = (day: string, ranges: string[][]) => {
    const next = { ...value }
    if (ranges.length) next[day] = ranges
    else delete next[day]
    onChange(next)
  }
  return (
    <Stack gap={6}>
      {DAYS.map(([k, label]) => {
        const ranges = value[k] ?? []
        return (
          <Group key={k} gap="xs" wrap="nowrap" align="center">
            <Text w={90} size="sm" fw={500}>{label}</Text>
            {ranges.length === 0 && <Text size="sm" c="dimmed" w={150}>Chiuso</Text>}
            {ranges.map((r, i) => (
              <Group key={i} gap={4} wrap="nowrap">
                <TextInput size="xs" w={70} value={r[0]} onChange={(e) => set(k, ranges.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} />
                <Text size="xs">–</Text>
                <TextInput size="xs" w={70} value={r[1]} onChange={(e) => set(k, ranges.map((x, j) => (j === i ? [x[0], e.target.value] : x)))} />
                <ActionIcon size="sm" variant="subtle" color="red" onClick={() => set(k, ranges.filter((_, j) => j !== i))}><IconTrash size={14} /></ActionIcon>
              </Group>
            ))}
            {ranges.length < 3 && <ActionIcon size="sm" variant="light" onClick={() => set(k, [...ranges, ranges.length ? ['15:00', '19:30'] : ['09:00', '13:00']])}><IconPlus size={14} /></ActionIcon>}
          </Group>
        )
      })}
    </Stack>
  )
}

export default function AgendaSettings() {
  const { status } = useOutletContext<AppCtx>()
  const has = (code: string) => status.menu.some((m: any) => m.code === code && m.enabled)
  const nav = useNavigate()
  const [s, setS] = useState<any>(null)
  const [wa, setWa] = useState<any>(null)
  const [token, setToken] = useState('')
  const [regs, setRegs] = useState<any[]>([])
  const [deps, setDeps] = useState<any[]>([])
  const [qr, setQr] = useState('')
  useEffect(() => {
    appApi('/api/agenda/impostazioni').then(setS).catch(notifyError)
    appApi('/api/marketing/impostazioni').then(setWa).catch(() => {})
    if (has('pos')) {
      appApi('/api/pos/casse').then(setRegs).catch(() => {})
      appApi('/api/pos/reparti').then(setDeps).catch(() => {})
    }
  }, [])
  useEffect(() => { if (s?.booking_url) QRCode.toDataURL(s.booking_url, { margin: 1, width: 220, color: { dark: '#0b2147', light: '#ffffff' } }).then(setQr) }, [s?.booking_url])
  if (!s) return <Loading />
  const save = async () => {
    try { setS(await appApi('/api/agenda/impostazioni', { method: 'PUT', body: s })); notifyOk('Impostazioni salvate') } catch (e) { notifyError(e) }
  }
  const saveWa = async () => {
    try { setWa(await appApi('/api/marketing/impostazioni', { method: 'PUT', body: { ...wa, whatsapp_token: token || null } })); setToken(''); notifyOk('WhatsApp salvato') } catch (e) { notifyError(e) }
  }
  return (
    <>
      <PageTitle title="Impostazioni del salone" subtitle="Orari, prenotazione online da smartphone, cassa e WhatsApp"
        right={<Group>{has('pos') && <Button variant="light" onClick={() => nav('/pos/ricevute')}>Ricevute: logo e intestazione</Button>}<Button onClick={save}>Salva</Button></Group>} />
      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Stack>
            <Paper withBorder p="md">
              <Title order={4} mb="sm">Orari di apertura</Title>
              <HoursEditor value={s.opening_hours} onChange={(h) => setS({ ...s, opening_hours: h })} />
              <NumberInput mt="sm" w={220} label="Intervallo dell'agenda (minuti)" value={s.slot_minutes} onChange={(v) => setS({ ...s, slot_minutes: Number(v) })} min={5} max={60} step={5} />
            </Paper>
            <Paper withBorder p="md">
              <Group justify="space-between" mb="sm"><Title order={4}>Prenotazione online</Title><VideoButton video="prenotazione_whatsapp" /></Group>
              <Checkbox mb="sm" label="I clienti possono prenotare dallo smartphone" checked={s.online_enabled} onChange={(e) => setS({ ...s, online_enabled: e.target.checked })} />
              <Group grow>
                <NumberInput label="Anticipo minimo (minuti)" value={s.online_lead_minutes} onChange={(v) => setS({ ...s, online_lead_minutes: Number(v) })} min={0} step={15} />
                <NumberInput label="Fino a quanti giorni avanti" value={s.online_max_days} onChange={(v) => setS({ ...s, online_max_days: Number(v) })} min={1} />
                <NumberInput label="Disdetta online fino a (ore prima)" value={s.cancel_hours} onChange={(v) => setS({ ...s, cancel_hours: Number(v) })} min={0} />
              </Group>
              <TextInput mt="sm" label="Nome mostrato ai clienti" placeholder={s.display_name} value={s.salon_name} onChange={(e) => setS({ ...s, salon_name: e.target.value })} />
              <Textarea mt="sm" label="Messaggio di benvenuto" value={s.welcome_text ?? ''} onChange={(e) => setS({ ...s, welcome_text: e.target.value })} />
            </Paper>
            {has('pos') && (
              <Paper withBorder p="md">
                <Title order={4} mb="sm">Cassa</Title>
                <Group grow>
                  <Select label="Cassa predefinita per gli incassi" data={regs.map((r) => ({ value: r.id, label: r.name }))} value={s.register_id} onChange={(v) => setS({ ...s, register_id: v })} clearable />
                  <Select label="Reparto dei servizi sul registratore" data={deps.map((d) => ({ value: d.id, label: d.name }))} value={s.department_id} onChange={(v) => setS({ ...s, department_id: v })} clearable />
                </Group>
                <Text size="xs" c="dimmed" mt="xs">Lo scontrino parte dal registratore telematico (Epson o Custom) collegato al computer della cassa con BluBeauty Agent: Cassa › Computer e periferiche.</Text>
              </Paper>
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack>
            <Paper withBorder p="md">
              <Title order={4} mb="xs">Il tuo link di prenotazione</Title>
              <Text size="sm" c="dimmed" mb="sm">Condividilo su Instagram, Facebook, Google e WhatsApp, o stampa il QR code per la vetrina e il bancone.</Text>
              {qr && <img src={qr} width={180} height={180} alt="QR code della prenotazione" style={{ display: 'block', margin: '0 auto' }} />}
              <Group mt="sm" wrap="nowrap">
                <TextInput value={s.booking_url} readOnly style={{ flex: 1 }} />
                <ActionIcon variant="light" size="lg" onClick={() => { navigator.clipboard?.writeText(s.booking_url); notifyOk('Link copiato') }}><IconCopy size={16} /></ActionIcon>
              </Group>
              <TextInput mt="sm" label="Indirizzo personalizzato" description="Lettere, numeri e trattini" value={s.slug} onChange={(e) => setS({ ...s, slug: e.target.value })} />
            </Paper>
            {wa && (
              <Paper withBorder p="md">
                <Title order={4} mb="xs">WhatsApp</Title>
                <SegmentedControl fullWidth value={wa.whatsapp_mode} onChange={(v) => setWa({ ...wa, whatsapp_mode: v })}
                  data={[{ value: 'simulato', label: 'Prova (simulato)' }, { value: 'cloud_api', label: 'WhatsApp Business' }]} />
                <Text size="xs" c="dimmed" mt="xs">In prova i messaggi si vedono nelle conversazioni ma non partono. Con WhatsApp Business (Cloud API di Meta) partono davvero dal numero del salone.</Text>
                <Anchor size="sm" href="/guide/BluBeauty-Guida-WhatsApp.pdf" target="_blank" mt={4} display="block">📄 Guida: collegare WhatsApp con la SIM del salone (passo passo)</Anchor>
                {wa.whatsapp_mode === 'cloud_api' && (
                  <Stack gap="xs" mt="sm">
                    <TextInput label="Phone number ID" value={wa.whatsapp_phone_id ?? ''} onChange={(e) => setWa({ ...wa, whatsapp_phone_id: e.target.value })} />
                    <PasswordInput label="Token di accesso" placeholder={wa.whatsapp_token_set ? 'salvato · lascia vuoto per non cambiarlo' : ''} value={token} onChange={(e) => setToken(e.target.value)} />
                    <TextInput label="ID dell'account WhatsApp Business (WABA ID)" description="Serve per far approvare i messaggi da Meta direttamente da BluBeauty"
                      value={wa.whatsapp_waba_id ?? ''} onChange={(e) => setWa({ ...wa, whatsapp_waba_id: e.target.value.replace(/\D/g, '') })} />
                  </Stack>
                )}
                <TextInput mt="sm" label="Link per le recensioni Google" placeholder="https://g.page/r/…/review" value={wa.review_url ?? ''} onChange={(e) => setWa({ ...wa, review_url: e.target.value })} />
                <Button mt="sm" variant="light" onClick={saveWa}>Salva WhatsApp</Button>
              </Paper>
            )}
          </Stack>
        </Grid.Col>
      </Grid>
    </>
  )
}
