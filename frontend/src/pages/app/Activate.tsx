import { Button, Center, Paper, PasswordInput, Stack, Text, Title } from '@mantine/core'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { appApi, tokens } from '../../api'
import { Logo } from '../../components'

export default function Activate() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (pw !== pw2) return setError('Le due password non coincidono')
    setBusy(true)
    setError('')
    try {
      const r = await appApi('/api/auth/activate', { body: { token: params.get('token'), password: pw } })
      tokens.set('user', r.token)
      nav('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Errore')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Center mih="100vh" p="md" bg="var(--mantine-color-blu-0)">
      <Paper p="xl" w={400} maw="100%" shadow="md">
        <form onSubmit={submit}>
          <Stack>
            <Logo size={40} />
            <Title order={3}>Attiva il tuo account</Title>
            <Text size="sm" c="dimmed">Scegli una password di almeno 8 caratteri.</Text>
            <PasswordInput label="Password" value={pw} onChange={(e) => setPw(e.currentTarget.value)} required minLength={8} autoComplete="new-password" />
            <PasswordInput label="Ripeti la password" value={pw2} onChange={(e) => setPw2(e.currentTarget.value)} required autoComplete="new-password" />
            {error && <Text c="red" size="sm">{error}</Text>}
            <Button type="submit" loading={busy}>Attiva e accedi</Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  )
}
