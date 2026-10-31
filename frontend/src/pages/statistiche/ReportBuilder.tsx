// Report builder (pacchetto Pro): scegli cosa analizzare, righe e colonne, misure, filtri, periodo e grafico;
// salva il report, scaricalo in Excel o fattelo mandare via email ogni giorno, settimana o mese.

import {
  ActionIcon, Alert, Badge, Button, Divider, Drawer, Group, Loader, Modal, MultiSelect, NavLink, Paper, ScrollArea, SegmentedControl, Select,
  SimpleGrid, Stack, Switch, Table, TagsInput, Text, TextInput, Title, Tooltip,
} from '@mantine/core'
import {
  IconChartBar, IconChartDonut, IconChartLine, IconCopy, IconDeviceFloppy, IconDownload, IconFilter, IconMail, IconNumbers, IconPlus, IconPrinter,
  IconTable, IconTrash, IconX,
} from '@tabler/icons-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi, fmtDate, tokens } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import ReportView from './ReportView'

const BI = (p: string, opts?: { method?: string; body?: unknown }) => appApi('/api/bi' + p, opts)
const WEEKDAYS = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
const EMPTY = { name: '', cube: 'vendite', shared: true, schedule: {} as any,
  config: { rows: ['mese'], columns: null as string | null, measures: ['fatturato'], filters: {} as Record<string, any[]>, period: { kind: 'ultimi_12_mesi', from: null as string | null, to: null as string | null },
    compare: null as string | null, chart: 'barre', sort: null, desc: true, limit: 200 } }

export async function download(url: string, body: unknown | undefined, name: string) {
  const r = await fetch(url, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tokens.get('user')}` },
    body: body ? JSON.stringify(body) : undefined })
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(typeof e.detail === 'string' ? e.detail : 'Esportazione non riuscita') }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await r.blob())
  a.download = name
  a.click()
}

export function useCubes() {
  const [cubes, setCubes] = useState<any[] | null>(null)
  const [periods, setPeriods] = useState<any[]>([])
  useEffect(() => { BI('/cubi').then(setCubes).catch(notifyError); BI('/periodi').then(setPeriods).catch(() => {}) }, [])
  return { cubes, periods }
}

export function resolvePeriod(periods: any[], p: { kind: string; from: string | null; to: string | null }) {
  if (p.kind === 'personalizzato') return [p.from, p.to]
  const x = periods.find((y) => y.value === p.kind)
  return x ? [x.from, x.to] : [null, null]
}

export default function ReportBuilder() {
  const { id } = useParams()
  const nav = useNavigate()
  const { cubes, periods } = useCubes()
  const [reports, setReports] = useState<any[]>([])
  const [rep, setRep] = useState<any>(EMPTY)
  const [model, setModel] = useState<any>(null)
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saveOpen, setSaveOpen] = useState(false)
  const [schedOpen, setSchedOpen] = useState(false)
  const [drill, setDrill] = useState<any>(null)
  const seq = useRef(0)
  const loadList = () => BI('/report').then(setReports).catch(() => {})
  useEffect(() => { loadList() }, [])
  useEffect(() => {
    if (!id || id === 'nuovo') { setRep(EMPTY); return }
    BI(`/report/${id}`).then(setRep).catch(notifyError)
  }, [id])
  useEffect(() => { setModel(null); BI(`/${rep.cube}/modello`).then(setModel).catch(notifyError) }, [rep.cube])

  const cfg = rep.config
  const setCfg = (patch: any) => setRep((r: any) => ({ ...r, config: { ...r.config, ...patch } }))
  const [from, to] = resolvePeriod(periods, cfg.period)
  const queryBody = useMemo(() => ({
    measures: cfg.measures, dimensions: [...cfg.rows, ...(cfg.columns ? [cfg.columns] : [])], date_from: from, date_to: to,
    filters: cfg.filters, compare: cfg.compare, sort: cfg.sort, desc: cfg.desc, limit: cfg.limit,
  }), [cfg, from, to])

  useEffect(() => {
    if (!model || !from || !to || !cfg.measures.length) return
    const n = ++seq.current
    setLoading(true)
    const t = setTimeout(() => {
      BI(`/${rep.cube}/query`, { body: queryBody }).then((r) => { if (n === seq.current) { setRes(r); setErr(null) } })
        .catch((e) => { if (n === seq.current) { setErr(e.message); setRes(null) } }).finally(() => { if (n === seq.current) setLoading(false) })
    }, 250)
    return () => clearTimeout(t)
  }, [queryBody, model, rep.cube])

  if (!cubes || !model) return <Loading />
  const dimOpts = (exclude: string[] = []) => {
    const groups: Record<string, any[]> = {}
    for (const d of model.dimensions) if (d.available && !exclude.includes(d.name)) (groups[d.group] ||= []).push({ value: d.name, label: d.label })
    return Object.entries(groups).map(([group, items]) => ({ group, items }))
  }
  const measOpts = model.measures.filter((m: any) => m.available).map((m: any) => ({ value: m.name, label: m.label }))
  const D = Object.fromEntries(model.dimensions.map((d: any) => [d.name, d]))

  async function save(asNew = false) {
    try {
      const body = { name: rep.name, cube: rep.cube, config: cfg, shared: rep.shared, schedule: rep.schedule || {} }
      const r = rep.id && !asNew ? await BI(`/report/${rep.id}`, { method: 'PUT', body }) : await BI('/report', { body })
      setRep(r); setSaveOpen(false); setSchedOpen(false); loadList(); notifyOk('Report salvato')
      if (!rep.id || asNew) nav(`/report/${r.id}`, { replace: true })
    } catch (e) { notifyError(e) }
  }
  async function remove() {
    if (!rep.id || !window.confirm(`Eliminare il report «${rep.name}»?`)) return
    try { await BI(`/report/${rep.id}`, { method: 'DELETE' }); loadList(); nav('/report') } catch (e) { notifyError(e) }
  }
  function drillRow(row: any) {
    const filters = { ...cfg.filters }
    for (const [d, v] of Object.entries<any>(row.dims)) filters[d] = [v.key]
    setDrill({ title: Object.values<any>(row.dims).map((v) => v.label).join(' · '), loading: true, rows: [] })
    BI(`/${rep.cube}/dettaglio`, { body: { ...queryBody, filters } }).then((rows) => setDrill((x: any) => ({ ...x, loading: false, rows }))).catch(notifyError)
  }

  return (
    <>
      <PageTitle title={rep.id ? rep.name : 'Nuovo report'} subtitle="Scegli cosa analizzare, come raggrupparlo e come vederlo; salvalo e fattelo arrivare via email"
        right={<Group gap="xs">
          <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => (rep.id
            ? download(`/api/bi/report/${rep.id}/excel`, undefined, `${rep.name || 'report'}.xlsx`)
            : download(`/api/bi/${rep.cube}/excel`, { ...queryBody, limit: 5000 }, `analisi-${rep.cube}.xlsx`)).catch(notifyError)}>Excel</Button>
          <Button variant="default" leftSection={<IconPrinter size={16} />} onClick={() => window.print()}>PDF</Button>
          {rep.id && <Button variant="default" leftSection={<IconMail size={16} />} onClick={() => setSchedOpen(true)}>{rep.schedule?.frequency ? 'Invio programmato' : 'Invia per email'}</Button>}
          <Button leftSection={<IconDeviceFloppy size={16} />} onClick={() => (rep.id ? save() : setSaveOpen(true))}>Salva</Button>
        </Group>} />
      <Group align="flex-start" wrap="nowrap" gap="md">
        <Paper withBorder w={230} p={6} className="no-print">
          <Button fullWidth variant="light" leftSection={<IconPlus size={16} />} mb={6} onClick={() => nav('/report/nuovo')}>Nuovo report</Button>
          <ScrollArea.Autosize mah="70vh">
            {reports.map((r) => (
              <NavLink key={r.id} active={r.id === rep.id} label={r.name} description={`${r.cube_label}${r.schedule_label ? ' · ' + r.schedule_label : ''}`}
                onClick={() => nav(`/report/${r.id}`)} leftSection={r.schedule_label ? <IconMail size={14} /> : null} />
            ))}
            {!reports.length && <Text size="xs" c="dimmed" p="xs">I report salvati compaiono qui.</Text>}
          </ScrollArea.Autosize>
        </Paper>
        <Stack style={{ flex: 1, minWidth: 0 }} gap="sm">
          <Paper withBorder p="sm" className="no-print">
            <SimpleGrid cols={{ base: 1, md: 2, xl: 4 }} spacing="sm">
              <Select label="Cosa analizzare" value={rep.cube} allowDeselect={false}
                data={cubes.map((c) => ({ value: c.name, label: c.label + (c.available ? '' : ' (Pro)'), disabled: !c.available }))}
                onChange={(v) => { const m0 = v === rep.cube ? cfg.measures : []; setRep({ ...rep, cube: v, config: { ...cfg, rows: ['mese'], columns: null, measures: m0, filters: {} } }) }} />
              <Select label="Periodo" value={cfg.period.kind} allowDeselect={false} description={from && to ? `${fmtDate(from)} – ${fmtDate(to)}` : undefined}
                data={[...periods.map((p) => ({ value: p.value, label: p.label })), { value: 'personalizzato', label: 'Date a scelta…' }]}
                onChange={(v) => setCfg({ period: { ...cfg.period, kind: v } })} />
              <Select label="Confronto" clearable placeholder="Nessuno" value={cfg.compare} onChange={(v) => setCfg({ compare: v })}
                data={[{ value: 'anno_precedente', label: 'Stesso periodo anno precedente' }, { value: 'periodo_precedente', label: 'Periodo precedente' }]} />
              <div>
                <Text size="sm" fw={500} mb={4}>Vista</Text>
                <SegmentedControl fullWidth value={cfg.chart} onChange={(v) => setCfg({ chart: v })} data={[
                  { value: 'tabella', label: <Tooltip label="Tabella"><IconTable size={16} /></Tooltip> },
                  { value: 'barre', label: <Tooltip label="Barre"><IconChartBar size={16} /></Tooltip> },
                  { value: 'linee', label: <Tooltip label="Linee"><IconChartLine size={16} /></Tooltip> },
                  { value: 'torta', label: <Tooltip label="Torta"><IconChartDonut size={16} /></Tooltip> },
                  { value: 'kpi', label: <Tooltip label="Solo numeri"><IconNumbers size={16} /></Tooltip> }]} />
              </div>
              {cfg.period.kind === 'personalizzato' && (
                <Group grow>
                  <TextInput type="date" label="Dal" value={cfg.period.from ?? ''} onChange={(e) => setCfg({ period: { ...cfg.period, from: e.currentTarget.value } })} />
                  <TextInput type="date" label="Al" value={cfg.period.to ?? ''} onChange={(e) => setCfg({ period: { ...cfg.period, to: e.currentTarget.value } })} />
                </Group>
              )}
            </SimpleGrid>
            <SimpleGrid cols={{ base: 1, md: 3 }} spacing="sm" mt="sm">
              <MultiSelect label="Righe" description="Fino a 3, dalla più generale" data={dimOpts(cfg.columns ? [cfg.columns] : [])} value={cfg.rows} maxValues={3}
                onChange={(v) => setCfg({ rows: v })} searchable clearable />
              <Select label="Colonne" description="Facoltativo: tabella pivot (es. mesi in colonna)" data={dimOpts(cfg.rows)} value={cfg.columns} clearable searchable
                onChange={(v) => setCfg({ columns: v })} />
              <MultiSelect label="Misure" description={model.measures.some((m: any) => !m.available) ? 'Margini e altre misure nel pacchetto Pro' : ' '}
                data={measOpts} value={cfg.measures} onChange={(v) => setCfg({ measures: v })} maxValues={8} searchable />
            </SimpleGrid>
            <Filters cube={rep.cube} model={model} filters={cfg.filters} onChange={(f) => setCfg({ filters: f })} />
          </Paper>
          <Paper withBorder p="md" pos="relative" mih={300}>
            <Group justify="space-between" mb="sm">
              <div>
                <Title order={4}>{rep.name || model.label}</Title>
                <Text size="xs" c="dimmed">{model.label} · {model.date_label}: {from && to ? `${fmtDate(from)} – ${fmtDate(to)}` : '…'}
                  {Object.keys(cfg.filters).length ? ` · filtri: ${Object.keys(cfg.filters).map((k) => D[k]?.label).join(', ')}` : ''}</Text>
              </div>
              {loading && <Loader size="sm" />}
            </Group>
            {err ? <Alert color="red">{err}</Alert> : res ? <ReportView model={model} res={res} cfg={cfg} onDrill={drillRow} />
              : !cfg.measures.length ? <Text c="dimmed">Scegli almeno una misura</Text> : null}
          </Paper>
        </Stack>
      </Group>

      <Modal opened={saveOpen} onClose={() => setSaveOpen(false)} title="Salva il report">
        <TextInput label="Nome" value={rep.name} onChange={(e) => setRep({ ...rep, name: e.currentTarget.value })} data-autofocus placeholder="es. Fatturato per categoria e mese" />
        <Switch mt="md" label="Visibile a tutti gli utenti dell'azienda" checked={rep.shared} onChange={(e) => setRep({ ...rep, shared: e.currentTarget.checked })} />
        <Group justify="flex-end" mt="lg"><Button disabled={!rep.name.trim()} onClick={() => save()}>Salva</Button></Group>
      </Modal>
      {rep.id && (
        <Group mt="sm" className="no-print">
          <Button size="xs" variant="subtle" leftSection={<IconCopy size={14} />} onClick={() => { setRep({ ...rep, id: undefined, name: `${rep.name} (copia)` }); setSaveOpen(true) }}>Duplica</Button>
          {rep.mine && <Button size="xs" variant="subtle" color="red" leftSection={<IconTrash size={14} />} onClick={remove}>Elimina</Button>}
        </Group>
      )}
      {schedOpen && <ScheduleModal rep={rep} setRep={setRep} onClose={() => setSchedOpen(false)} onSave={() => save()} />}
      <Drawer opened={!!drill} onClose={() => setDrill(null)} position="right" size="xl" title={drill?.title}>
        {drill?.loading ? <Loader /> : (
          <Table fz="sm" striped>
            <Table.Tbody>
              {(drill?.rows ?? []).map((r: any, i: number) => (
                <Table.Tr key={i}>
                  <Table.Td>{fmtDate(r.date)}</Table.Td><Table.Td>{r.label}</Table.Td><Table.Td>{r.party}</Table.Td>
                  <Table.Td>{r.description ?? r.item_code ?? ''}</Table.Td>
                  <Table.Td ta="right">{r.quantity ?? ''}</Table.Td>
                  <Table.Td ta="right" fw={600}>{r.revenue ?? r.amount ?? r.residual ?? ''}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Drawer>
      <style>{'@media print { .no-print, nav, header { display: none !important } }'}</style>
    </>
  )
}

function Filters({ cube, model, filters, onChange }: { cube: string; model: any; filters: Record<string, any[]>; onChange: (f: Record<string, any[]>) => void }) {
  const [adding, setAdding] = useState<string | null>(null)
  const D = Object.fromEntries(model.dimensions.map((d: any) => [d.name, d]))
  return (
    <Group mt="sm" gap="xs" align="flex-start">
      <IconFilter size={16} style={{ marginTop: 8 }} />
      {Object.entries(filters).map(([d, vals]) => (
        <FilterChip key={d} cube={cube} dim={d} label={D[d]?.label ?? d} values={vals} onChange={(v) => onChange(v.length ? { ...filters, [d]: v } : Object.fromEntries(Object.entries(filters).filter(([k]) => k !== d)))} />
      ))}
      <Select size="xs" w={200} placeholder="Aggiungi filtro" value={adding} searchable clearable
        data={model.dimensions.filter((x: any) => x.available && !x.time && !filters[x.name]).map((x: any) => ({ value: x.name, label: x.label }))}
        onChange={(v) => { if (v) onChange({ ...filters, [v]: [] }); setAdding(null) }} />
    </Group>
  )
}

function FilterChip({ cube, dim, label, values, onChange }: { cube: string; dim: string; label: string; values: any[]; onChange: (v: any[]) => void }) {
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([])
  const [q, setQ] = useState('')
  const labels = useRef<Record<string, string>>({})
  useEffect(() => {
    const t = setTimeout(() => BI(`/${cube}/valori/${dim}${q ? `?q=${encodeURIComponent(q)}` : ''}`).then((r) => {
      const o = r.map((x: any) => ({ value: x.key === null ? '__null__' : String(x.key), label: x.label }))
      o.forEach((x: any) => { labels.current[x.value] = x.label })
      setOpts(o)
    }).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [q, cube, dim])
  const value = values.map((v) => (v === null ? '__null__' : String(v)))
  const data = [...opts, ...value.filter((v) => !opts.some((o) => o.value === v)).map((v) => ({ value: v, label: labels.current[v] ?? v }))]
  return (
    <Paper withBorder px={6} py={2} radius="xl">
      <Group gap={4} wrap="nowrap">
        <Text size="xs" fw={600}>{label}:</Text>
        <MultiSelect size="xs" variant="unstyled" w={240} placeholder="scegli…" data={data} value={value} searchable searchValue={q} onSearchChange={setQ}
          onChange={(v) => onChange(v.map((x) => (x === '__null__' ? null : x)))} />
        <ActionIcon size="xs" variant="subtle" onClick={() => onChange([])}><IconX size={12} /></ActionIcon>
      </Group>
    </Paper>
  )
}

function ScheduleModal({ rep, setRep, onClose, onSave }: { rep: any; setRep: (r: any) => void; onClose: () => void; onSave: () => void }) {
  const s = rep.schedule || {}
  const set = (patch: any) => setRep({ ...rep, schedule: { ...s, ...patch } })
  const [sending, setSending] = useState(false)
  return (
    <Modal opened onClose={onClose} title="Invio via email">
      <Stack>
        <SegmentedControl value={s.frequency || ''} onChange={(v) => set({ frequency: v })}
          data={[{ value: '', label: 'Mai' }, { value: 'giornaliero', label: 'Ogni giorno' }, { value: 'settimanale', label: 'Ogni settimana' }, { value: 'mensile', label: 'Ogni mese' }]} />
        {s.frequency === 'settimanale' && <Select label="Giorno" data={WEEKDAYS.map((d, i) => ({ value: String(i), label: d }))} value={String(s.weekday ?? 0)} onChange={(v) => set({ weekday: Number(v) })} />}
        {s.frequency === 'mensile' && <Select label="Giorno del mese" data={Array.from({ length: 28 }, (_, i) => String(i + 1))} value={String(s.day ?? 1)} onChange={(v) => set({ day: Number(v) })} />}
        <TagsInput label="Destinatari" placeholder="email e Invio" value={s.emails ?? []} onChange={(v) => set({ emails: v })} />
        <Text size="xs" c="dimmed">Il report parte alle 7:41 con i numeri aggiornati ({rep.period_label?.toLowerCase() ?? 'periodo del report'}) e il file Excel allegato.</Text>
        <Divider />
        <Group justify="space-between">
          <Button variant="default" leftSection={<IconMail size={16} />} loading={sending} onClick={async () => {
            setSending(true)
            try { const r = await BI(`/report/${rep.id}/invia`, { method: 'POST' }); notifyOk(`Inviato a ${r.sent_to.join(', ')}`) } catch (e) { notifyError(e) } finally { setSending(false) }
          }}>Invia ora</Button>
          <Button onClick={onSave}>Salva</Button>
        </Group>
        {rep.last_sent_at && <Badge variant="light">Ultimo invio {new Date(rep.last_sent_at).toLocaleString('it-IT')}</Badge>}
      </Stack>
    </Modal>
  )
}
