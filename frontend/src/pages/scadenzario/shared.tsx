import { useEffect, useState } from 'react'

import { appApi, tokens } from '../../api'
import { notifyError } from '../../components'

export const SC = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/scadenzario' + path, opts)

export const METHODS: Record<string, string> = {
  MP01: 'Contanti', MP02: 'Assegno', MP03: 'Assegno circolare', MP05: 'Bonifico', MP08: 'Carta di pagamento',
  MP09: 'RID', MP12: 'Ri.Ba.', MP15: 'Giroconto', MP19: 'SEPA Direct Debit', MP23: 'PagoPA',
}
export const methodOptions = Object.entries(METHODS).map(([value, label]) => ({ value, label }))
export const KIND_LABEL: Record<string, string> = { cassa: 'Cassa', banca: 'Banca', carta: 'Carta', altro: 'Altro' }

export function useAccounts(reloadKey = 0) {
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { SC('/conti').then(setRows).catch(notifyError) }, [reloadKey])
  return rows
}

/** Scarica un file generato dal server (Excel) con l'autenticazione dell'utente. */
export async function download(path: string, filename: string) {
  try {
    const res = await fetch('/api/scadenzario' + path, { headers: { Authorization: `Bearer ${tokens.get('user')}` } })
    if (!res.ok) throw new Error('Esportazione non riuscita')
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) { notifyError(e) }
}

export const eur0 = (v: string | number) => Number(v).toLocaleString('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
