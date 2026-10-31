// Dashboard personali (Pro): widget presi dai report salvati, trascinabili per riordinarli, larghi da 1 a 4 colonne.

import { ActionIcon, Alert, Button, Group, Loader, Menu, Modal, Paper, Select, SegmentedControl, Switch, Text, TextInput } from '@mantine/core'
import { IconDotsVertical, IconExternalLink, IconGripVertical, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi } from '../../api'
import { Loading, PageTitle, notifyError } from '../../components'
import ReportView from './ReportView'

const BI = (p: string, opts?: { method?: string; body?: unknown }) => appApi('/api/bi' + p, opts)

export default function Dashboards() {
  const { id } = useParams()
  const nav = useNavigate()
  const [list, setList] = useState<any[] | null>(null)
  const [reports, setReports] = useState<any[]>([])
  const [dash, setDash] = useState<any>(null)
  const [adding, setAdding] = useState(false)
  const [naming, setNaming] = useState<string | null>(null)
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const load = () => BI('/dashboard').then((l) => { setList(l); if (!id && l.length) nav(`/dashboard/${l[0].id}`, { replace: true }) }).catch(notifyError)
  useEffect(() => { load(); BI('/report').then(setReports).catch(() => {}) }, [])
  useEffect(() => { setDash(list?.find((d) => d.id === id) ?? null) }, [id, list])

  async function persist(d: any) {
    setDash(d)
    try { const r = await BI(`/dashboard/${d.id}`, { method: 'PUT', body: { name: d.name, shared: d.shared, widgets: d.widgets } }); setList((l) => l!.map((x) => (x.id === r.id ? r : x))) } catch (e) { notifyError(e) }
  }
  async function create() {
    try { const r = await BI('/dashboard', { body: { name: naming || 'La mia dashboard', widgets: [] } }); setNaming(null); await load(); nav(`/dashboard/${r.id}`) } catch (e) { notifyError(e) }
  }
  if (!list) return <Loading />
  return (
    <>
      <PageTitle title="Dashboard" subtitle="I tuoi numeri in un colpo d'occhio: aggiungi i report salvati e disponili come preferisci"
        right={<Group gap="xs">
          {list.length > 0 && <Select w={240} data={list.map((d) => ({ value: d.id, label: d.name }))} value={id ?? null} onChange={(v) => v && nav(`/dashboard/${v}`)} allowDeselect={false} />}
          <Button variant="default" leftSection={<IconPlus size={16} />} onClick={() => setNaming('')}>Nuova dashboard</Button>
          {dash?.mine && <Button leftSection={<IconPlus size={16} />} onClick={() => setAdding(true)}>Aggiungi riquadro</Button>}
        </Group>} />
      {!list.length && <Alert color="blue">Crea la prima dashboard, poi aggiungi i riquadri scegliendo fra i report salvati nel report builder.</Alert>}
      {dash && !dash.widgets.length && <Alert color="gray">Dashboard vuota: usa «Aggiungi riquadro».{!reports.length && ' Prima salva almeno un report nel report builder.'}</Alert>}
      {dash && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 }}>
          {dash.widgets.map((w: any, i: number) => (
            <div key={w.report_id + i} draggable={dash.mine} onDragStart={() => setDragIdx(i)} onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragIdx === null || dragIdx === i) return
                const ws = [...dash.widgets]; const [x] = ws.splice(dragIdx, 1); ws.splice(i, 0, x); setDragIdx(null); persist({ ...dash, widgets: ws })
              }}
              style={{ gridColumn: `span ${w.width}`, opacity: dragIdx === i ? 0.5 : 1 }}>
              <Widget w={w} report={reports.find((r) => r.id === w.report_id)} editable={dash.mine}
                onChange={(nw) => persist({ ...dash, widgets: dash.widgets.map((x: any, n: number) => (n === i ? nw : x)) })}
                onRemove={() => persist({ ...dash, widgets: dash.widgets.filter((_: any, n: number) => n !== i) })} />
            </div>
          ))}
        </div>
      )}
      {dash?.mine && (
        <Group mt="md">
          <Switch label="Condivisa con tutti gli utenti" checked={dash.shared} onChange={(e) => persist({ ...dash, shared: e.currentTarget.checked })} />
          <Button size="xs" variant="subtle" color="red" leftSection={<IconTrash size={14} />} onClick={async () => {
            if (!window.confirm(`Eliminare la dashboard «${dash.name}»?`)) return
            await BI(`/dashboard/${dash.id}`, { method: 'DELETE' }).catch(notifyError); nav('/dashboard'); load()
          }}>Elimina dashboard</Button>
        </Group>
      )}
      <Modal opened={naming !== null} onClose={() => setNaming(null)} title="Nuova dashboard">
        <TextInput label="Nome" value={naming ?? ''} onChange={(e) => setNaming(e.currentTarget.value)} data-autofocus placeholder="es. Andamento settimanale" />
        <Group justify="flex-end" mt="md"><Button onClick={create}>Crea</Button></Group>
      </Modal>
      <Modal opened={adding} onClose={() => setAdding(false)} title="Aggiungi riquadro" size="lg">
        {reports.length === 0 ? <Text c="dimmed">Nessun report salvato: crealo nel report builder.</Text> : reports.map((r) => (
          <Paper key={r.id} withBorder p="xs" mb={6} style={{ cursor: 'pointer' }} onClick={() => {
            persist({ ...dash, widgets: [...dash.widgets, { report_id: r.id, width: r.config.chart === 'kpi' ? 1 : 2, view: r.config.chart === 'kpi' ? 'kpi' : r.config.chart === 'tabella' ? 'tabella' : 'grafico' }] })
            setAdding(false)
          }}>
            <Text fw={600}>{r.name}</Text><Text size="xs" c="dimmed">{r.cube_label} · {r.period_label}</Text>
          </Paper>
        ))}
        <Button variant="subtle" mt="sm" onClick={() => window.open('/report/nuovo', '_self')}>Crea un nuovo report</Button>
      </Modal>
    </>
  )
}

function Widget({ w, report, editable, onChange, onRemove }: { w: any; report: any; editable: boolean; onChange: (w: any) => void; onRemove: () => void }) {
  const nav = useNavigate()
  const [data, setData] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setData(null); BI(`/report/${w.report_id}/esegui`).then(setData).catch((e) => setErr(e.message)) }, [w.report_id, report?.updated_at])
  const cfg = data ? { ...data.report.config, chart: w.view === 'kpi' ? 'kpi' : w.view === 'tabella' ? 'tabella' : (['barre', 'linee', 'torta'].includes(data.report.config.chart) ? data.report.config.chart : 'barre') } : null
  return (
    <Paper withBorder p="sm" h="100%">
      <Group justify="space-between" wrap="nowrap" mb={6}>
        <Group gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
          {editable && <IconGripVertical size={14} style={{ cursor: 'grab', flexShrink: 0 }} color="var(--mantine-color-gray-5)" />}
          <div style={{ minWidth: 0 }}>
            <Text fw={600} size="sm" truncate>{report?.name ?? data?.report.name ?? '…'}</Text>
            <Text size="xs" c="dimmed" truncate>{report?.period_label}</Text>
          </div>
        </Group>
        <Menu position="bottom-end">
          <Menu.Target><ActionIcon variant="subtle" size="sm"><IconDotsVertical size={14} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconExternalLink size={14} />} onClick={() => nav(`/report/${w.report_id}`)}>Apri nel report builder</Menu.Item>
            {editable && (
              <>
                <Menu.Label>Vista</Menu.Label>
                <div style={{ padding: '0 8px 6px' }}><SegmentedControl size="xs" value={w.view} onChange={(v) => onChange({ ...w, view: v })} data={[{ value: 'kpi', label: 'Numeri' }, { value: 'grafico', label: 'Grafico' }, { value: 'tabella', label: 'Tabella' }]} /></div>
                <Menu.Label>Larghezza</Menu.Label>
                <div style={{ padding: '0 8px 6px' }}><SegmentedControl size="xs" value={String(w.width)} onChange={(v) => onChange({ ...w, width: Number(v) })} data={['1', '2', '3', '4']} /></div>
                <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={onRemove}>Togli dalla dashboard</Menu.Item>
              </>
            )}
          </Menu.Dropdown>
        </Menu>
      </Group>
      {err ? <Text size="sm" c="red">{err}</Text> : !data ? <Loader size="sm" /> : <ReportView model={data.model} res={data.result} cfg={cfg} compact />}
    </Paper>
  )
}
