import { Alert, Anchor, Badge, Button, Group, Paper, Progress, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { IconMail, IconPhone, IconWorld } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, PlanBadge, StatusBadge, notifyError } from '../../components'
import { BillingForm, PaymentsTable } from './Payment'

const PERIODS: Record<string, string> = { mensile: 'Mensile', annuale: 'Annuale', personalizzata: 'Personalizzata' }
const LIMITS: [string, string][] = [['max_users', 'Utenti'], ['max_companies', 'Ragioni sociali'], ['max_warehouses', 'Magazzini'], ['max_pos', 'Postazioni cassa']]

/** Pagina «Abbonamento» (standard comune §5): raggiungibile anche con l'abbonamento sospeso o la prova scaduta. */
export default function Subscription() {
  const [d, setD] = useState<any>(null)
  const [pay, setPay] = useState<any>(null)
  const [editBilling, setEditBilling] = useState(false)
  const nav = useNavigate()
  const loadPay = () => appApi('/api/app/pagamenti/opzioni').then(setPay).catch(() => {})
  useEffect(() => {
    appApi('/api/app/abbonamento').then((x) => { setD(x); if (x.is_admin) loadPay() }).catch(notifyError)
  }, [])
  if (!d) return <Loading />

  const days = d.days_left as number | null
  const when = days == null ? '' : days > 0 ? `tra ${days} giorni` : days === 0 ? 'oggi' : `scaduto da ${-days} giorni`
  const blocked = d.access === 'none'
  return (
    <Stack maw={1000}>
      <div>
        <Title order={2}>Abbonamento</Title>
        <Text c="dimmed" size="sm">{d.tenant}</Text>
      </div>

      {d.status === 'prova_scaduta' && <Alert color="red" title="La prova gratuita è terminata">
        I tuoi dati restano conservati per 30 giorni. Contattaci per attivare l'abbonamento: riparti esattamente da dove eri.</Alert>}
      {d.status === 'sospeso' && <Alert color="red" title="Accesso sospeso">
        I tuoi dati restano conservati. Contattaci per rinnovare l'abbonamento e tornare a usare il gestionale.</Alert>}
      {d.status === 'sola_lettura' && <Alert color="red">L'abbonamento è scaduto: puoi consultare ed esportare i dati, ma non inserirne di nuovi.
        Dopo {d.readonly_days} giorni di sola lettura l'accesso viene sospeso.</Alert>}
      {d.status === 'tolleranza' && <Alert color="red">L'abbonamento è scaduto: hai ancora accesso completo per {d.grace_days} giorni dalla scadenza, poi il gestionale passa in sola lettura.</Alert>}

      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Paper withBorder p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Piano</Text>
          <Group gap="xs" mt={4}><Text fz={20} fw={800}>{d.plan_name ?? '—'}</Text><PlanBadge code={d.plan_code} /></Group>
          <Text size="xs" c="dimmed">{d.is_trial ? 'Prova gratuita' : PERIODS[d.period] ?? ''}{d.amount != null && !d.is_trial ? ` · ${fmtEuro(d.amount)}` : ''}</Text>
        </Paper>
        <Paper withBorder p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Stato</Text>
          <Group mt={6}><StatusBadge status={d.status} label={d.status_label} /></Group>
        </Paper>
        <Paper withBorder p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{d.is_trial ? 'Fine della prova' : 'Scadenza'}</Text>
          <Text fz={20} fw={800}>{fmtDate(d.end_date)}</Text>
          <Text size="xs" c={days != null && days < 0 ? 'red' : 'dimmed'}>{when}</Text>
        </Paper>
      </SimpleGrid>

      {d.is_admin && d.online_payments && (
        <Paper withBorder p="md">
          <Group justify="space-between" wrap="wrap">
            <div>
              <Title order={4} mb={4}>Rinnova online</Title>
              <Text size="sm" c="dimmed">Carta, PayPal o bonifico, mensile o annuale. Il nuovo periodo parte dalla scadenza attuale.</Text>
            </div>
            <Button size="md" onClick={() => nav('/pagamento')}>Rinnova ora</Button>
          </Group>
          {pay?.bonifico_in_attesa && <Alert mt="sm" color="blue">Bonifico in attesa di conferma: {fmtEuro(pay.bonifico_in_attesa.totale)}, causale {pay.bonifico_in_attesa.causale}.
            {' '}<Anchor size="sm" onClick={() => nav('/pagamento')}>Vedi i dati</Anchor></Alert>}
        </Paper>
      )}

      {d.is_admin && pay && (
        <Paper withBorder p="md">
          <Group justify="space-between" mb="xs">
            <Title order={4}>Dati di fatturazione</Title>
            {!editBilling && <Anchor size="sm" onClick={() => setEditBilling(true)}>{pay.dati_fatturazione ? 'Modifica' : 'Inserisci'}</Anchor>}
          </Group>
          {editBilling ? <BillingForm initial={pay.dati_fatturazione} onSaved={() => { setEditBilling(false); loadPay() }} />
            : pay.dati_fatturazione ? <Text size="sm">{pay.dati_fatturazione.denominazione ?? `${pay.dati_fatturazione.nome} ${pay.dati_fatturazione.cognome}`}
              {' · '}{pay.dati_fatturazione.partita_iva ? `P.IVA ${pay.dati_fatturazione.partita_iva}` : `C.F. ${pay.dati_fatturazione.codice_fiscale}`}
              {' · '}{pay.dati_fatturazione.indirizzo}, {pay.dati_fatturazione.cap} {pay.dati_fatturazione.comune}</Text>
              : <Text size="sm" c="dimmed">Servono per la fattura dell'abbonamento: inseriscili prima di pagare.</Text>}
        </Paper>
      )}

      <Paper withBorder p="md">
        <Title order={4} mb={4}>Per rinnovare o cambiare piano</Title>
        <Text size="sm" c="dimmed" mb="sm">{blocked ? 'Scrivici o chiamaci: riattiviamo l\'accesso appena confermato il rinnovo.' : 'Scrivici o chiamaci: ti rispondono direttamente gli sviluppatori.'}</Text>
        <Group gap="xl">
          {d.contacts.email && <Anchor href={`mailto:${d.contacts.email}`}><Group gap={6}><IconMail size={16} />{d.contacts.email}</Group></Anchor>}
          {d.contacts.phone && <Anchor href={`tel:${d.contacts.phone.replace(/\s/g, '')}`}><Group gap={6}><IconPhone size={16} />{d.contacts.phone}</Group></Anchor>}
          {d.contacts.website && <Anchor href={d.contacts.website} target="_blank"><Group gap={6}><IconWorld size={16} />{d.contacts.website.replace(/^https?:\/\//, '')}</Group></Anchor>}
        </Group>
      </Paper>

      {d.usage && (
        <Paper withBorder p="md">
          <Title order={4} mb="sm">Uso rispetto ai limiti del piano</Title>
          <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
            {LIMITS.map(([k, label]) => {
              const used = d.usage[k] ?? 0
              const max = d.limits?.[k]
              const pct = max ? Math.min(100, (used / max) * 100) : 0
              return (
                <div key={k}>
                  <Group justify="space-between"><Text size="sm">{label}</Text><Text size="sm" fw={600}>{used} / {max ?? '—'}</Text></Group>
                  <Progress value={pct} color={pct >= 100 ? 'red' : pct >= 80 ? 'yellow' : 'blu'} mt={4} />
                </div>
              )
            })}
          </SimpleGrid>
        </Paper>
      )}

      {d.history && (
        <Paper withBorder>
          <Title order={4} p="md" pb={0}>Storico dei periodi</Title>
          <Table.ScrollContainer minWidth={520}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Piano</Table.Th><Table.Th>Dal</Table.Th><Table.Th>Al</Table.Th><Table.Th>Periodicità</Table.Th><Table.Th ta="right">Importo</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {d.history.map((h: any, i: number) => (
                  <Table.Tr key={i}>
                    <Table.Td><Group gap={6}>{h.plan_name}{h.is_trial && <Badge size="xs" variant="outline" color="cyan">prova</Badge>}</Group></Table.Td>
                    <Table.Td>{fmtDate(h.start_date)}</Table.Td>
                    <Table.Td>{fmtDate(h.end_date)}</Table.Td>
                    <Table.Td>{h.is_trial ? '—' : PERIODS[h.period] ?? h.period}</Table.Td>
                    <Table.Td ta="right">{h.is_trial ? 'gratuita' : fmtEuro(h.amount)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {pay?.pagamenti?.length > 0 && <PaymentsTable rows={pay.pagamenti} />}
      <Text size="xs" c="dimmed">{d.online_payments ? 'Operazioni senza IVA (regime forfettario). Ricevuta e proforma arrivano per email a pagamento confermato.'
        : 'Importi IVA esclusa. Pagamenti online non ancora disponibili: il rinnovo si concorda con BluCode Informatica.'}</Text>
    </Stack>
  )
}
