import { ActionIcon, Alert, Anchor, Badge, Button, Checkbox, Group, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Tabs, Text, Textarea, TextInput, Title } from '@mantine/core'
import { IconArrowLeft, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { Loading, notifyError, notifyOk } from '../../components'
import CustomerPrices from './CustomerPrices'
import { CustomField } from './ItemEditor'
import { A, dec, num, opts, useLookups } from './shared'

const EMPTY: any = {
  code: '', is_customer: true, is_supplier: false, person_type: 'azienda', name: '', first_name: '', last_name: '',
  vat_number: '', tax_code: '', sdi_code: '', pec: '', email: '', phone: '', mobile: '', website: '', address: '',
  street_number: '', zip_code: '', city: '', province: '', country: 'IT', iban: '', bank_name: '',
  payment_term_id: null, price_list_id: null, discount1: '', discount2: '', credit_limit: '', credit_policy: 'blocca',
  split_payment: false, vat_rate_id: null, customer_category_id: null, exemption_letter: '', notes: '', custom: {}, active: true, addresses: [],
}

export default function PartyEditor() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const isNew = id === 'nuovo'
  const nav = useNavigate()
  const L = useLookups()
  const [p, setP] = useState<any>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (isNew) {
      const supplier = params.get('tipo') === 'fornitori'
      setP({ ...EMPTY, is_customer: !supplier, is_supplier: supplier })
    } else A(`/soggetti/${id}`).then(setP).catch(notifyError)
  }, [id])

  if (!p || !L) return <Loading />
  const set = (k: string, v: any) => setP({ ...p, [k]: v })
  const field = (k: string) => ({ value: p[k] ?? '', onChange: (e: any) => set(k, e.currentTarget.value) })
  const back = p.is_customer ? '/clienti' : '/fornitori'

  async function save() {
    setBusy(true)
    try {
      const body: any = { ...p }
      for (const k of ['discount1', 'discount2', 'credit_limit']) body[k] = dec(body[k])
      for (const k of Object.keys(EMPTY)) if (body[k] === '') body[k] = null
      body.country = body.country || 'IT'
      body.code = body.code || null
      const r = isNew ? await A('/soggetti', { body }) : await A(`/soggetti/${id}`, { method: 'PUT', body })
      notifyOk('Anagrafica salvata')
      setP(r)
      if (isNew) nav(`/soggetti/${r.id}`, { replace: true })
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  async function deactivate() {
    if (!confirm('Disattivare questa anagrafica?')) return
    try { await A(`/soggetti/${id}`, { method: 'DELETE' }); nav(back) } catch (e) { notifyError(e) }
  }

  const addrs = p.addresses
  const updA = (i: number, k: string, v: any) => set('addresses', addrs.map((a: any, j: number) => (j === i ? { ...a, [k]: v } : a)))

  return (
    <>
      <Anchor size="sm" onClick={() => nav(back)}><Group gap={4}><IconArrowLeft size={14} />{p.is_customer ? 'Clienti' : 'Fornitori'}</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <Group gap="xs">
          <Title order={2}>{isNew ? (p.is_customer ? 'Nuovo cliente' : 'Nuovo fornitore') : p.name}</Title>
          {!isNew && <Badge variant="outline" ff="monospace">{p.code}</Badge>}
          {!p.active && <Badge color="gray">disattivato</Badge>}
        </Group>
        <Group>
          {!isNew && p.active && <Button variant="subtle" color="red" onClick={deactivate}>Disattiva</Button>}
          <Button onClick={save} loading={busy}>Salva</Button>
        </Group>
      </Group>
      {p.warnings?.map((w: string) => <Alert key={w} color="yellow" mb="sm">{w}</Alert>)}

      <Tabs defaultValue="anagrafica" keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="anagrafica">Anagrafica</Tabs.Tab>
          <Tabs.Tab value="commerciale">Condizioni commerciali</Tabs.Tab>
          {p.is_customer && !isNew && <Tabs.Tab value="prezzi">Prezzi netti</Tabs.Tab>}
          <Tabs.Tab value="destinazioni">Destinazioni {addrs.length > 0 && <Badge size="xs" ml={4}>{addrs.length}</Badge>}</Tabs.Tab>
          {L.settings.custom_fields.some((c) => c.entity === 'party') && <Tabs.Tab value="extra">Campi personalizzati</Tabs.Tab>}
        </Tabs.List>

        <Tabs.Panel value="anagrafica">
          <Paper withBorder p="md">
            <Group mb="md" wrap="wrap">
              <SegmentedControl value={p.person_type} onChange={(v) => set('person_type', v)}
                data={[{ value: 'azienda', label: 'Azienda' }, { value: 'privato', label: 'Privato' }, { value: 'pa', label: 'Pubblica amministrazione' }]} />
              <Checkbox label="Cliente" checked={p.is_customer} onChange={(e) => set('is_customer', e.currentTarget.checked)} />
              <Checkbox label="Fornitore" checked={p.is_supplier} onChange={(e) => set('is_supplier', e.currentTarget.checked)} />
            </Group>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
              <TextInput label="Codice" placeholder="automatico" {...field('code')} styles={{ input: { fontFamily: 'monospace' } }} />
              {p.person_type === 'privato' ? (
                <>
                  <TextInput label="Cognome" required {...field('last_name')} />
                  <TextInput label="Nome" required {...field('first_name')} />
                </>
              ) : (
                <TextInput label="Ragione sociale" required {...field('name')} style={{ gridColumn: 'span 2' }} />
              )}
              <TextInput label="Partita IVA" {...field('vat_number')} />
              <TextInput label="Codice fiscale" {...field('tax_code')} />
              <TextInput label={p.person_type === 'pa' ? 'Codice univoco ufficio (6)' : 'Codice destinatario SDI'} placeholder={p.person_type === 'privato' ? '0000000' : ''} {...field('sdi_code')} maxLength={7} />
              <TextInput label="PEC" {...field('pec')} />
            </SimpleGrid>
            <Text fw={600} mt="lg" mb="xs">Sede</Text>
            <SimpleGrid cols={{ base: 2, sm: 4, lg: 6 }}>
              <TextInput label="Indirizzo" {...field('address')} style={{ gridColumn: 'span 2' }} />
              <TextInput label="N. civico" {...field('street_number')} />
              <TextInput label="CAP" {...field('zip_code')} maxLength={10} />
              <TextInput label="Città" {...field('city')} />
              <Group grow gap="xs"><TextInput label="Prov." {...field('province')} maxLength={2} /><TextInput label="Nazione" {...field('country')} maxLength={2} /></Group>
            </SimpleGrid>
            <Text fw={600} mt="lg" mb="xs">Contatti</Text>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
              <TextInput label="Email" type="email" {...field('email')} />
              <TextInput label="Telefono" {...field('phone')} />
              <TextInput label="Cellulare" {...field('mobile')} />
              <TextInput label="Sito web" {...field('website')} />
            </SimpleGrid>
            <Textarea label="Note" mt="md" autosize minRows={2} {...field('notes')} />
            <Switch mt="md" label="Anagrafica attiva" checked={p.active} onChange={(e) => set('active', e.currentTarget.checked)} />
          </Paper>
        </Tabs.Panel>

        <Tabs.Panel value="commerciale">
          <Paper withBorder p="md">
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
              <Select label="Pagamento" data={opts(L.payments.filter((x) => x.active))} value={p.payment_term_id} onChange={(v) => set('payment_term_id', v)} clearable />
 {p.is_customer && <Select label="Categoria cliente" data={opts(L.customerCategories)} value={p.customer_category_id} onChange={(v) => set('customer_category_id', v)} clearable />}
              {p.is_customer && <Select label="Listino" data={opts(L.lists, (l) => `${l.code} — ${l.name}`)} value={p.price_list_id} onChange={(v) => set('price_list_id', v)} clearable />}
              <Group grow gap="xs">
                <NumberInput label="Sconto 1 %" value={num(p.discount1)} onChange={(v) => set('discount1', v)} min={0} max={100} />
                <NumberInput label="Sconto 2 %" value={num(p.discount2)} onChange={(v) => set('discount2', v)} min={0} max={100} />
              </Group>
              <TextInput label="IBAN" {...field('iban')} />
              <TextInput label="Banca" {...field('bank_name')} />
              <Select label="Esenzione IVA abituale" data={opts(L.vat.filter((v) => v.nature))} value={p.vat_rate_id} onChange={(v) => set('vat_rate_id', v)} clearable />
              <TextInput label="Dichiarazione d'intento (n. e data)" {...field('exemption_letter')} />
            </SimpleGrid>
            {p.is_customer && (
              <Paper withBorder p="md" mt="lg" bg="var(--mantine-color-blu-0)">
                <Text fw={600}>Fido</Text>
                <Text size="xs" c="dimmed" mb="sm">Esposizione massima: fatture non pagate + DDT e ordini non ancora fatturati.</Text>
                <Group align="flex-end" wrap="wrap">
                  <NumberInput label="Importo del fido (€)" value={num(p.credit_limit)} onChange={(v) => set('credit_limit', v)} min={0} decimalScale={2} w={200} placeholder="nessun limite" />
                  <SegmentedControl value={p.credit_policy} onChange={(v) => set('credit_policy', v)}
                    data={[{ value: 'blocca', label: 'Blocca le vendite' }, { value: 'avvisa', label: 'Solo avviso' }]} />
                </Group>
              </Paper>
            )}
            <Checkbox mt="md" label="Split payment (scissione dei pagamenti, PA e società controllate)" checked={p.split_payment} onChange={(e) => set('split_payment', e.currentTarget.checked)} />
          </Paper>
        </Tabs.Panel>

        <Tabs.Panel value="prezzi"><CustomerPrices partyId={p.id} /></Tabs.Panel>

        <Tabs.Panel value="destinazioni">
          <Paper withBorder>
            <Group justify="space-between" p="sm"><Text fw={600}>Destinazioni di consegna</Text>
              <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => set('addresses', [...addrs, { label: '', address: '', zip_code: '', city: '', province: '', country: 'IT', is_default: false }])}>Aggiungi</Button></Group>
            <Stack p="sm" gap="sm">
              {addrs.map((a: any, i: number) => (
                <Group key={i} align="flex-end" wrap="wrap">
                  <TextInput label="Nome" value={a.label} onChange={(e) => updA(i, 'label', e.currentTarget.value)} w={140} />
                  <TextInput label="Indirizzo" value={a.address} onChange={(e) => updA(i, 'address', e.currentTarget.value)} style={{ flex: 1, minWidth: 200 }} />
                  <TextInput label="CAP" value={a.zip_code ?? ''} onChange={(e) => updA(i, 'zip_code', e.currentTarget.value)} w={80} />
                  <TextInput label="Città" value={a.city ?? ''} onChange={(e) => updA(i, 'city', e.currentTarget.value)} w={150} />
                  <TextInput label="Prov." value={a.province ?? ''} onChange={(e) => updA(i, 'province', e.currentTarget.value)} w={60} maxLength={2} />
                  <Checkbox label="Predefinita" checked={a.is_default} onChange={(e) => updA(i, 'is_default', e.currentTarget.checked)} mb={8} />
                  <ActionIcon variant="subtle" color="red" mb={4} onClick={() => set('addresses', addrs.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon>
                </Group>
              ))}
              {addrs.length === 0 && <Text size="sm" c="dimmed">Nessuna destinazione oltre alla sede.</Text>}
            </Stack>
          </Paper>
        </Tabs.Panel>

        <Tabs.Panel value="extra">
          <Paper withBorder p="md">
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
              {L.settings.custom_fields.filter((c) => c.entity === 'party').map((c) => (
                <CustomField key={c.key} def={c} value={p.custom?.[c.key]} onChange={(v) => set('custom', { ...p.custom, [c.key]: v })} />
              ))}
            </SimpleGrid>
          </Paper>
        </Tabs.Panel>
      </Tabs>
    </>
  )
}
