import { Anchor, Button, Center, Paper, PasswordInput, Stack, Text, TextInput } from '@mantine/core'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, adminApi, tokens } from '../../api'
import { Logo } from '../../components'

export default function AdminLogin() {
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totp, setTotp] = useState('')
  const [needTotp, setNeedTotp] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const r = await adminApi('/auth/login', { body: { email, password, totp: totp || null } })
      tokens.set('admin', r.token)
      nav('/admin')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'totp_richiesto') setNeedTotp(true)
      else setError(err instanceof Error ? err.message : 'Errore')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Center mih="100vh" bg="var(--mantine-color-blu-9)" p="md">
      <Paper p="xl" w={380} maw="100%" shadow="lg">
        <form onSubmit={submit}>
          <Stack>
            <Logo size={40} />
            <Text c="dimmed" size="sm">Pannello di amministrazione</Text>
            <TextInput label="Email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required autoComplete="username" />
            <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} required autoComplete="current-password" />
            {needTotp && (
              <TextInput label="Codice di verifica (app Authenticator)" value={totp} onChange={(e) => setTotp(e.currentTarget.value)} inputMode="numeric" autoFocus />
            )}
            {error && <Text c="red" size="sm">{error}</Text>}
            <Button type="submit" loading={busy} fullWidth>Accedi</Button>
            <Anchor size="sm" ta="center" href="/admin/password-dimenticata">Password dimenticata?</Anchor>
          </Stack>
        </form>
      </Paper>
    </Center>
  )
}
