import { Button, Group, Paper, Text, Title } from '@mantine/core'
import { IconCreditCard } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'

import { fmtDate } from '../../api'

/** Aspetto del pulsante di rinnovo secondo lo stato dell'abbonamento: il cliente lo vede sempre, senza cercarlo. */
export function renewInfo(status: any) {
  const trial = status.status === 'prova' || status.status === 'prova_scaduta'
  const expired = ['tolleranza', 'sola_lettura', 'sospeso', 'prova_scaduta'].includes(status.status)
  const soon = status.status === 'in_scadenza' || (status.status === 'prova' && status.days_left != null && status.days_left <= 3)
  const label = trial ? "Attiva l'abbonamento" : 'Rinnova abbonamento'
  const color = expired ? 'red' : soon ? 'orange' : 'blue'
  let text: string
  if (status.status === 'prova_scaduta') text = 'La prova gratuita è terminata. Attiva l\'abbonamento per continuare con i tuoi dati.'
  else if (status.status === 'prova') text = `Prova gratuita: restano ${status.days_left} giorni.`
  else if (status.status === 'sospeso') text = 'L\'abbonamento è sospeso. Rinnova per tornare a lavorare.'
  else if (status.status === 'sola_lettura') text = 'Abbonamento scaduto: il gestionale è in sola lettura. Rinnova per tornare a lavorare.'
  else if (status.status === 'tolleranza') text = 'Abbonamento scaduto: rinnova per evitare la sola lettura.'
  else if (status.days_left != null && status.days_left >= 0) text = `Il tuo abbonamento scade il ${fmtDate(status.end_date)} (tra ${status.days_left} giorni).`
  else text = 'Rinnova il tuo abbonamento online con carta o bonifico.'
  return { label, color, text, expired, soon }
}

/** Pulsante nella testata, sempre visibile all'amministratore. */
export function RenewHeaderButton({ status }: { status: any }) {
  const nav = useNavigate()
  const { label, color } = renewInfo(status)
  return (
    <Button color={color} size="md" fw={700} leftSection={<IconCreditCard size={18} />} onClick={() => nav('/pagamento')} data-testid="rinnova-testata">
      <Text span visibleFrom="sm" inherit>{label}</Text>
      <Text span hiddenFrom="sm" inherit>{label.startsWith('Attiva') ? 'Attiva' : 'Rinnova'}</Text>
    </Button>
  )
}

/** Riquadro grande in cima alla schermata principale. */
export function RenewCard({ status }: { status: any }) {
  const nav = useNavigate()
  const { label, color, text } = renewInfo(status)
  return (
    <Paper withBorder p="lg" mb="lg" style={{ borderColor: `var(--mantine-color-${color}-6)`, borderWidth: 2 }}>
      <Group justify="space-between" wrap="wrap" gap="md">
        <div>
          <Title order={4}>{label}</Title>
          <Text c="dimmed" size="sm">{text}</Text>
        </div>
        <Button color={color} size="lg" fw={700} leftSection={<IconCreditCard size={22} />} onClick={() => nav('/pagamento')} data-testid="rinnova-home">
          {label}
        </Button>
      </Group>
    </Paper>
  )
}
