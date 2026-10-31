// Display cliente: seconda finestra (secondo monitor o display rivolto al cliente) aperta dalla cassa sullo stesso computer.
// Riceve righe e totale dalla cassa con BroadcastChannel, senza passare dal server.

import { Box, Group, Stack, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { appApi } from '../../api'
import { euro, qtyFmt } from './shared'

export const displayChannel = (reg: string) => `blubeauty-pos-display-${reg}`

export type DisplayState = {
  lines: { description: string; detail?: string; quantity: number; unit?: string; amount: number }[]
  promos: { description: string; amount: number }[]
  total: number; refund: boolean; last: { total: number; change: number } | null; promotions: string[]
}

export default function Display() {
  const { id } = useParams()
  const [st, setSt] = useState<DisplayState | null>(null)
  const [company, setCompany] = useState<any>(null)
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    appApi('/api/app/intestazione').then(setCompany).catch(() => {})
    const t = setInterval(() => setNow(new Date()), 30000)
    if (typeof BroadcastChannel === 'undefined' || !id) return () => clearInterval(t)
    const ch = new BroadcastChannel(displayChannel(id))
    ch.onmessage = (e) => { if (e.data?.type === 'state') setSt(e.data.state) }
    ch.postMessage({ type: 'hello' })
    return () => { ch.close(); clearInterval(t) }
  }, [id])
  const idle = !st || (!st.lines.length && !st.last)
  const color = company?.print_settings?.primary_color || '#2340a8'
  return (
    <Box h="100vh" style={{ background: '#0f172a', color: 'white', display: 'flex', flexDirection: 'column', overflow: 'hidden', cursor: 'none' }}>
      <Group justify="space-between" px={32} py={16} style={{ background: color }}>
        <Group gap="md">
          {company?.logo_url && <img src={company.logo_url} alt="" style={{ height: 44, background: 'white', borderRadius: 8, padding: 4 }} />}
          <Text fw={700} size="xl">{company?.name ?? ''}</Text>
        </Group>
        <Text size="lg" opacity={0.85}>{now.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</Text>
      </Group>
      {idle ? (
        <Stack flex={1} align="center" justify="center" gap="lg" px={40}>
          <Text style={{ fontSize: 56, fontWeight: 800 }}>Benvenuti</Text>
          {st?.promotions?.length ? (
            <Stack gap={10} align="center">
              <Text size="xl" c="orange.3" fw={700}>Le promozioni di oggi</Text>
              {st.promotions.slice(0, 5).map((p) => <Text key={p} style={{ fontSize: 26 }}>{p}</Text>)}
            </Stack>
          ) : null}
        </Stack>
      ) : !st!.lines.length && st!.last ? (
        <Stack flex={1} align="center" justify="center" gap="md">
          <Text style={{ fontSize: 30 }} opacity={0.8}>Totale pagato</Text>
          <Text style={{ fontSize: 72, fontWeight: 800 }}>{euro(st!.last.total)}</Text>
          {st!.last.change > 0 && <Text style={{ fontSize: 56, fontWeight: 800 }} c="green.4">Resto {euro(st!.last.change)}</Text>}
          <Text style={{ fontSize: 30 }} mt="xl">Grazie e arrivederci!</Text>
        </Stack>
      ) : (
        <>
          <Stack flex={1} px={40} py={24} gap={10} style={{ overflow: 'hidden', justifyContent: 'flex-end' }}>
            {st!.lines.slice(st!.promos.length ? -5 : -7).map((l, i, arr) => (
              <Group key={i} justify="space-between" wrap="nowrap" opacity={i === arr.length - 1 ? 1 : 0.7}>
                <Stack gap={0} style={{ minWidth: 0 }}>
                  <Text style={{ fontSize: i === arr.length - 1 ? 34 : 24 }} fw={i === arr.length - 1 ? 700 : 500} truncate>{l.description}</Text>
                  {(l.quantity !== 1 || l.detail) && <Text size="lg" opacity={0.7}>{[l.detail, l.quantity !== 1 ? `${qtyFmt(l.quantity)}${l.unit && l.unit !== 'PZ' ? ' ' + l.unit.toLowerCase() : ''}` : ''].filter(Boolean).join(' · ')}</Text>}
                </Stack>
                <Text style={{ fontSize: i === arr.length - 1 ? 34 : 24, fontVariantNumeric: 'tabular-nums' }} fw={700}>{euro(l.amount)}</Text>
              </Group>
            ))}
            {st!.promos.map((p, i) => (
              <Group key={'p' + i} justify="space-between" wrap="nowrap">
                <Text style={{ fontSize: 24 }} c="orange.3" truncate>{p.description}</Text>
                <Text style={{ fontSize: 24 }} c="orange.3" fw={700}>{euro(p.amount)}</Text>
              </Group>
            ))}
          </Stack>
          <Group justify="space-between" px={40} py={20} style={{ background: '#020617' }}>
            <Text style={{ fontSize: 36 }} fw={700}>{st!.refund ? 'RIMBORSO' : 'TOTALE'}</Text>
            <Text style={{ fontSize: 72, fontWeight: 800, fontVariantNumeric: 'tabular-nums' }} c={st!.refund ? 'red.4' : 'green.4'}>{euro(st!.total)}</Text>
          </Group>
        </>
      )}
    </Box>
  )
}
