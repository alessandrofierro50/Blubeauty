import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { tokens } from './api'
import AdminLayout from './pages/admin/AdminLayout'
import AdminLogin from './pages/admin/AdminLogin'
import Dashboard from './pages/admin/Dashboard'
import EmailLog from './pages/admin/EmailLog'
import Payments from './pages/admin/Payments'
import Settings from './pages/admin/Settings'
import TenantDetail from './pages/admin/TenantDetail'
import Tenants from './pages/admin/Tenants'
import Activate from './pages/app/Activate'
import { ForgotPassword, ResetPassword } from './pages/app/Passwords'
import Trial from './pages/app/Trial'
import AppLayout from './pages/app/AppLayout'
import Home from './pages/app/Home'
import Subscription from './pages/app/Subscription'
import Payment, { PaymentResult } from './pages/app/Payment'
import Login from './pages/app/Login'
import Users from './pages/app/Users'
import ItemEditor from './pages/anagrafiche/ItemEditor'
import Items from './pages/anagrafiche/Items'
import Parties from './pages/anagrafiche/Parties'
import PartyEditor from './pages/anagrafiche/PartyEditor'
import Tables from './pages/anagrafiche/Tables'
import { PromotionEditor, PromotionsList } from './pages/anagrafiche/Promotions'
import { CatalogEditor, CatalogPrint, CatalogsList } from './pages/anagrafiche/Catalogs'
import { InventoryList, InventoryReview, Lots, Places, Serials } from './pages/magazzino/Inventory'
import MobileCount from './pages/magazzino/MobileCount'
import Operation from './pages/magazzino/Operation'
import { Movements, StockDetail, StockList } from './pages/magazzino/Stock'
import CompanySettings from './pages/app/CompanySettings'
import { PurchaseEditor, PurchaseList } from './pages/acquisti/Purchases'
import Reorder from './pages/acquisti/Reorder'
import XmlImport from './pages/acquisti/XmlImport'
import Contracts from './pages/vendite/Contracts'
import Due from './pages/scadenzario/Due'
import Stats from './pages/statistiche/Stats'
import Analyses from './pages/statistiche/Analyses'
import Dashboards from './pages/statistiche/Dashboards'
import ReportBuilder from './pages/statistiche/ReportBuilder'
import EInvoiceSettings from './pages/fatturapa/Settings'
import SdiInbox from './pages/fatturapa/Inbox'
import Liquidity from './pages/scadenzario/Liquidity'
import Reminders from './pages/scadenzario/Reminders'
import { CustomerPurchases, ItemHistory } from './pages/vendite/Reports'
import SalesEditor from './pages/vendite/SalesEditor'
import SalesList from './pages/vendite/SalesList'
import SalesPrint from './pages/vendite/SalesPrint'
import SalesSettings from './pages/vendite/SalesSettings'
import DdtInvoicing from './pages/vendite/DdtInvoicing'
import Cassa from './pages/pos/Cassa'
import CustomerDisplay from './pages/pos/Display'
import PosSessions from './pages/pos/Sessions'
import PosSetup from './pages/pos/Setup'
import Devices from './pages/periferiche/Devices'
import { LabelTemplates, PrintLabels } from './pages/periferiche/Labels'
import Agenda from './pages/agenda/Agenda'
import AgendaSettings from './pages/agenda/AgendaSettings'
import { ClientDetail, ClientsList } from './pages/agenda/Clients'
import Services from './pages/agenda/Services'
import Marketing from './pages/marketing/Marketing'
import Booking, { MyAppointment } from './pages/prenota/Booking'

function RequireAuth({ scope, children }: { scope: 'admin' | 'user'; children: JSX.Element }) {
  const loc = useLocation()
  if (!tokens.get(scope)) return <Navigate to={scope === 'admin' ? '/admin/login' : `/login?next=${encodeURIComponent(loc.pathname)}`} replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route path="/admin/password-dimenticata" element={<ForgotPassword scope="admin" />} />
      <Route path="/admin/reimposta-password" element={<ResetPassword scope="admin" />} />
      <Route path="/admin" element={<RequireAuth scope="admin"><AdminLayout /></RequireAuth>}>
        <Route index element={<Dashboard />} />
        <Route path="aziende" element={<Tenants />} />
        <Route path="aziende/:id" element={<TenantDetail />} />
        <Route path="impostazioni" element={<Settings />} />
        <Route path="email" element={<EmailLog />} />
        <Route path="pagamenti" element={<Payments />} />
      </Route>

      <Route path="/login" element={<Login />} />
      <Route path="/password-dimenticata" element={<ForgotPassword scope="user" />} />
      <Route path="/reimposta-password" element={<ResetPassword scope="user" />} />
      <Route path="/prova" element={<Trial />} />
      <Route path="/attiva" element={<Activate />} />
      <Route path="/stampa/catalogo/:id" element={<RequireAuth scope="user"><CatalogPrint /></RequireAuth>} />
      <Route path="/stampa/vendita/:id" element={<RequireAuth scope="user"><SalesPrint /></RequireAuth>} />
      <Route path="/cassa" element={<RequireAuth scope="user"><Cassa /></RequireAuth>} />
      <Route path="/cassa/:id" element={<RequireAuth scope="user"><Cassa /></RequireAuth>} />
      <Route path="/cassa/:id/display" element={<RequireAuth scope="user"><CustomerDisplay /></RequireAuth>} />
      <Route path="/conta/:id" element={<RequireAuth scope="user"><MobileCount /></RequireAuth>} />
      {/* Prenotazione online pubblica (smartphone dei clienti): nessun login */}
      <Route path="/prenota/:slug" element={<Booking />} />
      <Route path="/prenota/:slug/a/:token" element={<MyAppointment />} />
      <Route path="/" element={<RequireAuth scope="user"><AppLayout /></RequireAuth>}>
        <Route index element={<Home />} />
        <Route path="utenti" element={<Users />} />
        <Route path="abbonamento" element={<Subscription />} />
        <Route path="pagamento" element={<Payment />} />
        <Route path="pagamento/esito" element={<PaymentResult />} />
        <Route path="agenda" element={<Agenda />} />
        <Route path="agenda/clienti" element={<ClientsList />} />
        <Route path="agenda/clienti/:id" element={<ClientDetail />} />
        <Route path="agenda/servizi" element={<Services />} />
        <Route path="agenda/impostazioni" element={<AgendaSettings />} />
        <Route path="marketing" element={<Marketing />} />
        <Route path="articoli" element={<Items />} />
        <Route path="articoli/:id" element={<ItemEditor />} />
        <Route path="clienti" element={<Parties kind="clienti" />} />
        <Route path="fornitori" element={<Parties kind="fornitori" />} />
        <Route path="soggetti/:id" element={<PartyEditor />} />
        <Route path="tabelle" element={<Tables />} />
        <Route path="promozioni" element={<PromotionsList />} />
        <Route path="promozioni/:id" element={<PromotionEditor />} />
        <Route path="cataloghi" element={<CatalogsList />} />
        <Route path="cataloghi/:id" element={<CatalogEditor />} />
        <Route path="magazzino" element={<Navigate to="/magazzino/giacenze" replace />} />
        <Route path="magazzino/giacenze" element={<StockList />} />
        <Route path="magazzino/articolo/:id" element={<StockDetail />} />
        <Route path="magazzino/operazione" element={<Operation />} />
        <Route path="magazzino/trasferimento" element={<Operation transfer />} />
        <Route path="magazzino/movimenti" element={<Movements />} />
        <Route path="magazzino/inventari" element={<InventoryList />} />
        <Route path="magazzino/inventari/:id" element={<InventoryReview />} />
        <Route path="magazzino/lotti" element={<Lots />} />
        <Route path="magazzino/matricole" element={<Serials />} />
        <Route path="magazzino/punti-vendita" element={<Places />} />
        <Route path="impostazioni/azienda" element={<CompanySettings />} />
        <Route path="acquisti" element={<PurchaseList />} />
        <Route path="acquisti/import-xml" element={<XmlImport />} />
        <Route path="acquisti/riordino" element={<Reorder />} />
        <Route path="acquisti/ricevute-sdi" element={<SdiInbox />} />
        <Route path="impostazioni/fatturazione-elettronica" element={<EInvoiceSettings />} />
        <Route path="impostazioni/vendite" element={<SalesSettings />} />
        <Route path="acquisti/:id" element={<PurchaseEditor />} />
        <Route path="vendite" element={<SalesList />} />
        <Route path="vendite/contratti" element={<Contracts />} />
        <Route path="vendite/fatturazione-ddt" element={<DdtInvoicing />} />
        <Route path="vendite/storico-articolo" element={<ItemHistory />} />
        <Route path="vendite/acquistato-cliente" element={<CustomerPurchases />} />
        <Route path="vendite/:id" element={<SalesEditor />} />
        <Route path="scadenzario" element={<Due />} />
        <Route path="statistiche" element={<Stats />} />
        <Route path="statistiche/:tab" element={<Stats />} />
        <Route path="report" element={<ReportBuilder />} />
        <Route path="report/:id" element={<ReportBuilder />} />
        <Route path="dashboard" element={<Dashboards />} />
        <Route path="dashboard/:id" element={<Dashboards />} />
        <Route path="analisi" element={<Analyses />} />
        <Route path="analisi/:tab" element={<Analyses />} />
        <Route path="scadenzario/liquidita" element={<Liquidity />} />
        <Route path="scadenzario/solleciti" element={<Reminders />} />
        <Route path="pos/aperture" element={<PosSessions />} />
        <Route path="pos/casse" element={<PosSetup />} />
        <Route path="pos/casse/:tab" element={<PosSetup />} />
        <Route path="periferiche" element={<Devices />} />
        <Route path="periferiche/:tab" element={<Devices />} />
        <Route path="etichette" element={<PrintLabels />} />
        <Route path="etichette-modelli" element={<LabelTemplates />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
