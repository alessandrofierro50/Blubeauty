import { Alert, Anchor, AppShell, Badge, Burger, Button, CloseButton, Divider, Group, Menu, Modal, NavLink, Switch, Text, TextInput, UnstyledButton } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconBrandWhatsapp, IconCalendarEvent, IconCalendarUser, IconCalendarPlus, IconCalendarDollar, IconSun, IconUserHeart, IconCreditCard, IconBox, IconBuildingStore, IconBuildingWarehouse, IconCash, IconChartBar, IconChartDots, IconFileInvoice, IconNumbers, IconChevronDown, IconHome, IconKey, IconLogout, IconPrinter, IconReceipt, IconTruck, IconTruckDelivery, IconUsers, IconAddressBook, IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { ApiError, appApi, tokens } from '../../api'
import { HEADER_ACTION_ID, Loading, Logo, PlanBadge } from '../../components'
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
    links: [['/agenda', 'Agenda del giorno'], ['/agenda/clienti', 'Clienti'], ['/agenda/servizi', 'Servizi e operatori'], ['/agenda/turni', 'Turni e assenze'], ['/agenda/impostazioni', 'Impostazioni del salone']],
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
    links: [['/cassa', 'Vendita al banco'], ['/pos/aperture', 'Chiusure di cassa'], ['/pos/casse', 'Casse e reparti'], ['/pos/ricevute', 'Ricevute: logo e intestazione'], ['/periferiche', 'Computer e periferiche', 'periferiche'], ['/etichette-modelli', 'Modelli di etichette', 'periferiche']],
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

// Parole con cui si cerca una funzione oltre al suo nome (casella «Cerca funzione»)
const KEYWORDS: Record<string, string> = {
  '/agenda': 'appuntamenti calendario prenotazioni giorno',
  '/agenda/clienti': 'clienti schede rubrica telefono compleanno scheda tecnica colore punti tessera',
  '/agenda/servizi': 'servizi listino prezzi operatori parrucchiere estetista durata posa cabine',
  '/agenda/turni': 'turni ferie malattia permesso assenze orario chiusura festivi riposo giorno libero',
  '/agenda/impostazioni': 'impostazioni orari apertura prenotazione online link whatsapp salone',
  '/marketing': 'marketing whatsapp messaggi promemoria campagne compleanno fidelity fedelta punti premi tessere recensioni',
  '/articoli': 'prodotti articoli shampoo vendita rivendita codice a barre',
  '/clienti': 'anagrafica clienti partita iva codice fiscale fatturazione',
  '/fornitori': 'fornitori grossista',
  '/promozioni': 'promozioni sconti offerte',
  '/tabelle': 'iva aliquote pagamenti unita di misura categorie marche listini',
  '/magazzino/giacenze': 'giacenze scorte quantita disponibili',
  '/magazzino/operazione': 'carico scarico rettifica',
  '/magazzino/inventari': 'inventario conta',
  '/vendite': 'fatture note di credito documenti',
  '/statistiche': 'statistiche incassi fatturato andamento',
  '/scadenzario': 'scadenze incassi pagamenti rate',
  '/cassa': 'cassa scontrino registratore vendita al banco incasso copia cortesia',
  '/pos/aperture': 'chiusura cassa z fondo cassa quadratura',
  '/pos/casse': 'casse reparti tasti rapidi',
  '/pos/ricevute': 'ricevuta non fiscale logo intestazione scontrino cortesia stampa saluti',
  '/periferiche': 'registratore telematico stampante termica agent periferiche',
  '/acquisti': 'acquisti ordini fornitore ddt fatture passive',
  '/impostazioni/azienda': 'dati azienda logo intestazione stampe',
  '/impostazioni/vendite': 'numerazione documenti',
  '/impostazioni/fatturazione-elettronica': 'fatturazione elettronica sdi aruba xml',
  '/utenti': 'utenti password accessi dipendenti',
  '/abbonamento': 'abbonamento pagamento rinnovo pacchetto',
}

/** Testo senza accenti e in minuscolo, per cercare «piu» e trovare «più». */
const plain = (t: string) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

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
  const [q, setQ] = useState('')  // casella «Cerca funzione» del menu completo
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
  const enabledMod = (code: string) => status.menu.some((x: any) => x.code === code && x.enabled)
  const functions: { to: string; label: string; section: string; Icon: any }[] = [
    ...status.menu.filter((m: any) => m.enabled && SECTIONS[m.code]).flatMap((m: any) => SECTIONS[m.code].links
      .filter(([, , mod]) => !mod || enabledMod(mod))
      .map(([to, label]) => ({ to, label, section: SECTIONS[m.code].label, Icon: ICONS[m.code] ?? IconBox }))),
    ...(me.user.role === 'amministratore' ? [
      { to: '/impostazioni/azienda', label: 'Dati azienda e stampe', section: 'Impostazioni', Icon: IconBuildingStore },
      { to: '/impostazioni/vendite', label: 'Documenti di vendita', section: 'Impostazioni', Icon: IconNumbers },
      ...(enabledMod('fatturapa') ? [{ to: '/impostazioni/fatturazione-elettronica', label: 'Fatturazione elettronica', section: 'Impostazioni', Icon: IconFileInvoice }] : []),
      { to: '/utenti', label: 'Utenti', section: 'Impostazioni', Icon: IconUsers },
      { to: '/abbonamento', label: 'Abbonamento', section: 'Impostazioni', Icon: IconCreditCard },
    ] : []),
  ]
  const words = plain(q).split(/\s+/).filter(Boolean)
  const found = words.length ? functions
    .map((f) => {
      const name = plain(f.label), all = `${name} ${plain(f.section)} ${plain(KEYWORDS[f.to] ?? '')}`
      if (!words.every((w) => all.includes(w))) return null
      const sec = `${name} ${plain(f.section)}`
      return { ...f, score: words.every((w) => name.includes(w)) ? 0 : words.every((w) => sec.includes(w)) ? 1 : 2 }  // prima il nome, poi il gruppo, poi le parole chiave
    })
    .filter((f): f is NonNullable<typeof f> => !!f)
    .sort((a, b) => a.score - b.score) : []
  return (
    <AppShell header={{ height: 60 }} navbar={{ width: simple ? 280 : 250, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="lg">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Logo />
            <Text fw={600} visibleFrom="sm" truncate>{me.tenant.name}</Text>
            <PlanBadge code={status.plan_code} />
            <div id={HEADER_ACTION_ID} style={{ display: 'flex', alignItems: 'center' }} />
          </Group>
          <Group gap="xs" wrap="nowrap">
            {me.impersonated && <Badge color="orange">Assistenza</Badge>}
            <Menu position="bottom-end">
              <Menu.Target>
                <UnstyledButton><Group gap={4} wrap="nowrap"><Text size="sm" visibleFrom="md">{me.user.full_name}</Text><IconChevronDown size={14} /></Group></UnstyledButton>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{me.user.email}</Menu.Label>
                {me.user.role === 'amministratore' && status.menu.some((m: any) => m.code === 'agenda' && m.enabled) && <Menu.Item leftSection={<IconBuildingStore size={14} />} onClick={() => nav('/agenda/impostazioni')}>Impostazioni del salone</Menu.Item>}
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
              ['/agenda/turni', 'Turni e assenze', IconCalendarUser, null],
              ['/marketing', 'Messaggi e punti', IconBrandWhatsapp, null],
              ['/cassa', 'Cassa e prodotti', IconCash, 'pos'],
              ...(me.user.role === 'amministratore' ? [['/agenda/impostazioni', 'Impostazioni del salone', IconBuildingStore, null]] : []),
            ].filter(([, , , mod]) => !mod || status.menu.some((x: any) => x.code === mod && x.enabled)).map(([to, label, Icon]: any) => (
              <NavLink key={to} label={<Text fz={18} fw={600}>{label}</Text>} leftSection={<Icon size={26} />} py={14} style={{ borderRadius: 12 }}
                active={to === '/' ? loc.pathname === '/' : loc.pathname === to || (to !== '/agenda' && loc.pathname.startsWith(to + '/'))}
                onClick={() => { nav(to); close() }} />
            ))}
            <Divider my="md" />
            <Switch size="md" label="Mostra tutte le funzioni" checked={false} onChange={() => setSimple(false)} />
          </>
        ) : (<>
        <Switch size="md" mb="sm" style={{ flexShrink: 0 }} label="Modalità semplice" checked={false} onChange={() => setSimple(true)} />
        <Button fullWidth mb="xs" style={{ flexShrink: 0 }} variant={loc.pathname === '/' ? 'filled' : 'light'} leftSection={<IconHome size={18} />} justify="flex-start"
          onClick={() => { setQ(''); nav('/'); close() }}>Schermata principale</Button>
        <TextInput mb="xs" style={{ flexShrink: 0 }} placeholder="Cerca funzione…" leftSection={<IconSearch size={16} />} value={q} data-testid="cerca-funzione"
          rightSection={q ? <CloseButton size="sm" onClick={() => setQ('')} aria-label="Svuota la ricerca" /> : null}
          onChange={(e) => setQ(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setQ('')
            if (e.key === 'Enter' && found[0]) { nav(found[0].to); setQ(''); close() }
          }} />
        {q.trim() ? (
          found.length ? found.map((f, i) => (
            <NavLink key={f.to} label={f.label} description={f.section} leftSection={<f.Icon size={18} />} active={i === 0} variant="light"
              onClick={() => { nav(f.to); setQ(''); close() }} />
          )) : <Text size="sm" c="dimmed" px="sm" py="xs">Nessuna funzione trovata per «{q.trim()}»</Text>
        ) : (<>
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
