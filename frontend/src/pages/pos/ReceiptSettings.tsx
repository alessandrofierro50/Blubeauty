// Ricevute: logo, intestazione e piede della copia di cortesia e della ricevuta non fiscale, con anteprima e stampa di prova.
import { Alert, Button, FileButton, Grid, Group, Paper, SegmentedControl, Select, Slider, Stack, Switch, Text, Textarea, Title } from '@mantine/core'
import { IconPhoto, IconPrinter, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { appApi, tokens } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { ReceiptLines } from '../salone/Prints'

const lines = (t: string) => t.split('\n').map((x) => x.trim()).filter(Boolean)

export default function ReceiptSettings() {
  const [cfg, setCfg] = useState<any>(null)
  const [header, setHeader] = useState('')
  const [footer, setFooter] = useState('')
  const [regs, setRegs] = useState<any[]>([])
  const [reg, setReg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [stamp, setStamp] = useState(0)  // per ricaricare l'immagine del logo in bianco e nero
  const [mono, setMono] = useState<string | null>(null)
  useEffect(() => {  // il logo come esce sulla termica (chiamata con accesso, poi immagine locale)
    if (!stamp) return
    fetch('/api/pos/ricevute/logo-termica.png', { headers: { Authorization: `Bearer ${tokens.get('user')}` } })
      .then((r) => (r.ok ? r.blob() : null)).then((b) => setMono(b ? URL.createObjectURL(b) : null)).catch(() => setMono(null))
  }, [stamp])

  const apply = (c: any) => { setCfg(c); setHeader((c.header ?? []).join('\n')); setFooter((c.footer ?? []).join('\n')); setStamp(Date.now()) }
  useEffect(() => {
    appApi('/api/pos/ricevute').then(apply).catch(notifyError)
    appApi('/api/pos/casse').then((r) => { setRegs(r); setReg(r[0]?.id ?? null) }).catch(() => {})
  }, [])
  if (!cfg) return <Loading />

  async function save(patch: any = {}) {
    setBusy(true)
    try {
      const body = { logo: cfg.logo, logo_width_mm: cfg.logo_width_mm, header: lines(header), footer: lines(footer),
        header_on_rt: cfg.header_on_rt, show_vat: cfg.show_vat, ...patch }
      apply(await appApi('/api/pos/ricevute', { method: 'PUT', body }))
      notifyOk('Ricevute salvate')
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function upload(file: File | null) {
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/pos/ricevute/logo', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${tokens.get('user')}` } })
    if (!res.ok) { notifyError(new Error((await res.json().catch(() => ({}))).detail || 'Caricamento non riuscito')); return }
    apply(await res.json())
    notifyOk('Logo caricato')
  }
  async function removeLogo() {
    try { apply(await appApi('/api/pos/ricevute/logo', { method: 'DELETE' })) } catch (e) { notifyError(e) }
  }
  async function test(where: 'termica' | 'registratore') {
    try { await appApi('/api/pos/ricevute/prova', { body: { register_id: reg, where } }); notifyOk(`Stampa di prova inviata ${where === 'termica' ? 'alla stampante' : 'al registratore'}`) } catch (e) { notifyError(e) }
  }
  const logoUrl = cfg.logo === 'proprio' ? cfg.own_logo_url : cfg.logo === 'azienda' ? cfg.company_logo_url : null
  const current = regs.find((r) => r.id === reg)

  return (
    <>
      <PageTitle title="Ricevute: logo e intestazione" subtitle="Valgono per la copia di cortesia e per la ricevuta non fiscale, sulla stampante termica, sul registratore e dal computer" />
      <Grid gutter="xl">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Stack>
            <Paper withBorder p="md" radius="md">
              <Title order={4} mb="xs">Logo</Title>
              <SegmentedControl fullWidth value={cfg.logo} onChange={(v) => save({ logo: v })} data-testid="logo-scelta"
                data={[{ value: 'azienda', label: 'Logo dell\'azienda' }, { value: 'proprio', label: 'Logo per le ricevute' }, { value: 'nessuno', label: 'Nessun logo' }]} />
              {cfg.logo === 'azienda' && !cfg.company_logo_url && <Alert mt="sm" color="yellow">L'azienda non ha ancora un logo: caricalo in «Dati azienda e stampe» oppure caricane uno qui per le ricevute.</Alert>}
              <Group mt="sm">
                <FileButton onChange={upload} accept="image/png,image/jpeg,image/webp">
                  {(props) => <Button {...props} variant="light" leftSection={<IconPhoto size={16} />}>{cfg.own_logo_url ? 'Cambia il logo delle ricevute' : 'Carica un logo per le ricevute'}</Button>}
                </FileButton>
                {cfg.own_logo_url && <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} onClick={removeLogo}>Togli</Button>}
              </Group>
              {logoUrl && (
                <>
                  <Text size="sm" fw={500} mt="md">Larghezza sulla stampante termica: {cfg.logo_width_mm} mm</Text>
                  <Slider min={15} max={70} step={5} value={cfg.logo_width_mm} onChange={(v) => setCfg({ ...cfg, logo_width_mm: v })} onChangeEnd={(v) => save({ logo_width_mm: v })}
                    marks={[{ value: 20, label: '20' }, { value: 40, label: '40' }, { value: 60, label: '60' }]} mb="lg" />
                  <Text size="xs" c="dimmed" mb={4}>Come esce sulla termica (bianco e nero):</Text>
                  {mono && <Paper withBorder p="xs" bg="white" style={{ display: 'inline-block' }}>
                    <img src={mono} alt="Logo in bianco e nero" style={{ maxWidth: 300, display: 'block' }} />
                  </Paper>}
                  <Text size="xs" c="dimmed" mt={4}>Il registratore stampa il suo logo e la sua intestazione, programmati dal tecnico.</Text>
                </>
              )}
            </Paper>

            <Paper withBorder p="md" radius="md">
              <Title order={4} mb="xs">Intestazione e saluti</Title>
              <Textarea label="Righe in alto (una per riga)" autosize minRows={4} maxRows={8} value={header} onChange={(e) => setHeader(e.currentTarget.value)}
                placeholder={(cfg.default_header ?? []).join('\n')}
                description="Vuoto: ragione sociale, indirizzo, P.IVA e telefono dai Dati azienda. La prima riga esce più grande." />
              <Textarea mt="sm" label="Righe in fondo (una per riga)" autosize minRows={2} maxRows={6} value={footer} onChange={(e) => setFooter(e.currentTarget.value)}
                placeholder="es. Grazie e arrivederci!" />
              <Switch mt="md" label="Colonna IVA come sullo scontrino fiscale" checked={cfg.show_vat} onChange={(e) => setCfg({ ...cfg, show_vat: e.currentTarget.checked })} />
              <Switch mt="xs" label="Stampa queste righe anche sul registratore" description="Di solito no: il registratore stampa già la sua intestazione"
                checked={cfg.header_on_rt} onChange={(e) => setCfg({ ...cfg, header_on_rt: e.currentTarget.checked })} />
              <Button mt="md" loading={busy} onClick={() => save()} data-testid="salva-ricevute">Salva</Button>
            </Paper>

            <Paper withBorder p="md" radius="md">
              <Title order={4} mb="xs">Stampa di prova</Title>
              {regs.length === 0 ? <Text size="sm" c="dimmed">Nessuna cassa configurata.</Text> : (
                <Group align="flex-end">
                  <Select label="Cassa" data={regs.map((r) => ({ value: r.id, label: r.name }))} value={reg} onChange={setReg} allowDeselect={false} w={220} />
                  <Button variant="light" leftSection={<IconPrinter size={16} />} disabled={!current?.devices?.printer} onClick={() => test('termica')}>Sulla stampante termica</Button>
                  <Button variant="light" leftSection={<IconPrinter size={16} />} disabled={!current?.devices?.rt} onClick={() => test('registratore')}>Sul registratore</Button>
                </Group>
              )}
            </Paper>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Text fw={600} mb="xs">Anteprima (stampante termica 80 mm)</Text>
          <Paper withBorder shadow="sm" p="sm" bg="#fcfcf8" c="black" style={{ maxWidth: 360 }} data-testid="anteprima-ricevuta">
            <ReceiptLines lines={cfg.preview.lines} width="100%" />
          </Paper>
          <Text size="xs" c="dimmed" mt="xs">L'anteprima si aggiorna dopo «Salva».</Text>
        </Grid.Col>
      </Grid>
    </>
  )
}
