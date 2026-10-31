import { Anchor, Button, Center, Paper, PasswordInput, Stack, Text, TextInput } from '@mantine/core'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { appApi, tokens } from '../../api'
import { brand } from '../../brand'
import { Logo } from '../../components'

export default function Login() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const r = await appApi('/api/auth/login', { body: { email, password } })
      tokens.set('user', r.token)
      const next = params.get('next')
      if (next && next.startsWith('/') && !next.startsWith('//')) { nav(next); return }
      // l'agente lavora dall'app del giro (tablet o smartphone)
      const me = await appApi('/api/auth/me').catch(() => null)
      nav(me?.user?.role === 'agente' ? '/giro' : '/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Errore')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Center mih="100vh" p="md" style={{ background: `linear-gradient(135deg, ${brand.colors.dark}, ${brand.colors.primary})` }}>
      <Paper p="xl" w={400} maw="100%" shadow="xl">
        <form onSubmit={submit}>
          <Stack>
            <Logo size={44} />
            <Text c="dimmed" size="sm">{brand.tagline}</Text>
            <TextInput label="Email" type="email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required autoComplete="username" />
            <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} required autoComplete="current-password" />
            {error && <Text c="red" size="sm">{error}</Text>}
            <Button type="submit" loading={busy} fullWidth size="md">Accedi</Button>
            <Anchor size="sm" ta="center" href="/password-dimenticata">Password dimenticata?</Anchor>
            <Text size="xs" c="dimmed" ta="center">Problemi di accesso? <Anchor size="xs" href="mailto:assistenza@blucodeinformatica.it">Contatta l'assistenza</Anchor></Text>
          </Stack>
        </form>
      </Paper>
    </Center>
  )
}
