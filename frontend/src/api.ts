// Client HTTP minimo. Due sessioni separate: super amministratore e utente azienda.

export type Scope = 'admin' | 'user'

const KEY: Record<Scope, string> = { admin: 'blubeauty_admin_token', user: 'blubeauty_user_token' }

function store(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export const tokens = {
  get: (s: Scope) => store()?.getItem(KEY[s]) ?? null,
  set: (s: Scope, t: string) => store()?.setItem(KEY[s], t),
  clear: (s: Scope) => store()?.removeItem(KEY[s]),
}

export class ApiError extends Error {
  status: number
  code?: string
  detail?: any
  constructor(status: number, message: string, code?: string, detail?: any) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

export async function api<T = any>(scope: Scope, path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const t = tokens.get(scope)
  if (t) headers.Authorization = `Bearer ${t}`
  const res = await fetch(path, {
    method: opts.method ?? (opts.body ? 'POST' : 'GET'),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const d = data?.detail
    let message = 'Errore imprevisto'
    let code: string | undefined
    if (typeof d === 'string') message = d
    else if (d && typeof d === 'object' && 'message' in d) {
      message = d.message
      code = d.code
    } else if (Array.isArray(d)) message = 'Controlla i campi inseriti'
    if (res.status === 401 && scope && !path.endsWith('/login')) {
      tokens.clear(scope)
    }
    // password provvisoria non ancora cambiata (anche da /cassa o /giro): si torna al gestionale, che chiede il cambio
    if (res.status === 403 && code === 'cambio_password' && window.location.pathname !== '/') window.location.assign('/')
    // abbonamento sospeso o prova scaduta (anche da /cassa o /giro): il gestionale mostra solo la pagina «Abbonamento»
    if (res.status === 402 && scope === 'user' && (code === 'abbonamento_sospeso' || code === 'prova_scaduta')
      && window.location.pathname !== '/') window.location.assign('/')
    throw new ApiError(res.status, message, code, d)
  }
  return data as T
}

export const adminApi = <T = any>(path: string, opts?: { method?: string; body?: unknown }) => api<T>('admin', '/api/admin' + path, opts)
export const appApi = <T = any>(path: string, opts?: { method?: string; body?: unknown }) => api<T>('user', path, opts)

export const fmtDate = (iso?: string | null) => (iso ? new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('it-IT') : '—')
export const fmtEuro = (v: string | number) => Number(v).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' })
export const isoDate = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** Scarica un file generato dal server con l'autenticazione della sessione indicata. */
export async function downloadFile(scope: Scope, path: string, filename: string) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${tokens.get(scope)}` } })
  if (!res.ok) throw new ApiError(res.status, 'Scaricamento non riuscito')
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
