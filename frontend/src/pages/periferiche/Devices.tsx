// Computer del negozio (BluBeauty Agent) e periferiche: abbinamento, configurazione, prova, coda dei lavori.

import {
  ActionIcon, Alert, Badge, Button, Code, CopyButton, Group, JsonInput, Modal, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Table, Tabs,
  Text, TextInput, Tooltip,
} from '@mantine/core'
import { IconCopy, IconDeviceDesktop, IconDownload, IconPencil, IconPlayerPlay, IconPlus, IconRefresh, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { tokens } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { PER } from './LabelView'

const KIND_COLOR: Record<string, string> = { rt: 'grape', stampante: 'blue', etichette: 'teal', bilancia: 'orange' }
const STATUS_COLOR: Record<string, string> = { in_coda: 'yellow', inviato: 'blue', eseguito: 'green', errore: 'red', annullato: 'gray' }
const KIND_JOB: Record<string, string> = { 'rt.receipt': 'Documento commerciale', 'rt.refund': 'Reso / annullo', 'rt.z': 'Chiusura giornaliera Z',
  'rt.x': 'Lettura X', 'print.text': 'Ricevuta', 'print.zpl': 'Etichette', 'scale.read': 'Lettura bilancia', status: 'Prova' }

export function downloadAgent() {
  fetch('/api/periferiche/agent/scarica', { headers: { Authorization: `Bearer ${tokens.get('user')}` } })
    .then((r) => { if (!r.ok) throw new Error('Scaricamento non riuscito'); return r.blob() })
    .then((b) => { const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'BluBeautyAgent.zip'; a.click() })
    .catch(notifyError)
}

export default function Devices() {
  const { tab } = useParams()
  const nav = useNavigate()
  return (
    <>
      <PageTitle title="Computer e periferiche" subtitle="Registratore telematico, stampanti di ricevute ed etichette, bilance collegati tramite BluBeauty Agent"
        right={<Button variant="light" leftSection={<IconDownload size={16} />} onClick={downloadAgent}>Scarica BluBeauty Agent</Button>} />
      <Tabs value={tab ?? 'dispositivi'} onChange={(v) => nav(v === 'dispositivi' ? '/periferiche' : `/periferiche/${v}`)} mb="md">
        <Tabs.List><Tabs.Tab value="dispositivi">Computer e dispositivi</Tabs.Tab><Tabs.Tab value="lavori">Coda dei lavori</Tabs.Tab></Tabs.List>
      </Tabs>
      {tab === 'lavori' ? <Jobs /> : <AgentsAndDevices />}
    </>
  )
}

function AgentsAndDevices() {
  const [agents, setAgents] = useState<any[] | null>(null)
  const [devices, setDevices] = useState<any[]>([])
  const [drivers, setDrivers] = useState<any>(null)
  const [pairing, setPairing] = useState<any>(null)
  const [newName, setNewName] = useState<string | null>(null)
  const [edit, setEdit] = useState<any>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const load = () => Promise.all([PER('/computer'), PER('/dispositivi')]).then(([a, d]) => { setAgents(a); setDevices(d) }).catch(notifyError)
  useEffect(() => { load(); PER('/driver').then(setDrivers).catch(() => {}); const t = setInterval(load, 15000); return () => clearInterval(t) }, [])

  async function createAgent() {
    try { const a = await PER('/computer', { body: { name: newName || 'Computer cassa' } }); setNewName(null); setPairing(a); load() } catch (e) { notifyError(e) }
  }
  async function test(d: any) {
    setTesting(d.id)
    try {
      const r = await PER(`/dispositivi/${d.id}/prova`, { method: 'POST' })
      if (r.ok) notifyOk(d.kind === 'bilancia' ? `Peso letto: ${Number(r.result.weight).toLocaleString('it-IT')} kg` : d.kind === 'rt' ? `Il registratore risponde${r.result?.model ? ` (${r.result.model})` : ''}${r.result?.vat_table?.length ? ` · aliquote IVA: ${r.result.vat_table.map((x: any) => `${x.index}=${x.rate}%`).join(', ')}` : ''}${r.result?.problems?.length ? ` · attenzione: ${r.result.problems.join(', ')}` : ''}` : 'Stampa di prova inviata')
      else notifyError(new Error(r.error || 'Prova non riuscita'))
    } catch (e) { notifyError(e) } finally { setTesting(null) }
  }
  if (!agents || !drivers) return <Loading />
  return (
    <Stack>
      {agents.length === 0 && (
        <Alert color="blue" title="Come si collegano le periferiche">
          1. Scarica BluBeauty Agent e installalo sul computer della cassa (serve Python, le istruzioni sono nel file LEGGIMI). 2. Crea qui il computer:
          ti diamo un codice di abbinamento. 3. Aggiungi le periferiche (registratore, stampanti, bilancia) e collegale alla cassa in «Casse e reparti».
        </Alert>
      )}
      <Group justify="flex-end"><Button leftSection={<IconPlus size={16} />} onClick={() => setNewName('')}>Nuovo computer</Button></Group>
      {agents.map((a) => (
        <Paper withBorder key={a.id}>
          <Group justify="space-between" p="sm" style={{ borderBottom: '1px solid var(--mantine-color-gray-3)' }}>
            <Group gap="sm">
              <IconDeviceDesktop size={22} />
              <div>
                <Group gap={6}><Text fw={600}>{a.name}</Text>
                  {!a.paired ? <Badge color="yellow">da abbinare</Badge> : a.online ? <Badge color="green">collegato</Badge> : <Badge color="red">non raggiungibile</Badge>}
                </Group>
                <Text size="xs" c="dimmed">{a.paired ? `${a.hostname ?? ''} · ${a.platform ?? ''} · agent ${a.version ?? ''}${a.last_seen_at ? ` · visto ${new Date(a.last_seen_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}` : ''}` : 'Installa l\'agent e usa il codice di abbinamento'}</Text>
              </div>
            </Group>
            <Group gap={4}>
              <Button size="xs" variant="subtle" onClick={() => PER(`/computer/${a.id}/codice`, { method: 'POST' }).then(setPairing).catch(notifyError)}>{a.paired ? 'Nuovo abbinamento' : 'Codice di abbinamento'}</Button>
              <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setEdit({ agent_id: a.id, name: '', driver: null, address: '', options: {}, active: true })}>Dispositivo</Button>
              <Tooltip label="Elimina il computer (l'agent smette di funzionare)"><ActionIcon variant="subtle" color="red" onClick={() => {
                if (window.confirm(`Eliminare «${a.name}» e i suoi dispositivi?`)) PER(`/computer/${a.id}`, { method: 'DELETE' }).then(load).catch(notifyError)
              }}><IconTrash size={16} /></ActionIcon></Tooltip>
            </Group>
          </Group>
          <Table>
            <Table.Tbody>
              {devices.filter((d) => d.agent_id === a.id).map((d) => (
                <Table.Tr key={d.id} opacity={d.active ? 1 : 0.5}>
                  <Table.Td w={190}><Badge variant="light" color={KIND_COLOR[d.kind]}>{d.kind_label}</Badge></Table.Td>
                  <Table.Td fw={500}>{d.name}</Table.Td>
                  <Table.Td><Text size="sm">{d.driver_label}</Text><Text size="xs" c="dimmed">{d.address}</Text></Table.Td>
                  <Table.Td ta="right" w={150}>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <Button size="xs" variant="subtle" leftSection={<IconPlayerPlay size={14} />} loading={testing === d.id} onClick={() => test(d)}>Prova</Button>
                      <ActionIcon variant="subtle" onClick={() => setEdit(d)}><IconPencil size={16} /></ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
              {!devices.some((d) => d.agent_id === a.id) && <Table.Tr><Table.Td><Text size="sm" c="dimmed" p="xs">Nessun dispositivo su questo computer</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Paper>
      ))}
      <Modal opened={newName !== null} onClose={() => setNewName(null)} title="Nuovo computer">
        <TextInput label="Nome" placeholder="es. PC cassa 1" value={newName ?? ''} onChange={(e) => setNewName(e.currentTarget.value)} data-autofocus />
        <Group justify="flex-end" mt="md"><Button onClick={createAgent}>Crea e genera il codice</Button></Group>
      </Modal>
      <Modal opened={!!pairing?.pairing_code} onClose={() => setPairing(null)} title={`Abbina «${pairing?.name}»`} size="lg">
        <Text size="sm">Sul computer del negozio, nella cartella di BluBeauty Agent, esegui:</Text>
        <Group mt="sm" gap="xs" wrap="nowrap">
          <Code block style={{ flex: 1 }}>{`python blubeauty_agent.py abbina ${window.location.origin} ${pairing?.pairing_code}`}</Code>
          <CopyButton value={`python blubeauty_agent.py abbina ${window.location.origin} ${pairing?.pairing_code}`}>
            {({ copied, copy }) => <ActionIcon variant="light" onClick={copy} color={copied ? 'green' : undefined}><IconCopy size={16} /></ActionIcon>}
          </CopyButton>
        </Group>
        <Text size="sm" mt="md">Poi avvialo con <Code>python blubeauty_agent.py avvia</Code> (su Windows: doppio clic su avvia-agent.bat).</Text>
        <Text size="xs" c="dimmed" mt="sm">Il codice vale 24 ore e una sola volta. Un nuovo abbinamento sostituisce quello precedente.</Text>
      </Modal>
      {edit && <DeviceEditor d={edit} agents={agents} drivers={drivers} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load() }} />}
    </Stack>
  )
}

function DeviceEditor({ d, agents, drivers, onClose, onSaved }: { d: any; agents: any[]; drivers: any; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState<any>({ ...d, options: { ...(d.options || {}) } })
  const [advanced, setAdvanced] = useState(JSON.stringify(d.options?.payments ?? {}, null, 1))
  const spec = v.driver ? drivers.drivers[v.driver] : null
  const set = (k: string, x: any) => setV({ ...v, [k]: x })
  const opt = (k: string, x: any) => setV({ ...v, options: { ...v.options, [k]: x } })
  const driverData = Object.entries(drivers.kinds).map(([kind, label]: any) => ({
    group: label, items: Object.entries(drivers.drivers).filter(([, s]: any) => s.kind === kind).map(([value, s]: any) => ({ value, label: s.label })),
  }))
  async function save() {
    try {
      let payments = {}
      try { payments = advanced.trim() ? JSON.parse(advanced) : {} } catch { throw new Error('Pagamenti: formato non valido') }
      const options = { ...v.options, ...(spec?.kind === 'rt' ? { payments } : {}) }
      const body = { agent_id: v.agent_id, name: v.name, driver: v.driver, address: v.address || null, options, active: v.active }
      await (v.id ? PER(`/dispositivi/${v.id}`, { method: 'PUT', body }) : PER('/dispositivi', { body }))
      notifyOk('Dispositivo salvato')
      onSaved()
    } catch (e) { notifyError(e) }
  }
  async function remove() {
    if (!window.confirm('Eliminare il dispositivo?')) return
    try { await PER(`/dispositivi/${v.id}`, { method: 'DELETE' }); onSaved() } catch (e) { notifyError(e) }
  }
  const deps = v.options.departments ?? spec?.options.departments ?? {}
  return (
    <Modal opened onClose={onClose} title={v.id ? v.name : 'Nuovo dispositivo'} size="lg">
      <Stack>
        <SimpleGrid cols={2}>
          <Select label="Tipo e collegamento" data={driverData} value={v.driver} searchable allowDeselect={false}
            onChange={(x) => setV({ ...v, driver: x, options: { ...(drivers.drivers[x!]?.options ?? {}), ...(v.driver === x ? v.options : {}) },
              name: v.name || drivers.drivers[x!]?.label.split(' (')[0] })} />
          <Select label="Computer" data={agents.map((a) => ({ value: a.id, label: a.name }))} value={v.agent_id} onChange={(x) => set('agent_id', x)} allowDeselect={false} />
        </SimpleGrid>
        <TextInput label="Nome" value={v.name} onChange={(e) => set('name', e.currentTarget.value)} placeholder="es. Registratore cassa 1" />
        {spec && spec.address && <TextInput label={spec.address.split(',')[0]} description={spec.address} value={v.address ?? ''} onChange={(e) => set('address', e.currentTarget.value)} />}
        {spec?.kind === 'rt' && (
          <>
            {!v.driver.startsWith('simulatore') && <TextInput label="Matricola del registratore" description="Serve nei resi e negli annulli (è sulla targhetta, es. 99MEY012345)"
              value={v.options.serial ?? ''} onChange={(e) => opt('serial', e.currentTarget.value.toUpperCase())} />}
            <div>
              <Text size="sm" fw={500}>Reparti del registratore per aliquota IVA</Text>
              <Text size="xs" c="dimmed" mb={4}>Devono corrispondere alla programmazione del registratore; i reparti della cassa con un numero proprio hanno la precedenza.</Text>
              <Group gap="xs">
                {Object.entries(deps).map(([rate, n]: any) => (
                  <NumberInput key={rate} w={110} size="xs" label={rate === '0' ? 'Esente (0%)' : `IVA ${rate}%`} min={1} max={99} value={n}
                    onChange={(x) => opt('departments', { ...deps, [rate]: Number(x) || 1 })} />
                ))}
              </Group>
            </div>
            {v.driver === 'custom_rt' && (
              <div>
                <Text size="sm" fw={500}>Indici IVA del registratore (facoltativi)</Text>
                <Text size="xs" c="dimmed" mb={4}>Vuoti: BluBeauty li legge da solo dal registratore (pulsante «Prova» per vederli). Scrivili solo se il tecnico lo indica.</Text>
                <Group gap="xs">
                  {['22', '10', '5', '4'].map((rate) => (
                    <NumberInput key={rate} w={110} size="xs" label={`IVA ${rate}%`} min={1} max={99} value={v.options.vat_ids?.[rate] ?? ''}
                      onChange={(x) => opt('vat_ids', { ...(v.options.vat_ids ?? {}), [rate]: Number(x) || undefined })} />
                  ))}
                  <Select w={210} size="xs" label="Carta del registratore" allowDeselect={false} value={String(v.options.width ?? 32)}
                    data={[{ value: '32', label: '57 mm (32 caratteri)' }, { value: '42', label: '80 mm (42 caratteri)' }]}
                    onChange={(x) => opt('width', Number(x) || 32)} />
                </Group>
              </div>
            )}
            {v.driver === 'custom_rt' && (
              <SimpleGrid cols={2}>
                <TextInput label="Utente (se richiesto)" value={v.options.username ?? ''} onChange={(e) => opt('username', e.currentTarget.value)} />
                <TextInput label="Password" type="password" value={v.options.password ?? ''} onChange={(e) => opt('password', e.currentTarget.value)} />
              </SimpleGrid>
            )}
            {!v.driver.startsWith('simulatore') && <JsonInput label="Pagamenti (avanzato)" description={v.driver === 'epson_rt' ? 'es. {"buono": "6-1"}: tipo-indice del registratore per metodo' : 'es. {"buono": 3}: numero del pagamento sul registratore'}
              value={advanced} onChange={setAdvanced} autosize minRows={2} formatOnBlur />}
            {v.driver === 'simulatore_rt' && <Switch label="Simula un errore (carta finita)" checked={!!v.options.fail} onChange={(e) => opt('fail', e.currentTarget.checked ? 'Carta finita' : '')} />}
          </>
        )}
        {spec?.kind === 'stampante' && (
          <SimpleGrid cols={2}>
            <NumberInput label="Caratteri per riga" description="48 per carta da 80 mm, 32 per 58 mm" value={v.options.columns ?? 48} onChange={(x) => opt('columns', Number(x) || 48)} />
            <Select label="Tabella dei caratteri" description="Se gli accenti escono strani (es. «piΩ»), prova PC850"
              data={Object.entries(drivers.charsets ?? {}).map(([value, label]: any) => ({ value, label }))}
              value={v.options.charset ?? 'pc858'} onChange={(x) => opt('charset', x || 'pc858')} allowDeselect={false} />
          </SimpleGrid>
        )}
        {v.driver === 'bilancia_seriale' && (
          <SimpleGrid cols={2}>
            <Select label="Velocità (baud)" data={['2400', '4800', '9600', '19200']} value={String(v.options.baud ?? 9600)} onChange={(x) => opt('baud', Number(x))} />
            <TextInput label="Richiesta del peso" description="Es. W\r; vuoto se la bilancia trasmette da sola" value={v.options.request ?? ''} onChange={(e) => opt('request', e.currentTarget.value)} />
            <TextInput label="Formato del peso (espressione regolare)" value={v.options.regex ?? ''} onChange={(e) => opt('regex', e.currentTarget.value)} />
            <Switch mt="lg" label="La bilancia comunica in grammi" checked={!!v.options.grams} onChange={(e) => opt('grams', e.currentTarget.checked)} />
          </SimpleGrid>
        )}
        {v.driver === 'simulatore_bilancia' && <TextInput label="Peso fisso (kg)" description="Vuoto: un peso a caso" value={v.options.weight ?? ''} onChange={(e) => opt('weight', e.currentTarget.value)} />}
        <Switch label="Attivo" checked={v.active} onChange={(e) => set('active', e.currentTarget.checked)} />
        <Group justify="space-between">
          {v.id ? <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} onClick={remove}>Elimina</Button> : <span />}
          <Group><Button variant="default" onClick={onClose}>Annulla</Button><Button disabled={!v.driver || !v.name} onClick={save}>Salva</Button></Group>
        </Group>
      </Stack>
    </Modal>
  )
}

function Jobs() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [st, setSt] = useState<string | null>(null)
  const load = () => PER(`/lavori?limit=200${st ? `&stato=${st}` : ''}`).then(setRows).catch(notifyError)
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [st])
  async function retry(j: any) {
    try { await PER(`/lavori/${j.id}/riprova`, { body: { force: false } }); load() } catch (e: any) {
      if (e.status === 409 && j.status === 'inviato' && window.confirm(`${e.message}\n\nRipetere comunque?`)) {
        await PER(`/lavori/${j.id}/riprova`, { body: { force: true } }).catch(notifyError); load()
      } else notifyError(e)
    }
  }
  if (!rows) return <Loading />
  return (
    <Paper withBorder>
      <Group p="sm" justify="space-between">
        <Select placeholder="Tutti gli stati" clearable value={st} onChange={setSt} data={[{ value: 'in_coda', label: 'In coda' }, { value: 'inviato', label: 'In stampa' },
          { value: 'eseguito', label: 'Eseguiti' }, { value: 'errore', label: 'Con errore' }]} />
        <ActionIcon variant="subtle" onClick={load}><IconRefresh size={18} /></ActionIcon>
      </Group>
      <Table fz="sm">
        <Table.Thead><Table.Tr><Table.Th>Quando</Table.Th><Table.Th>Lavoro</Table.Th><Table.Th>Dispositivo</Table.Th><Table.Th>Stato</Table.Th><Table.Th>Esito</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((j) => (
            <Table.Tr key={j.id}>
              <Table.Td>{new Date(j.created_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'medium' })}</Table.Td>
              <Table.Td>{KIND_JOB[j.kind] ?? j.kind}</Table.Td>
              <Table.Td>{j.device_name}</Table.Td>
              <Table.Td><Badge color={STATUS_COLOR[j.status]} variant="light">{j.status_label}</Badge></Table.Td>
              <Table.Td>{j.error ? <Text size="xs" c="red">{j.error}</Text> : j.result?.number ? <Text size="xs">n. {j.result.z}-{j.result.number}{j.result.simulated ? ' (simulato)' : ''}</Text>
                : j.result?.z ? <Text size="xs">Z {j.result.z}</Text> : j.result?.weight ? <Text size="xs">{j.result.weight} kg</Text> : null}</Table.Td>
              <Table.Td ta="right">
                {(j.status === 'errore' || j.status === 'inviato') && <Button size="xs" variant="subtle" onClick={() => retry(j)}>Riprova</Button>}
                {j.status === 'in_coda' && <Button size="xs" variant="subtle" color="gray" onClick={() => PER(`/lavori/${j.id}/annulla`, { method: 'POST' }).then(load).catch(notifyError)}>Annulla</Button>}
              </Table.Td>
            </Table.Tr>
          ))}
          {!rows.length && <Table.Tr><Table.Td colSpan={6}><Text c="dimmed" ta="center" py="lg">Nessun lavoro</Text></Table.Td></Table.Tr>}
        </Table.Tbody>
      </Table>
    </Paper>
  )
}

