// Fatturazione DDT di fine mese (standard comune del progetto, comune/fatturazione-ddt.md):
// clienti con DDT da fatturare → DDT del cliente con le righe → selezione di tutti o alcuni → fatture differite.
// Il singolo DDT si apre in una finestra sopra l'elenco: chiudendola la selezione resta com'era.

import { Alert, Anchor, Badge, Button, Checkbox, Group, Modal, Paper, ScrollArea, SimpleGrid, Stack, Switch, Table, Text, TextInput, UnstyledButton } from '@mantine/core'
import { IconExternalLink, IconEye, IconFileInvoice } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtDate, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { S } from './shared'

// dal 20 del mese si propone la fine del mese in corso, prima la fine del mese scorso; le fatture non vanno oltre oggi
const defaultUntil = () => { const n = new Date(); return isoDate(new Date(n.getFullYear(), n.getMonth() + (n.getDate() >= 20 ? 1 : 0), 0)) }
const defaultInvDate = () => { const u = defaultUntil(), t = isoDate(new Date()); return u < t ? u : t }

export default function DdtInvoicing() {
  const nav = useNavigate()
  // la selezione resta anche se si apre la scheda di un DDT e si torna indietro
  const KEY = 'blubeauty.fatturazione-ddt'
  const [saved] = useState<any>(() => { try { return JSON.parse(sessionStorage.getItem(KEY) ?? 'null') } catch { return null } })
  const [until, setUntil] = useState<string>(saved?.until ?? defaultUntil())
  const [invDate, setInvDate] = useState(defaultInvDate())
  const [confirmNow, setConfirmNow] = useState(true)
  const [data, setData] = useState<any>(null)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [current, setCurrent] = useState<string | null>(null)
  const [view, setView] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<any[] | null>(null)

  useEffect(() => { if (data) try { sessionStorage.setItem(KEY, JSON.stringify({ sel: [...sel], current, until })) } catch { /* niente */ } }, [sel, current, data])
  const load = (keep = false) => S(`/fatturazione-ddt?fino_al=${until}`).then((r) => {
    setData(r)
    const valid = new Set<string>(r.customers.flatMap((c: any) => c.ddts.map((d: any) => d.id)))
    setSel(keep && saved ? new Set((saved.sel as string[]).filter((i) => valid.has(i))) : new Set())
    if (keep && saved?.current) setCurrent(saved.current)
    setCurrent((c) => (r.customers.some((x: any) => x.party_id === c) ? c : r.customers[0]?.party_id ?? null))
  }).catch(notifyError)
  useEffect(() => { if (until) load(saved?.until === until) }, [until])

  const customers: any[] = data?.customers ?? []
  const cust = customers.find((c) => c.party_id === current)
  const ids = (c: any) => c.ddts.map((d: any) => d.id) as string[]
  const state = (c: any) => { const n = ids(c).filter((i) => sel.has(i)).length; return n === 0 ? 'none' : n === c.count ? 'all' : 'some' }
  const toggle = (list: string[], on: boolean) => setSel((s) => { const n = new Set(s); list.forEach((i) => (on ? n.add(i) : n.delete(i))); return n })
  const allIds = useMemo(() => customers.flatMap(ids), [data])
  const selCustomers = customers.filter((c) => state(c) !== 'none')
  const selTaxable = customers.reduce((t, c) => t + c.ddts.filter((d: any) => sel.has(d.id)).reduce((x: number, d: any) => x + Number(d.taxable), 0), 0)
  const invoices = selCustomers.reduce((t, c) => t + new Set(c.ddts.filter((d: any) => sel.has(d.id)).map((d: any) => d.payment_term)).size, 0)

  async function run() {
    if (customers.some((c) => c.ddts.some((d: any) => sel.has(d.id) && d.date > invDate))) return notifyError(new Error('La data delle fatture non può precedere quella dei DDT'))
    setBusy(true)
    try {
      const r = await S('/fatturazione-differita', { body: { ddt_ids: [...sel], doc_date: invDate, confirm: confirmNow } })
      r.warnings?.forEach((w: string) => notifyError(new Error(w)))
      notifyOk(`${r.documents.length} ${r.documents.length === 1 ? 'fattura creata' : 'fatture create'}`)
      setDone(r.documents)
      load()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  return (
    <>
      <PageTitle title="Fatturazione DDT di fine mese" subtitle="Scegli i clienti e i DDT da fatturare: una fattura differita per cliente con tutti i DDT selezionati" />
      <Paper withBorder p="sm" mb="md">
        <Group align="flex-end" wrap="wrap">
          <TextInput type="date" label="DDT fino al" value={until} onChange={(e) => setUntil(e.currentTarget.value)} />
          <TextInput type="date" label="Data delle fatture" value={invDate} onChange={(e) => setInvDate(e.currentTarget.value)} />
          <Switch mb={8} label="Emetti subito (altrimenti in bozza)" checked={confirmNow} onChange={(e) => setConfirmNow(e.currentTarget.checked)} />
          <div style={{ flex: 1 }} />
          {data && <Text size="sm" c="dimmed" mb={8}>{data.ddt_count} DDT da fatturare di {customers.length} {customers.length === 1 ? 'cliente' : 'clienti'} · imponibile {fmtEuro(data.taxable)}</Text>}
        </Group>
      </Paper>

      {done && done.length > 0 && (
        <Alert color="teal" mb="md" withCloseButton onClose={() => setDone(null)} title="Fatture create">
          <Group gap="md">{done.map((f) => <Anchor key={f.id} size="sm" onClick={() => nav(`/vendite/${f.id}`)}>{f.party_name} · {f.number_label ? `n. ${f.number_label}` : 'bozza'} · {fmtEuro(f.total)}</Anchor>)}</Group>
        </Alert>
      )}

      {!data ? <Loading /> : customers.length === 0 ? (
        <Paper withBorder p="xl"><Text ta="center" c="dimmed">Nessun DDT da fatturare fino al {fmtDate(until)}.</Text></Paper>
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Paper withBorder>
            <Group justify="space-between" p="sm" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
              <Checkbox label={<Text size="sm" fw={600}>Seleziona tutti i clienti</Text>} checked={sel.size === allIds.length && allIds.length > 0}
                indeterminate={sel.size > 0 && sel.size < allIds.length} onChange={(e) => toggle(allIds, e.currentTarget.checked)} />
              <Text size="xs" c="dimmed">{customers.length} {customers.length === 1 ? 'cliente' : 'clienti'}</Text>
            </Group>
            <ScrollArea.Autosize mah="62vh">
              {customers.map((c) => {
                const st = state(c)
                return (
                  <Group key={c.party_id} gap="sm" wrap="nowrap" px="sm" py={8}
                    style={{ borderBottom: '1px solid var(--mantine-color-default-border)', background: c.party_id === current ? 'var(--mantine-color-blue-light)' : undefined }}>
                    <Checkbox checked={st === 'all'} indeterminate={st === 'some'} onChange={(e) => toggle(ids(c), e.currentTarget.checked)} aria-label={`Seleziona ${c.name}`} />
                    <UnstyledButton style={{ flex: 1 }} onClick={() => setCurrent(c.party_id)}>
                      <Group justify="space-between" wrap="nowrap">
                        <div>
                          <Text size="sm" fw={600}>{c.name}</Text>
                          <Text size="xs" c="dimmed">{c.count} DDT{c.city ? ` · ${c.city}` : ''}{c.payment_terms > 1 ? ` · ${c.payment_terms} pagamenti diversi` : ''}</Text>
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <Text size="sm" fw={600}>{fmtEuro(c.taxable)}</Text>
                          <Text size="xs" c="dimmed">imponibile</Text>
                        </div>
                      </Group>
                    </UnstyledButton>
                  </Group>
                )
              })}
            </ScrollArea.Autosize>
          </Paper>

          <Paper withBorder>
            {!cust ? <Text p="md" c="dimmed">Scegli un cliente dall'elenco.</Text> : (
              <>
                <Group justify="space-between" p="sm" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  <Checkbox label={<Text size="sm" fw={600}>{cust.name}: tutti i DDT</Text>} checked={state(cust) === 'all'} indeterminate={state(cust) === 'some'}
                    onChange={(e) => toggle(ids(cust), e.currentTarget.checked)} />
                  <Text size="sm">{fmtEuro(cust.taxable)}</Text>
                </Group>
                <ScrollArea.Autosize mah="62vh">
                  <Stack gap={0}>
                    {cust.ddts.map((d: any) => (
                      <div key={d.id} style={{ borderBottom: '1px solid var(--mantine-color-default-border)', padding: '8px 12px' }}>
                        <Group justify="space-between" wrap="nowrap" mb={4}>
                          <Checkbox checked={sel.has(d.id)} onChange={(e) => toggle([d.id], e.currentTarget.checked)}
                            label={<Group gap={6}><Text size="sm" fw={600}>DDT n. {d.number_label}</Text><Text size="sm" c="dimmed">del {fmtDate(d.date)}</Text>
                              {d.partial && <Badge size="xs" variant="light" color="orange">in parte fatturato</Badge>}</Group>} />
                          <Group gap={4} wrap="nowrap">
                            <Text size="sm" fw={600}>{fmtEuro(d.taxable)}</Text>
                            <Button size="compact-xs" variant="subtle" leftSection={<IconEye size={14} />} onClick={() => setView(d)}>Apri</Button>
                          </Group>
                        </Group>
                        {(d.reference || d.payment_term) && <Text size="xs" c="dimmed" ml={30}>{[d.reference && `Rif. ${d.reference}`, d.payment_term].filter(Boolean).join(' · ')}</Text>}
                        <Table fz="xs" ml={30} mt={4} style={{ width: 'calc(100% - 30px)' }} verticalSpacing={2}>
                          <Table.Tbody>
                            {d.lines.map((l: any, i: number) => l.text ? (
                              <Table.Tr key={i}><Table.Td colSpan={5} c="dimmed" fs="italic">{l.description}</Table.Td></Table.Tr>
                            ) : (
                              <Table.Tr key={i}>
                                <Table.Td c="dimmed" ff="monospace" w={80}>{l.code ?? ''}</Table.Td>
                                <Table.Td>{l.description}</Table.Td>
                                <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}>{Number(l.quantity).toLocaleString('it-IT')} {l.unit ?? ''}</Table.Td>
                                <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}>{fmtEuro(l.unit_price)}{l.discount ? ` −${l.discount}` : ''}</Table.Td>
                                <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}>{fmtEuro(l.amount)}</Table.Td>
                              </Table.Tr>
                            ))}
                          </Table.Tbody>
                        </Table>
                      </div>
                    ))}
                  </Stack>
                </ScrollArea.Autosize>
              </>
            )}
          </Paper>
        </SimpleGrid>
      )}

      {sel.size > 0 && (
        <Paper withBorder p="sm" mt="md" bg="var(--mantine-color-blue-light)" style={{ position: 'sticky', bottom: 8 }}>
          <Group justify="space-between">
            <Text size="sm"><b>{sel.size}</b> DDT di <b>{selCustomers.length}</b> {selCustomers.length === 1 ? 'cliente' : 'clienti'} · imponibile <b>{fmtEuro(selTaxable)}</b> ·
              {' '}{invoices === 1 ? 'verrà creata 1 fattura' : `verranno create ${invoices} fatture`} del {fmtDate(invDate)}{confirmNow ? '' : ' (in bozza)'}</Text>
            <Group gap="xs">
              <Button variant="default" size="xs" onClick={() => setSel(new Set())}>Deseleziona</Button>
              <Button leftSection={<IconFileInvoice size={16} />} loading={busy} onClick={run}>Crea {invoices === 1 ? 'fattura' : 'fatture'}</Button>
            </Group>
          </Group>
        </Paper>
      )}

      <Modal opened={!!view} onClose={() => setView(null)} size="min(1000px, 96vw)" padding="xs"
        title={<Group gap="sm"><Text fw={600}>DDT n. {view?.number_label} · {cust?.name}</Text>
          {view && <Anchor size="sm" onClick={() => nav(`/vendite/${view.id}`)}><Group gap={4}><IconExternalLink size={14} />Apri la scheda</Group></Anchor>}</Group>}>
        {view && <iframe src={`/stampa/vendita/${view.id}`} title="DDT" style={{ width: '100%', height: '78vh', border: '1px solid var(--mantine-color-default-border)', borderRadius: 6, background: '#fff' }} />}
      </Modal>
    </>
  )
}
