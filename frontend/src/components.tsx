import { Badge, Center, Group, Loader, Paper, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { brand } from './brand'

export function Logo({ size = 32, withName = true }: { size?: number; withName?: boolean }) {
  return (
    <Group gap={10} wrap="nowrap">
      <img src={brand.logo} width={size} height={size} alt="" />
      {withName && (
        <Text fw={800} size={size > 36 ? 'xl' : 'lg'} c={`light-dark(${brand.colors.dark}, #FFFFFF)`} style={{ letterSpacing: -0.3, fontFamily: 'Archivo, sans-serif' }}>
          Blu<span style={{ color: `light-dark(${brand.colors.primary}, #7FB2F0)`, fontWeight: 400 }}>Beauty</span>
        </Text>
      )}
    </Group>
  )
}

const STATUS_COLORS: Record<string, string> = {
  prova: 'cyan',
  attivo: 'green',
  in_scadenza: 'yellow',
  tolleranza: 'orange',
  sola_lettura: 'red',
  sospeso: 'gray',
  prova_scaduta: 'gray',
  programmato: 'blue',
}

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <Badge color={STATUS_COLORS[status] ?? 'gray'} variant="light">
      {label}
    </Badge>
  )
}

export function PlanBadge({ code }: { code?: string | null }) {
  if (!code) return <Badge variant="outline" color="gray">—</Badge>
  const color = code === 'SALONE' ? 'blu' : code === 'AGENDA' ? 'teal' : 'gray'
  return <Badge color={color}>{code}</Badge>
}

export function PageTitle({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <Group justify="space-between" align="flex-end" mb="lg" wrap="wrap">
      <Stack gap={2}>
        <Title order={2}>{title}</Title>
        {subtitle && <Text c="dimmed" size="sm">{subtitle}</Text>}
      </Stack>
      {right}
    </Group>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Paper withBorder p="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text fz={28} fw={800} mt={4}>{value}</Text>
      {hint && <Text size="xs" c="dimmed">{hint}</Text>}
    </Paper>
  )
}

export function Loading() {
  return (
    <Center h={200}>
      <Loader />
    </Center>
  )
}

export function notifyError(e: unknown) {
  notifications.show({ color: 'red', title: 'Errore', message: e instanceof Error ? e.message : String(e) })
}

export function notifyOk(message: string) {
  notifications.show({ color: 'green', message })
}


/** Posto nella barra in alto (accanto al pacchetto) dove una pagina può mettere il suo pulsante principale. */
export const HEADER_ACTION_ID = 'header-action'

export function HeaderAction({ children }: { children: ReactNode }) {
  const [el, setEl] = useState<HTMLElement | null>(null)
  useEffect(() => { setEl(document.getElementById(HEADER_ACTION_ID)) }, [])
  return el ? createPortal(children, el) : null
}
