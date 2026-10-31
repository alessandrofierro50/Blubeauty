import { Alert, Anchor, Badge, Button, Group, Menu, Paper, Stack, Text, Timeline } from '@mantine/core'
import { IconAlertTriangle, IconChevronDown, IconCircleCheck, IconDownload, IconRefresh, IconSend, IconShieldCheck } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { notifyError, notifyOk } from '../../components'
import { downloadXml } from './ExportXml'
import { FE, NOTIFY_LABEL, SDI_COLOR, SDI_HELP, SDI_LABEL } from './shared'

async function saveXml(url: string, name: string) {
  try { await downloadXml(url, name) } catch (e) { notifyError(e) }
}

/** Stato della fattura elettronica dentro il documento: controlli, invio, notifiche SDI. */
export default function SdiPanel({ docId, number, year, onChanged }: { docId: string; number?: number; year?: number; onChanged?: () => void }) {
  const [st, setSt] = useState<any>(null)
  const [settings, setSettings] = useState<any>(null)
  const [verify, setVerify] = useState<any>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const load = () => FE(`/documenti/${docId}`).then(setSt).catch(notifyError)
  useEffect(() => { load(); FE('/impostazioni').then(setSettings).catch(() => {}) }, [docId])
  if (!st) return null
  const cur = st.current
  const status = cur?.status ?? 'da_inviare'

  async function run(key: string, fn: () => Promise<any>) {
    setBusy(key)
    try { await fn() } catch (e) { notifyError(e) } finally { setBusy(null) }
  }
  const send = () => run('send', async () => {
    const r = await FE(`/documenti/${docId}/invia`, { body: {} })
    if (r.status === 'errore_elaborazione') notifyError(new Error(r.errors.map((e: any) => e.description).join('; ')))
    else notifyOk('Fattura presa in carico da Aruba: lo stato si aggiorna da solo')
    setVerify(null); load(); onChanged?.()
  })
  const check = () => run('check', async () => setVerify(await FE(`/documenti/${docId}/verifica`, { body: {} })))
  const refresh = () => run('refresh', async () => { await FE(`/documenti/${docId}/aggiorna`, { body: {} }); load(); onChanged?.() })
  const simulate = (type: string) => run('sim', async () => { await FE(`/documenti/${docId}/simula-notifica`, { body: { type } }); notifyOk('Notifica simulata: aggiorna tra qualche secondo') })

  return (
    <Paper withBorder p="md">
      <Group justify="space-between" mb="xs">
        <Group gap="xs"><IconShieldCheck size={18} /><Text fw={600} size="sm">Fattura elettronica</Text>
          <Badge color={SDI_COLOR[status]} variant="light">{SDI_LABEL[status]}</Badge>
          {cur?.attempt > 1 && <Text size="xs" c="dimmed">invio n. {cur.attempt}</Text>}</Group>
        <Group gap={4}>
          {st.can_send && <Button size="xs" variant="default" leftSection={<IconCircleCheck size={14} />} loading={busy === 'check'} onClick={check}>Verifica</Button>}
          {st.can_send && <Button size="xs" leftSection={<IconSend size={14} />} loading={busy === 'send'} onClick={send} disabled={!!st.check?.errors?.length}>{cur ? 'Reinvia' : 'Invia a SDI'}</Button>}
          <Button size="xs" variant="default" leftSection={<IconDownload size={14} />} onClick={() => saveXml(`/api/fatturapa/documenti/${docId}/xml`, `fattura-${number ?? 'bozza'}-${year ?? ''}.xml`)}>Esporta XML</Button>
          {cur?.filename && <Button size="xs" variant="subtle" leftSection={<IconRefresh size={14} />} loading={busy === 'refresh'} onClick={refresh}>Aggiorna</Button>}
          {settings?.environment === 'demo' && cur?.filename && <Menu position="bottom-end">
            <Menu.Target><Button size="xs" variant="subtle" px={6}><IconChevronDown size={14} /></Button></Menu.Target>
            <Menu.Dropdown>
              <Menu.Label>Simulatore SDI (ambiente di prova)</Menu.Label>
              {['RC', 'NS', 'MC', 'NE_EC01', 'NE_EC02'].map((t) => <Menu.Item key={t} onClick={() => simulate(t)}>Simula {NOTIFY_LABEL[t.slice(0, 2)] ?? t}{t.endsWith('EC01') ? ' (accettata)' : t.endsWith('EC02') ? ' (rifiutata)' : ''}</Menu.Item>)}
            </Menu.Dropdown>
          </Menu>}
        </Group>
      </Group>
      <Stack gap="xs">
        {SDI_HELP[status] && cur && <Text size="sm" c={SDI_COLOR[status] === 'red' ? 'red' : 'orange'}>{SDI_HELP[status]}</Text>}
        {cur?.errors?.length > 0 && (
          <Alert color="red" py="xs" icon={<IconAlertTriangle size={16} />} title="Errori segnalati">
            {cur.errors.map((e: any, i: number) => <Text key={i} size="sm">{e.code ? <b>{e.code} </b> : null}{e.description}</Text>)}
          </Alert>
        )}
        {!cur && st.check?.errors?.length > 0 && (
          <Alert color="orange" py="xs" title="Da sistemare prima dell'invio">
            {st.check.errors.map((e: string) => <Text key={e} size="sm">• {e}</Text>)}
            <Text size="xs" mt={4}>Correggi l'anagrafica del cliente o i <Anchor size="xs" href="/impostazioni/azienda">dati azienda</Anchor>: l'XML si rigenera da solo.</Text>
          </Alert>
        )}
        {st.check?.warnings?.map((w: string) => <Text key={w} size="xs" c="orange">⚠ {w}</Text>)}
        {verify && (
          <Alert color={verify.ok ? 'green' : 'red'} py="xs" onClose={() => setVerify(null)} withCloseButton>
            {verify.ok ? <Text size="sm">Tutto in regola: XML valido{verify.aruba === 'ok' ? ' e accettato dai controlli di Aruba (nessun invio effettuato)' : verify.aruba ? ` (verifica Aruba non eseguita: ${verify.aruba})` : ''}.</Text>
              : verify.errors.map((e: string) => <Text key={e} size="sm">• {e}</Text>)}
          </Alert>
        )}
        {cur?.notifications?.length > 0 && (
          <Timeline active={cur.notifications.length} bulletSize={14} lineWidth={2} mt="xs">
            {cur.sent_at && <Timeline.Item title={<Text size="xs">Presa in carico da Aruba</Text>}><Text size="10px" c="dimmed">{new Date(cur.sent_at).toLocaleString('it-IT')}</Text></Timeline.Item>}
            {cur.notifications.map((n: any, i: number) => (
              <Timeline.Item key={i} title={<Text size="xs">{NOTIFY_LABEL[n.type] ?? n.type}{n.result ? ` · ${n.result === 'EC01' ? 'accettata' : 'rifiutata'}` : ''}</Text>}>
                <Text size="10px" c="dimmed">{n.date ? new Date(n.date).toLocaleString('it-IT') : ''}</Text>
              </Timeline.Item>
            ))}
          </Timeline>
        )}
        {cur?.sdi_id && <Text size="xs" c="dimmed">Identificativo SDI {cur.sdi_id} · file {cur.filename}</Text>}
      </Stack>
    </Paper>
  )
}
