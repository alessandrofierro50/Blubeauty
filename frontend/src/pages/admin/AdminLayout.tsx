import { AppShell, Burger, Button, Group, NavLink, Text } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconBuildingStore, IconCreditCard, IconLayoutDashboard, IconLogout, IconMail, IconSettings } from '@tabler/icons-react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { tokens } from '../../api'
import { Logo } from '../../components'

const LINKS = [
  { to: '/admin', label: 'Panoramica', icon: IconLayoutDashboard, exact: true },
  { to: '/admin/aziende', label: 'Aziende clienti', icon: IconBuildingStore },
  { to: '/admin/pagamenti', label: 'Pagamenti', icon: IconCreditCard },
  { to: '/admin/email', label: 'Email inviate', icon: IconMail },
  { to: '/admin/impostazioni', label: 'Impostazioni e account', icon: IconSettings },
]

export default function AdminLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const nav = useNavigate()
  const loc = useLocation()

  return (
    <AppShell header={{ height: 60 }} navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="lg">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Logo />
            <Text size="xs" c="dimmed" visibleFrom="xs">Super amministratore</Text>
          </Group>
          <Button variant="subtle" color="gray" leftSection={<IconLogout size={16} />}
            onClick={() => { tokens.clear('admin'); nav('/admin/login') }}>
            Esci
          </Button>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="sm">
        {LINKS.map((l) => (
          <NavLink key={l.to} label={l.label} leftSection={<l.icon size={18} />}
            active={l.exact ? loc.pathname === l.to : loc.pathname.startsWith(l.to)}
            onClick={() => { nav(l.to); close() }} style={{ borderRadius: 8 }} />
        ))}
      </AppShell.Navbar>
      <AppShell.Main bg="var(--mantine-color-body)">
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
