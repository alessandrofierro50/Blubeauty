import { Alert, Badge, Button, Checkbox, Group, Modal, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Table, Tabs, Text, TextInput, Textarea, Title } from '@mantine/core'
import { IconBrandWhatsapp, IconEye, IconMail } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { SC } from './shared'

const LEVEL = { 1: 'Promemoria cortese', 2: 'Secondo sollecito', 3: 'Diffida' } as Record<number, string>
const LEVEL_COLOR = { 1: 'blue', 2: 'orange', 3: 'red' } as Record<number, string>

export default function Reminders() {
  const [tab, setTab] = useState<string | null>('proposta')
  return (
    <>
      <PageTitle title="Solleciti di pagamento" subtitle="Clienti in ritardo: promemoria cortese, secondo sollecito, diffida" />
      <Tabs value={tab} onChange={setTab} mb="md">
        <Tabs.List><Tabs.Tab value="proposta">Da sollecitare</Tabs.Tab><Tabs.Tab value="storico">Inviati</Tabs.Tab><Tabs.Tab value="impostazioni">Impostazioni e modelli</Tabs.Tab></Tabs.List>
      </Tabs>
      {tab === 'proposta' && <Proposal />}
      {tab === 'storico' && <History />}
      {tab === 'impostazioni' && <SettingsTab />}
    </>
  )
}

function Proposal() {
  const nav = useNavigate()
  const [rows, setRows] = useState<any[] | null>(null)
  const [sel, setSel] = useState<string[]>([])
  const [levels, setLevels] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const load = () => SC('/solleciti/proposta').then((r) => {
    setRows(r)
    setSel(r.filter((x: any) => x.due_now && x.email).map((x: any) => x.party_id))
    setLevels(Object.fromEntries(r.map((x: any) => [x.party_id, String(x.suggested_level)])))
  }).catch(notifyError)
  useEffect(() => { load() }, [])

  async function sendEmail(ids: string[]) {
    setBusy(true)
    try {
      let ok = 0
      for (const id of ids) {  // un livello per cliente
        const r = await SC('/solleciti/invia', { body: { party_ids: [id], level: Number(levels[id]) } })
        r.results.filter((x: any) => x.status !== 'inviato').forEach((x: any) => notifyError(new Error(`${x.name}: ${x.error}`)))
        ok += r.sent
      }
      if (ok) notifyOk(`${ok} solleciti inviati`)
      load()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function sendWhatsapp(id: string) {
    try {
      const r = await SC('/solleciti/whatsapp', { body: { party_id: id, level: Number(levels[id]) } })
      window.open(r.url, '_blank')
      if (!r.phone) notifyError(new Error('Il cliente non ha un numero di cellulare: scegli il contatto in WhatsApp'))
      load()
    } catch (e) { notifyError(e) }
  }
  async function showPreview(id: string) {
    try { setPreview(await SC('/solleciti/anteprima', { body: { party_id: id, level: Number(levels[id]) } })) } catch (e) { notifyError(e) }
  }

  if (!rows) return <Loading />
  if (!rows.length) return <Paper withBorder p="xl"><Text ta="center" c="dimmed">Nessun cliente in ritardo con i pagamenti. 🎉</Text></Paper>
  const total = rows.reduce((s, r) => s + Number(r.total), 0)
  return (
    <>
      <Group justify="space-between" mb="sm">
        <Text size="sm">{rows.length} clienti in ritardo · scaduto totale <b>{fmtEuro(total)}</b></Text>
        <Button leftSection={<IconMail size={16} />} disabled={!sel.length} loading={busy} onClick={() => sendEmail(sel)}>Invia {sel.length} solleciti via email</Button>
      </Group>
      <Paper withBorder>
        <Table.ScrollContainer minWidth={900}>
          <Table verticalSpacing="sm">
            <Table.Thead><Table.Tr><Table.Th w={36} /><Table.Th>Cliente</Table.Th><Table.Th ta="right">Scaduto</Table.Th><Table.Th>Ritardo</Table.Th><Table.Th>Ultimo sollecito</Table.Th><Table.Th w={190}>Da inviare</Table.Th><Table.Th w={150} /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.party_id}>
                  <Table.Td><Checkbox checked={sel.includes(r.party_id)} disabled={!r.email} onChange={(e) => setSel(e.currentTarget.checked ? [...sel, r.party_id] : sel.filter((x) => x !== r.party_id))} /></Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={600} style={{ cursor: 'pointer' }} onClick={() => nav(`/scadenzario?direzione=attiva&stato=scadute&party=${r.party_id}`)}>{r.name}</Text>
                    <Text size="xs" c={r.email ? 'dimmed' : 'red'}>{r.email ?? 'nessuna email'}{r.phone ? ` · ${r.phone}` : ''}</Text>
                  </Table.Td>
                  <Table.Td ta="right"><Text fw={700}>{fmtEuro(r.total)}</Text><Text size="xs" c="dimmed">{r.count} {r.count === 1 ? 'scadenza' : 'scadenze'}{r.unpaid ? ` · ${r.unpaid} insolute` : ''}</Text></Table.Td>
                  <Table.Td><Text size="sm" c="red" fw={600}>{r.days_late} giorni</Text><Text size="xs" c="dimmed">dal {fmtDate(r.oldest_due)}</Text></Table.Td>
                  <Table.Td fz="sm">{r.last_reminder ? <><Badge size="sm" variant="light" color={LEVEL_COLOR[r.last_reminder.level]}>{r.last_reminder.level}° livello</Badge><Text size="xs" c="dimmed">{new Date(r.last_reminder.at).toLocaleDateString('it-IT')} · {r.last_reminder.channel}</Text></> : <Text size="xs" c="dimmed">mai</Text>}</Table.Td>
                  <Table.Td>
                    <Select size="xs" data={[1, 2, 3].map((l) => ({ value: String(l), label: `${l}° · ${LEVEL[l]}` }))} value={levels[r.party_id]} onChange={(v) => setLevels({ ...levels, [r.party_id]: v ?? '1' })} allowDeselect={false} />
                    {!r.due_now && <Text size="10px" c="dimmed">non ancora in programma</Text>}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      <Button size="compact-xs" variant="subtle" leftSection={<IconEye size={12} />} onClick={() => showPreview(r.party_id)}>Vedi</Button>
                      <Button size="compact-xs" variant="light" color="green" leftSection={<IconBrandWhatsapp size={12} />} onClick={() => sendWhatsapp(r.party_id)}>WhatsApp</Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
      <Modal opened={!!preview} onClose={() => setPreview(null)} size="lg" title={preview ? `Anteprima · ${LEVEL[preview.level]}` : ''}>
        {preview && (
          <Stack>
            <Text size="sm"><b>Oggetto:</b> {preview.subject}</Text>
            <Paper withBorder p="md"><div dangerouslySetInnerHTML={{ __html: preview.html }} /></Paper>
          </Stack>
        )}
      </Modal>
    </>
  )
}

function History() {
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { SC('/solleciti/storico').then(setRows).catch(notifyError) }, [])
  if (!rows) return <Loading />
  return (
    <Paper withBorder>
      <Table verticalSpacing="sm">
        <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Cliente</Table.Th><Table.Th>Livello</Table.Th><Table.Th>Canale</Table.Th><Table.Th ta="right">Importo</Table.Th><Table.Th>Esito</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.id}>
              <Table.Td fz="sm">{new Date(r.sent_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
              <Table.Td fz="sm" fw={500}>{r.name}</Table.Td>
              <Table.Td><Badge size="sm" variant="light" color={LEVEL_COLOR[r.level]}>{r.level_label}</Badge></Table.Td>
              <Table.Td fz="sm">{r.channel === 'whatsapp' ? 'WhatsApp' : 'Email'}{r.automatic && <Badge ml={4} size="xs" variant="outline">automatico</Badge>}<Text size="xs" c="dimmed">{r.recipients.join(', ')}</Text></Table.Td>
              <Table.Td ta="right">{fmtEuro(r.total)}</Table.Td>
              <Table.Td>{r.status === 'inviato' ? <Badge color="green" variant="dot">inviato</Badge> : <><Badge color="red" variant="dot">errore</Badge><Text size="xs" c="red">{r.error}</Text></>}</Table.Td>
            </Table.Tr>
          ))}
          {rows.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="lg">Nessun sollecito inviato</Text></Table.Td></Table.Tr>}
        </Table.Tbody>
      </Table>
    </Paper>
  )
}

function SettingsTab() {
  const [s, setS] = useState<any>(null)
  useEffect(() => { SC('/solleciti/impostazioni').then(setS).catch(notifyError) }, [])
  if (!s) return <Loading />
  const setTpl = (lvl: string, k: string, v: string) => setS({ ...s, templates: { ...s.templates, [lvl]: { ...s.templates[lvl], [k]: v } } })
  async function save() {
    try { setS(await SC('/solleciti/impostazioni', { method: 'PUT', body: { ...s, days: s.days.map(Number), block_overdue_days: s.block_overdue_days ? Number(s.block_overdue_days) : null } })); notifyOk('Impostazioni salvate') } catch (e) { notifyError(e) }
  }
  return (
    <Stack>
      <Paper withBorder p="md">
        <Title order={5} mb="sm">Quando sollecitare</Title>
        <SimpleGrid cols={{ base: 1, sm: 3 }} mb="sm">
          {[0, 1, 2].map((n) => <NumberInput key={n} label={`${LEVEL[n + 1]} dopo (giorni di ritardo)`} value={s.days[n]} min={1} onChange={(v) => setS({ ...s, days: s.days.map((d: number, j: number) => (j === n ? v : d)) })} />)}
        </SimpleGrid>
        <Switch label="Invia i solleciti in automatico ogni mattina (solo ai clienti con email, senza mai ripetere lo stesso livello)" checked={s.auto} onChange={(e) => setS({ ...s, auto: e.currentTarget.checked })} />
      </Paper>
      <Paper withBorder p="md">
        <Title order={5} mb="xs">Clienti insolventi</Title>
        <Group align="flex-end">
          <NumberInput w={260} label="Blocca o avvisa in vendita dopo giorni di ritardo" placeholder="disattivato" value={s.block_overdue_days ?? ''} min={1} onChange={(v) => setS({ ...s, block_overdue_days: v === '' ? null : v })} />
          <Text size="xs" c="dimmed" maw={480}>Si applica il criterio del fido scelto nell'anagrafica del cliente (blocca o avvisa). Le scadenze segnate «insolute» lo attivano sempre.</Text>
        </Group>
      </Paper>
      <Paper withBorder p="md">
        <Title order={5} mb="xs">Modelli dei messaggi</Title>
        <Alert variant="light" mb="sm" py="xs">Puoi usare: <code>{'{cliente}'}</code> <code>{'{elenco}'}</code> (tabella dei documenti) <code>{'{totale}'}</code> <code>{'{giorni}'}</code> <code>{'{iban}'}</code> <code>{'{azienda}'}</code>; per WhatsApp anche <code>{'{documenti}'}</code>.</Alert>
        <Tabs defaultValue="1">
          <Tabs.List>{[1, 2, 3].map((l) => <Tabs.Tab key={l} value={String(l)}>{LEVEL[l]}</Tabs.Tab>)}<Tabs.Tab value="wa">WhatsApp</Tabs.Tab></Tabs.List>
          {['1', '2', '3'].map((l) => (
            <Tabs.Panel key={l} value={l} pt="sm">
              <TextInput label="Oggetto" value={s.templates[l].subject} onChange={(e) => setTpl(l, 'subject', e.currentTarget.value)} mb="xs" />
              <Textarea label="Testo (HTML semplice)" autosize minRows={6} value={s.templates[l].body} onChange={(e) => setTpl(l, 'body', e.currentTarget.value)} styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }} />
            </Tabs.Panel>
          ))}
          <Tabs.Panel value="wa" pt="sm"><Textarea autosize minRows={3} value={s.whatsapp} onChange={(e) => setS({ ...s, whatsapp: e.currentTarget.value })} /></Tabs.Panel>
        </Tabs>
      </Paper>
      <Group justify="flex-end"><Button onClick={save}>Salva impostazioni</Button></Group>
    </Stack>
  )
}
