import { ActionIcon, Alert, Badge, Button, Code, Group, Modal, Paper, Select, Stack, Switch, Table, Text, TextInput, Tooltip } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconKey, IconPlus } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { appApi } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'

export default function Users() {
  const [data, setData] = useState<any>(null)
  const [opened, { open, close }] = useDisclosure()
  const [f, setF] = useState({ full_name: '', email: '', role: 'vendite' })
  const [temp, setTemp] = useState<any>(null)

  const load = () => appApi('/api/app/users').then(setData).catch(notifyError)
  useEffect(() => { load() }, [])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    try {
      await appApi('/api/app/users', { body: f })
      notifyOk('Utente creato: gli abbiamo inviato l\'email di attivazione')
      setF({ full_name: '', email: '', role: 'vendite' })
      close()
      load()
    } catch (err) { notifyError(err) }
  }

  async function toggleActive(u: any) {
    try {
      await appApi(`/api/app/users/${u.id}`, { method: 'PATCH', body: { active: !u.active } })
      load()
    } catch (err) { notifyError(err) }
  }

  async function resetPassword(u: any) {
    if (!window.confirm(`Generare una password provvisoria per ${u.full_name}? Quella attuale smette di funzionare.`)) return
    try {
      setTemp(await appApi(`/api/app/users/${u.id}/password`, { body: { send_email: true } }))
      load()
    } catch (err) { notifyError(err) }
  }

  if (!data) return <Loading />
  const activeCount = data.users.filter((u: any) => u.active).length
  return (
    <>
      <PageTitle title="Utenti" subtitle={`${activeCount} di ${data.max_users} utenti attivi`}
        right={<Button leftSection={<IconPlus size={16} />} onClick={open} disabled={activeCount >= data.max_users}>Nuovo utente</Button>} />
      <Paper withBorder>
        <Table.ScrollContainer minWidth={560}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Nome</Table.Th><Table.Th>Email</Table.Th><Table.Th>Ruolo</Table.Th><Table.Th>Stato</Table.Th><Table.Th>Attivo</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {data.users.map((u: any) => (
                <Table.Tr key={u.id}>
                  <Table.Td fw={600}>{u.full_name}</Table.Td>
                  <Table.Td>{u.email}</Table.Td>
                  <Table.Td>{u.role}</Table.Td>
                  <Table.Td>{u.pending_activation ? <Badge color="yellow" variant="light">invito inviato</Badge> : u.must_change_password ? <Badge color="cyan" variant="light">password provvisoria</Badge> : <Badge color="green" variant="light">ok</Badge>}</Table.Td>
                  <Table.Td><Switch checked={u.active} onChange={() => toggleActive(u)} /></Table.Td>
                  <Table.Td>{u.id !== data.me && (
                    <Tooltip label="Password provvisoria"><ActionIcon variant="subtle" onClick={() => resetPassword(u)} aria-label="Password provvisoria"><IconKey size={16} /></ActionIcon></Tooltip>
                  )}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
      {activeCount >= data.max_users && <Text size="sm" c="dimmed" mt="sm">Hai raggiunto il numero massimo di utenti del tuo pacchetto.</Text>}
      <Modal opened={!!temp} onClose={() => setTemp(null)} title="Password provvisoria">
        {temp && (
          <Stack>
            <Text size="sm">Nome utente: <b>{temp.username}</b></Text>
            <Text size="sm">Password provvisoria: <Code fz="md">{temp.password}</Code></Text>
            <Alert color={temp.email_sent ? 'teal' : 'yellow'}>
              {temp.email_sent ? 'Le credenziali sono state inviate anche per email.' : 'Email non inviata: comunica tu la password.'} Al primo accesso verrà chiesto di cambiarla.
            </Alert>
            <Group justify="flex-end"><Button onClick={() => setTemp(null)}>Chiudi</Button></Group>
          </Stack>
        )}
      </Modal>
      <Modal opened={opened} onClose={close} title="Nuovo utente">
        <form onSubmit={create}>
          <Stack>
            <TextInput label="Nome e cognome" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.currentTarget.value })} />
            <TextInput label="Email" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.currentTarget.value })} />
            <Select label="Ruolo" data={data.roles} value={f.role} onChange={(v) => setF({ ...f, role: v ?? 'vendite' })} allowDeselect={false} />
            <Group justify="flex-end"><Button variant="default" onClick={close}>Annulla</Button><Button type="submit">Crea e invia invito</Button></Group>
          </Stack>
        </form>
      </Modal>
    </>
  )
}
