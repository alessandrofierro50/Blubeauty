// Visualizzazione di un risultato del motore BI: KPI, tabella (anche pivot righe × colonne), grafico a barre, linee o torta.
// La usano il report builder, le dashboard e le pagine di analisi.

import { BarChart, DonutChart, LineChart } from '@mantine/charts'
import { Badge, Group, Paper, ScrollArea, SimpleGrid, Table, Text } from '@mantine/core'

export type Cfg = { rows: string[]; columns: string | null; measures: string[]; chart: string; compare?: string | null }
const PALETTE = ['blue.6', 'teal.6', 'orange.6', 'grape.6', 'red.6', 'cyan.6', 'lime.7', 'pink.6', 'indigo.6', 'yellow.7']

export function fmtValue(v: any, format: string, compact = false) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (format === 'euro') return n.toLocaleString('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: compact && Math.abs(n) >= 1000 ? 0 : 2 })
  if (format === 'percento') return `${n.toLocaleString('it-IT', { maximumFractionDigits: 1 })}%`
  if (format === 'giorni') return `${n.toLocaleString('it-IT', { maximumFractionDigits: 1 })} gg`
  return n.toLocaleString('it-IT', { maximumFractionDigits: format === 'intero' ? 0 : 2 })
}

export function Delta({ v }: { v: any }) {
  if (v === null || v === undefined) return null
  const x = Number(v)
  return <Text span size="xs" fw={600} c={x >= 0 ? 'teal' : 'red'}>{x >= 0 ? '▲' : '▼'} {Math.abs(x).toLocaleString('it-IT', { maximumFractionDigits: 1 })}%</Text>
}

export default function ReportView({ model, res, cfg, compact = false, onDrill }: {
  model: any; res: any; cfg: Cfg; compact?: boolean; onDrill?: (row: any) => void
}) {
  const M = Object.fromEntries(model.measures.map((m: any) => [m.name, m]))
  const D = Object.fromEntries(model.dimensions.map((d: any) => [d.name, d]))
  const meas = cfg.measures.filter((m) => M[m])
  const kpi = (
    <SimpleGrid cols={{ base: 1, sm: Math.min(meas.length, compact ? 2 : 4) }} spacing="sm">
      {meas.map((m) => (
        <Paper key={m} withBorder p="sm">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{M[m].label}</Text>
          <Group gap={8} align="baseline"><Text fw={800} size={compact ? '22px' : '28px'}>{fmtValue(res.totals[m], M[m].format)}</Text><Delta v={res.totals_delta?.[m]} /></Group>
          {res.totals_compare && <Text size="xs" c="dimmed">confronto {fmtValue(res.totals_compare[m], M[m].format)}</Text>}
        </Paper>
      ))}
    </SimpleGrid>
  )
  if (cfg.chart === 'kpi' || (!cfg.rows.length && !cfg.columns)) return kpi
  if (!res.rows.length) return <Text c="dimmed" ta="center" py="lg">Nessun dato nel periodo</Text>
  // risultato non ancora allineato alla configurazione (es. appena cambiato report): si aspetta quello nuovo
  const need = [...cfg.rows, ...(cfg.columns ? [cfg.columns] : [])]
  if (need.some((d) => !res.rows[0].dims?.[d])) return <Text c="dimmed" ta="center" py="lg">Aggiornamento…</Text>

  const rowKey = (r: any) => cfg.rows.map((d) => String(r.dims[d]?.key)).join('|')
  const rowLabel = (r: any) => cfg.rows.map((d) => r.dims[d]?.label).join(' · ')
  const col = cfg.columns
  const colValues: { key: any; label: string }[] = []
  if (col) {
    const seen = new Set()
    for (const r of res.rows) { const k = String(r.dims[col].key); if (!seen.has(k)) { seen.add(k); colValues.push({ key: r.dims[col].key, label: r.dims[col].label }) } }
    if (D[col]?.time) colValues.sort((a, b) => String(a.key).localeCompare(String(b.key)))
  }
  const grouped = new Map<string, { label: string; first: any; cells: Record<string, any> }>()
  for (const r of res.rows) {
    const k = rowKey(r)
    if (!grouped.has(k)) grouped.set(k, { label: rowLabel(r), first: r, cells: {} })
    grouped.get(k)!.cells[col ? String(r.dims[col].key) : '_'] = r.values
  }
  const groups = [...grouped.values()]

  if (cfg.chart === 'barre' || cfg.chart === 'linee') {
    const m0 = meas[0]
    const top = col ? colValues.slice(0, 8) : []
    // nel grafico solo le misure con la stessa unità della prima (euro con euro, conteggi con conteggi)
    const plotted = meas.filter((m) => M[m].format === M[m0].format)
    const series = col ? top.map((c, i) => ({ name: c.label, color: PALETTE[i % PALETTE.length] })) : plotted.map((m, i) => ({ name: M[m].label, color: PALETTE[i % PALETTE.length] }))
    const data = groups.slice(0, compact ? 15 : 40).map((g) => {
      const o: any = { label: g.label, _row: g.first }
      if (col) top.forEach((c) => { o[c.label] = Number(g.cells[String(c.key)]?.[m0] ?? 0) })
      else plotted.forEach((m) => { o[M[m].label] = Number(g.cells._?.[m] ?? 0) })
      return o
    })
    const Chart: any = cfg.chart === 'linee' ? LineChart : BarChart
    const fmt = (v: number) => fmtValue(v, M[col ? m0 : meas[0]].format, true)
    return (
      <>
        {!compact && kpi}
        <Chart h={compact ? 220 : 340} mt={compact ? 0 : 'md'} dataKey="label" data={data} series={series} withLegend={series.length > 1}
          valueFormatter={fmt} tickLine="y" xAxisProps={{ interval: data.length > 12 ? 'preserveStartEnd' : 0 }}
          {...(cfg.chart === 'linee' ? { curveType: 'monotone' } : {
            maxBarWidth: 36,
            ...(onDrill ? { barProps: { onClick: (d: any) => d?.payload?._row && onDrill(d.payload._row), style: { cursor: 'pointer' } } } : {}),
          })} />
        {col && colValues.length > 8 && <Text size="xs" c="dimmed">Nel grafico i primi 8 valori di «{D[col].label}»</Text>}
        {!col && plotted.length < meas.length && <Text size="xs" c="dimmed">Nel grafico solo le misure in {M[m0].format === 'euro' ? 'euro' : 'stessa unità'} di «{M[m0].label}»; le altre sono nei riquadri sopra o nella vista tabella.</Text>}
      </>
    )
  }

  if (cfg.chart === 'torta') {
    const m0 = meas[0]
    const sorted = [...groups].sort((a, b) => Number(b.cells._?.[m0] ?? 0) - Number(a.cells._?.[m0] ?? 0)).filter((g) => Number(g.cells._?.[m0] ?? 0) > 0)
    const top = sorted.slice(0, 7)
    const rest = sorted.slice(7).reduce((a, g) => a + Number(g.cells._?.[m0] ?? 0), 0)
    const data = [...top.map((g, i) => ({ name: g.label, value: Number(g.cells._?.[m0] ?? 0), color: PALETTE[i] })), ...(rest > 0 ? [{ name: 'Altri', value: rest, color: 'gray.4' }] : [])]
    return (
      <Group align="center" wrap="nowrap" gap="lg">
        <DonutChart data={data} size={compact ? 160 : 220} thickness={compact ? 26 : 34} withTooltip valueFormatter={(v: number) => fmtValue(v, M[m0].format)} />
        <div style={{ flex: 1, minWidth: 0 }}>
          {data.map((d) => (
            <Group key={d.name} justify="space-between" wrap="nowrap" gap="xs">
              <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}><Badge size="xs" circle color={d.color} /><Text size="sm" truncate>{d.name}</Text></Group>
              <Text size="sm" fw={600}>{fmtValue(d.value, M[m0].format, true)}</Text>
            </Group>
          ))}
        </div>
      </Group>
    )
  }

  // tabella (pivot se c'è la dimensione in colonna)
  const additive = (m: string) => ['euro', 'numero', 'intero'].includes(M[m].format) && !M[m].derived
  return (
    <>
      {!compact && <div style={{ marginBottom: 12 }}>{kpi}</div>}
      <ScrollArea type="auto" mah={compact ? 300 : undefined}>
        <Table striped highlightOnHover fz="sm" withColumnBorders={!!col} stickyHeader>
          <Table.Thead>
            {col && meas.length > 1 && (
              <Table.Tr>
                <Table.Th colSpan={cfg.rows.length || 1} />
                {colValues.map((c) => <Table.Th key={String(c.key)} colSpan={meas.length} ta="center">{c.label}</Table.Th>)}
                <Table.Th colSpan={meas.length} ta="center">Totale</Table.Th>
              </Table.Tr>
            )}
            <Table.Tr>
              {(cfg.rows.length ? cfg.rows : ['_']).map((d) => <Table.Th key={d}>{D[d]?.label ?? ''}</Table.Th>)}
              {col ? [...colValues.map((c) => meas.map((m) => <Table.Th key={String(c.key) + m} ta="right">{meas.length > 1 ? M[m].label : c.label}</Table.Th>)),
                ...meas.map((m) => <Table.Th key={'t' + m} ta="right">{meas.length > 1 ? M[m].label : 'Totale'}</Table.Th>)]
                : meas.map((m) => <Table.Th key={m} ta="right">{M[m].label}{cfg.compare ? ' (Δ%)' : ''}</Table.Th>)}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {groups.slice(0, compact ? 50 : 1000).map((g, i) => (
              <Table.Tr key={i} style={{ cursor: onDrill ? 'pointer' : undefined }} onClick={() => onDrill?.(g.first)}>
                {(cfg.rows.length ? cfg.rows : ['_']).map((d) => <Table.Td key={d}>{g.first.dims[d]?.label ?? ''}</Table.Td>)}
                {col ? [...colValues.map((c) => meas.map((m) => <Table.Td key={String(c.key) + m} ta="right">{g.cells[String(c.key)] ? fmtValue(g.cells[String(c.key)][m], M[m].format) : ''}</Table.Td>)),
                  ...meas.map((m) => <Table.Td key={'t' + m} ta="right" fw={600}>{additive(m) ? fmtValue(Object.values(g.cells).reduce((a: number, v: any) => a + Number(v?.[m] ?? 0), 0), M[m].format) : ''}</Table.Td>)]
                  : meas.map((m) => <Table.Td key={m} ta="right">{fmtValue(g.cells._?.[m], M[m].format)}{cfg.compare && <> <Delta v={g.first.delta?.[m]} /></>}</Table.Td>)}
              </Table.Tr>
            ))}
          </Table.Tbody>
          <Table.Tfoot>
            <Table.Tr>
              <Table.Th colSpan={cfg.rows.length || 1}>Totale</Table.Th>
              {col ? [...colValues.map((c) => meas.map((m) => <Table.Th key={String(c.key) + m} ta="right">{additive(m) ? fmtValue(groups.reduce((a, g) => a + Number(g.cells[String(c.key)]?.[m] ?? 0), 0), M[m].format) : ''}</Table.Th>)),
                ...meas.map((m) => <Table.Th key={'t' + m} ta="right">{fmtValue(res.totals[m], M[m].format)}</Table.Th>)]
                : meas.map((m) => <Table.Th key={m} ta="right">{fmtValue(res.totals[m], M[m].format)}</Table.Th>)}
            </Table.Tr>
          </Table.Tfoot>
        </Table>
      </ScrollArea>
      {res.truncated && <Text size="xs" c="dimmed" mt={4}>Risultato troncato: restringi il periodo o i filtri, oppure esporta in Excel.</Text>}
    </>
  )
}
