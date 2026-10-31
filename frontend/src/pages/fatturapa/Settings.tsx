import { Alert, Anchor, Badge, Button, Code, Group, Paper, PasswordInput, SegmentedControl, Stack, Switch, Text, TextInput, Title } from '@mantine/core'
import { IconCheck, IconPlugConnected } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import ExportXmlButton from './ExportXml'
import { FE, useModule } from './shared'

export default function EInvoiceSettings() {
  const nav = useNavigate()
  const enabled = useModule('fatturapa')
  const [s, setS] = useState<any>(null)
  const [password, setPassword] = useState('')
  const [signCredential, setSignCredential] = useState('')
  const [test, setTest] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (enabled) FE('/impostazioni').then(setS).catch(notifyError) }, [enabled])

  if (!enabled) {
    return (
      <>
        <PageTitle title="Fatturazione elettronica" />
        <Alert title="Modulo extra non attivo">La fatturazione elettronica (invio e ricezione tramite SDI) è un modulo extra: chiedi di attivarlo. Nel frattempo puoi emettere e stampare le fatture e importare a mano gli XML delle fatture d'acquisto.</Alert>
      </>
    )
  }
  if (!s) return <Loading />

  async function save() {
    setBusy(true)
    try {
      const r = await FE('/impostazioni', { method: 'PUT', body: { mode: s.mode, username: s.username, password: password || null, auto_send: s.auto_send, sign_domain: s.sign_domain, sign_credential: signCredential || null } })
      setS(r); setPassword(''); setSignCredential(''); notifyOk('Impostazioni salvate')
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function probe() {
    setTest(null)
    try { setTest(await FE('/impostazioni/prova', { body: {} })) } catch (e) { notifyError(e) }
  }
  return (
    <>
      <PageTitle title="Fatturazione elettronica" subtitle="Invio e ricezione delle fatture tramite SDI con Aruba"
        right={<Group gap="xs"><ExportXmlButton /><Badge size="lg" variant="light" color={s.environment === 'demo' ? 'orange' : 'green'}>{s.environment === 'demo' ? 'Ambiente di prova Aruba' : 'Produzione'}</Badge></Group>} />
      <Stack maw={760}>
        <Paper withBorder p="md">
          <Title order={5} mb="xs">Collegamento ad Aruba</Title>
          <SegmentedControl fullWidth value={s.mode} onChange={(v) => setS({ ...s, mode: v })} mb="sm"
            data={[{ value: 'piattaforma', label: 'Servizio incluso in BluBeauty' }, { value: 'proprio', label: 'Ho già un mio account Aruba' }]} />
          {s.mode === 'piattaforma' ? (
            <Text size="sm" c="dimmed">Le fatture passano dall'account Aruba di BluBeauty, a cui la tua azienda è collegata. {s.platform_available ? <Text span c="green" fw={600}>Servizio attivo.</Text> : <Text span c="orange" fw={600}>Il collegamento non è ancora stato attivato: contatta l'assistenza.</Text>}</Text>
          ) : (
            <Stack gap="xs">
              <TextInput label="Nome utente Aruba (Fatturazione Elettronica)" value={s.username} onChange={(e) => setS({ ...s, username: e.currentTarget.value })} />
              <PasswordInput label="Password" placeholder={s.has_password ? '•••••••• (salvata: lascia vuoto per non cambiarla)' : ''} value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
              <Text size="xs" c="dimmed">La password viene conservata cifrata e non è mai mostrata.</Text>
            </Stack>
          )}
          <Group mt="md">
            <Button variant="default" leftSection={<IconPlugConnected size={16} />} onClick={probe}>Prova il collegamento</Button>
            {test && <Text size="sm" c="green"><IconCheck size={14} /> Collegato come <b>{test.user}</b>{test.expires ? ` · servizio valido fino al ${new Date(test.expires).toLocaleDateString('it-IT')}` : ''}</Text>}
          </Group>
        </Paper>
        <Paper withBorder p="md">
          <Title order={5} mb="xs">Invio</Title>
          <Switch label="Invia a SDI in automatico ogni fattura emessa" description="Se i controlli non passano, la fattura resta emessa e trovi l'avviso nel documento" checked={s.auto_send} onChange={(e) => setS({ ...s, auto_send: e.currentTarget.checked })} />
          {s.mode === 'proprio' && (
            <Stack gap="xs" mt="md">
              <Text size="sm" fw={600}>Firma automatica Aruba (solo se l'hai acquistata, serve per le fatture alla PA)</Text>
              <Group grow>
                <TextInput label="Dominio di firma" value={s.sign_domain} onChange={(e) => setS({ ...s, sign_domain: e.currentTarget.value })} />
                <PasswordInput label="Credenziale di firma" placeholder={s.has_sign_credential ? '•••••••• (salvata)' : ''} value={signCredential} onChange={(e) => setSignCredential(e.currentTarget.value)} />
              </Group>
            </Stack>
          )}
        </Paper>
        <Paper withBorder p="md">
          <Title order={5} mb="xs">Ricezione delle fatture d'acquisto</Title>
          <Text size="sm">Per ricevere le fatture dei fornitori in BluBeauty registra questo <b>codice destinatario</b> nel sito dell'Agenzia delle Entrate (Fatture e Corrispettivi › Registrazione dell'indirizzo telematico) e comunicalo ai fornitori:</Text>
          <Code block mt="xs" fz="lg" ta="center">{s.recipient_code}</Code>
          <Text size="sm" mt="xs">Le fatture arrivano da sole in <Anchor fz="inherit" onClick={() => nav('/acquisti/ricevute-sdi')}>Acquisti › Fatture ricevute da SDI</Anchor>{s.last_in_sync ? ` (ultimo controllo ${new Date(s.last_in_sync).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })})` : ''}.</Text>
        </Paper>
        <Alert variant="light" title="Prima di iniziare">Controlla in <Anchor fz="inherit" onClick={() => nav('/impostazioni/azienda')}>Dati azienda</Anchor> partita IVA, indirizzo completo, regime fiscale e, per le società, i dati REA: finiscono in ogni fattura elettronica.</Alert>
        <Group justify="flex-end"><Button onClick={save} loading={busy}>Salva</Button></Group>
      </Stack>
    </>
  )
}
