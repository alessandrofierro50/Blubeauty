import { NumberInput, Table, Text } from '@mantine/core'
import { useEffect, useState } from 'react'

import { appApi } from '../../api'
import { notifyError } from '../../components'

export const W = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/magazzino' + path, opts)

export function useWarehouses() {
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { W('/magazzini').then((r) => setRows(r.rows)).catch(notifyError) }, [])
  return rows
}

export const qty = (v: any, unit?: string) => {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return `${n.toLocaleString('it-IT', { maximumFractionDigits: 3 })}${unit ? ' ' + unit : ''}`
}

export const REASON_COLORS: Record<string, string> = {
  carico: 'green', acquisto: 'green', reso_cliente: 'teal', scarico: 'red', vendita: 'blue', reso_fornitore: 'orange',
  rettifica: 'yellow', inventario: 'grape', trasferimento: 'cyan', omaggio: 'pink', scarto: 'gray',
}

type Variant = { id: string; code: string; size?: string | null; color?: string | null; format?: string | null }

/** Ordina le taglie in modo naturale (XS < S < M < L < XL…, numeri crescenti). */
const SIZE_ORDER = ['XXXS', 'XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', '3XL', '4XL', '5XL', 'TU', 'UNICA']
function sizeKey(s: string) {
  const i = SIZE_ORDER.indexOf(s.toUpperCase())
  if (i >= 0) return `0${String(i).padStart(3, '0')}`
  const n = parseFloat(s.replace(',', '.'))
  return isNaN(n) ? `2${s}` : `1${String(n * 100).padStart(8, '0')}`
}

export function gridAxes(variants: Variant[]) {
  const sizes = [...new Set(variants.map((v) => v.size || '—'))].sort((a, b) => sizeKey(a).localeCompare(sizeKey(b)))
  const colors = [...new Set(variants.map((v) => v.color || v.format || '—'))]
  const cell = (color: string, size: string) => variants.find((v) => (v.color || v.format || '—') === color && (v.size || '—') === size)
  return { sizes, colors, cell }
}

/**
 * Griglia colori × taglie. In sola lettura mostra le quantità con totali; in modifica ogni cella è un campo.
 * values: { variantId: number }
 */
export function VariantGrid({ variants, values, onChange, minStock, compact }: {
  variants: Variant[]
  values: Record<string, number | string | undefined>
  onChange?: (variantId: string, value: number | string) => void
  minStock?: number | null
  compact?: boolean
}) {
  const { sizes, colors, cell } = gridAxes(variants)
  const num = (v: any) => (v === '' || v === undefined || v === null ? 0 : Number(v))
  const rowTotal = (c: string) => sizes.reduce((t, s) => { const v = cell(c, s); return t + (v ? num(values[v.id]) : 0) }, 0)
  const colTotal = (s: string) => colors.reduce((t, c) => { const v = cell(c, s); return t + (v ? num(values[v.id]) : 0) }, 0)
  const total = variants.reduce((t, v) => t + num(values[v.id]), 0)
  return (
    <Table.ScrollContainer minWidth={Math.max(320, 110 + sizes.length * (onChange ? 84 : 64))}>
      <Table withColumnBorders withTableBorder verticalSpacing={compact ? 2 : 6} ta="center" style={{ tableLayout: 'fixed' }}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={110} />
            {sizes.map((s) => <Table.Th key={s} ta="center">{s}</Table.Th>)}
            <Table.Th ta="center" w={70} c="dimmed">Totale</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {colors.map((c) => (
            <Table.Tr key={c}>
              <Table.Td ta="left" fw={600}>{c}</Table.Td>
              {sizes.map((s) => {
                const v = cell(c, s)
                if (!v) return <Table.Td key={s} bg="var(--mantine-color-gray-1)" />
                const val = values[v.id]
                if (onChange) {
                  return (
                    <Table.Td key={s} p={4}>
                      <NumberInput size="xs" hideControls value={val === undefined ? '' : val} min={0} placeholder="0"
                        onChange={(x) => onChange(v.id, x)} styles={{ input: { textAlign: 'center' } }} aria-label={`${c} ${s}`} />
                    </Table.Td>
                  )
                }
                const n = num(val)
                const low = minStock != null && n < minStock
                return (
                  <Table.Td key={s} fw={n ? 600 : 400} c={n < 0 ? 'red' : n === 0 ? 'dimmed' : low ? 'orange' : undefined}>
                    {n ? n.toLocaleString('it-IT') : '·'}
                  </Table.Td>
                )
              })}
              <Table.Td fw={700}>{rowTotal(c).toLocaleString('it-IT')}</Table.Td>
            </Table.Tr>
          ))}
          <Table.Tr>
            <Table.Td ta="left"><Text size="sm" c="dimmed">Totale</Text></Table.Td>
            {sizes.map((s) => <Table.Td key={s} fw={700}>{colTotal(s).toLocaleString('it-IT')}</Table.Td>)}
            <Table.Td fw={800}>{total.toLocaleString('it-IT')}</Table.Td>
          </Table.Tr>
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
