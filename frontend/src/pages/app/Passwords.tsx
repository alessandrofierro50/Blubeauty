// Password: "password dimenticata" e reimpostazione dal link (utenti delle aziende e super amministratore),
// cambio obbligatorio della password provvisoria al primo accesso, cambio volontario.

import { Alert, Anchor, Button, Center, List, Paper, PasswordInput, Progress, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconCheck, IconLock } from '@tabler/icons-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { adminApi, appApi, tokens } from '../../api'
import { brand } from '../../brand'
import { Logo, notifyError, notifyOk } from '../../components'

type Scope = 'user' | 'admin'
const call = (scope: Scope, path: string, body: unknown) => (scope === 'admin' ? adminApi('/auth' + path, { body }) : appApi('/api/auth' + path, { body }))
const minLen = (scope: Scope) => (scope === 'admin' ? 12 : 8)

export function strength(p: string) {
  let s = 0
  if (p.length >= 8) s += 25
  if (p.length >= 12) s += 25
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) s += 20
  if (/\d/.test(p)) s += 15
  if (/[^A-Za-z0-9]/.test(p)) s += 15
  return Math.min(100, s)
}

function Frame({ scope, children }: { scope: Scope; children: React.ReactNode }) {
  return (
    <Center mih="100vh" p="md" style={{ background: scope === 'admin' ? 'var(--mantine-color-blu-9)' : `linear-gradient(135deg, ${brand.colors.dark}, ${brand.colors.primary})` }}>
      <Paper p="xl" w={420} maw="100%" shadow="xl">{children}</Paper>
    </Center>
  )
}

/** Due campi (nuova password e conferma) con indicatore di robustezza. */
export function NewPassword({ scope, value, onChange }: { scope: Scope; value: { a: string; b: string }; onChange: (v: { a: string; b: string }) => void }) {
  const s = strength(value.a)
  return (
    <>
      <PasswordInput label="Nuova password" value={value.a} onChange={(e) => onChange({ ...value, a: e.currentTarget.value })} required autoComplete="new-password"
        description={`Almeno ${minLen(scope)} caratteri, con lettere e numeri`} />
      {value.a && <Progress value={s} color={s < 50 ? 'red' : s < 75 ? 'yellow' : 'teal'} size="sm" />}
      <PasswordInput label="Ripeti la nuova password" value={value.b} onChange={(e) => onChange({ ...value, b: e.currentTarget.value })} required autoComplete="new-password"
        error={value.b && value.a !== value.b ? 'Le due password sono diverse' : undefined} />
    </>
  )
}
export const passwordOk = (scope: Scope, v: { a: string; b: string }) =>
  v.a.length >= minLen(scope) && v.a === v.b && /\d/.test(v.a) && /[A-Za-z]/.test(v.a)

export function ForgotPassword({ scope }: { scope: Scope }) {
  const [email, setEmail] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try { setDone((await call(scope, '/password-dimenticata', { email })).message) } catch (err) { notifyError(err) } finally { setBusy(false) }
  }
  return (
    <Frame scope={scope}>
      <Stack>
        <Logo size={40} />
        <Title order={3}>Password dimenticata</Title>
        {done ? (
          <Alert color="teal" icon={<IconCheck />}>{done} Controlla anche la cartella spam. Il link vale un'ora.</Alert>
        ) : (
          <form onSubmit={submit}>
            <Stack>
              <Text size="sm" c="dimmed">Scrivi l'email con cui accedi: ti mandiamo un link per scegliere una nuova password.</Text>
              <TextInput label="Email" type="email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required autoComplete="username" autoFocus />
              <Button type="submit" loading={busy} fullWidth>Mandami il link</Button>
            </Stack>
          </form>
        )}
        <Anchor size="sm" ta="center" href={scope === 'admin' ? '/admin/login' : '/login'}>Torna all'accesso</Anchor>
      </Stack>
    </Frame>
  )
}

export function ResetPassword({ scope }: { scope: Scope }) {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const token = params.get('token') ?? ''
  const [pw, setPw] = useState({ a: '', b: '' })
  const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await call(scope, '/reimposta-password', { token, password: pw.a })
      notifyOk('Password aggiornata')
      if (scope === 'user' && r.token) { tokens.set('user', r.token); nav('/') } else nav(scope === 'admin' ? '/admin/login' : '/login')
    } catch (err) { notifyError(err) } finally { setBusy(false) }
  }
  return (
    <Frame scope={scope}>
      <form onSubmit={submit}>
        <Stack>
          <Logo size={40} />
          <Title order={3}>Scegli una nuova password</Title>
          {!token && <Alert color="red">Link incompleto: apri il link ricevuto per email.</Alert>}
          <NewPassword scope={scope} value={pw} onChange={setPw} />
          <Button type="submit" loading={busy} disabled={!token || !passwordOk(scope, pw)} fullWidth>Salva la password</Button>
          <Anchor size="sm" ta="center" href={scope === 'admin' ? '/admin/password-dimenticata' : '/password-dimenticata'}>Il link è scaduto? Richiedine uno nuovo</Anchor>
        </Stack>
      </form>
    </Frame>
  )
}

/** Cambio della password: obbligatorio al primo accesso con la password provvisoria, o volontario dal menu. */
export function ChangePassword({ scope, forced = false, onDone }: { scope: Scope; forced?: boolean; onDone: () => void }) {
  const [current, setCurrent] = useState('')
  const [pw, setPw] = useState({ a: '', b: '' })
  const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      if (scope === 'admin') await adminApi('/auth/password', { body: { current, new: pw.a } })
      else await appApi('/api/auth/password', { body: { current, new: pw.a } })
      notifyOk('Password cambiata')
      setCurrent(''); setPw({ a: '', b: '' })
      onDone()
    } catch (err) { notifyError(err) } finally { setBusy(false) }
  }
  return (
    <form onSubmit={submit}>
      <Stack>
        {forced && (
          <Alert color="blue" icon={<IconLock />} title="Scegli la tua password">
            Stai usando una password provvisoria. Prima di continuare scegline una tua, che conosci solo tu.
          </Alert>
        )}
        <PasswordInput label={forced ? 'Password provvisoria (quella ricevuta)' : 'Password attuale'} value={current} onChange={(e) => setCurrent(e.currentTarget.value)} required autoComplete="current-password" />
        <NewPassword scope={scope} value={pw} onChange={setPw} />
        {scope === 'admin' && <List size="xs" c="dimmed"><List.Item>Per l'amministratore servono almeno 12 caratteri: vede i dati di tutte le aziende.</List.Item></List>}
        <Button type="submit" loading={busy} disabled={!current || !passwordOk(scope, pw)}>Cambia password</Button>
      </Stack>
    </form>
  )
}

export function ForcedChange({ onDone, onLogout }: { onDone: () => void; onLogout: () => void }) {
  return (
    <Frame scope="user">
      <Stack>
        <Logo size={40} />
        <ChangePassword scope="user" forced onDone={onDone} />
        <Anchor size="sm" ta="center" onClick={onLogout}>Esci</Anchor>
      </Stack>
    </Frame>
  )
}
