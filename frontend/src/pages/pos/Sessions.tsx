// Aperture e chiusure di cassa: quadratura del contante, incassi per metodo, IVA, scontrini e resi.

import { Badge, Button, Drawer, Group, Paper, Select, SimpleGrid, Table, Text, TextInput } from '@mantine/core'
import { IconCash, IconPrinter } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { appApi, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, Stat, notifyError } from '../../components'
import { PRINT_CSS, ReceiptPrint, SessionPrint } from './Receipt'
import { P } from './shared'

export default function Sessions() {
  const nav = useNavigate()
  const [regs, setRegs] = useState<any[]>([])
  const [reg, setReg] = useState<string | null>(null)
  const [from, setFrom] = useState(isoDate(new Date(Date.now() - 30 * 86400000)))
  const [to, setTo] = useState(isoDate(new Date()))
  const [rows, setRows] = useState<any[] | null>(null)
  const [open, setOpen] = useState<any>(null)
  useEffect(() => { P('/casse').then(setRegs).catch(notifyError) }, [])
  useEffect(() => {
    setRows(null)
    const p = new URLSearchParams()
    if (reg) p.set('register_id', reg)
    if (from) p.set('date_from', from)
    if (to) p.set('date_to', to)
    P(`/aperture?${p}`).then(setRows).catch(notifyError)
  }, [reg, from, to])
  const closed = (rows ?? []).filter((r) => r.status === 'chiusa')
  const takings = (rows ?? []).reduce((a, r) => a + Number(r.takings), 0)
  const diff = closed.reduce((a, r) => a + Number(r.difference || 0), 0)
  return (
    <>
      <PageTitle title="Chiusure di cassa" subtitle="Aperture, quadrature del contante e documenti emessi al banco"
        right={<Button leftSection={<IconCash size={16} />} onClick={() => nav('/cassa')}>Apri la cassa</Button>} />
      <Group mb="md" align="flex-end">
        {regs.length > 1 && <Select label="Cassa" placeholder="Tutte le casse" data={regs.map((r) => ({ value: r.id, label: r.name }))} value={reg} onChange={setReg} clearable />}
        <TextInput type="date" label="Dal" value={from} onChange={(e) => setFrom(e.currentTarget.value)} />
        <TextInput type="date" label="Al" value={to} onChange={(e) => setTo(e.currentTarget.value)} />
      </Group>
      {!rows ? <Loading /> : (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
            <Stat label="Aperture" value={rows.length} hint={`${rows.length - closed.length} ancora aperte`} />
            <Stat label="Incassato" value={fmtEuro(takings)} hint="al netto dei resi" />
            <Stat label="Media per apertura" value={fmtEuro(rows.length ? takings / rows.length : 0)} />
            <Stat label="Differenze di cassa" value={<Text span fw={700} fz="inherit" c={Math.abs(diff) > 0.001 ? 'red' : undefined}>{fmtEuro(diff)}</Text>} hint="contato − atteso" />
          </SimpleGrid>
          <Paper withBorder>
            <Table highlightOnHover>
              <Table.Thead><Table.Tr><Table.Th>Cassa</Table.Th><Table.Th>Apertura</Table.Th><Table.Th>Chiusura</Table.Th><Table.Th>Operatore</Table.Th><Table.Th ta="right">Incassato</Table.Th><Table.Th ta="right">Contante atteso</Table.Th><Table.Th ta="right">Differenza</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => P(`/aperture/${r.id}`).then((s) => setOpen({ ...s, register_name: r.register_name })).catch(notifyError)}>
                    <Table.Td>{r.register_name}</Table.Td>
                    <Table.Td>{new Date(r.opened_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
                    <Table.Td>{r.closed_at ? new Date(r.closed_at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : <Badge color="green">aperta</Badge>}{r.z_number && <Text span size="xs" c="dimmed"> · Z {r.z_number}</Text>}</Table.Td>
                    <Table.Td>{r.opened_by}</Table.Td>
                    <Table.Td ta="right" fw={600}>{fmtEuro(r.takings)}</Table.Td>
                    <Table.Td ta="right">{r.expected_cash ? fmtEuro(r.expected_cash) : '—'}</Table.Td>
                    <Table.Td ta="right">{r.difference !== null ? <Text span fw={600} c={Number(r.difference) === 0 ? 'green' : 'red'}>{fmtEuro(r.difference)}</Text> : '—'}</Table.Td>
                  </Table.Tr>
                ))}
                {!rows.length && <Table.Tr><Table.Td colSpan={7}><Text c="dimmed" ta="center" py="lg">Nessuna apertura nel periodo</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
        </>
      )}
      {open && <SessionDrawer ses={open} onClose={() => setOpen(null)} />}
    </>
  )
}

function SessionDrawer({ ses, onClose }: { ses: any; onClose: () => void }) {
  const [docs, setDocs] = useState<any[] | null>(null)
  const [doc, setDoc] = useState<any>(null)
  const [company, setCompany] = useState<any>(null)
  const [printing, setPrinting] = useState<any>(null)
  useEffect(() => { P(`/scontrini?session_id=${ses.id}&limit=200`).then(setDocs).catch(notifyError); appApi('/api/app/intestazione').then(setCompany).catch(() => {}) }, [ses.id])
  const s = ses.summary
  const print = (what: any) => { setPrinting(what); setTimeout(() => window.print(), 150) }
  const label: Record<string, string> = { SCO: 'Scontrino', RSO: 'Reso', FTI: 'Fattura' }
  return (
    <Drawer opened onClose={onClose} position="right" size="xl" title={`${ses.register_name} · ${new Date(ses.opened_at).toLocaleDateString('it-IT')}`}>
      <style>{PRINT_CSS}</style>
      <div id="pos-print">{printing?.kind === 'session' ? <SessionPrint ses={ses} company={company} register={ses.register_name} /> : printing ? <ReceiptPrint r={printing} company={company} register={ses.register_name} /> : null}</div>
      <SimpleGrid cols={3} mb="md">
        <Stat label="Netto" value={fmtEuro(s.net_total)} hint={`${s.receipts} scontrini · medio ${fmtEuro(s.average)}`} />
        <Stat label="Contante atteso" value={fmtEuro(s.expected_cash)} hint={ses.counted_cash ? `contato ${fmtEuro(ses.counted_cash)}` : 'cassa aperta'} />
        <Stat label="Differenza" value={ses.difference !== null ? fmtEuro(ses.difference) : '—'} />
      </SimpleGrid>
      <SimpleGrid cols={2} mb="md">
        <Paper withBorder p="sm">
          <Text fw={600} size="sm" mb={4}>Incassi per metodo</Text>
          {Object.entries(s.by_method).map(([m, v]: any) => <Group key={m} justify="space-between"><Text size="sm">{v.label} ({v.count})</Text><Text size="sm" fw={600}>{fmtEuro(v.amount)}</Text></Group>)}
          <Group justify="space-between" mt={4}><Text size="sm">Prelievi / versamenti</Text><Text size="sm">{Number(s.withdrawals) ? '−' : ''}{fmtEuro(s.withdrawals)} / {fmtEuro(s.deposits)}</Text></Group>
        </Paper>
        <Paper withBorder p="sm">
          <Text fw={600} size="sm" mb={4}>Corrispettivi per aliquota</Text>
          {s.vat.map((v: any) => <Group key={v.rate} justify="space-between"><Text size="sm">IVA {Number(v.rate)}% · imponibile {fmtEuro(v.taxable)}</Text><Text size="sm" fw={600}>{fmtEuro(v.vat)}</Text></Group>)}
        </Paper>
      </SimpleGrid>
      {ses.moves?.length > 0 && (
        <Paper withBorder p="sm" mb="md">
          <Text fw={600} size="sm" mb={4}>Movimenti di contante</Text>
          {ses.moves.map((m: any) => <Group key={m.id} justify="space-between"><Text size="sm">{m.kind === 'prelievo' ? 'Prelievo' : 'Versamento'} · {m.reason ?? ''}</Text><Text size="sm">{fmtEuro(m.amount)}</Text></Group>)}
        </Paper>
      )}
      <Group justify="space-between" mb={6}><Text fw={600}>Documenti</Text><Button size="xs" variant="light" leftSection={<IconPrinter size={14} />} onClick={() => print({ kind: 'session' })}>Stampa riepilogo</Button></Group>
      <Group align="flex-start" wrap="nowrap">
        <Table highlightOnHover style={{ flex: 1 }} fz="sm">
          <Table.Tbody>
            {(docs ?? []).map((d) => (
              <Table.Tr key={d.id} style={{ cursor: 'pointer' }} bg={doc?.id === d.id ? 'blue.0' : undefined} onClick={() => P(`/scontrini/${d.id}`).then(setDoc).catch(notifyError)}>
                <Table.Td><Badge size="sm" variant="light" color={d.doc_type === 'RSO' ? 'red' : d.doc_type === 'FTI' ? 'grape' : 'blue'}>{label[d.doc_type]} {d.number}</Badge></Table.Td>
                <Table.Td>{new Date(d.created_at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</Table.Td>
                <Table.Td ta="right" fw={600}>{d.doc_type === 'RSO' ? '−' : ''}{fmtEuro(d.total)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {doc && (
          <Paper withBorder p="sm" w={300}>
            <ReceiptPrint r={doc} company={null} register={ses.register_name} />
            <Button fullWidth mt="sm" size="xs" variant="light" leftSection={<IconPrinter size={14} />} onClick={() => print(doc)}>Ristampa</Button>
          </Paper>
        )}
      </Group>
    </Drawer>
  )
}
