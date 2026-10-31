// Prova gratuita: modulo pubblico (lo stesso che il sito blucodeinformatica.it manda a /api/public/prova).
// Le credenziali arrivano solo per email: così l'accesso va a chi possiede davvero quell'indirizzo.

import { Alert, Anchor, Button, Center, Checkbox, Loader, Paper, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconMailCheck } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../../api'
import { brand } from '../../brand'
import { Logo } from '../../components'

export default function Trial() {
  const opened = useRef(Date.now())
  const [info, setInfo] = useState<any>(null)
  const [f, setF] = useState({ company_name: '', vat_number: '', sector: '', name: '', email: '', phone: '', website: '' })
  const [privacy, setPrivacy] = useState(false)
  const [terms, setTerms] = useState(false)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<{ msg: string; code?: string } | null>(null)
  useEffect(() => { api('user', '/api/public/prova').then(setInfo).catch(() => setInfo({ enabled: false })) }, [])
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.currentTarget.value })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await api('user', '/api/public/prova', { body: { ...f, vat_number: f.vat_number || null, sector: f.sector || null, phone: f.phone || null,
        privacy, terms, terms_version: info.terms_version, elapsed_ms: Date.now() - opened.current } })
      setDone(r.message)
    } catch (err) {
      setError({ msg: err instanceof Error ? err.message : 'Errore', code: err instanceof ApiError ? err.code : undefined })
    } finally { setBusy(false) }
  }
  return (
    <Center mih="100vh" p="md" style={{ background: `linear-gradient(135deg, ${brand.colors.dark}, ${brand.colors.primary})` }}>
      <Paper p="xl" w={560} maw="100%" shadow="xl">
        <Stack>
          <Logo size={44} />
          {!info ? <Loader /> : done ? (
            <>
              <Title order={2}>Controlla la posta</Title>
              <Alert color="teal" icon={<IconMailCheck />}>{done} Al primo accesso sceglierai una password tua. Se non la trovi, guarda nella cartella spam.</Alert>
              <Button component="a" href="/login" size="md">Vai all'accesso</Button>
            </>
          ) : !info.enabled ? (
            <Alert color="gray">Le iscrizioni alla prova gratuita sono chiuse. <Anchor href={info.website_url ?? 'https://blucodeinformatica.it'}>Contattaci</Anchor> per una demo.</Alert>
          ) : (
            <form onSubmit={submit}>
              <Stack>
                <div>
                  <Title order={2}>Prova BluBeauty gratis per {info.days} giorni</Title>
                  <Text c="dimmed" size="sm">Pacchetto {info.plan}, senza carta di credito. Ti mandiamo subito per email nome utente e password.</Text>
                </div>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <TextInput label="Ragione sociale" required value={f.company_name} onChange={set('company_name')} autoComplete="organization" />
                  <TextInput label="Partita IVA" value={f.vat_number} onChange={set('vat_number')} />
                  <TextInput label="Nome e cognome" required value={f.name} onChange={set('name')} autoComplete="name" />
                  <TextInput label="Settore" placeholder="es. Ferramenta" value={f.sector} onChange={set('sector')} />
                  <TextInput label="Email" type="email" required value={f.email} onChange={set('email')} autoComplete="email" />
                  <TextInput label="Telefono" value={f.phone} onChange={set('phone')} autoComplete="tel" />
                </SimpleGrid>
                {/* campo trappola per i robot: invisibile */}
                <input type="text" name="website" value={f.website} onChange={set('website')} tabIndex={-1} autoComplete="off" aria-hidden="true"
                  style={{ position: 'absolute', left: -5000, width: 1, height: 1, opacity: 0 }} />
                <Checkbox checked={privacy} onChange={(e) => setPrivacy(e.currentTarget.checked)}
                  label={<>Ho letto l'<Anchor href={info.privacy_url} target="_blank">informativa sulla privacy</Anchor></>} />
                <Checkbox checked={terms} onChange={(e) => setTerms(e.currentTarget.checked)}
                  label={<>Accetto i <Anchor href={info.terms_url} target="_blank">termini di utilizzo</Anchor> (versione {info.terms_version})</>} />
                {error && <Alert color="red">{error.msg}{error.code === 'email_registrata' && <> <Anchor href="/password-dimenticata">Recupera la password</Anchor></>}</Alert>}
                <Button type="submit" size="md" loading={busy} disabled={!privacy || !terms}>Attiva la prova gratuita</Button>
                <Text size="xs" c="dimmed" ta="center">Hai già un accesso? <Anchor size="xs" href="/login">Entra</Anchor></Text>
              </Stack>
            </form>
          )}
        </Stack>
      </Paper>
    </Center>
  )
}
