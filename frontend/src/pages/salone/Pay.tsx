// Incasso semplice e stampa della ricevuta non fiscale: pochi pulsanti grandi, le opzioni avanzate restano nascoste.
import { Alert, Badge, Box, Button, Checkbox, Collapse, Group, Modal, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput, ThemeIcon } from '@mantine/core'
import { IconCash, IconCheck, IconCreditCard, IconDeviceDesktop, IconGift, IconPrinter, IconReceipt, IconSettings } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { ApiError, appApi, fmtEuro } from '../../api'
import { notifyError, notifyOk } from '../../components'
import type { Appointment } from '../agenda/lib'

const BIG = { size: 'xl', radius: 'lg', h: 72, fz: 20 } as const
export const NONFISCAL_REASONS = ['Buono regalo venduto', 'Pagamento di una fattura già emessa', 'Altro motivo']

export function PayModal({ appt, onClose, onDone }: { appt: Appointment; onClose: () => void; onDone: (a: Appointment) => void }) {
  const [client, setClient] = useState<any>(null)
  const [reward, setReward] = useState<string | null>(null)
  const [more, setMore] = useState(false)
  const [catalog, setCatalog] = useState<any[]>([])
  const [regId, setRegId] = useState<string | null>(null)
  const [products, setProducts] = useState<{ item_id: string; label: string; price: number }[]>([])
  const [discount, setDiscount] = useState(0)
  const [invoice, setInvoice] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<{ appt: Appointment; receipt: any } | null>(null)
  const [nfAllowed, setNfAllowed] = useState(true)  // la cassa consente la ricevuta non fiscale al posto dello scontrino
  const [docKind, setDocKind] = useState<'scontrino' | 'ricevuta'>('scontrino')
  const [reason, setReason] = useState(NONFISCAL_REASONS[0])
  const [other, setOther] = useState('')
  const nonfiscal = docKind === 'ricevuta' && !invoice ? (reason === 'Altro motivo' ? other.trim() : reason) : null

  useEffect(() => {
    if (appt.party_id) appApi(`/api/agenda/clienti/${appt.party_id}`).then(setClient).catch(() => {})
    appApi('/api/agenda/impostazioni').then(async (s) => {
      const regs = await appApi('/api/pos/casse').catch(() => [])
      const id = s.register_id ?? regs.find((r: any) => r.active)?.id ?? null
      setRegId(id)
      setNfAllowed(regs.find((r: any) => r.id === id)?.settings?.nonfiscal_allowed !== false)
      if (id) appApi(`/api/pos/casse/${id}/catalogo`).then((c) => setCatalog(c.items.filter((i: any) => i.price && i.active))).catch(() => {})
    }).catch(() => {})
  }, [appt.id])

  const services = Number(appt.total)
  const rw = client?.loyalty?.rewards?.find((r: any) => r.id === reward)
  const rewardValue = !rw ? 0 : rw.kind === 'sconto_percento' ? services * rw.value / 100
    : rw.kind === 'servizio' ? Number(appt.items.find((i) => i.service_id === rw.service_id)?.price ?? 0) : Math.min(rw.value ?? 0, services)
  const available = (client?.loyalty?.rewards ?? []).filter((r: any) => r.available)
  const prod = products.reduce((s, p) => s + p.price, 0)
  const total = Math.max(0, services - Math.min(discount || 0, services) - rewardValue + prod)

  const pay = async (method: string) => {
    if (docKind === 'ricevuta' && !invoice && !nonfiscal) { notifyError(new Error('Scrivi il motivo della ricevuta non fiscale')); return }
    setBusy(method)
    const body = { register_id: regId, invoice, discount: discount || null, reward_id: reward, payments: [{ method, amount: total.toFixed(2) }], nonfiscal_reason: nonfiscal,
      products: products.map((p) => ({ item_id: p.item_id, quantity: '1', unit_price_gross: p.price.toFixed(2) })) }
    try {
      let r
      try {
        r = await appApi(`/api/agenda/appuntamenti/${appt.id}/incassa`, { body })
      } catch (e) {
        // cassa chiusa: la apriamo noi (fondo 0) e riproviamo, senza far fare passaggi in più
        if (e instanceof ApiError && e.status === 409 && /cassa non è aperta|già chiusa/.test(e.message) && regId) {
          await appApi(`/api/pos/casse/${regId}/apri`, { body: { opening_float: '0' } })
          r = await appApi(`/api/agenda/appuntamenti/${appt.id}/incassa`, { body })
        } else throw e
      }
      setDone({ appt: r.appointment, receipt: r.receipt })
    } catch (e) { notifyError(e) } finally { setBusy(null) }
  }

  if (done) {
    const rt = done.receipt.fiscal?.rt
    return (
      <Modal opened onClose={() => onDone(done.appt)} withCloseButton={false} size="md" centered radius="lg">
        <Stack align="center" ta="center" py="md">
          <ThemeIcon size={84} radius={84} color="green" variant="light"><IconCheck size={48} /></ThemeIcon>
          <Text fz={26} fw={800}>Fatto! {fmtEuro(done.receipt.total)}</Text>
          <Text c="dimmed">{done.receipt.doc_type === 'FTI' ? `Fattura n. ${done.receipt.number} emessa` : done.receipt.fiscal?.nonfiscal ? `Ricevuta non fiscale n. ${done.receipt.number} registrata` : rt ? 'Lo scontrino sta uscendo dal registratore' : 'Pagamento registrato (nessun registratore collegato)'}</Text>
          {client?.loyalty && <Badge size="xl" variant="light" leftSection={<IconGift size={16} />}>Punti fedeltà aggiornati</Badge>}
          <ReceiptButtons apptId={done.appt.id} />
          <Button size="lg" variant="subtle" onClick={() => onDone(done.appt)}>Chiudi</Button>
        </Stack>
      </Modal>
    )
  }

  return (
    <Modal opened onClose={onClose} title={<Text fw={700} fz="lg">Incassa · {appt.client ?? 'Cliente'}</Text>} size="lg" radius="lg" centered>
      <Stack>
        <Paper withBorder radius="lg" p="md">
          {appt.items.map((it) => <Group key={it.id} justify="space-between"><Text fz="lg">{it.service}</Text><Text fz="lg">{fmtEuro(it.price)}</Text></Group>)}
          {products.map((p, i) => <Group key={i} justify="space-between"><Text fz="lg">{p.label}</Text><Text fz="lg">{fmtEuro(p.price)}</Text></Group>)}
          {rw && <Group justify="space-between" c="green"><Text fz="lg">🎁 {rw.name}</Text><Text fz="lg">−{fmtEuro(rewardValue || 0)}</Text></Group>}
          <Group justify="space-between" mt="xs"><Text fz={30} fw={800}>Totale</Text><Text fz={34} fw={800} c="blu" data-testid="pay-total">{fmtEuro(total)}</Text></Group>
        </Paper>
        {client?.loyalty && (
          <Alert color={available.length ? 'green' : 'blu'} icon={<IconGift />} radius="lg" title={`${client.first_name ?? client.name} ha ${client.loyalty.points} punti`}>
            {available.length ? (
              <Group gap="xs" mt={4}>
                {available.map((r: any) => <Button key={r.id} size="md" radius="xl" variant={reward === r.id ? 'filled' : 'light'} color="green"
                  onClick={() => setReward(reward === r.id ? null : r.id)}>{reward === r.id ? '✓ ' : ''}Usa «{r.name}»</Button>)}
              </Group>
            ) : client.loyalty.next ? <Text size="sm">Ancora {client.loyalty.next.missing} punti per «{client.loyalty.next.name}»</Text> : null}
          </Alert>
        )}
        {nfAllowed && !invoice && (
          <Paper withBorder radius="lg" p="sm">
            <SegmentedControl fullWidth size="lg" radius="lg" value={docKind} onChange={(v) => setDocKind(v as any)} data-testid="tipo-documento"
              data={[{ value: 'scontrino', label: 'Scontrino fiscale' }, { value: 'ricevuta', label: 'Ricevuta non fiscale' }]} />
            {docKind === 'ricevuta' && (
              <Stack gap={6} mt="sm">
                <Select size="md" label="Motivo (stampato sulla ricevuta)" data={NONFISCAL_REASONS} value={reason} onChange={(v) => setReason(v || NONFISCAL_REASONS[0])} allowDeselect={false} />
                {reason === 'Altro motivo' && <TextInput size="md" placeholder="Scrivi il motivo" maxLength={120} value={other} onChange={(e) => setOther(e.currentTarget.value)} />}
                <Text size="xs" c="dimmed">Esce sul registratore come documento non fiscale. Usala solo quando lo scontrino non è dovuto.</Text>
              </Stack>
            )}
          </Paper>
        )}
        <Text fw={600} ta="center">Come paga?</Text>
        <SimpleGrid cols={3}>
          <Button {...BIG} color="green" leftSection={<IconCash size={26} />} loading={busy === 'contanti'} disabled={!!busy || !regId} onClick={() => pay('contanti')}>Contanti</Button>
          <Button {...BIG} leftSection={<IconCreditCard size={26} />} loading={busy === 'carta'} disabled={!!busy || !regId} onClick={() => pay('carta')}>Carta</Button>
          <Button {...BIG} variant="light" leftSection={<IconCreditCard size={26} />} loading={busy === 'bancomat'} disabled={!!busy || !regId} onClick={() => pay('bancomat')}>Bancomat</Button>
        </SimpleGrid>
        {!regId && <Text c="orange" ta="center">Manca la cassa: chiedi all'amministratore di collegarla in Impostazioni.</Text>}
        <Button variant="subtle" leftSection={<IconSettings size={16} />} onClick={() => setMore(!more)}>{more ? 'Nascondi' : 'Altre opzioni'}: prodotti, sconto, fattura</Button>
        <Collapse in={more}>
          <Stack>
            <Select placeholder="Aggiungi un prodotto venduto" searchable value={null} size="md"
              data={catalog.map((c) => ({ value: c.id, label: `${c.description} · ${fmtEuro(c.price)}` }))}
              onChange={(v) => { const c = catalog.find((x) => x.id === v); if (c) setProducts([...products, { item_id: c.id, label: c.description, price: Number(c.price) }]) }} />
            <NumberInput label="Sconto (€)" value={discount} onChange={(v) => setDiscount(Number(v) || 0)} min={0} decimalScale={2} decimalSeparator="," size="md" />
            <Checkbox size="md" label="Vuole la fattura" checked={invoice} onChange={(e) => setInvoice(e.target.checked)} disabled={!appt.party_id} />
          </Stack>
        </Collapse>
      </Stack>
    </Modal>
  )
}

/** Tre modi di stampare la ricevuta NON fiscale: termica 80 mm, registratore (documento non fiscale), dal computer. */
export function ReceiptButtons({ apptId }: { apptId: string }) {
  const print = async (where: 'termica' | 'registratore') => {
    try { const r = await appApi(`/api/agenda/appuntamenti/${apptId}/ricevuta`, { body: { where } }); notifyOk(`Ricevuta inviata a «${r.device}»`) } catch (e) { notifyError(e) }
  }
  return (
    <Box w="100%">
      <Text size="sm" c="dimmed" mb={6}>Ricevuta non fiscale per la cliente</Text>
      <Stack gap="xs">
        <Button fullWidth variant="light" size="lg" radius="lg" justify="flex-start" leftSection={<IconPrinter size={22} />} onClick={() => print('termica')}>Stampante dello scontrino (80 mm)</Button>
        <Button fullWidth variant="light" size="lg" radius="lg" justify="flex-start" leftSection={<IconReceipt size={22} />} onClick={() => print('registratore')}>Registratore di cassa (non fiscale)</Button>
        <Button fullWidth variant="light" size="lg" radius="lg" justify="flex-start" leftSection={<IconDeviceDesktop size={22} />} onClick={() => window.open(`/stampa/ricevuta/${apptId}`, '_blank')} aria-label="Computer">Stampa dal computer</Button>
      </Stack>
    </Box>
  )
}
