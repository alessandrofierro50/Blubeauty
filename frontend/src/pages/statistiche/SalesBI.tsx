import { BarChart } from '@mantine/charts'
import {
  ActionIcon, Anchor, Badge, Breadcrumbs, Button, CloseButton, Drawer, Group, Menu, Paper, Progress, SegmentedControl, SimpleGrid,
  Table, Text, TextInput, Title, Tooltip,
} from '@mantine/core'
import { IconArrowBackUp, IconChevronDown, IconDownload, IconFilter, IconListDetails } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro, isoDate, tokens } from '../../api'
import { Loading, notifyError } from '../../components'

const BI = (p: string, body: any) => appApi('/api/bi/vendite' + p, { body })
type Chip = { key: any; label: string }
type Filters = Record<string, Chip[]>
const eur0 = (v: any) => Number(v ?? 0).toLocaleString('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const num = (v: any) => Number(v ?? 0).toLocaleString('it-IT', { maximumFractionDigits: 2 })
const DIM_LABEL: Record<string, string> = {
  anno: 'Anno', trimestre: 'Trimestre', mese: 'Mese', giorno: 'Giorno', cliente: 'Cliente', provincia: 'Provincia',
  categoria_principale: 'Categoria', categoria: 'Sottocategoria', articolo: 'Articolo', marca: 'Marca', tipo_documento: 'Documento',
}
const PRODUCT_LEVELS = ['categoria_principale', 'categoria', 'articolo']

function presets() {
  const t = new Date(); const y = t.getFullYear(); const m = t.getMonth()
  return {
    mese: [isoDate(new Date(y, m, 1)), isoDate(t)], mese_scorso: [isoDate(new Date(y, m - 1, 1)), isoDate(new Date(y, m, 0))],
    trimestre: [isoDate(new Date(y, Math.floor(m / 3) * 3, 1)), isoDate(t)], anno: [`${y}-01-01`, isoDate(t)],
    anno_scorso: [`${y - 1}-01-01`, `${y - 1}-12-31`], dodici: [isoDate(new Date(y, m - 11, 1)), isoDate(t)],
    tre_anni: [`${y - 2}-01-01`, isoDate(t)],
  } as Record<string, [string, string]>
}
function timeLevel(from: string, to: string) {
  const days = (new Date(to).getTime() - new Date(from).getTime()) / 86400000
  return days <= 45 ? 'giorno' : days <= 800 ? 'mese' : 'anno'
}
function Delta({ v, size = 'xs' }: { v?: string | null; size?: string }) {
  if (v == null) return null
  const n = Number(v)
  return <Text span size={size} fw={600} c={n >= 0 ? 'green' : 'red'}>{n >= 0 ? '▲' : '▼'} {Math.abs(n).toLocaleString('it-IT')}%</Text>
}
function filterBody(f: Filters) {
  return Object.fromEntries(Object.entries(f).filter(([, v]) => v.length).map(([k, v]) => [k, v.map((c) => c.key)]))
}

export default function SalesBI({ pro }: { pro: boolean }) {
  const nav = useNavigate()
  const [preset, setPreset] = useState('anno')
  const [range, setRange] = useState<[string, string]>(presets().anno)
  const [history, setHistory] = useState<{ range: [string, string]; preset: string }[]>([])
  const [compare, setCompare] = useState('anno_precedente')
  const [filters, setFilters] = useState<Filters>({})
  const [productLevel, setProductLevel] = useState(0)
  const [kpi, setKpi] = useState<any>(null)
  const [trend, setTrend] = useState<any>(null)
  const [products, setProducts] = useState<any>(null)
  const [customers, setCustomers] = useState<any>(null)
  const [provinces, setProvinces] = useState<any>(null)
  const [items, setItems] = useState<any>(null)
  const [detail, setDetail] = useState<any[] | null>(null)
  const level = timeLevel(range[0], range[1])
  const cmp = compare || null
  const base = useMemo(() => ({ date_from: range[0], date_to: range[1], filters: filterBody(filters), compare: cmp }), [range, filters, cmp])
  const kpiMeasures = ['fatturato', 'documenti', 'clienti', 'fattura_media', ...(pro ? ['margine', 'margine_pct'] : [])]

  useEffect(() => {
    const run = (setter: (v: any) => void, body: any) => { setter(null); BI('/query', { ...base, ...body }).then(setter).catch(notifyError) }
    run(setKpi, { measures: kpiMeasures })
    run(setTrend, { measures: ['fatturato'], dimensions: [level] })
    run(setProducts, { measures: ['fatturato'], dimensions: [PRODUCT_LEVELS[productLevel]], sort: 'fatturato', limit: 12 })
    run(setCustomers, { measures: ['fatturato', 'documenti'], dimensions: ['cliente'], sort: 'fatturato', limit: 10 })
    run(setProvinces, { measures: ['fatturato'], dimensions: ['provincia'], sort: 'fatturato', limit: 10 })
    run(setItems, { measures: ['fatturato', 'quantita', 'prezzo_medio', ...(pro ? ['margine_pct'] : [])], dimensions: ['articolo'], sort: 'fatturato', limit: 15 })
  }, [base, level, productLevel, pro])

  const addFilter = (dim: string, chip: Chip) => setFilters((f) => ({ ...f, [dim]: (f[dim] ?? []).some((x) => x.key === chip.key) ? f[dim] : [...(f[dim] ?? []), chip] }))
  const removeFilter = (dim: string, key: any) => setFilters((f) => ({ ...f, [dim]: (f[dim] ?? []).filter((x) => x.key !== key) }))
  const choose = (p: string) => { setPreset(p); setHistory([]); if (p !== 'custom') setRange(presets()[p]) }

  function drillTime(row: any) {
    const k = row.dims[level].key
    let next: [string, string] | null = null
    if (level === 'anno') next = [`${k}-01-01`, `${k}-12-31`]
    if (level === 'mese') { const [y, m] = String(k).split('-').map(Number); next = [isoDate(new Date(y, m - 1, 1)), isoDate(new Date(y, m, 0))] }
    if (!next) return
    setHistory((h) => [...h, { range, preset }])
    setPreset('custom')
    setRange(next)
  }
  function drillUp() {
    const last = history[history.length - 1]
    if (!last) return
    setHistory(history.slice(0, -1)); setRange(last.range); setPreset(last.preset)
  }
  function drillProduct(row: any) {
    const dim = PRODUCT_LEVELS[productLevel]
    addFilter(dim, { key: row.dims[dim].key, label: row.dims[dim].label })
    if (productLevel < PRODUCT_LEVELS.length - 1) setProductLevel(productLevel + 1)
  }
  async function openDetail() {
    setDetail([])
    try { setDetail(await BI('/dettaglio', { ...base, measures: ['fatturato'] })) } catch (e) { notifyError(e) }
  }
  async function exportBy(dim: string) {
    try {
      const res = await fetch('/api/bi/vendite/excel', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tokens.get('user')}` },
        body: JSON.stringify({ ...base, measures: ['fatturato', 'quantita', 'documenti', ...(pro ? ['margine', 'margine_pct'] : [])].filter((m) => dim !== 'cliente' || m !== 'quantita'), dimensions: [dim], sort: dim === 'mese' ? null : 'fatturato', limit: 1000 }) })
      if (!res.ok) throw new Error('Esportazione non riuscita')
      const a = document.createElement('a'); a.href = URL.createObjectURL(await res.blob()); a.download = `analisi-vendite-${dim}.xlsx`; a.click()
    } catch (e) { notifyError(e) }
  }

  const chips = Object.entries(filters).flatMap(([dim, list]) => list.map((c) => ({ dim, ...c })))
  const kv = kpi?.totals
  const kd = kpi?.totals_delta ?? {}
  const kc = kpi?.totals_compare ?? {}
  return (
    <>
      <Paper withBorder p="sm" mb="md" style={{ position: 'sticky', top: 60, zIndex: 5 }}>
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Group gap="xs" wrap="wrap">
            <SegmentedControl size="xs" value={preset} onChange={choose} data={[{ value: 'mese', label: 'Mese' }, { value: 'mese_scorso', label: 'Mese scorso' }, { value: 'trimestre', label: 'Trimestre' }, { value: 'anno', label: 'Anno' }, { value: 'anno_scorso', label: 'Anno scorso' }, { value: 'dodici', label: '12 mesi' }, { value: 'tre_anni', label: '3 anni' }, { value: 'custom', label: 'Periodo' }]} />
            {preset === 'custom' && <>
              <TextInput size="xs" type="date" value={range[0]} onChange={(e) => e.currentTarget.value && setRange([e.currentTarget.value, range[1]])} />
              <TextInput size="xs" type="date" value={range[1]} onChange={(e) => e.currentTarget.value && setRange([range[0], e.currentTarget.value])} />
            </>}
          </Group>
          <Group gap="xs">
            <SegmentedControl size="xs" value={compare} onChange={setCompare} data={[{ value: 'anno_precedente', label: 'vs anno prec.' }, { value: 'periodo_precedente', label: 'vs periodo prec.' }, { value: '', label: 'Nessun confronto' }]} />
            <Button size="xs" variant="default" leftSection={<IconListDetails size={14} />} onClick={openDetail}>Righe</Button>
            <Menu position="bottom-end">
              <Menu.Target><Button size="xs" variant="default" leftSection={<IconDownload size={14} />} rightSection={<IconChevronDown size={12} />}>Excel</Button></Menu.Target>
              <Menu.Dropdown>
                {[['mese', 'per mese'], ['cliente', 'per cliente'], ['articolo', 'per articolo'], ['categoria_principale', 'per categoria'], ['provincia', 'per provincia']].map(([d, l]) => <Menu.Item key={d} onClick={() => exportBy(d)}>Vendite {l}</Menu.Item>)}
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
        {chips.length > 0 && (
          <Group gap={6} mt="xs">
            <IconFilter size={14} color="var(--mantine-color-dimmed)" />
            {chips.map((c) => (
              <Badge key={c.dim + c.key} variant="light" size="lg" pr={3} style={{ textTransform: 'none' }}
                rightSection={<CloseButton size="xs" onClick={() => { removeFilter(c.dim, c.key); if (PRODUCT_LEVELS.includes(c.dim)) setProductLevel(Math.max(0, PRODUCT_LEVELS.indexOf(c.dim))) }} />}>
                {DIM_LABEL[c.dim]}: {c.label}
              </Badge>
            ))}
            <Anchor size="xs" onClick={() => { setFilters({}); setProductLevel(0) }}>Azzera filtri</Anchor>
          </Group>
        )}
      </Paper>

      <SimpleGrid cols={{ base: 2, md: pro ? 6 : 4 }} mb="md">
        {[['fatturato', 'Fatturato', 'euro'], ['documenti', 'Vendite', 'n'], ['clienti', 'Clienti', 'n'], ['fattura_media', 'Vendita media', 'euro'],
          ...(pro ? [['margine', 'Margine', 'euro'], ['margine_pct', 'Margine %', 'pct']] : [])].map(([m, label, f]) => (
          <Paper key={m} withBorder p="md" radius="md">
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>{label}</Text>
            <Text fw={800} fz={22}>{!kv ? '…' : f === 'euro' ? fmtEuro(kv[m] ?? 0) : f === 'pct' ? (kv[m] != null ? `${num(kv[m])}%` : '—') : num(kv[m])}</Text>
            {cmp && kv && <Text size="xs" c="dimmed"><Delta v={kd[m]} /> {kc[m] != null ? `da ${f === 'euro' ? eur0(kc[m]) : f === 'pct' ? `${num(kc[m])}%` : num(kc[m])}` : 'nessun confronto'}</Text>}
          </Paper>
        ))}
      </SimpleGrid>

      <Paper withBorder p="md" mb="md">
        <Group justify="space-between" mb="xs">
          <Group gap="xs">
            <Title order={5}>Andamento per {DIM_LABEL[level].toLowerCase()}</Title>
            {history.length > 0 && <Tooltip label="Torna al livello precedente"><ActionIcon variant="light" size="sm" onClick={drillUp}><IconArrowBackUp size={14} /></ActionIcon></Tooltip>}
          </Group>
          <Text size="xs" c="dimmed">{fmtDate(range[0])} – {fmtDate(range[1])}{level !== 'giorno' ? ' · clicca una barra per scendere nel dettaglio' : ''}</Text>
        </Group>
        {!trend ? <Loading /> : (
          <BarChart h={250} dataKey="label" withLegend={!!cmp} maxBarWidth={30} valueFormatter={eur0}
            data={trend.rows.filter((r: any) => r.dims[level]).map((r: any) => ({ label: r.dims[level].label, row: r, Fatturato: Number(r.values.fatturato), ...(cmp ? { Confronto: Number(r.compare?.fatturato ?? 0) } : {}) }))}
            series={[{ name: 'Fatturato', color: 'blu.6' }, ...(cmp ? [{ name: 'Confronto', color: 'gray.4' }] : [])]}
            barProps={{ onClick: (d: any) => d?.payload?.row && drillTime(d.payload.row), style: { cursor: level !== 'giorno' ? 'pointer' : undefined } } as any} />
        )}
      </Paper>

      <SimpleGrid cols={{ base: 1, lg: 2 }} mb="md">
        <Widget title="Prodotti" loading={!products}
          subtitle={<Breadcrumbs separator="›" fz="xs">{PRODUCT_LEVELS.slice(0, productLevel + 1).map((l, i) => <Anchor key={l} size="xs" c={i === productLevel ? 'dimmed' : undefined} onClick={() => setProductLevel(i)}>{DIM_LABEL[l]}</Anchor>)}</Breadcrumbs>}>
          {products && <RankList res={products} dim={PRODUCT_LEVELS[productLevel]} cmp={!!cmp} onClick={drillProduct} hint={productLevel < 2 ? 'clicca per vedere il dettaglio' : 'clicca per filtrare'} />}
        </Widget>
        <Widget title="Clienti" loading={!customers} subtitle={<Text size="xs" c="dimmed">i primi 10</Text>}>
          {customers && <RankList res={customers} dim="cliente" cmp={!!cmp} onClick={(r) => addFilter('cliente', { key: r.dims.cliente.key, label: r.dims.cliente.label })}
            extra={(r) => <Text size="xs" c="dimmed">{r.values.documenti} fatt.</Text>} />}
        </Widget>
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 3 }}>
        <Widget title="Province" loading={!provinces}>
          {provinces && <RankList res={provinces} dim="provincia" cmp={!!cmp} onClick={(r) => addFilter('provincia', { key: r.dims.provincia.key, label: r.dims.provincia.label })} />}
        </Widget>
        <Paper withBorder p="md" style={{ gridColumn: 'span 2' }}>
          <Group justify="space-between" mb="xs"><Title order={5}>Articoli più venduti</Title><Text size="xs" c="dimmed">clicca per filtrare · doppio clic per lo storico</Text></Group>
          {!items || (items.rows.length && !items.rows[0].dims.articolo) ? <Loading /> : (
            <Table.ScrollContainer minWidth={560}>
              <Table verticalSpacing={5} fz="sm" highlightOnHover>
                <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th ta="right">Quantità</Table.Th><Table.Th ta="right">Prezzo medio</Table.Th><Table.Th ta="right">Fatturato</Table.Th>{cmp && <Table.Th ta="right">Δ</Table.Th>}{pro && <Table.Th ta="right">Margine</Table.Th>}</Table.Tr></Table.Thead>
                <Table.Tbody>
                  {items.rows.map((r: any) => (
                    <Table.Tr key={String(r.dims.articolo.key)} style={{ cursor: 'pointer' }} onClick={() => addFilter('articolo', { key: r.dims.articolo.key, label: r.dims.articolo.label })}
                      onDoubleClick={() => r.dims.articolo.key && nav(`/vendite/storico-articolo?item=${r.dims.articolo.key}`)}>
                      <Table.Td>{r.dims.articolo.label}</Table.Td>
                      <Table.Td ta="right">{r.dims.articolo.key ? num(r.values.quantita) : '—'}</Table.Td>
                      <Table.Td ta="right">{r.dims.articolo.key && r.values.prezzo_medio ? fmtEuro(r.values.prezzo_medio) : '—'}</Table.Td>
                      <Table.Td ta="right" fw={600}>{fmtEuro(r.values.fatturato)}</Table.Td>
                      {cmp && <Table.Td ta="right"><Delta v={r.delta?.fatturato} /></Table.Td>}
                      {pro && <Table.Td ta="right">{r.values.margine_pct != null ? `${num(r.values.margine_pct)}%` : '—'}</Table.Td>}
                    </Table.Tr>
                  ))}
                  {!items.rows.length && <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="md">Nessuna vendita</Text></Table.Td></Table.Tr>}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Paper>
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt="sm">Fatturato = fatture immediate e differite meno note di credito, IVA esclusa, per data del documento.{!pro && ' Margini, tabelle pivot e report personalizzati sono nelle statistiche avanzate (pacchetto Pro).'}</Text>

      <Drawer opened={detail !== null} onClose={() => setDetail(null)} position="right" size="xl" title={<Text fw={700}>Righe dei documenti{chips.length ? ' (con i filtri attivi)' : ''}</Text>}>
        {detail && (
          <Table verticalSpacing={4} fz="sm" highlightOnHover>
            <Table.Thead><Table.Tr><Table.Th>Documento</Table.Th><Table.Th>Cliente</Table.Th><Table.Th>Descrizione</Table.Th><Table.Th ta="right">Q.tà</Table.Th><Table.Th ta="right">Importo</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {detail.map((r, i) => (
                <Table.Tr key={i} style={{ cursor: 'pointer' }} onClick={() => nav(`/vendite/${r.document_id}`)}>
                  <Table.Td><Text size="sm">{r.label}</Text><Text size="xs" c="dimmed">{fmtDate(r.date)}</Text></Table.Td>
                  <Table.Td>{r.party}</Table.Td>
                  <Table.Td>{r.item_code && <Text span size="xs" ff="monospace" c="dimmed">{r.item_code} </Text>}{r.description}</Table.Td>
                  <Table.Td ta="right">{num(r.quantity)} {r.unit ?? ''}</Table.Td>
                  <Table.Td ta="right" fw={600} c={Number(r.revenue) < 0 ? 'red' : undefined}>{fmtEuro(r.revenue)}</Table.Td>
                </Table.Tr>
              ))}
              {!detail.length && <Table.Tr><Table.Td colSpan={5}><Text c="dimmed" ta="center" py="md">Nessuna riga</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        )}
      </Drawer>
    </>
  )
}

function Widget({ title, subtitle, loading, children }: { title: string; subtitle?: React.ReactNode; loading?: boolean; children: React.ReactNode }) {
  return (
    <Paper withBorder p="md">
      <Group justify="space-between" mb="xs"><Title order={5}>{title}</Title>{subtitle}</Group>
      {loading ? <Loading /> : children}
    </Paper>
  )
}

function RankList({ res, dim, cmp, onClick, hint, extra }: { res: any; dim: string; cmp: boolean; onClick: (r: any) => void; hint?: string; extra?: (r: any) => React.ReactNode }) {
  const total = Number(res.totals.fatturato) || 1
  if (res.rows.length && !res.rows[0].dims[dim]) return <Loading />  // dati del livello precedente: arrivano i nuovi
  if (!res.rows.length) return <Text c="dimmed" ta="center" py="md">Nessuna vendita</Text>
  return (
    <>
      {res.rows.map((r: any) => {
        const share = (Number(r.values.fatturato) / total) * 100
        return (
          <div key={String(r.dims[dim].key)} style={{ cursor: 'pointer', padding: '4px 6px', borderRadius: 6 }} className="bi-row" onClick={() => onClick(r)}>
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="sm" truncate style={{ flex: 1 }}>{r.dims[dim].label}</Text>
              {extra?.(r)}
              {cmp && <Delta v={r.delta?.fatturato} />}
              <Text size="sm" fw={600} w={96} ta="right">{fmtEuro(r.values.fatturato)}</Text>
              <Text size="xs" c="dimmed" w={44} ta="right">{share.toLocaleString('it-IT', { maximumFractionDigits: 1 })}%</Text>
            </Group>
            <Progress value={Math.max(0, share)} size={4} mt={2} />
          </div>
        )
      })}
      <style>{'.bi-row:hover{background:var(--mantine-color-default-hover)}'}</style>
      {hint && <Text size="xs" c="dimmed" mt={4}>{hint}</Text>}
    </>
  )
}
