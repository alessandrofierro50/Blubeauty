import { Alert, Anchor, Button, Code, CopyButton, Group, Loader, Paper, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, TextInput, Title, UnstyledButton } from '@mantine/core'
import { IconBuildingBank, IconCheck, IconCircleCheck, IconCircleX, IconCopy, IconCreditCard, IconBrandPaypal } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { appApi, downloadFile, fmtDate, fmtEuro } from '../../api'
import { Loading, notifyError, notifyOk } from '../../components'

/* Pagamento dell'abbonamento (contratto comune pagamenti.md): dati di fatturazione, piano, periodicità e metodo.
   Il browser non manda mai un prezzo: gli importi mostrati arrivano dal server e il server li ricalcola al checkout. */

const METHOD_ICON: Record<string, any> = { carta: IconCreditCard, paypal: IconBrandPaypal, bonifico: IconBuildingBank }
const METHOD_HINT: Record<string, string> = {
  carta: 'Pagina sicura di Stripe: anche Google Pay e Apple Pay',
  paypal: 'Con il tuo conto PayPal',
  bonifico: 'Attivazione quando riceviamo l\'accredito',
}
const EMPTY = { tipo: 'azienda', denominazione: '', nome: '', cognome: '', partita_iva: '', codice_fiscale: '', indirizzo: '', cap: '',
  comune: '', provincia: '', nazione: 'IT', codice_destinatario: '', pec: '', email: '' }

export function BillingForm({ initial, onSaved }: { initial: any; onSaved: (d: any) => void }) {
  const [f, setF] = useState<any>({ ...EMPTY, ...(initial ?? {}) })
  const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: any) => setF({ ...f, [k]: typeof e === 'string' || e === null ? e : e.currentTarget.value })
  async function save() {
    setBusy(true)
    try {
      const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v === '' ? null : v]))
      const r = await appApi('/api/app/pagamenti/dati-fatturazione', { method: 'PUT', body })
      notifyOk('Dati di fatturazione salvati')
      onSaved(r.dati_fatturazione)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  const priv = f.tipo === 'privato'
  return (
    <Stack gap="sm">
      <SegmentedControl value={f.tipo} onChange={(v) => setF({ ...f, tipo: v })}
        data={[{ value: 'azienda', label: 'Azienda o professionista' }, { value: 'privato', label: 'Privato' }, { value: 'pa', label: 'Pubblica amministrazione' }]} />
      {priv ? (
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput label="Nome" required value={f.nome} onChange={set('nome')} />
          <TextInput label="Cognome" required value={f.cognome} onChange={set('cognome')} />
        </SimpleGrid>
      ) : <TextInput label={f.tipo === 'pa' ? 'Ente' : 'Ragione sociale'} required value={f.denominazione} onChange={set('denominazione')} />}
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {!priv && <TextInput label="Partita IVA" required={f.tipo === 'azienda'} value={f.partita_iva} onChange={set('partita_iva')} />}
        <TextInput label="Codice fiscale" required={f.tipo !== 'azienda'} value={f.codice_fiscale} onChange={set('codice_fiscale')} />
      </SimpleGrid>
      <TextInput label="Indirizzo" required value={f.indirizzo} onChange={set('indirizzo')} />
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <TextInput label="CAP" required value={f.cap} onChange={set('cap')} />
        <TextInput label="Comune" required value={f.comune} onChange={set('comune')} />
        <TextInput label="Provincia" required maxLength={2} value={f.provincia} onChange={set('provincia')} />
        <TextInput label="Nazione" maxLength={2} value={f.nazione} onChange={set('nazione')} />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <TextInput label={f.tipo === 'pa' ? 'Codice univoco ufficio (6 caratteri)' : 'Codice destinatario SDI'} maxLength={7}
          description={priv ? 'Vuoto = 0000000' : f.tipo === 'pa' ? undefined : '7 caratteri, oppure indica la PEC'}
          value={f.codice_destinatario} onChange={set('codice_destinatario')} />
        {f.tipo !== 'pa' && <TextInput label="PEC" value={f.pec} onChange={set('pec')} />}
      </SimpleGrid>
      <TextInput label="Email per la ricevuta" description="Vuoto = email dell'azienda" value={f.email} onChange={set('email')} />
      <Group justify="flex-end"><Button loading={busy} onClick={save}>Salva i dati</Button></Group>
    </Stack>
  )
}

function TransferBox({ b, onBack }: { b: any; onBack?: () => void }) {
  const rows: [string, string][] = [['Intestatario', b.intestatario], ['IBAN', b.iban], ['Importo', fmtEuro(b.importo)], ['Causale', b.causale]]
  return (
    <Paper withBorder p="md">
      <Title order={4} mb={4}>Dati per il bonifico</Title>
      <Text size="sm" c="dimmed" mb="sm">Indica esattamente questa causale. L'abbonamento si rinnova quando confermiamo l'accredito
        (di solito 1–2 giorni lavorativi): fino ad allora non viene emesso nessun documento. Ricevuta e fattura arrivano per email dopo la conferma.</Text>
      <Table withRowBorders={false}>
        <Table.Tbody>
          {rows.map(([k, v]) => (
            <Table.Tr key={k}>
              <Table.Td c="dimmed" w={120}>{k}</Table.Td>
              <Table.Td><Code fz="sm">{v}</Code></Table.Td>
              <Table.Td w={40}>
                <CopyButton value={k === 'Importo' ? String(b.importo).replace('.', ',') : v}>
                  {({ copied, copy }) => <UnstyledButton onClick={copy} aria-label={`Copia ${k}`}>{copied ? <IconCheck size={16} /> : <IconCopy size={16} />}</UnstyledButton>}
                </CopyButton>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {onBack && <Button variant="subtle" mt="xs" onClick={onBack}>Scegli un altro metodo</Button>}
    </Paper>
  )
}

export default function Payment() {
  const [o, setO] = useState<any>(null)
  const [plan, setPlan] = useState<string | null>(null)
  const [period, setPeriod] = useState('annuale')
  const [method, setMethod] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [transfer, setTransfer] = useState<any>(null)

  const load = () => appApi('/api/app/pagamenti/opzioni').then((d) => {
    setO(d)
    setPlan((p) => p ?? (d.piani.some((x: any) => x.code === d.attuale.piano) ? d.attuale.piano : d.piani[0]?.code ?? null))
    if (d.attuale.periodicita === 'mensile') setPeriod('mensile')
    setMethod((m) => m ?? d.metodi[0]?.code ?? null)
    setEditing(!d.dati_completi)
    setTransfer(d.bonifico_in_attesa?.bonifico ?? null)
  }).catch(notifyError)
  useEffect(() => { load() }, [])
  if (!o) return <Loading />

  const sel = o.piani.find((p: any) => p.code === plan)
  const price = sel?.prezzi?.[period]
  async function pay() {
    setBusy(true)
    try {
      const r = await appApi('/api/app/pagamenti/checkout', { body: { piano: plan, periodicita: period, metodo: method } })
      if (r.redirect_url) { window.location.assign(r.redirect_url); return }
      setTransfer(r.bonifico)
      load()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  return (
    <Stack maw={860}>
      <div>
        <Title order={2}>Rinnova l'abbonamento</Title>
        <Text c="dimmed" size="sm">{o.attuale.scadenza ? `${o.attuale.prova ? 'Fine della prova' : 'Scadenza attuale'}: ${fmtDate(o.attuale.scadenza)}. ` : ''}
          Il nuovo periodo parte dalla fine di quello in corso, o da oggi se è già scaduto.</Text>
      </div>

      {o.metodi.length === 0 && <Alert color="yellow">I pagamenti online non sono ancora attivi: contattaci dalla pagina «Abbonamento».</Alert>}

      <Paper withBorder p="md">
        <Group justify="space-between" mb="sm">
          <Title order={4}>1. Dati di fatturazione</Title>
          {!editing && <Anchor size="sm" onClick={() => setEditing(true)}>Modifica</Anchor>}
        </Group>
        {editing ? <BillingForm initial={o.dati_fatturazione} onSaved={() => load()} /> : (
          <Text size="sm">{o.dati_fatturazione.tipo === 'privato' ? `${o.dati_fatturazione.nome} ${o.dati_fatturazione.cognome}` : o.dati_fatturazione.denominazione}
            {' · '}{o.dati_fatturazione.partita_iva ? `P.IVA ${o.dati_fatturazione.partita_iva}` : `C.F. ${o.dati_fatturazione.codice_fiscale}`}
            {' · '}{o.dati_fatturazione.indirizzo}, {o.dati_fatturazione.cap} {o.dati_fatturazione.comune}
            {' · '}{o.dati_fatturazione.codice_destinatario ? `SDI ${o.dati_fatturazione.codice_destinatario}` : `PEC ${o.dati_fatturazione.pec}`}</Text>
        )}
      </Paper>

      {transfer ? <TransferBox b={transfer} onBack={() => setTransfer(null)} /> : (
        <Paper withBorder p="md" style={{ opacity: o.dati_completi && o.metodi.length ? 1 : 0.55 }}>
          <Title order={4} mb="sm">2. Piano e pagamento</Title>
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select label="Piano" value={plan} onChange={setPlan} allowDeselect={false}
                data={o.piani.map((p: any) => ({ value: p.code, label: p.name }))} />
              <div>
                <Text size="sm" fw={500} mb={4}>Periodicità</Text>
                <SegmentedControl fullWidth value={period} onChange={setPeriod}
                  data={[{ value: 'mensile', label: 'Mensile', disabled: !sel?.prezzi?.mensile }, { value: 'annuale', label: 'Annuale', disabled: !sel?.prezzi?.annuale }]} />
              </div>
            </SimpleGrid>
            <SimpleGrid cols={{ base: 1, sm: 3 }}>
              {o.metodi.map((m: any) => {
                const Icon = METHOD_ICON[m.code]
                const on = method === m.code
                return (
                  <UnstyledButton key={m.code} onClick={() => setMethod(m.code)} aria-pressed={on}>
                    <Paper withBorder p="sm" style={{ borderColor: on ? 'var(--mantine-color-blu-6)' : undefined, borderWidth: on ? 2 : 1 }}>
                      <Group gap="xs" wrap="nowrap"><Icon size={20} /><Text fw={600}>{m.label}</Text></Group>
                      <Text size="xs" c="dimmed" mt={4}>{METHOD_HINT[m.code]}</Text>
                    </Paper>
                  </UnstyledButton>
                )
              })}
            </SimpleGrid>
            {price && (
              <Paper bg="var(--mantine-color-default-hover)" p="sm">
                <Group justify="space-between"><Text size="sm">Canone {period}</Text><Text size="sm">{fmtEuro(price.importo)}</Text></Group>
                {Number(price.bollo) > 0 && <Group justify="space-between"><Text size="sm">Rimborso imposta di bollo</Text><Text size="sm">{fmtEuro(price.bollo)}</Text></Group>}
                <Group justify="space-between" mt={4}><Text fw={700}>Totale</Text><Text fw={800} fz="lg">{fmtEuro(price.totale)}</Text></Group>
                <Text size="xs" c="dimmed">Operazione senza IVA (regime forfettario).</Text>
              </Paper>
            )}
            <Group justify="flex-end">
              <Button size="md" loading={busy} disabled={!o.dati_completi || !method || !price} onClick={pay}>
                {method === 'bonifico' ? 'Mostra i dati per il bonifico' : `Paga ${price ? fmtEuro(price.totale) : ''}`}
              </Button>
            </Group>
          </Stack>
        </Paper>
      )}

      {o.pagamenti.length > 0 && <PaymentsTable rows={o.pagamenti} />}
    </Stack>
  )
}

export function PaymentsTable({ rows }: { rows: any[] }) {
  return (
    <Paper withBorder>
      <Title order={4} p="md" pb={0}>I tuoi pagamenti</Title>
      <Table.ScrollContainer minWidth={560}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Piano</Table.Th><Table.Th>Metodo</Table.Th><Table.Th>Stato</Table.Th><Table.Th ta="right">Totale</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>{fmtDate((p.pagato_il ?? p.creato_il)?.slice(0, 10))}</Table.Td>
                <Table.Td>{p.piano_nome} · {p.periodicita}</Table.Td>
                <Table.Td>{p.metodo_label}</Table.Td>
                <Table.Td>{p.stato_label}</Table.Td>
                <Table.Td ta="right">{fmtEuro(p.totale)}</Table.Td>
                <Table.Td>{p.ha_pdf && <Anchor size="sm" onClick={() => downloadFile('user', `/api/app/pagamenti/${p.id}/pdf`, `Proforma_${p.fattura.replace('/', '_')}.pdf`).catch(notifyError)}>Proforma {p.fattura}</Anchor>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Paper>
  )
}

/** Pagine di esito «Pagamento riuscito» / «Pagamento annullato»: attende la conferma del gestore (webhook). */
export function PaymentResult() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const id = params.get('id')
  const outcome = params.get('stato')
  const [p, setP] = useState<any>(null)
  const [tries, setTries] = useState(0)
  useEffect(() => {
    if (!id || outcome !== 'ok') return
    let stop = false
    const tick = async (n: number) => {
      try {
        const r = await appApi(`/api/app/pagamenti/${id}`)
        if (stop) return
        setP(r)
        setTries(n)
        if (r.stato === 'in_attesa' && n < 30) setTimeout(() => tick(n + 1), 2000)
      } catch { /* la pagina resta com'è */ }
    }
    tick(0)
    return () => { stop = true }
  }, [id, outcome])

  if (outcome !== 'ok') {
    return (
      <Stack maw={560} align="flex-start">
        <Group gap="xs"><IconCircleX size={32} color="var(--mantine-color-red-6)" /><Title order={2}>Pagamento annullato</Title></Group>
        <Text>{outcome === 'errore' ? 'Il pagamento non è andato a buon fine.' : 'Non è stato addebitato nulla.'} Puoi riprovare quando vuoi, anche con un altro metodo.</Text>
        <Button onClick={() => nav('/pagamento')}>Torna al pagamento</Button>
      </Stack>
    )
  }
  const done = p?.stato === 'pagato'
  return (
    <Stack maw={560} align="flex-start">
      {done ? (
        <>
          <Group gap="xs"><IconCircleCheck size={32} color="var(--mantine-color-green-6)" /><Title order={2}>Pagamento riuscito</Title></Group>
          <Text>Grazie! Abbonamento {p.piano_nome} rinnovato dal {fmtDate(p.periodo?.dal)} al {fmtDate(p.periodo?.al)}.
            La ricevuta con la proforma della fattura {p.fattura} arriva per email.</Text>
          <Group><Button onClick={() => window.location.assign('/')}>Vai al gestionale</Button><Button variant="light" onClick={() => nav('/abbonamento')}>Abbonamento</Button></Group>
        </>
      ) : p?.stato === 'fallito' ? (
        <>
          <Group gap="xs"><IconCircleX size={32} color="var(--mantine-color-red-6)" /><Title order={2}>Pagamento non riuscito</Title></Group>
          <Button onClick={() => nav('/pagamento')}>Riprova</Button>
        </>
      ) : (
        <>
          <Group gap="xs"><Loader size="sm" /><Title order={2}>Stiamo confermando il pagamento…</Title></Group>
          <Text c="dimmed">Aspettiamo la conferma di {p?.metodo_label ?? 'Stripe o PayPal'}: di solito bastano pochi secondi.
            {tries >= 30 && ' Sta richiedendo più del solito: riceverai comunque un\'email appena confermato.'}</Text>
        </>
      )}
    </Stack>
  )
}
