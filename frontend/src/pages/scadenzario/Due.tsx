import {
  ActionIcon, Anchor, Badge, Button, Checkbox, Divider, Drawer, Group, Modal, NumberInput, Pagination, Paper, SegmentedControl, Select,
  SimpleGrid, Stack, Switch, Table, Text, TextInput, Textarea, Tooltip,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconAlertTriangle, IconDownload, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { fmtDate, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, Stat, notifyError, notifyOk } from '../../components'
import { num } from '../anagrafiche/shared'
import { CustomerPicker } from '../vendite/shared'
import { KIND_LABEL, METHODS, SC, download, methodOptions, useAccounts } from './shared'

const STATI = [{ value: 'aperte', label: 'Aperte' }, { value: 'scadute', label: 'Scadute' }, { value: 'insolute', label: 'Insolute' }, { value: 'pagate', label: 'Pagate' }, { value: 'tutte', label: 'Tutte' }]

export default function Due() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [dir, setDir] = useState(params.get('direzione') ?? 'tutte')
  const [stato, setStato] = useState(params.get('stato') ?? 'aperte')
  const [party, setParty] = useState<string | null>(params.get('party'))
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [method, setMethod] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [dq] = useDebouncedValue(q, 250)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)
  const [sel, setSel] = useState<string[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [bulk, setBulk] = useState(false)
  const [manual, setManual] = useState(false)
  const [reload, setReload] = useState(0)
  const accounts = useAccounts(reload)

  const query = () => {
    const p = new URLSearchParams({ stato })
    if (dir !== 'tutte') p.set('direzione', dir)
    if (party) p.set('party_id', party)
    if (from) p.set('date_from', from)
    if (to) p.set('date_to', to)
    if (method) p.set('method', method)
    if (dq) p.set('q', dq)
    return p
  }
  const load = () => { const p = query(); p.set('page', String(page)); SC('/scadenze?' + p).then(setData).catch(notifyError) }
  useEffect(load, [dir, stato, party, from, to, method, dq, page, reload])
  useEffect(() => { setPage(1); setSel([]) }, [dir, stato, party, from, to, method, dq])
  const refresh = () => { setReload((r) => r + 1); setSel([]) }

  async function quickPay(r: any) {
    try {
      await SC(`/scadenze/${r.id}/pagamenti`, { body: { pay_date: isoDate(new Date()) } })
      notifyOk(r.direction === 'attiva' ? 'Incasso registrato' : 'Pagamento registrato')
      refresh()
    } catch (e) { notifyError(e) }
  }

  const t = data?.totals
  const selRows = data?.rows.filter((r: any) => sel.includes(r.id)) ?? []
  const selTotal = selRows.reduce((s: number, r: any) => s + Number(r.residual) * (r.direction === 'attiva' ? 1 : -1), 0)
  return (
    <>
      <PageTitle title="Scadenzario" subtitle="Tutto quello che devi incassare e pagare, in un'unica schermata"
        right={<Group>
          <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => download('/scadenze/excel?' + query(), `scadenzario-${isoDate(new Date())}.xlsx`)}>Excel</Button>
          <Button leftSection={<IconPlus size={16} />} onClick={() => setManual(true)}>Nuova scadenza</Button>
        </Group>} />
      {t && (
        <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
          <Stat label="Da incassare" value={fmtEuro(t.receivable)} hint={Number(t.receivable_overdue) ? `di cui scaduto ${fmtEuro(t.receivable_overdue)}` : 'nulla di scaduto'} />
          <Stat label="Da pagare" value={fmtEuro(t.payable)} hint={Number(t.payable_overdue) ? `di cui scaduto ${fmtEuro(t.payable_overdue)}` : 'nulla di scaduto'} />
          <Stat label="Saldo crediti − debiti" value={<Text span c={Number(t.balance) < 0 ? 'red' : 'green'} fw={700} fz="inherit">{fmtEuro(t.balance)}</Text>} />
          <Paper withBorder p="md" radius="md" style={{ cursor: 'pointer' }} onClick={() => nav('/scadenzario/liquidita')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Liquidità oggi</Text>
            <Text fw={700} fz="xl">{accounts ? fmtEuro(accounts.filter((a) => a.active).reduce((s, a) => s + Number(a.balance), 0)) : '…'}</Text>
            <Text size="xs" c="blue">Fotografia e previsione →</Text>
          </Paper>
        </SimpleGrid>
      )}
      <Paper withBorder p="sm" mb="md">
        <Group wrap="wrap" align="flex-end" gap="sm">
          <SegmentedControl value={dir} onChange={setDir} data={[{ value: 'tutte', label: 'Tutte' }, { value: 'attiva', label: 'Da incassare' }, { value: 'passiva', label: 'Da pagare' }]} />
          <Select w={130} data={STATI} value={stato} onChange={(v) => setStato(v ?? 'aperte')} allowDeselect={false} />
          <CustomerPicker tipo="tutti" value={party} onChange={setParty} w={220} clearable placeholder="Cliente o fornitore" />
          <TextInput type="date" w={150} value={from} onChange={(e) => setFrom(e.currentTarget.value)} aria-label="Scadenza dal" />
          <TextInput type="date" w={150} value={to} onChange={(e) => setTo(e.currentTarget.value)} aria-label="Scadenza al" />
          <Select w={150} placeholder="Modalità" data={methodOptions} value={method} onChange={setMethod} clearable />
          <TextInput placeholder="Cerca" leftSection={<IconSearch size={14} />} value={q} onChange={(e) => setQ(e.currentTarget.value)} style={{ flex: 1, minWidth: 140 }} />
        </Group>
      </Paper>
      {sel.length > 0 && (
        <Paper withBorder p="sm" mb="md" bg="var(--mantine-color-blue-light)">
          <Group justify="space-between">
            <Text size="sm">{sel.length} scadenze selezionate · saldo {fmtEuro(selTotal)}</Text>
            <Group><Button size="xs" variant="default" onClick={() => setSel([])}>Deseleziona</Button><Button size="xs" onClick={() => setBulk(true)}>Registra incasso / pagamento</Button></Group>
          </Group>
        </Paper>
      )}
      {!data ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={900}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead><Table.Tr>
                <Table.Th w={36}><Checkbox checked={!!data.rows.length && data.rows.filter((r: any) => r.status !== 'pagata').every((r: any) => sel.includes(r.id))} onChange={(e) => setSel(e.currentTarget.checked ? data.rows.filter((r: any) => r.status !== 'pagata').map((r: any) => r.id) : [])} /></Table.Th>
                <Table.Th>Scadenza</Table.Th><Table.Th>Soggetto</Table.Th><Table.Th>Descrizione</Table.Th><Table.Th>Modalità</Table.Th><Table.Th ta="right">Importo</Table.Th><Table.Th ta="right">Residuo</Table.Th><Table.Th>Stato</Table.Th><Table.Th w={100} />
              </Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.rows.map((r: any) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => setOpen(r.id)}>
                    <Table.Td onClick={(e) => e.stopPropagation()}>{r.status !== 'pagata' && <Checkbox checked={sel.includes(r.id)} onChange={(e) => setSel(e.currentTarget.checked ? [...sel, r.id] : sel.filter((x) => x !== r.id))} />}</Table.Td>
                    <Table.Td>
                      <Text size="sm" fw={600} c={r.overdue ? 'red' : undefined}>{fmtDate(r.due_date)}</Text>
                      {r.overdue && <Text size="10px" c="red">da {r.days_late} gg</Text>}
                    </Table.Td>
                    <Table.Td><Group gap={6} wrap="nowrap"><Badge size="xs" variant="light" color={r.direction === 'attiva' ? 'teal' : 'orange'}>{r.direction === 'attiva' ? 'Incasso' : 'Pagamento'}</Badge><Text size="sm" truncate maw={200}>{r.party_name ?? '—'}</Text></Group></Table.Td>
                    <Table.Td fz="sm"><Text size="sm" truncate maw={320}>{r.description.split(' – ').filter((x: string) => x !== r.party_name).join(' – ')}</Text></Table.Td>
                    <Table.Td fz="sm">{r.method_label ?? '—'}</Table.Td>
                    <Table.Td ta="right" fz="sm">{fmtEuro(r.amount)}</Table.Td>
                    <Table.Td ta="right" fw={700} c={Number(r.residual) < 0 ? 'red' : undefined}>{r.status === 'pagata' ? '—' : fmtEuro(r.residual)}</Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <Badge variant="dot" color={r.status === 'pagata' ? 'green' : r.status === 'parziale' ? 'yellow' : r.overdue ? 'red' : 'blue'}>{r.status === 'pagata' ? (r.direction === 'attiva' ? 'incassata' : 'pagata') : r.status}</Badge>
                        {r.unpaid && <Badge size="xs" color="red">insoluta</Badge>}
                        {r.reminder_level > 0 && <Tooltip label={`Sollecito di ${r.reminder_level}° livello inviato`}><Badge size="xs" variant="outline" color="orange">{r.reminder_level}°</Badge></Tooltip>}
                      </Group>
                    </Table.Td>
                    <Table.Td onClick={(e) => e.stopPropagation()}>{r.status !== 'pagata' && <Button size="compact-xs" variant="light" onClick={() => quickPay(r)}>{r.direction === 'attiva' ? 'Incassa' : 'Paga'}</Button>}</Table.Td>
                  </Table.Tr>
                ))}
                {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={9}><Text ta="center" c="dimmed" py="lg">Nessuna scadenza con questi filtri</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {data.total > 0 && <Group justify="space-between" p="sm" style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}><Text size="sm" c="dimmed">{data.total} scadenze</Text><Text size="sm">Residuo in pagina (incassi − pagamenti) <b>{fmtEuro(data.filtered_residual)}</b></Text></Group>}
        </Paper>
      )}
      {data && data.total > data.page_size && <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / data.page_size)} value={page} onChange={setPage} /></Group>}

      <InstallmentDrawer id={open} accounts={accounts ?? []} onClose={() => setOpen(null)} onChanged={refresh} />
      {bulk && <BulkModal rows={selRows} accounts={accounts ?? []} onClose={() => setBulk(false)} onDone={() => { setBulk(false); refresh() }} />}
      {manual && <ManualModal accounts={accounts ?? []} onClose={() => setManual(false)} onDone={() => { setManual(false); refresh() }} />}
    </>
  )
}

function accountOptions(accounts: any[]) {
  return accounts.filter((a) => a.active).map((a) => ({ value: a.id, label: `${a.name} (${KIND_LABEL[a.kind]})` }))
}

function BulkModal({ rows, accounts, onClose, onDone }: { rows: any[]; accounts: any[]; onClose: () => void; onDone: () => void }) {
  const [when, setWhen] = useState(isoDate(new Date()))
  const [acc, setAcc] = useState<string | null>(accounts.find((a) => a.is_default)?.id ?? accounts[0]?.id ?? null)
  const inc = rows.filter((r) => r.direction === 'attiva').reduce((s, r) => s + Number(r.residual), 0)
  const out = rows.filter((r) => r.direction === 'passiva').reduce((s, r) => s + Number(r.residual), 0)
  async function go() {
    try {
      const r = await SC('/incasso-multiplo', { body: { ids: rows.map((x) => x.id), pay_date: when, account_id: acc } })
      notifyOk(`${r.paid} scadenze chiuse`)
      onDone()
    } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title="Chiudi le scadenze selezionate">
      <Stack>
        <Text size="sm">Viene registrato il residuo di ogni scadenza: {inc ? <>incassi <b>{fmtEuro(inc)}</b></> : null}{inc && out ? ' · ' : ''}{out ? <>pagamenti <b>{fmtEuro(out)}</b></> : null}.</Text>
        <TextInput type="date" label="Data" value={when} onChange={(e) => setWhen(e.currentTarget.value)} />
        <Select label="Conto" data={accountOptions(accounts)} value={acc} onChange={setAcc} />
        <Group justify="flex-end"><Button onClick={go}>Registra</Button></Group>
      </Stack>
    </Modal>
  )
}

function ManualModal({ accounts, onClose, onDone }: { accounts: any[]; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState<any>({ direction: 'passiva', party_id: null, description: '', due_date: isoDate(new Date()), amount: '', method: 'MP05', account_id: null, notes: '', repeat: false, repeat_months: 1, repeat_count: 12 })
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }))
  async function save() {
    try {
      const r = await SC('/scadenze', { body: { direction: f.direction, party_id: f.party_id, description: f.description, due_date: f.due_date, amount: String(f.amount),
        method: f.method, account_id: f.account_id, notes: f.notes || null, repeat_months: f.repeat ? Number(f.repeat_months) : 0, repeat_count: f.repeat ? Number(f.repeat_count) : 1 } })
      notifyOk(r.created > 1 ? `${r.created} scadenze create` : 'Scadenza creata')
      onDone()
    } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title="Nuova scadenza" size="lg">
      <Stack>
        <SegmentedControl value={f.direction} onChange={(v) => set('direction', v)} data={[{ value: 'passiva', label: 'Da pagare' }, { value: 'attiva', label: 'Da incassare' }]} />
        <TextInput label="Descrizione" placeholder={f.direction === 'passiva' ? 'es. Affitto, F24, rata finanziamento, stipendi' : 'es. Rimborso, contributo'} value={f.description} onChange={(e) => set('description', e.currentTarget.value)} required />
        <SimpleGrid cols={2}>
          <TextInput type="date" label="Scadenza" value={f.due_date} onChange={(e) => set('due_date', e.currentTarget.value)} />
          <NumberInput label="Importo" value={num(f.amount)} onChange={(v) => set('amount', v)} min={0} decimalScale={2} prefix="€ " />
          <Select label="Modalità" data={methodOptions} value={f.method} onChange={(v) => set('method', v)} clearable />
          <Select label="Conto" data={accountOptions(accounts)} value={f.account_id} onChange={(v) => set('account_id', v)} clearable />
        </SimpleGrid>
        <CustomerPicker tipo="tutti" label="Soggetto (facoltativo)" value={f.party_id} onChange={(v) => set('party_id', v)} clearable />
        <Switch label="Si ripete" checked={f.repeat} onChange={(e) => set('repeat', e.currentTarget.checked)} />
        {f.repeat && (
          <SimpleGrid cols={2}>
            <Select label="Ogni" data={[{ value: '1', label: 'mese' }, { value: '2', label: '2 mesi' }, { value: '3', label: 'trimestre' }, { value: '6', label: 'semestre' }, { value: '12', label: 'anno' }]} value={String(f.repeat_months)} onChange={(v) => set('repeat_months', v)} />
            <NumberInput label="Quante volte" value={f.repeat_count} onChange={(v) => set('repeat_count', v)} min={2} max={120} />
          </SimpleGrid>
        )}
        <Textarea label="Note" autosize minRows={1} value={f.notes} onChange={(e) => set('notes', e.currentTarget.value)} />
        <Group justify="flex-end"><Button onClick={save} disabled={!f.description || !Number(f.amount)}>Crea</Button></Group>
      </Stack>
    </Modal>
  )
}

function InstallmentDrawer({ id, accounts, onClose, onChanged }: { id: string | null; accounts: any[]; onClose: () => void; onChanged: () => void }) {
  const nav = useNavigate()
  const [i, setI] = useState<any>(null)
  const [pay, setPay] = useState<any>(null)
  const [edit, setEdit] = useState<any>(null)
  useEffect(() => {
    setI(null)
    if (id) SC(`/scadenze/${id}`).then((r) => { setI(r); setEdit({ due_date: r.due_date, method: r.method, account_id: r.account_id, notes: r.notes ?? '' }) }).catch(notifyError)
  }, [id])
  useEffect(() => { if (i) setPay({ pay_date: isoDate(new Date()), amount: Number(i.residual), account_id: i.account_id ?? accounts.find((a) => a.is_default)?.id ?? null, notes: '' }) }, [i?.id, i?.residual])
  const done = (r: any, msg: string) => { setI(r); onChanged(); notifyOk(msg) }
  async function addPayment() {
    try { done(await SC(`/scadenze/${i.id}/pagamenti`, { body: { ...pay, amount: String(pay.amount), notes: pay.notes || null } }), 'Registrato') } catch (e) { notifyError(e) }
  }
  async function delPayment(pid: string) {
    if (!confirm('Eliminare questo movimento?')) return
    try { done(await SC(`/pagamenti/${pid}`, { method: 'DELETE' }), 'Movimento eliminato') } catch (e) { notifyError(e) }
  }
  async function saveEdit() {
    try { done(await SC(`/scadenze/${i.id}`, { method: 'PUT', body: edit }), 'Scadenza aggiornata') } catch (e) { notifyError(e) }
  }
  async function toggleUnpaid() {
    if (!i.unpaid && i.payments.length && !confirm('Segnare come insoluta? L\'incasso registrato verrà stornato.')) return
    try { done(await SC(`/scadenze/${i.id}/insoluta`, { body: { unpaid: !i.unpaid } }), i.unpaid ? 'Non più insoluta' : 'Segnata come insoluta') } catch (e) { notifyError(e) }
  }
  async function remove() {
    if (!confirm('Eliminare la scadenza?')) return
    try { await SC(`/scadenze/${i.id}`, { method: 'DELETE' }); onChanged(); onClose() } catch (e) { notifyError(e) }
  }
  const attiva = i?.direction === 'attiva'
  return (
    <Drawer opened={!!id} onClose={onClose} position="right" size="md" title={<Text fw={700}>{i ? (attiva ? 'Da incassare' : 'Da pagare') : ''}</Text>}>
      {!i ? <Loading /> : (
        <Stack>
          <div>
            <Text fw={600}>{i.party_name ?? 'Senza soggetto'}</Text>
            <Text size="sm" c="dimmed">{i.description}</Text>
            {i.document && <Anchor size="sm" onClick={() => nav(`/${i.document.direction === 'vendita' ? 'vendite' : 'acquisti'}/${i.document_id}`)}>Apri il documento</Anchor>}
          </div>
          <SimpleGrid cols={3}>
            <Paper withBorder p="xs"><Text size="10px" c="dimmed">Importo</Text><Text fw={700}>{fmtEuro(i.amount)}</Text></Paper>
            <Paper withBorder p="xs"><Text size="10px" c="dimmed">{attiva ? 'Incassato' : 'Pagato'}</Text><Text fw={700}>{fmtEuro(i.paid_amount)}</Text></Paper>
            <Paper withBorder p="xs"><Text size="10px" c="dimmed">Residuo</Text><Text fw={700} c={Number(i.residual) && i.overdue ? 'red' : undefined}>{fmtEuro(i.residual)}</Text></Paper>
          </SimpleGrid>
          {i.unpaid && <Badge color="red" leftSection={<IconAlertTriangle size={12} />}>Insoluta</Badge>}
          {i.overdue && <Text size="sm" c="red">Scaduta da {i.days_late} giorni{i.reminder_level ? ` · sollecito di ${i.reminder_level}° livello inviato` : ''}</Text>}

          {i.payments.length > 0 && (
            <div>
              <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={4}>{attiva ? 'Incassi' : 'Pagamenti'}</Text>
              {i.payments.map((p: any) => (
                <Group key={p.id} justify="space-between" py={4} style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  <div><Text size="sm">{fmtDate(p.pay_date)} · {accounts.find((a) => a.id === p.account_id)?.name ?? '—'}</Text>{p.notes && <Text size="xs" c="dimmed">{p.notes}</Text>}</div>
                  <Group gap={4}><Text size="sm" fw={600}>{fmtEuro(p.amount)}</Text><ActionIcon variant="subtle" color="red" size="sm" onClick={() => delPayment(p.id)}><IconTrash size={14} /></ActionIcon></Group>
                </Group>
              ))}
            </div>
          )}

          {i.status !== 'pagata' && pay && (
            <Paper withBorder p="sm">
              <Text size="sm" fw={600} mb="xs">Registra {attiva ? 'incasso' : 'pagamento'}</Text>
              <SimpleGrid cols={2} spacing="xs">
                <TextInput type="date" size="xs" label="Data" value={pay.pay_date} onChange={(e) => setPay({ ...pay, pay_date: e.currentTarget.value })} />
                <NumberInput size="xs" label="Importo" value={num(pay.amount)} onChange={(v) => setPay({ ...pay, amount: v })} decimalScale={2} prefix="€ " />
                <Select size="xs" label="Conto" data={accountOptions(accounts)} value={pay.account_id} onChange={(v) => setPay({ ...pay, account_id: v })} />
                <TextInput size="xs" label="Note" placeholder="es. bonifico CRO…" value={pay.notes} onChange={(e) => setPay({ ...pay, notes: e.currentTarget.value })} />
              </SimpleGrid>
              <Group justify="flex-end" mt="xs"><Button size="xs" onClick={addPayment}>Registra</Button></Group>
            </Paper>
          )}

          <Divider label="Dettagli" labelPosition="left" />
          {edit && (
            <SimpleGrid cols={2} spacing="xs">
              <TextInput type="date" size="xs" label="Scadenza" value={edit.due_date} onChange={(e) => setEdit({ ...edit, due_date: e.currentTarget.value })} />
              <Select size="xs" label="Modalità" data={methodOptions} value={edit.method} onChange={(v) => setEdit({ ...edit, method: v })} clearable />
              <Select size="xs" label="Banca d'appoggio" data={accountOptions(accounts)} value={edit.account_id} onChange={(v) => setEdit({ ...edit, account_id: v })} clearable />
              <TextInput size="xs" label="Note" value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.currentTarget.value })} />
            </SimpleGrid>
          )}
          <Group justify="space-between">
            <Group gap="xs">
              {attiva && <Button size="xs" variant="light" color="red" onClick={toggleUnpaid}>{i.unpaid ? 'Non è più insoluta' : 'Segna insoluta'}</Button>}
              {i.manual && <Button size="xs" variant="subtle" color="red" onClick={remove}>Elimina</Button>}
            </Group>
            <Button size="xs" variant="default" onClick={saveEdit}>Salva dettagli</Button>
          </Group>
          {i.method && <Text size="xs" c="dimmed">Modalità prevista: {METHODS[i.method] ?? i.method}</Text>}
        </Stack>
      )}
    </Drawer>
  )
}
