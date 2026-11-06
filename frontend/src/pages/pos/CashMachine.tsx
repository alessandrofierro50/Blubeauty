// Cassa automatica VNE in cassa (procedura comune BluCode «cassa-automatica-vne.md», come BluOrderScan):
// finestra di attesa del pagamento, verifica degli esiti incerti e «Gestione cassa automatica».

import { Alert, Badge, Button, Checkbox, Group, Loader, Modal, NumberInput, Paper, ScrollArea, Select, SimpleGrid, Stack, Table, Text, TextInput } from '@mantine/core'
import { IconAlertTriangle, IconArrowBackUp, IconCash, IconDoorEnter, IconExternalLink, IconEraser, IconPackageExport, IconRefresh } from '@tabler/icons-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { notifyError, notifyOk } from '../../components'
import { METHODS, P, euro } from './shared'

const POLL_MS = 500
const FINAL_JOB = ['eseguito', 'errore', 'annullato']
const ALERT_BG: Record<string, string> = { vuoto: 'red.0', basso: 'yellow.0' }

/** Attesa del pagamento: da pagare, inserito, mancano/resto, avvisi; annulla (restituisci) o accetta il parziale. Si chiude all'esito. */
export function CashWait({ payment, onDone }: { payment: any; onDone: (p: any) => void }) {
  const [p, setP] = useState<any>(payment)
  const [busy, setBusy] = useState(false)
  const done = useRef(false)
  useEffect(() => {
    let alive = true
    let t: any
    const tick = async () => {
      try {
        const next = await P(`/cassa-automatica/pagamenti/${payment.id}`)
        if (!alive) return
        setP(next)
        if (next.status !== 'in_corso' && !done.current) { done.current = true; onDone(next); return }
      } catch { /* rete: si riprova */ }
      if (alive) t = setTimeout(tick, POLL_MS)
    }
    t = setTimeout(tick, POLL_MS)
    return () => { alive = false; clearTimeout(t) }
  }, [payment.id])
  const live = p.live || {}
  const amount = live.amount ?? p.amount_cents
  const inserted = Math.max(0, live.inserted || 0)
  const queued = p.job_status === 'in_coda'
  const ask = async (mode: 'restituisci' | 'parziale') => {
    setBusy(true)
    try { setP(await P(`/cassa-automatica/pagamenti/${p.id}/annulla`, { body: { mode } })) } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Modal opened onClose={() => {}} withCloseButton={false} closeOnClickOutside={false} closeOnEscape={false} title="Cassa automatica" centered size="lg">
      <Text size="sm" c="dimmed" mb="sm">{queued ? 'Invio dell\'importo alla cassa tramite BluBeauty Agent…' : 'In attesa che il cliente inserisca il denaro. Il resto esce dalla cassa.'}</Text>
      <SimpleGrid cols={3} spacing="xs" data-testid="cash-wait">
        <Paper p="sm" bg="dark.7" c="white" ta="center"><Text size="xs" tt="uppercase" opacity={0.8}>Da pagare</Text><Text fw={800} size="26px">{euro(amount)}</Text></Paper>
        <Paper p="sm" bg="green.7" c="white" ta="center"><Text size="xs" tt="uppercase" opacity={0.8}>Inserito</Text><Text fw={800} size="26px">{live.card ? 'carta' : euro(inserted)}</Text></Paper>
        <Paper p="sm" withBorder ta="center"><Text size="xs" tt="uppercase" c="dimmed">{inserted > amount ? 'Resto' : 'Mancano'}</Text>
          <Text fw={800} size="26px">{euro(inserted > amount ? (live.rest || inserted - amount) : Math.max(0, amount - inserted))}</Text></Paper>
      </SimpleGrid>
      <Group gap="xs" mt="sm">
        {queued ? <Loader size="xs" /> : <IconCash size={18} color="var(--mantine-color-green-7)" />}
        <Text size="sm">{p.cancel_request ? 'Annullamento richiesto: la cassa restituisce il denaro inserito…' : queued ? 'Il computer del negozio sta inviando il pagamento' : 'Pagamento in corso sulla cassa'}</Text>
      </Group>
      {live.warning && <Alert mt="sm" color="orange" icon={<IconAlertTriangle />}>{live.warning}</Alert>}
      <Group justify="flex-end" mt="lg">
        {inserted > 0 && <Button variant="default" disabled={busy || p.cancel_request === 1}
          onClick={() => window.confirm(`Chiudere accettando solo ${euro(Math.min(inserted, amount))} già inseriti? La differenza andrà incassata in altro modo.`) && ask('parziale')}>Accetta parziale</Button>}
        <Button color="red" variant="light" leftSection={<IconArrowBackUp size={18} />} disabled={busy || !!p.cancel_request} onClick={() => ask('restituisci')}>
          {inserted > 0 ? 'Annulla e restituisci il denaro' : 'Annulla'}</Button>
      </Group>
    </Modal>
  )
}

/** Esiti incerti o parziali: si guarda il display della cassa e si registra com'è andata (mai un nuovo incasso automatico). */
export function CashVerify({ payments, onClose, onResolved }: { payments: any[]; onClose: () => void; onResolved: (p: any) => void }) {
  const [metodo, setMetodo] = useState<Record<string, string>>({})
  const [note, setNote] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  async function resolve(p: any, esito: 'pagato' | 'non_pagato') {
    if (esito === 'non_pagato' && !window.confirm('Confermi che sul display della cassa il pagamento NON risulta incassato?')) return
    setBusy(p.id)
    try { onResolved(await P(`/cassa-automatica/pagamenti/${p.id}/risolvi`, { body: { esito, metodo: metodo[p.id] || null, note: note[p.id] || '' } })) }
    catch (e) { notifyError(e) } finally { setBusy(null) }
  }
  return (
    <Modal opened onClose={onClose} title="Cassa automatica: pagamenti da verificare" size="lg" centered>
      <Stack>
        {payments.length === 0 && <Text c="dimmed">Nessun pagamento da verificare.</Text>}
        {payments.map((p) => (
          <Paper key={p.id} withBorder p="sm" radius="md">
            <Group justify="space-between"><Text fw={700}>{euro(p.amount_cents)} con la cassa automatica</Text>
              <Text size="xs" c="dimmed">{p.created_at ? new Date(p.created_at).toLocaleString('it-IT') : ''} · {p.lines} righe</Text></Group>
            <Alert color="orange" mt="xs" icon={<IconAlertTriangle />}>{p.message}</Alert>
            {p.partial && p.kept_cents < p.amount_cents && (
              <Select mt="xs" label={`Come hai incassato i restanti ${euro(p.amount_cents - p.kept_cents)}?`} value={metodo[p.id] ?? null}
                data={METHODS.filter((m) => m.value !== 'buono_regalo').map((m) => ({ value: m.value, label: m.label }))}
                onChange={(v) => setMetodo({ ...metodo, [p.id]: v || '' })} />
            )}
            <TextInput mt="xs" placeholder="Nota (es. visto sul display)" maxLength={200} value={note[p.id] ?? ''} onChange={(e) => setNote({ ...note, [p.id]: e.currentTarget.value })} />
            <Group justify="flex-end" mt="sm">
              <Button variant="default" loading={busy === p.id} onClick={() => resolve(p, 'non_pagato')}>Non pagato</Button>
              <Button color="green" loading={busy === p.id} disabled={p.partial && p.kept_cents < p.amount_cents && !metodo[p.id]} onClick={() => resolve(p, 'pagato')}>
                Pagato: registra la vendita</Button>
            </Group>
          </Paper>
        ))}
      </Stack>
    </Modal>
  )
}

function Content({ cash }: { cash: any }) {
  if (!cash) return <Text size="sm" c="dimmed">Premi «Aggiorna» per leggere il contenuto della cassa.</Text>
  const rows = (list: any[], kind: string) => (list || []).filter((x) => x.value).map((x, i) => (
    <Table.Tr key={`${kind}-${i}`} bg={ALERT_BG[x.alert]}>
      <Table.Td>{kind}</Table.Td><Table.Td fw={700}>{euro(x.value)}</Table.Td><Table.Td ta="right">{x.qty}</Table.Td>
      <Table.Td ta="right">{euro(x.value * x.qty)}</Table.Td><Table.Td>{x.alert && x.alert !== 'ok' ? x.alert : ''}</Table.Td>
    </Table.Tr>
  ))
  const stacker = (cash.notes || []).filter((x: any) => x.stacker_cents).reduce((a: number, x: any) => a + x.stacker_cents, 0)
  return (
    <Stack gap="xs">
      <SimpleGrid cols={3} spacing="xs">
        <Paper p="xs" bg="dark.7" c="white" ta="center"><Text size="xs" tt="uppercase" opacity={0.8}>Totale disponibile</Text><Text fw={800} size="xl">{euro(cash.total_cents || 0)}</Text></Paper>
        <Paper p="xs" withBorder ta="center"><Text size="xs" tt="uppercase" c="dimmed">Banconote</Text><Text fw={700} size="lg">{euro(cash.recycler_total_cents || 0)}</Text></Paper>
        <Paper p="xs" withBorder ta="center"><Text size="xs" tt="uppercase" c="dimmed">Monete</Text><Text fw={700} size="lg">{euro(cash.hopper_total_cents || 0)}</Text></Paper>
      </SimpleGrid>
      {stacker > 0 && <Text size="xs" c="dimmed">Nel cassetto di raccolta (stacker, non usato per il resto): <b>{euro(stacker)}</b></Text>}
      {cash.problems?.length > 0 && <Alert color="red" icon={<IconAlertTriangle />}>{cash.problems.join(' · ')}</Alert>}
      <ScrollArea.Autosize mah={220}>
        <Table fz="sm"><Table.Thead><Table.Tr><Table.Th>Tipo</Table.Th><Table.Th>Taglio</Table.Th><Table.Th ta="right">Pezzi</Table.Th><Table.Th ta="right">Valore</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>{rows(cash.notes, 'Banconota')}{rows(cash.coins, 'Moneta')}</Table.Tbody></Table>
      </ScrollArea.Autosize>
      {cash.read_at && <Text size="xs" c="dimmed">Letto alle {new Date(cash.read_at).toLocaleTimeString('it-IT')}</Text>}
    </Stack>
  )
}

const RUNNING: Record<string, string> = {
  carico: 'Carico in corso: inserisci banconote e monete nella cassa', prelievo: 'Prelievo in corso: ritira il denaro dalla cassa',
  svuota: 'Svuotamento in corso: non usare la cassa finché non ha finito', stato: 'Lettura del contenuto…', apri: 'Sblocco della porta…', azzera: 'Azzeramento…',
}

/** «Gestione cassa automatica»: disponibilità per taglio, carico, prelievo, svuotamento, porta, azzeramento. canAdmin = amministrazione. */
export function CashPanel({ registerId, canAdmin, onClose }: { registerId: string; canAdmin: boolean; onClose: () => void }) {
  const [ov, setOv] = useState<any>(null)
  const [cash, setCash] = useState<any>(null)
  const [job, setJob] = useState<any>(null)
  const [acceptAll, setAcceptAll] = useState(false)
  const [amount, setAmount] = useState<string | number>('')
  const [taglio, setTaglio] = useState('all')
  const [comment, setComment] = useState('')
  const base = `/casse/${registerId}/cassa-automatica`
  const load = useCallback(() => P(base).then((o) => { setOv(o); setCash(o.cash); if (o.job) setJob(o.job) }).catch((e) => { notifyError(e); setOv({ device: null }) }), [base])
  useEffect(() => { load() }, [load])

  async function run(op: string, body: any = {}, confirm?: string) {
    if (confirm && !window.confirm(confirm)) return
    try { setJob(await P(`${base}/${op}`, { body })) } catch (e) { notifyError(e) }
  }
  useEffect(() => {
    if (!job || FINAL_JOB.includes(job.status)) return undefined
    const t = setTimeout(async () => {
      try {
        const j = await P(`/cassa-automatica/lavori/${job.id}`)
        setJob(j)
        if (FINAL_JOB.includes(j.status)) {
          const r = j.result || {}
          if (r.cash) setCash(r.cash)
          if (j.status !== 'eseguito') { if (j.status === 'errore') notifyError(new Error(j.error || 'Operazione non riuscita: controlla il display della cassa')) }
          else if (j.op === 'carico') notifyOk(`Carico concluso: inseriti ${euro(r.amount || 0)}`)
          else if (j.op === 'prelievo') notifyOk(r.status === 'completed' ? `Prelevati ${euro(r.withdrawed || 0)}` : 'Prelievo interrotto')
          else if (j.op === 'svuota') notifyOk(`Svuotamento concluso: tolti ${euro(r.removed || 0)}`)
          else if (j.op === 'apri') notifyOk('Porta sbloccata: apri con la chiave')
          else if (j.op === 'azzera') notifyOk('Contatori del cassetto azzerati')
        }
      } catch { /* rete: si riprova */ }
    }, 800)
    return () => clearTimeout(t)
  }, [job])
  const stop = async () => { try { setJob(await P(`/cassa-automatica/lavori/${job.id}/stop`, { method: 'POST' })) } catch (e) { notifyError(e) } }
  const busy = !!job && !FINAL_JOB.includes(job.status)
  const cents = Math.round(Number(String(amount).replace(',', '.')) * 100) || 0
  const tagli = [{ value: 'all', label: 'Banconote e monete' }, { value: 'monete', label: 'Solo monete' },
    ...((cash?.notes || []).filter((x: any) => x.value).map((x: any) => ({ value: `banconota_${x.value}`, label: `Banconote da ${euro(x.value)}` }))),
    ...((cash?.coins || []).filter((x: any) => x.value >= 50).map((x: any) => ({ value: `monete_${x.value}`, label: `Monete da ${euro(x.value)}` })))]
  const dev = ov?.device

  return (
    <Modal opened onClose={() => !busy && onClose()} title="Gestione cassa automatica" size="xl" centered>
      {!ov && <Loader />}
      {ov && !dev && <Text c="dimmed">Nessuna cassa automatica collegata a questa cassa: aggiungila in «Computer e periferiche» e scegline una nelle impostazioni della cassa.</Text>}
      {dev && (
        <Stack>
          <Group gap="xs">
            <Text fw={700}>{dev.name}</Text><Text size="sm" c="dimmed">{dev.address}</Text>
            <Badge color={dev.agent_online ? 'green' : 'red'} variant="light">{dev.agent_name}: {dev.agent_online ? 'collegato' : 'non collegato'}</Badge>
            <Group gap="xs" ml="auto">
              {dev.webtool_url && <Button size="xs" variant="light" component="a" href={dev.webtool_url} target="_blank" rel="noreferrer" leftSection={<IconExternalLink size={14} />}>WebTool</Button>}
              <Button size="xs" variant="default" disabled={busy} leftSection={<IconRefresh size={14} />} onClick={() => run('stato')}>Aggiorna</Button>
            </Group>
          </Group>
          <Content cash={cash} />
          {busy && (
            <Paper withBorder p="sm" bg="blue.0">
              <Group gap="xs"><Loader size="xs" /><Text fw={600}>{job.status === 'in_coda' ? 'Invio alla cassa tramite BluBeauty Agent…' : RUNNING[job.op]}</Text></Group>
              {job.op === 'carico' && <Text fw={800} size="32px" mt="xs">{euro(job.progress?.amount || 0)}</Text>}
              {['carico', 'prelievo'].includes(job.op) && <Button mt="xs" onClick={stop} disabled={!!job.cancel_request}>{job.op === 'carico' ? 'Fine carico' : 'Fine prelievo'}</Button>}
            </Paper>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Paper withBorder p="sm">
              <Text fw={600} mb="xs">Carico di monete e banconote</Text>
              <Checkbox label="Accetta tutti i tagli (per il cambio)" checked={acceptAll} onChange={(e) => setAcceptAll(e.currentTarget.checked)} />
              <Button fullWidth mt="sm" disabled={busy} onClick={() => run('carico', { accept_all: acceptAll })}>Inizia carico</Button>
            </Paper>
            {canAdmin && (
              <Paper withBorder p="sm">
                <Text fw={600} mb="xs">Prelievo</Text>
                <SimpleGrid cols={2} spacing="xs">
                  <NumberInput label="Importo (€)" decimalSeparator="," min={0} value={amount} onChange={setAmount} />
                  <Select label="In" data={tagli} value={taglio} onChange={(v) => setTaglio(v || 'all')} allowDeselect={false} />
                </SimpleGrid>
                <TextInput mt="xs" placeholder="Motivo (facoltativo)" maxLength={80} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
                <Button fullWidth mt="sm" variant="light" disabled={busy || !cents} leftSection={<IconPackageExport size={16} />}
                  onClick={() => run('prelievo', { amount_cents: cents, taglio, comment }, `Prelevare ${euro(cents)} dalla cassa automatica?`)}>Preleva</Button>
              </Paper>
            )}
          </SimpleGrid>
          {canAdmin && (
            <Paper withBorder p="sm">
              <Text fw={600} mb="xs">Svuotamento</Text>
              <SimpleGrid cols={2}>
                {([['monete', 'Monete'], ['banconote', 'Banconote']] as const).map(([w, l]) => (
                  <Stack key={w} gap={6}>
                    <Text size="sm" fw={600}>{l}</Text>
                    <Button variant="default" disabled={busy} onClick={() => run('svuota', { what: w, full: false }, `Svuotare le ${l.toLowerCase()} lasciando il fondo cassa?`)}>Fino al fondo cassa</Button>
                    <Button variant="default" color="red" disabled={busy}
                      onClick={() => run('svuota', { what: w, full: true }, `Svuotare TUTTE le ${l.toLowerCase()}? La cassa non potrà dare il resto finché non la ricarichi.`)}>Svuota tutto</Button>
                  </Stack>
                ))}
              </SimpleGrid>
            </Paper>
          )}
          {canAdmin && (
            <Paper withBorder p="sm">
              <Text fw={600} mb="xs">Cassetto e porta</Text>
              <Group gap="xs">
                <Button variant="default" disabled={busy} leftSection={<IconDoorEnter size={16} />} onClick={() => run('apri', { wait: '0' }, 'Sbloccare la porta della cassa automatica?')}>Apri porta</Button>
                {([[0, 'Ho svuotato la cassa monete'], [1, 'Ho svuotato lo stacker banconote'], [2, 'Ho svuotato entrambi']] as const).map(([v, l]) => (
                  <Button key={v} variant="default" disabled={busy} leftSection={<IconEraser size={16} />}
                    onClick={() => run('azzera', { peripheral: v }, `${l}: azzerare il contatore nella cassa? Fallo solo dopo averli svuotati davvero.`)}>{l}</Button>
                ))}
              </Group>
              <Text size="xs" c="dimmed" mt="xs">Lo stacker e la cassa monete raccolgono il denaro che non serve per il resto: dopo averli svuotati a mano azzera il loro contatore.</Text>
            </Paper>
          )}
          {!canAdmin && <Text size="xs" c="dimmed">Prelievo, svuotamento e apertura della porta sono riservati all'amministrazione.</Text>}
        </Stack>
      )}
    </Modal>
  )
}
