import { Alert, Anchor, Badge, Button, Checkbox, Code, Drawer, Group, Modal, Paper, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { adminApi, downloadFile, fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'

const STATUS_COLOR: Record<string, string> = { in_attesa: 'yellow', pagato: 'green', fallito: 'red', annullato: 'gray' }
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' }) : '—')

/** Pagamenti degli abbonamenti (contratto comune pagamenti.md): elenco con filtri, conferma o annullo dei bonifici,
 *  XML e proforma da scaricare, reinvio delle email. */
export default function Payments() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [stato, setStato] = useState<string | null>('in_attesa')
  const [metodo, setMetodo] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const load = () => {
    const p = new URLSearchParams()
    if (stato) p.set('stato', stato)
    if (metodo) p.set('metodo', metodo)
    if (q.trim()) p.set('q', q.trim())
    adminApi(`/pagamenti?${p}`).then(setRows).catch(notifyError)
  }
  useEffect(() => { load() }, [stato, metodo])

  return (
    <>
      <PageTitle title="Pagamenti" subtitle="Rinnovi pagati online: carta, PayPal e bonifici da confermare"
        right={<Button variant="light" leftSection={<IconDownload size={16} />}
          onClick={() => downloadFile('admin', `/api/admin/pagamenti/export?${new URLSearchParams({ ...(stato ? { stato } : {}), ...(metodo ? { metodo } : {}) })}`, 'pagamenti.csv').catch(notifyError)}>Esporta CSV</Button>} />
      <Group mb="md" align="flex-end">
        <Select label="Stato" clearable placeholder="Tutti" value={stato} onChange={setStato} w={170}
          data={[{ value: 'in_attesa', label: 'In attesa' }, { value: 'pagato', label: 'Pagati' }, { value: 'fallito', label: 'Falliti' }, { value: 'annullato', label: 'Annullati' }]} />
        <Select label="Metodo" clearable placeholder="Tutti" value={metodo} onChange={setMetodo} w={170}
          data={[{ value: 'carta', label: 'Carta' }, { value: 'paypal', label: 'PayPal' }, { value: 'bonifico', label: 'Bonifico' }]} />
        <TextInput label="Cerca" placeholder="Azienda, causale, fattura" value={q} onChange={(e) => setQ(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()} w={260} />
        <Button variant="default" onClick={load}>Cerca</Button>
      </Group>
      {!rows ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={820}>
            <Table highlightOnHover>
              <Table.Thead><Table.Tr><Table.Th>Creato</Table.Th><Table.Th>Azienda</Table.Th><Table.Th>Piano</Table.Th><Table.Th>Metodo</Table.Th>
                <Table.Th>Causale</Table.Th><Table.Th>Stato</Table.Th><Table.Th>Fattura</Table.Th><Table.Th ta="right">Totale</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => setOpen(r.id)}>
                    <Table.Td>{when(r.creato_il)}</Table.Td>
                    <Table.Td>{r.azienda}</Table.Td>
                    <Table.Td>{r.piano} · {r.periodicita}</Table.Td>
                    <Table.Td>{r.metodo_label}</Table.Td>
                    <Table.Td><Text size="xs" ff="monospace">{r.causale}</Text></Table.Td>
                    <Table.Td><Badge variant="light" color={STATUS_COLOR[r.stato]}>{r.stato_label}</Badge></Table.Td>
                    <Table.Td>{r.fattura ?? '—'}</Table.Td>
                    <Table.Td ta="right">{fmtEuro(r.totale)}</Table.Td>
                  </Table.Tr>
                ))}
                {rows.length === 0 && <Table.Tr><Table.Td colSpan={8}><Text c="dimmed" ta="center" py="md">Nessun pagamento</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      <Drawer opened={!!open} onClose={() => setOpen(null)} position="right" size="lg" title="Pagamento">
        {open && <PaymentDetail id={open} onChange={load} />}
      </Drawer>
    </>
  )
}

function PaymentDetail({ id, onChange }: { id: string; onChange: () => void }) {
  const [p, setP] = useState<any>(null)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [resend, setResend] = useState({ cliente: true, blucode: true })
  const nav = useNavigate()
  useEffect(() => { adminApi(`/pagamenti/${id}`).then(setP).catch(notifyError) }, [id])
  if (!p) return <Loading />

  async function act(path: string, body?: unknown, msg?: string) {
    setBusy(true)
    try {
      const r = await adminApi(`/pagamenti/${id}/${path}`, { method: 'POST', body: body ?? {} })
      setP(r)
      onChange()
      if (msg) notifyOk(msg)
    } catch (e) { notifyError(e) } finally { setBusy(false); setConfirm(false) }
  }
  const b = p.dati_fatturazione ?? {}
  const rows: [string, any][] = [
    ['Azienda', <Anchor key="a" onClick={() => nav(`/admin/aziende/${p.tenant_id}`)}>{p.azienda}</Anchor>],
    ['Piano', `${p.piano_nome} · ${p.periodicita}`], ['Metodo', p.metodo_label],
    ['Importo', `${fmtEuro(p.importo)}${Number(p.bollo) ? ` + bollo ${fmtEuro(p.bollo)}` : ''} = ${fmtEuro(p.totale)}`],
    ['Causale', <Code key="c">{p.causale}</Code>], ['Creato', when(p.creato_il)], ['Pagato', when(p.pagato_il)],
    ['Confermato da', p.confermato_da ?? '—'], ['Riferimento gestore', p.rif_pagamento ?? p.rif_gestore ?? '—'],
    ['Periodo creato', p.periodo ? `${fmtDate(p.periodo.dal)} – ${fmtDate(p.periodo.al)}` : '—'],
    ['Fattura', p.fattura ? `${p.fattura} del ${fmtDate(p.fattura_data)} (${p.formato})` : '—'],
    ['Email', p.email_cliente_il || p.email_admin_il ? `cliente ${when(p.email_cliente_il)} · BluCode ${when(p.email_admin_il)}` : '—'],
  ]
  if (p.sdi_stato) rows.push(['SDI', `${p.sdi_stato}${p.sdi_file ? ` · ${p.sdi_file}` : ''}${p.sdi_errore ? ` · ${p.sdi_errore}` : ''}`])
  return (
    <Stack>
      <Group><Badge size="lg" variant="light" color={STATUS_COLOR[p.stato]}>{p.stato_label}</Badge></Group>
      {p.errore && <Alert color="red">{p.errore}</Alert>}
      {p.errori_fattura?.length > 0 && <Alert color="red" title="XML non generato o non valido">{p.errori_fattura.join(' · ')}<br />Correggi i dati e premi «Reinvia»: il numero resta lo stesso.</Alert>}
      {p.errore_email && <Alert color="orange">Email non inviate: {p.errore_email}</Alert>}
      <Table withRowBorders={false}><Table.Tbody>
        {rows.map(([k, v]) => <Table.Tr key={k}><Table.Td c="dimmed" w={170}>{k}</Table.Td><Table.Td>{v}</Table.Td></Table.Tr>)}
      </Table.Tbody></Table>
      <Paper withBorder p="sm">
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Dati di fatturazione al momento del pagamento</Text>
        <Text size="sm">{b.denominazione ?? `${b.nome ?? ''} ${b.cognome ?? ''}`} · {b.partita_iva ? `P.IVA ${b.partita_iva}` : ''} {b.codice_fiscale ? `C.F. ${b.codice_fiscale}` : ''}</Text>
        <Text size="sm">{b.indirizzo}, {b.cap} {b.comune} {b.provincia ? `(${b.provincia})` : ''} · {b.codice_destinatario ? `SDI ${b.codice_destinatario}` : ''} {b.pec ? `PEC ${b.pec}` : ''}</Text>
      </Paper>

      {p.stato === 'in_attesa' && (
        <Group>
          {p.metodo === 'bonifico' && <Button color="green" loading={busy} onClick={() => setConfirm(true)}>Conferma bonifico</Button>}
          <Button color="red" variant="light" loading={busy} onClick={() => act('annulla', undefined, 'Pagamento annullato')}>Annulla pagamento in attesa</Button>
        </Group>
      )}
      {p.stato === 'pagato' && (
        <Stack gap="xs">
          <Group>
            {p.ha_xml && <Button variant="light" leftSection={<IconDownload size={16} />} onClick={() => downloadFile('admin', `/api/admin/pagamenti/${id}/xml`, `fattura_${p.fattura.replace('/', '_')}.xml`).catch(notifyError)}>XML</Button>}
            {p.ha_pdf && <Button variant="light" leftSection={<IconDownload size={16} />} onClick={() => downloadFile('admin', `/api/admin/pagamenti/${id}/pdf`, `Proforma_${p.fattura.replace('/', '_')}.pdf`).catch(notifyError)}>Proforma PDF</Button>}
          </Group>
          <Group>
            <Checkbox label="al cliente" checked={resend.cliente} onChange={(e) => setResend({ ...resend, cliente: e.currentTarget.checked })} />
            <Checkbox label="a BluCode (XML)" checked={resend.blucode} onChange={(e) => setResend({ ...resend, blucode: e.currentTarget.checked })} />
            <Button variant="default" loading={busy} disabled={!resend.cliente && !resend.blucode} onClick={() => act('reinvia', resend, 'Email reinviate')}>Reinvia</Button>
          </Group>
        </Stack>
      )}
      <Modal opened={confirm} onClose={() => setConfirm(false)} title="Conferma bonifico">
        <Text size="sm" mb="md">Confermi di aver ricevuto <b>{fmtEuro(p.totale)}</b> con causale <Code>{p.causale}</Code>?
          Verranno creati il nuovo periodo e la fattura (numero, XML e proforma), e partiranno le email. Una fattura emessa non si cancella.</Text>
        <Group justify="flex-end"><Button variant="default" onClick={() => setConfirm(false)}>Annulla</Button>
          <Button color="green" loading={busy} onClick={() => act('conferma-bonifico', undefined, 'Bonifico confermato')}>Conferma</Button></Group>
      </Modal>
    </Stack>
  )
}

/** Impostazioni › Pagamenti: metodi attivi, IBAN e intestatario del bonifico, bollo; stato delle chiavi e del cedente. */
export function PaymentSettings() {
  const [s, setS] = useState<any>(null)
  useEffect(() => { adminApi('/pagamenti/impostazioni').then(setS).catch(notifyError) }, [])
  if (!s) return <Loading />
  async function save() {
    try {
      setS(await adminApi('/pagamenti/impostazioni', { method: 'PUT', body: { metodi: s.metodi, iban: s.iban, intestatario: s.intestatario, bollo_a_carico: s.bollo_a_carico } }))
      notifyOk('Impostazioni dei pagamenti salvate')
    } catch (e) { notifyError(e) }
  }
  const toggle = (m: string, on: boolean) => setS({ ...s, metodi: on ? [...s.metodi, m] : s.metodi.filter((x: string) => x !== m) })
  return (
    <Stack maw={760}>
      <Paper withBorder p="md">
        <Title order={4} mb="sm">Metodi di pagamento</Title>
        <Stack gap="xs">
          {Object.entries(s.methods).map(([m, v]: [string, any]) => (
            <Group key={m} justify="space-between">
              <Checkbox label={v.label} checked={s.metodi.includes(m)} onChange={(e) => toggle(m, e.currentTarget.checked)} />
              {v.active ? <Badge color="green" variant="light">attivo</Badge>
                : v.configured ? <Badge color="gray" variant="light">spento</Badge>
                  : <Text size="xs" c="red">manca {v.missing}</Text>}
            </Group>
          ))}
        </Stack>
        <Text size="xs" c="dimmed" mt="sm">Le chiavi di Stripe e PayPal si impostano solo nel file .env del server. PayPal: {s.paypal_mode === 'live' ? 'produzione' : 'sandbox (prova)'}.</Text>
      </Paper>
      <Paper withBorder p="md">
        <Title order={4} mb="sm">Bonifico e bollo</Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput label="Intestatario" value={s.intestatario ?? ''} onChange={(e) => setS({ ...s, intestatario: e.currentTarget.value })} />
          <TextInput label="IBAN" value={s.iban ?? ''} onChange={(e) => setS({ ...s, iban: e.currentTarget.value })} />
          <Select label="Bollo virtuale (oltre 77,47 €)" value={s.bollo_a_carico} onChange={(v) => setS({ ...s, bollo_a_carico: v })} allowDeselect={false}
            data={[{ value: 'cliente', label: 'A carico del cliente (riga «Rimborso imposta di bollo»)' }, { value: 'cedente', label: 'A carico di BluCode' }]} />
        </SimpleGrid>
        <Group justify="flex-end" mt="md"><Button onClick={save}>Salva</Button></Group>
      </Paper>
      <Paper withBorder p="md">
        <Title order={4} mb="sm">Fatture</Title>
        <Text size="sm">Sezionale <b>N/{s.sezionale}</b> · regime {s.regime} · invio {s.invio === 'sdi' ? 'diretto allo SDI tramite Aruba' : 'manuale (XML per email a BluCode)'}</Text>
        <Text size="sm">Cedente: {s.cedente.denominazione || '—'} · P.IVA {s.cedente.piva || '—'} · {s.cedente.indirizzo} {s.cedente.cap} {s.cedente.comune} {s.cedente.provincia}</Text>
        {s.cedente_problems.length > 0 && <Alert color="red" mt="sm">Dati del cedente da completare nel .env: {s.cedente_problems.join(' · ')}</Alert>}
        <Text size="xs" c="dimmed" mt="sm">Indirizzi dei webhook da registrare: Stripe <Code>{s.webhooks.stripe}</Code> · PayPal <Code>{s.webhooks.paypal}</Code></Text>
      </Paper>
    </Stack>
  )
}
