import { Alert, Anchor, AppShell, Badge, Burger, Button, Divider, Group, Menu, Modal, NavLink, Switch, Text, UnstyledButton } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconBrandWhatsapp, IconCalendarEvent, IconCalendarPlus, IconCalendarDollar, IconSun, IconUserHeart, IconCreditCard, IconBox, IconBuildingStore, IconBuildingWarehouse, IconCash, IconChartBar, IconChartDots, IconFileInvoice, IconNumbers, IconChevronDown, IconHome, IconKey, IconLogout, IconPrinter, IconReceipt, IconTruck, IconTruckDelivery, IconUsers, IconAddressBook } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { ApiError, appApi, tokens } from '../../api'
import { Loading, Logo, PlanBadge } from '../../components'
import { ChangePassword, ForcedChange } from './Passwords'
import Payment, { PaymentResult } from './Payment'
import Subscription from './Subscription'

const ICONS: Record<string, any> = {
  anagrafiche: IconAddressBook, magazzino: IconBuildingWarehouse, acquisti: IconTruckDelivery, vendite: IconReceipt, scadenzario: IconCalendarDollar,
  fatturapa: IconFileInvoice, statistiche_base: IconChartBar, pos: IconCash, periferiche: IconPrinter,
  statistiche_avanzate: IconChartDots, tentata_vendita: IconTruck, agenda: IconCalendarEvent, marketing: IconBrandWhatsapp,
}

// Sezioni del menu per i moduli già realizzati (gli altri si aggiungono man mano)
const SECTIONS: Record<string, { label: string; links: [string, string, string?][] }> = {
  agenda: {
    label: 'Agenda',
    links: [['/agenda', 'Agenda del giorno'], ['/agenda/clienti', 'Clienti'], ['/agenda/servizi', 'Servizi e operatori'], ['/agenda/impostazioni', 'Orari e prenotazione online']],
  },
  marketing: {
    label: 'Marketing WhatsApp',
    links: [['/marketing', 'Messaggi e campagne']],
  },
  anagrafiche: {
    label: 'Anagrafiche',
    links: [['/articoli', 'Prodotti'], ['/clienti', 'Anagrafiche clienti'], ['/fornitori', 'Fornitori'], ['/promozioni', 'Promozioni'], ['/tabelle', 'Tabelle']],
  },
  magazzino: {
    label: 'Magazzino',
    links: [['/magazzino/giacenze', 'Giacenze'], ['/magazzino/operazione', 'Carico e scarico'], ['/magazzino/trasferimento', 'Trasferimenti'],
      ['/magazzino/movimenti', 'Movimenti'], ['/magazzino/inventari', 'Inventari'], ['/magazzino/lotti', 'Lotti e scadenze'],
      ['/magazzino/matricole', 'Matricole'], ['/etichette', 'Stampa etichette', 'periferiche'], ['/magazzino/punti-vendita', 'Punti vendita e magazzini']],
  },
  vendite: {
    label: 'Fatture',
    links: [['/vendite', 'Fatture e note di credito'], ['/vendite/acquistato-cliente', 'Acquistato per cliente']],
  },
  statistiche_base: {
    label: 'Statistiche',
    links: [['/statistiche', 'Vendite'], ['/statistiche/banco', 'Vendita al banco', 'pos'], ['/statistiche/magazzino', 'Magazzino']],
  },
  statistiche_avanzate: {
    label: 'Statistiche avanzate',
    links: [['/dashboard', 'Dashboard'], ['/report', 'Report builder'], ['/analisi/abc', 'Analisi ABC'], ['/analisi/magazzino', 'Rotazione e articoli fermi'],
      ['/analisi/clienti', 'Clienti: frequenza e inattivi'], ['/analisi/garanzie', 'Garanzie']],
  },
  scadenzario: {
    label: 'Scadenzario',
    links: [['/scadenzario', 'Scadenze, incassi e pagamenti'], ['/scadenzario/liquidita', 'Liquidità'], ['/scadenzario/solleciti', 'Solleciti']],
  },
  pos: {
    label: 'Cassa',
    links: [['/cassa', 'Vendita al banco'], ['/pos/aperture', 'Chiusure di cassa'], ['/pos/casse', 'Casse e reparti'], ['/periferiche', 'Computer e periferiche', 'periferiche'], ['/etichette-modelli', 'Modelli di etichette', 'periferiche']],
  },
  tentata_vendita: {
    label: 'Tentata vendita',
    links: [['/tentata/giri', 'Giri e rientri'], ['/tentata/furgoni', 'Furgoni e giro clienti'], ['/giro', 'App dell\'agente']],
  },
  acquisti: {
    label: 'Acquisti',
    links: [['/acquisti', 'Ordini, DDT e fatture'], ['/acquisti/ricevute-sdi', 'Fatture ricevute da SDI', 'fatturapa'], ['/acquisti/import-xml', 'Importa fatture XML'], ['/acquisti/riordino', 'Proposta di riordino']],
  },
}

export type AppCtx = { me: any; status: any; reload: () => void; simple?: boolean; setSimple?: (v: boolean) => void }

const SIMPLE_KEY = 'blubeauty_semplice'
const readSimple = () => { try { return localStorage.getItem(SIMPLE_KEY) !== '0' } catch { return true } }

// Voce del menu da evidenziare: quella col percorso più lungo che corrisponde alla pagina.
function bestLink(links: (string | undefined)[][], path: string) {
  return links.map(([to]) => to as string).filter((to) => path === to || path.startsWith(to + "/"))
    .sort((a, b) => b.length - a.length)[0]
}

export default function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const nav = useNavigate()
  const loc = useLocation()
  const [me, setMe] = useState<any>(null)
  const [status, setStatus] = useState<any>(null)
  const [blocked, setBlocked] = useState<string | null>(null)
  const [pwOpen, setPwOpen] = useState(false)
  // Modalità semplice (predefinita): poche voci grandi per chi non vuole cercare le funzioni
  const [simpleMode, setSimpleMode] = useState(readSimple)
  const setSimple = (v: boolean) => { setSimpleMode(v); try { localStorage.setItem(SIMPLE_KEY, v ? '1' : '0') } catch { /* niente */ } }

  const load = async () => {
    try {
      const [m, s] = await Promise.all([appApi('/api/auth/me'), appApi('/api/app/status')])
      setMe(m)
      setStatus(s)
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) setBlocked(e.message)
      else if (e instanceof ApiError && e.status === 401) nav('/login')
    }
  }
  useEffect(() => { load() }, [])

  function logout() {
    tokens.clear('user')
    nav('/login')
  }

  if (blocked) {
    return (
      <Group justify="center" mih="100vh" p="md">
        <Alert color="red" title="Accesso sospeso" maw={460}>
          {blocked}
          <Button mt="md" variant="light" color="red" onClick={logout}>Esci</Button>
        </Alert>
      </Group>
    )
  }
  if (!me || !status) return <Loading />
  // password provvisoria: va cambiata prima di usare il gestionale
  if (me.user.must_change_password) return <ForcedChange onDone={load} onLogout={logout} />

  // abbonamento sospeso o prova scaduta: resta solo la pagina «Abbonamento» (con i contatti), il cambio password e l'uscita
  if (status.access === 'none') {
    return (
      <AppShell header={{ height: 60 }} padding="lg">
        <AppShell.Header>
          <Group h="100%" px="md" justify="space-between" wrap="nowrap">
            <Group wrap="nowrap"><Logo /><Text fw={600} visibleFrom="sm" truncate>{me.tenant.name}</Text></Group>
            <Group gap="xs" wrap="nowrap">
              <Button variant="subtle" leftSection={<IconKey size={14} />} onClick={() => setPwOpen(true)}>Cambia password</Button>
              <Button variant="subtle" leftSection={<IconLogout size={14} />} onClick={logout}>Esci</Button>
            </Group>
          </Group>
        </AppShell.Header>
        <AppShell.Main>
          {status.banner && <Alert color="red" mb="md">{status.banner.text}{me.user.role === 'amministratore' && loc.pathname === '/' && <> <Anchor size="sm" fw={700} onClick={() => nav('/pagamento')}>Rinnova ora</Anchor></>}</Alert>}
          {/* anche da sospesi si può pagare: pagina di pagamento e di esito, poi si ricarica lo stato */}
          {me.user.role === 'amministratore' && loc.pathname === '/pagamento' ? <Payment />
            : me.user.role === 'amministratore' && loc.pathname === '/pagamento/esito' ? <PaymentResult /> : <Subscription />}
        </AppShell.Main>
        <Modal opened={pwOpen} onClose={() => setPwOpen(false)} title="Cambia password">
          <ChangePassword scope="user" onDone={() => setPwOpen(false)} />
        </Modal>
      </AppShell>
    )
  }

  const banner = status.banner
  const simple = simpleMode && status.menu.some((m: any) => m.code === 'agenda' && m.enabled)
  return (
    <AppShell header={{ height: 60 }} navbar={{ width: simple ? 280 : 250, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="lg">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Logo />
            <Text fw={600} visibleFrom="sm" truncate>{me.tenant.name}</Text>
            <PlanBadge code={status.plan_code} />
          </Group>
          <Group gap="xs" wrap="nowrap">
            {me.impersonated && <Badge color="orange">Assistenza</Badge>}
            <Menu position="bottom-end">
              <Menu.Target>
                <UnstyledButton><Group gap={4} wrap="nowrap"><Text size="sm" visibleFrom="md">{me.user.full_name}</Text><IconChevronDown size={14} /></Group></UnstyledButton>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{me.user.email}</Menu.Label>
                <Menu.Item leftSection={<IconKey size={14} />} onClick={() => setPwOpen(true)}>Cambia password</Menu.Item>
                <Menu.Item leftSection={<IconLogout size={14} />} onClick={logout}>Esci</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="sm" style={{ overflowY: 'auto' }}>
        {simple ? (
          <>
            {[
              ['/', 'Oggi', IconSun, null],
              ['/nuovo', 'Nuovo appuntamento', IconCalendarPlus, null],
              ['/agenda', 'Agenda', IconCalendarEvent, null],
              ['/agenda/clienti', 'Clienti', IconUserHeart, null],
              ['/marketing', 'Messaggi e punti', IconBrandWhatsapp, null],
              ['/cassa', 'Cassa e prodotti', IconCash, 'pos'],
            ].filter(([, , , mod]) => !mod || status.menu.some((x: any) => x.code === mod && x.enabled)).map(([to, label, Icon]: any) => (
              <NavLink key={to} label={<Text fz={18} fw={600}>{label}</Text>} leftSection={<Icon size={26} />} py={14} style={{ borderRadius: 12 }}
                active={to === '/' ? loc.pathname === '/' : loc.pathname === to || (to !== '/agenda' && loc.pathname.startsWith(to + '/'))}
                onClick={() => { nav(to); close() }} />
            ))}
            <Divider my="md" />
            <Switch size="md" label="Mostra tutte le funzioni" checked={false} onChange={() => setSimple(false)} />
            {me.user.role === 'amministratore' && <NavLink mt="sm" label="Impostazioni del salone" leftSection={<IconBuildingStore size={20} />} onClick={() => { nav('/agenda/impostazioni'); close() }} />}
          </>
        ) : (<>
        <Switch size="md" mb="sm" label="Modalità semplice" checked={false} onChange={() => setSimple(true)} />
        <NavLink label="Home" leftSection={<IconHome size={18} />} active={loc.pathname === '/'} onClick={() => { nav('/'); close() }} />
        {/* Menu essenziale: solo i moduli attivi e già disponibili. Gli altri sono elencati nella Home. */}
        {status.menu.filter((m: any) => m.enabled && SECTIONS[m.code]).map((m: any) => {
          const Icon = ICONS[m.code] ?? IconBox
          const sec = SECTIONS[m.code]
          return (
            <NavLink key={m.code} label={sec.label} leftSection={<Icon size={18} />} defaultOpened
              active={sec.links.some(([to]) => loc.pathname.startsWith(to))} childrenOffset={28}>
              {sec.links.filter(([, , mod]) => !mod || status.menu.some((x: any) => x.code === mod && x.enabled)).map(([to, label]) => (
                <NavLink key={to} label={label} active={bestLink(sec.links, loc.pathname) === to || (to === '/clienti' && loc.pathname.startsWith('/soggetti'))}
                  onClick={() => { nav(to); close() }} />
              ))}
            </NavLink>
          )
        })}
        {me.user.role === 'amministratore' && (
          <>
            <NavLink label="Dati azienda e stampe" leftSection={<IconBuildingStore size={18} />} active={loc.pathname === '/impostazioni/azienda'} onClick={() => { nav('/impostazioni/azienda'); close() }} mt="sm" />
            <NavLink label="Documenti di vendita" leftSection={<IconNumbers size={18} />} active={loc.pathname === '/impostazioni/vendite'} onClick={() => { nav('/impostazioni/vendite'); close() }} />
            {status.menu.some((x: any) => x.code === 'fatturapa' && x.enabled) && <NavLink label="Fatturazione elettronica" leftSection={<IconFileInvoice size={18} />} active={loc.pathname === '/impostazioni/fatturazione-elettronica'} onClick={() => { nav('/impostazioni/fatturazione-elettronica'); close() }} />}
            <NavLink label="Utenti" leftSection={<IconUsers size={18} />} active={loc.pathname === '/utenti'} onClick={() => { nav('/utenti'); close() }} />
            <NavLink label="Abbonamento" leftSection={<IconCreditCard size={18} />} active={loc.pathname === '/abbonamento'} onClick={() => { nav('/abbonamento'); close() }} />
          </>
        )}
        </>)}
      </AppShell.Navbar>
      <AppShell.Main>
        {banner && <Alert color={banner.level === 'error' ? 'red' : banner.level === 'warning' ? 'yellow' : 'blue'} mb="md">
          {banner.text}{me.user.role === 'amministratore' && banner.renew && !loc.pathname.startsWith('/pagamento') && <> <Anchor size="sm" fw={700} onClick={() => nav('/pagamento')}>Rinnova ora</Anchor></>}
          {me.user.role === 'amministratore' && loc.pathname !== '/abbonamento' && <> <Anchor size="sm" onClick={() => nav('/abbonamento')}>Vedi abbonamento</Anchor></>}</Alert>}
        <Outlet context={{ me, status, reload: load, simple, setSimple } satisfies AppCtx} />
      </AppShell.Main>
      <Modal opened={pwOpen} onClose={() => setPwOpen(false)} title="Cambia password">
        <ChangePassword scope="user" onDone={() => setPwOpen(false)} />
      </Modal>
    </AppShell>
  )
}
