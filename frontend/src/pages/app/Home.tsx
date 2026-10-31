import { Badge, Button, Group, Paper, SimpleGrid, Text, ThemeIcon, Title } from '@mantine/core'
import { IconCalendarEvent, IconCheck, IconFileInvoice, IconFileText, IconLock, IconTruckDelivery } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { PageTitle, StatusBadge } from '../../components'
import type { AppCtx } from './AppLayout'

export default function Home() {
  const { me, status } = useOutletContext<AppCtx>()
  const nav = useNavigate()
  const has = (code: string) => status.menu.some((m: any) => m.code === code && m.enabled)
  const [k, setK] = useState<any>(null)
  const [ag, setAg] = useState<any>(null)
  useEffect(() => { if (has('statistiche_base')) appApi('/api/statistiche/riepilogo').then(setK).catch(() => {}) }, [])
  useEffect(() => { if (has('agenda')) appApi('/api/agenda/riepilogo').then(setAg).catch(() => {}) }, [])
  const hour = new Date().getHours()
  const growth = k && Number(k.previous_year.revenue) ? (Number(k.year.revenue) / Number(k.previous_year.revenue) - 1) * 100 : null
  return (
    <>
      <PageTitle title={`${hour < 13 ? 'Buongiorno' : hour < 18 ? 'Buon pomeriggio' : 'Buonasera'}, ${me.user.full_name.split(' ')[0]}`} subtitle={me.tenant.name}
        right={<Group>
          {has('agenda') && <Button leftSection={<IconCalendarEvent size={16} />} onClick={() => nav('/agenda')}>Agenda</Button>}
          {has('vendite') && <Button variant="default" leftSection={<IconFileInvoice size={16} />} onClick={() => nav('/vendite/nuovo?tipo=FTI')}>Fattura</Button>}
          {has('acquisti') && <Button variant="default" leftSection={<IconTruckDelivery size={16} />} onClick={() => nav('/acquisti/nuovo?tipo=DDTF')}>Carico prodotti</Button>}
        </Group>} />
      {ag && (
        <SimpleGrid cols={{ base: 2, md: 4 }} mb="lg">
          <Paper withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav('/agenda')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Appuntamenti oggi</Text>
            <Title order={3} mt={6}>{ag.today}</Title>
            <Text size="sm" c="dimmed">{ag.to_collect} da incassare</Text>
          </Paper>
          <Paper withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav('/agenda')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Incasso previsto oggi</Text>
            <Title order={3} mt={6}>{fmtEuro(ag.expected)}</Title>
          </Paper>
          <Paper withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav('/marketing')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Prenotazioni online</Text>
            <Title order={3} mt={6}>{ag.online_30}</Title>
            <Text size="sm" c="dimmed">ultimi 30 giorni</Text>
          </Paper>
          <Paper withBorder p="md">
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Il tuo link di prenotazione</Text>
            <Text size="sm" mt={8} style={{ wordBreak: 'break-all' }}><a href={ag.booking_url} target="_blank" rel="noreferrer">{ag.booking_url}</a></Text>
          </Paper>
        </SimpleGrid>
      )}
      {k && (
        <SimpleGrid cols={{ base: 2, md: 4 }} mb="lg">
          <Paper withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav('/statistiche')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Fatturato del mese</Text>
            <Title order={3} mt={6}>{fmtEuro(k.month.revenue)}</Title>
            <Text size="sm" c="dimmed">{k.month.invoices} fatture</Text>
          </Paper>
          <Paper withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav('/statistiche')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Fatturato dell'anno</Text>
            <Title order={3} mt={6}>{fmtEuro(k.year.revenue)}</Title>
            {growth != null ? <Text size="sm" c={growth >= 0 ? 'green' : 'red'}>{growth >= 0 ? '+' : ''}{growth.toFixed(1).replace('.', ',')}% sull'anno scorso</Text> : <Text size="sm" c="dimmed">imponibile</Text>}
          </Paper>
          <Paper withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav('/scadenzario?direzione=attiva')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Da incassare</Text>
            <Title order={3} mt={6}>{fmtEuro(k.receivables.open)}</Title>
            <Text size="sm" c={Number(k.receivables.overdue) > 0 ? 'red' : 'dimmed'}>{Number(k.receivables.overdue) > 0 ? `scaduto ${fmtEuro(k.receivables.overdue)}` : 'nulla di scaduto'}</Text>
          </Paper>
          <Paper withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav('/scadenzario/liquidita')}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Liquidità</Text>
            <Title order={3} mt={6}>{fmtEuro(k.liquidity)}</Title>
            <Text size="sm" c="dimmed">da pagare {fmtEuro(k.payables.open)}</Text>
          </Paper>
        </SimpleGrid>
      )}
      <SimpleGrid cols={{ base: 1, md: 3 }} mb="lg">
        <Paper withBorder p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Abbonamento</Text>
          <Group mt={6}><Title order={3}>{status.plan_name}</Title></Group>
          <Group mt={6}><StatusBadge status={status.status} label={status.status_label} /></Group>
        </Paper>
        <Paper withBorder p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Scadenza</Text>
          <Title order={3} mt={6}>{fmtDate(status.end_date)}</Title>
          <Text size="sm" c="dimmed">{status.days_left >= 0 ? `tra ${status.days_left} giorni` : 'scaduto'}</Text>
        </Paper>
        <Paper withBorder p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Utenti consentiti</Text>
          <Title order={3} mt={6}>{status.limits.max_users}</Title>
        </Paper>
      </SimpleGrid>
      <Paper withBorder p="md">
        <Title order={4} mb="sm">I tuoi moduli</Title>
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          {status.menu.map((m: any) => (
            <Group key={m.code} gap="sm" wrap="nowrap">
              <ThemeIcon variant="light" color={m.enabled ? 'green' : 'gray'} radius="xl">
                {m.enabled ? <IconCheck size={16} /> : <IconLock size={16} />}
              </ThemeIcon>
              <div>
                <Text size="sm" fw={500} c={m.enabled ? undefined : 'dimmed'}>{m.label}</Text>
                {!m.enabled && <Badge size="xs" variant="outline" color="gray">{m.extra ? 'modulo extra' : 'pacchetto superiore'}</Badge>}
              </div>
            </Group>
          ))}
        </SimpleGrid>
      </Paper>
    </>
  )
}
