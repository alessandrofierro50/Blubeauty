import { Button, ColorInput, FileButton, Grid, Group, Image, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Text, Textarea, TextInput } from '@mantine/core'
import { IconPhotoUp, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { appApi, tokens } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'

const REGIMI = [
  ['RF01', 'Ordinario'], ['RF02', 'Contribuenti minimi'], ['RF04', 'Agricoltura e pesca'], ['RF05', 'Vendita sali e tabacchi'],
  ['RF06', 'Commercio fiammiferi'], ['RF07', 'Editoria'], ['RF08', 'Telefonia pubblica'], ['RF09', 'Rivendita documenti di trasporto'],
  ['RF10', 'Intrattenimenti e giochi'], ['RF11', 'Agenzie viaggi e turismo'], ['RF12', 'Agriturismo'], ['RF13', 'Vendite a domicilio'],
  ['RF14', 'Rivendita beni usati e d\'arte'], ['RF15', 'Agenzie aste beni usati'], ['RF16', 'IVA per cassa P.A.'], ['RF17', 'IVA per cassa'],
  ['RF18', 'Altro'], ['RF19', 'Forfettario'], ['RF20', 'Franchigia IVA UE'],
].map(([value, label]) => ({ value, label: `${value} – ${label}` }))

/** Intestazione condivisa da tutte le stampe (cataloghi, listini, preventivi, ordini, DDT, fatture). */
export function PrintHeader({ c, title, subtitle }: { c: any; title?: string; subtitle?: string }) {
  const ps = c.print_settings ?? {}
  const color = ps.primary_color || '#2340a8'
  const right = ps.logo_position === 'destra'
  const logo = c.logo_url ? <img src={c.logo_url} alt="" style={{ maxHeight: 64, maxWidth: 200, objectFit: 'contain' }} /> : null
  const info = (
    <div style={{ fontSize: 11, lineHeight: 1.45, textAlign: right ? 'left' : 'right', color: '#33415c' }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: '#1b2b45' }}>{c.name}</div>
      {[c.address, [c.zip_code, c.city, c.province && `(${c.province})`].filter(Boolean).join(' ')].filter(Boolean).map((l: string) => <div key={l}>{l}</div>)}
      {(c.vat_number || c.tax_code) && <div>P.IVA {c.vat_number ?? '—'}{c.tax_code && c.tax_code !== c.vat_number ? ` · C.F. ${c.tax_code}` : ''}</div>}
      {[c.phone, c.email, c.website].filter(Boolean).length > 0 && <div>{[c.phone, c.email, c.website].filter(Boolean).join(' · ')}</div>}
    </div>
  )
  return (
    <div style={{ borderBottom: `3px solid ${color}`, paddingBottom: 10, marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexDirection: right ? 'row-reverse' : 'row' }}>
        <div>{logo ?? <div style={{ fontWeight: 800, fontSize: 20, color }}>{c.name}</div>}</div>
        {info}
      </div>
      {ps.header_note && <div style={{ fontSize: 11, color: '#4a5b75', marginTop: 6 }}>{ps.header_note}</div>}
      {title && <div style={{ marginTop: 12 }}><div style={{ fontSize: 22, fontWeight: 800, color: '#0b2147' }}>{title}</div>{subtitle && <div style={{ fontSize: 12, color: '#4a5b75' }}>{subtitle}</div>}</div>}
    </div>
  )
}

export function PrintFooter({ c }: { c: any }) {
  const ps = c.print_settings ?? {}
  const bank = ps.show_bank && c.iban ? `${c.bank_name ? c.bank_name + ' · ' : ''}IBAN ${c.iban}` : ''
  if (!bank && !ps.footer) return null
  return (
    <div style={{ marginTop: 18, borderTop: '1px solid #dfe5ef', paddingTop: 8, fontSize: 10, color: '#4a5b75', display: 'flex', justifyContent: 'space-between', gap: 12 }}>
      <span>{ps.footer}</span><span>{bank}</span>
    </div>
  )
}

export default function CompanySettings() {
  const [c, setC] = useState<any>(null)
  useEffect(() => { appApi('/api/app/intestazione').then(setC).catch(notifyError) }, [])
  if (!c) return <Loading />
  const set = (k: string, v: any) => setC({ ...c, [k]: v })
  const setPs = (k: string, v: any) => setC({ ...c, print_settings: { ...c.print_settings, [k]: v } })
  const field = (k: string) => ({ value: c[k] ?? '', onChange: (e: any) => set(k, e.currentTarget.value) })

  async function save() {
    try {
      const { id, logo_url: _l, ...body } = c
      setC(await appApi(`/api/app/azienda/${id}`, { method: 'PUT', body }))
      notifyOk('Dati salvati')
    } catch (e) { notifyError(e) }
  }
  async function upload(file: File | null) {
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await fetch(`/api/app/azienda/${c.id}/logo`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${tokens.get('user')}` } })
      const r = await res.json()
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : 'Caricamento non riuscito')
      setC({ ...c, logo_url: r.logo_url })
    } catch (e) { notifyError(e) }
  }
  async function removeLogo() {
    try { const r = await appApi(`/api/app/azienda/${c.id}/logo`, { method: 'DELETE' }); setC({ ...c, logo_url: r.logo_url }) } catch (e) { notifyError(e) }
  }

  return (
    <>
      <PageTitle title="Dati azienda e stampe" subtitle="Intestazione, logo e layout usati in cataloghi, listini, preventivi, ordini, DDT e fatture"
        right={<Button onClick={save}>Salva</Button>} />
      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, lg: 6 }}>
          <Stack>
            <Paper withBorder p="md">
              <Text fw={600} mb="sm">Logo</Text>
              <Group>
                <div style={{ width: 160, height: 80, border: '1px dashed var(--mantine-color-gray-4)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'white' }}>
                  {c.logo_url ? <Image src={c.logo_url} mah={70} maw={150} fit="contain" alt="" /> : <Text size="xs" c="dimmed">nessun logo</Text>}
                </div>
                <Stack gap="xs">
                  <FileButton onChange={upload} accept="image/png,image/jpeg,image/webp">{(p) => <Button variant="light" leftSection={<IconPhotoUp size={16} />} {...p}>Carica logo</Button>}</FileButton>
                  {c.logo_url && <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} onClick={removeLogo}>Rimuovi</Button>}
                </Stack>
              </Group>
              <Text size="xs" c="dimmed" mt="xs">Consigliato PNG con sfondo trasparente.</Text>
            </Paper>
            <Paper withBorder p="md">
              <Text fw={600} mb="sm">Dati in intestazione</Text>
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <TextInput label="Ragione sociale" {...field('name')} />
                <TextInput label="Partita IVA" {...field('vat_number')} />
                <TextInput label="Codice fiscale" {...field('tax_code')} />
                <Select label="Regime fiscale" data={REGIMI} value={c.tax_regime ?? 'RF01'} onChange={(v) => set('tax_regime', v ?? 'RF01')} allowDeselect={false} searchable />
                <TextInput label="Indirizzo" {...field('address')} />
                <Group grow gap="xs"><TextInput label="CAP" {...field('zip_code')} /><TextInput label="Prov." maxLength={2} {...field('province')} /></Group>
                <TextInput label="Città" {...field('city')} />
                <TextInput label="Telefono" {...field('phone')} />
                <TextInput label="Email" {...field('email')} />
                <TextInput label="PEC" {...field('pec')} />
                <TextInput label="Sito web" {...field('website')} />
                <TextInput label="Banca" {...field('bank_name')} />
                <TextInput label="IBAN" {...field('iban')} />
              </SimpleGrid>
              <Text fw={600} mt="lg" mb={4}>Iscrizione al registro imprese (REA)</Text>
              <Text size="xs" c="dimmed" mb="sm">Obbligatoria nelle fatture elettroniche delle società iscritte. Lascia vuoto se non sei iscritto.</Text>
              <SimpleGrid cols={{ base: 2, sm: 4 }}>
                <TextInput label="Ufficio (prov.)" maxLength={2} {...field('rea_office')} onChange={(e) => set('rea_office', e.currentTarget.value.toUpperCase())} />
                <TextInput label="Numero REA" {...field('rea_number')} />
                <TextInput label="Capitale sociale €" {...field('share_capital')} />
                <Select label="Soci" data={[{ value: 'SU', label: 'Socio unico' }, { value: 'SM', label: 'Più soci' }]} value={c.sole_shareholder ?? null} onChange={(v) => set('sole_shareholder', v)} clearable />
              </SimpleGrid>
              <Switch mt="sm" label="Società in liquidazione" checked={!!c.in_liquidation} onChange={(e) => set('in_liquidation', e.currentTarget.checked)} />
            </Paper>
            <Paper withBorder p="md">
              <Text fw={600} mb="sm">Layout di stampa</Text>
              <Stack>
                <Group align="flex-end">
                  <ColorInput label="Colore principale" value={c.print_settings.primary_color} onChange={(v) => setPs('primary_color', v)} w={180}
                    swatches={['#2340a8', '#0b2147', '#2B8A3E', '#C2185B', '#E8590C', '#495057', '#7048E8']} />
                  <div><Text size="sm" fw={500} mb={4}>Logo</Text>
                    <SegmentedControl value={c.print_settings.logo_position} onChange={(v) => setPs('logo_position', v)} data={[{ value: 'sinistra', label: 'A sinistra' }, { value: 'destra', label: 'A destra' }]} /></div>
                </Group>
                <TextInput label="Nota sotto l'intestazione" placeholder="es. Capitale sociale € 10.000 i.v. – REA LE-123456" value={c.print_settings.header_note} onChange={(e) => setPs('header_note', e.currentTarget.value)} />
                <Textarea label="Piè di pagina" autosize placeholder="es. Grazie per averci scelto!" value={c.print_settings.footer} onChange={(e) => setPs('footer', e.currentTarget.value)} />
                <Switch label="Mostra le coordinate bancarie nel piè di pagina" checked={c.print_settings.show_bank} onChange={(e) => setPs('show_bank', e.currentTarget.checked)} />
              </Stack>
            </Paper>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 6 }}>
          <Paper withBorder p="lg" bg="white" pos="sticky" top={76} style={{ color: '#1b2b45' }}>
            <Text size="xs" c="dimmed" mb="sm" tt="uppercase" fw={600}>Anteprima</Text>
            <PrintHeader c={c} title="Preventivo n. 12/2026" subtitle="del 28/10/2026 · Spett.le Cliente Srl" />
            <div style={{ height: 160, background: 'repeating-linear-gradient(#fff 0 22px, #f3f5f9 22px 23px)', borderRadius: 4 }} />
            <PrintFooter c={c} />
          </Paper>
        </Grid.Col>
      </Grid>
    </>
  )
}
