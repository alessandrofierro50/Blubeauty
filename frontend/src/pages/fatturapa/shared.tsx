import { Badge, Tooltip } from '@mantine/core'
import { useOutletContext } from 'react-router-dom'

import { appApi } from '../../api'
import type { AppCtx } from '../app/AppLayout'

export const FE = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/fatturapa' + path, opts)

/** true se il modulo è attivo per l'azienda (pacchetto o modulo extra). */
export function useModule(code: string) {
  const ctx = useOutletContext<AppCtx>()
  return !!ctx?.status?.menu?.find((m: any) => m.code === code && m.enabled)
}

export const SDI_LABEL: Record<string, string> = {
  da_inviare: 'Da inviare', presa_in_carico: 'Presa in carico', errore_elaborazione: 'Errore', inviata: 'Inviata a SDI',
  scartata: 'Scartata', non_consegnata: 'Nel cassetto fiscale', recapito_impossibile: 'Recapito impossibile', consegnata: 'Consegnata',
  accettata: 'Accettata', rifiutata: 'Rifiutata', decorrenza_termini: 'Decorrenza termini',
}
export const SDI_COLOR: Record<string, string> = {
  da_inviare: 'gray', presa_in_carico: 'blue', errore_elaborazione: 'red', inviata: 'blue', scartata: 'red', non_consegnata: 'yellow',
  recapito_impossibile: 'orange', consegnata: 'green', accettata: 'green', rifiutata: 'red', decorrenza_termini: 'green',
}
export const SDI_HELP: Record<string, string> = {
  non_consegnata: 'SDI non è riuscito a recapitarla: è comunque emessa e il cliente la trova nel suo cassetto fiscale. Mandagli una copia.',
  scartata: 'SDI l\'ha scartata: correggi i dati indicati e reinviala entro 5 giorni con lo stesso numero e la stessa data.',
  errore_elaborazione: 'Aruba non l\'ha trasmessa: correggi e reinviala.',
  rifiutata: 'La Pubblica Amministrazione l\'ha rifiutata: emetti una nota di credito o reinviala corretta.',
}
export const RESENDABLE = ['da_inviare', 'errore_elaborazione', 'scartata', 'rifiutata']

export function SdiBadge({ status }: { status?: string | null }) {
  if (!status) return null
  return (
    <Tooltip label={SDI_HELP[status] ?? SDI_LABEL[status]} multiline w={260} disabled={!SDI_HELP[status]}>
      <Badge size="xs" variant="light" color={SDI_COLOR[status] ?? 'gray'}>SDI · {SDI_LABEL[status] ?? status}</Badge>
    </Tooltip>
  )
}

export const NOTIFY_LABEL: Record<string, string> = {
  RC: 'Ricevuta di consegna', NS: 'Notifica di scarto', MC: 'Mancata consegna', AT: 'Impossibilità di recapito',
  NE: 'Esito del committente', DT: 'Decorrenza termini', MT: 'Metadati',
}
