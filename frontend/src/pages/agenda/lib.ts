// Tipi e utilità condivise dalle pagine dell'agenda.
export type Staff = { id: string; first_name: string; last_name: string; color: string; active: boolean; bookable_online: boolean; sort_order: number; working_hours: Record<string, string[][]>; working_hours_b?: Record<string, string[][]>; alt_week_a?: string | null }
export type Service = { id: string; name: string; category_id: string | null; price: string; duration_min: number; processing_start_min: number | null; processing_min: number | null; staff_ids: string[]; resource_ids: string[]; bookable_online: boolean; active: boolean; description: string | null; vat_rate_id: string | null; department_id: string | null; recall_days: number | null; sort_order: number }
export type Item = { id: string; service_id: string; service: string; staff_id: string | null; resource_id: string | null; starts_at: string; ends_at: string; price: string; processing_start_min: number | null; processing_min: number | null }
export type Appointment = { id: string; party_id: string | null; client: string | null; client_mobile: string | null; starts_at: string; ends_at: string; status: string; channel: string; notes: string | null; document_id: string | null; total: string; items: Item[]; messages?: Msg[]; public_url?: string; document?: any }
export type Msg = { id: string; kind: string; channel: string; to: string; body: string; status: string; inbound: boolean; created_at: string; error: string | null }

export const STATUS: Record<string, { label: string; color: string }> = {
  prenotato: { label: 'Prenotato', color: 'gray' },
  confermato: { label: 'Confermato', color: 'blu' },
  arrivato: { label: 'In salone', color: 'yellow' },
  concluso: { label: 'Concluso', color: 'grape' },
  pagato: { label: 'Pagato', color: 'green' },
  disdetto: { label: 'Disdetto', color: 'red' },
  non_presentato: { label: 'Non presentato', color: 'red' },
}

export const CHANNEL: Record<string, string> = { salone: 'Inserito dal salone', online: 'Prenotazione online (smartphone)', telefono: 'Telefono', whatsapp: 'WhatsApp' }

export const DAYS: [string, string][] = [['mon', 'Lunedì'], ['tue', 'Martedì'], ['wed', 'Mercoledì'], ['thu', 'Giovedì'], ['fri', 'Venerdì'], ['sat', 'Sabato'], ['sun', 'Domenica']]

export const KIND_LABEL: Record<string, string> = {
  conferma: 'Conferma', promemoria: 'Promemoria', disdetta: 'Disdetta', grazie: 'Grazie + recensione', richiamo: 'Richiamo',
  compleanno: 'Compleanno', clienti_persi: 'Clienti persi', campagna: 'Campagna',
}

export const hhmm = (iso: string) => new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Rome' })
export const longDay = (d: Date | string) => new Date(d).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Rome' })
export const minutesOf = (iso: string) => {
  const t = hhmm(iso).split(':').map(Number)
  return t[0] * 60 + t[1]
}
export const dayKey = (d: Date) => ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'][d.getDay()]
