// Prenotazione online PUBBLICA: il cliente prenota e disdice da solo dallo smartphone (nessun login).
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { brand } from '../../brand'
import './booking.css'

type Page = { name: string; slug: string; address: string; phone: string | null; welcome_text: string | null; cancel_hours: number; max_days: number
  services: { id: string; name: string; description: string | null; category: string; price: string; duration_min: number; staff_ids: string[] }[]
  staff: { id: string; first_name: string; color: string }[] }
type Step = 'servizio' | 'operatore' | 'orario' | 'dati' | 'fatto'

const euro = (v: string | number) => Number(v).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' })
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const KEY = 'blubeauty_cliente'

async function call<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch('/api/prenota/' + path, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message ?? 'Qualcosa non ha funzionato, riprova')
  return data
}

export function Mark({ size = 18 }: { size?: number }) {
  return <img src={brand.logo} width={size} height={size} alt="" />
}

function WhatsAppIcon() {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="#25D366" aria-hidden><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm5.8 14.2c-.2.7-1.4 1.3-2 1.4-.5.1-1.2.1-1.9-.1a17 17 0 0 1-1.7-.6 13.4 13.4 0 0 1-5.1-4.5c-.4-.5-1-1.5-1-2.8s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.2.1.3 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.7 1.2 1.6 2 1.1 1 2 1.3 2.3 1.4.3.1.4.1.6-.1l.8-1c.2-.3.4-.2.6-.1l1.9.9c.3.1.5.2.5.3.1.2.1.7-.1 1.3Z" /></svg>
}

export default function Booking() {
  const { slug = '' } = useParams()
  const [page, setPage] = useState<Page | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState<Step>('servizio')
  const [service, setService] = useState<Page['services'][0] | null>(null)
  const [staffId, setStaffId] = useState<string | null>(null)
  const [day, setDay] = useState(iso(new Date()))
  const [slots, setSlots] = useState<{ key: string; times: string[] } | null>(null)
  const [time, setTime] = useState<string | null>(null)
  const [form, setForm] = useState({ first_name: '', last_name: '', phone: '', privacy: false, marketing: false, website: '' })
  const [busy, setBusy] = useState(false)
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => { call<Page>(slug).then(setPage).catch((e) => setError(e.message)) }, [slug])
  useEffect(() => {
    try { const s = localStorage.getItem(KEY); if (s) setForm((f) => ({ ...f, ...JSON.parse(s) })) } catch { /* senza archivio locale */ }
  }, [])
  const key = `${service?.id}|${staffId}|${day}`
  useEffect(() => {
    if (step !== 'orario' || !service) return
    let on = true
    call<string[]>(`${slug}/orari?service_id=${service.id}&day=${day}${staffId ? `&staff_id=${staffId}` : ''}`)
      .then((t) => on && setSlots({ key: `${service.id}|${staffId}|${day}`, times: t })).catch(() => on && setSlots({ key: `${service.id}|${staffId}|${day}`, times: [] }))
    return () => { on = false }
  }, [step, key])
  const days = useMemo(() => Array.from({ length: Math.min(page?.max_days ?? 30, 30) }, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return d }), [page])
  const cats = useMemo(() => {
    const m = new Map<string, Page['services']>()
    page?.services.forEach((s) => m.set(s.category, [...(m.get(s.category) ?? []), s]))
    return [...m.entries()]
  }, [page])

  if (error) return <div className="bk-wrap"><div className="bk-app"><div className="bk-head"><h1>Prenotazione online</h1></div><main className="bk-main"><p className="bk-warn">{error}</p></main></div></div>
  if (!page) return <div className="bk-wrap"><div className="bk-app"><div className="bk-head" style={{ height: 160 }} /></div></div>
  const times = slots?.key === key ? slots.times : null
  const staffName = page.staff.find((s) => s.id === staffId)?.first_name
  const dayLabel = new Date(day + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' })
  const back = () => setStep(step === 'operatore' ? 'servizio' : step === 'orario' ? 'operatore' : step === 'dati' ? 'orario' : step)

  const confirm = async () => {
    setBusy(true); setError(null)
    try {
      const r = await call<{ token: string }>(`${slug}/prenotazioni`, { service_id: service!.id, staff_id: staffId, day, time, ...form, phone: form.phone })
      try { localStorage.setItem(KEY, JSON.stringify({ first_name: form.first_name, last_name: form.last_name, phone: form.phone })) } catch { /* niente */ }
      setToken(r.token); setStep('fatto')
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="bk-wrap">
      <div className="bk-app">
        <header className="bk-head">
          <div className="bk-top">
            {step !== 'servizio' && step !== 'fatto' ? <button className="bk-pill" onClick={back}>← Indietro</button>
              : <span className="bk-brand"><Mark /> BluBeauty</span>}
            {page.phone && <a className="bk-pill" href={`tel:${page.phone}`}>📞 Chiama</a>}
          </div>
          <h1>{page.name}</h1>
          {page.address && <p>{page.address}</p>}
          {step !== 'fatto' && <div className="bk-progress">{['servizio', 'operatore', 'orario', 'dati'].map((s, i) => <span key={s} className={i <= ['servizio', 'operatore', 'orario', 'dati'].indexOf(step) ? 'on' : ''} />)}</div>}
        </header>

        <main className="bk-main">
          {step === 'servizio' && <section>
            {page.welcome_text && <p className="bk-welcome">{page.welcome_text}</p>}
            <h2>Cosa desideri prenotare?</h2>
            {cats.map(([cat, list]) => (
              <div key={cat}>
                <p className="bk-cat">{cat}</p>
                {list.map((s) => (
                  <button key={s.id} className="bk-card" data-testid="service" onClick={() => { setService(s); setStaffId(null); setTime(null); setStep('operatore') }}>
                    <span><b>{s.name}</b><small>{s.duration_min} min{s.description ? ` · ${s.description}` : ''}</small></span>
                    <span className="bk-price">{euro(s.price)}</span>
                  </button>
                ))}
              </div>
            ))}
          </section>}

          {step === 'operatore' && service && <section>
            <h2>Con chi?</h2>
            <div className="bk-grid">
              <button className="bk-staff" data-testid="staff" onClick={() => { setStaffId(null); setStep('orario') }}><i style={{ background: brand.colors.primary }}>★</i>Prima disponibile</button>
              {page.staff.filter((s) => service.staff_ids.includes(s.id)).map((s) => (
                <button key={s.id} className="bk-staff" data-testid="staff" onClick={() => { setStaffId(s.id); setStep('orario') }}><i style={{ background: s.color }}>{s.first_name[0]}</i>{s.first_name}</button>
              ))}
            </div>
          </section>}

          {step === 'orario' && service && <section>
            <h2>Quando?</h2>
            <div className="bk-days">
              {days.map((d) => (
                <button key={iso(d)} data-testid="day" className={iso(d) === day ? 'on' : ''} onClick={() => { setDay(iso(d)); setTime(null) }}>
                  <small>{d.toLocaleDateString('it-IT', { weekday: 'short' })}</small><b>{d.getDate()}</b><small>{d.toLocaleDateString('it-IT', { month: 'short' })}</small>
                </button>
              ))}
            </div>
            <p className="bk-muted" style={{ textTransform: 'capitalize' }}>{dayLabel}</p>
            {times === null ? <div className="bk-slots">{Array.from({ length: 8 }, (_, i) => <span key={i} className="bk-skel" />)}</div>
              : times.length === 0 ? <p className="bk-warn">Nessun orario libero in questa giornata. Prova un altro giorno 🙂</p>
                : <div className="bk-slots">{times.map((t) => <button key={t} data-testid="slot" onClick={() => { setTime(t); setStep('dati') }}>{t}</button>)}</div>}
          </section>}

          {step === 'dati' && service && time && <section>
            <div className="bk-summary"><b>{service.name}</b><span style={{ textTransform: 'capitalize' }}>{dayLabel} · ore {time}</span><span>{staffName ? `con ${staffName}` : 'Primo operatore disponibile'} · {euro(service.price)}</span></div>
            <h2>I tuoi dati</h2>
            <div className="bk-row">
              <input name="first_name" placeholder="Nome" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
              <input name="last_name" placeholder="Cognome" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
            </div>
            <input name="phone" placeholder="Cellulare (WhatsApp)" inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            <input name="website" tabIndex={-1} autoComplete="off" className="bk-trap" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} />
            <label className="bk-check"><input type="checkbox" name="privacy" checked={form.privacy} onChange={(e) => setForm({ ...form, privacy: e.target.checked })} />Accetto l'informativa privacy per la gestione della prenotazione</label>
            <label className="bk-check"><input type="checkbox" name="marketing" checked={form.marketing} onChange={(e) => setForm({ ...form, marketing: e.target.checked })} />Voglio ricevere offerte e novità su WhatsApp</label>
            {error && <p className="bk-error">{error}</p>}
          </section>}

          {step === 'fatto' && token && service && <section className="bk-done">
            <div className="bk-ok">✓</div>
            <h2>Prenotazione confermata!</h2>
            <p><b>{service.name}</b><br /><span style={{ textTransform: 'capitalize' }}>{dayLabel}</span> alle {time}</p>
            <p className="bk-wa"><WhatsAppIcon /> Ti abbiamo inviato la conferma su WhatsApp</p>
            <Link className="bk-outline" to={`/prenota/${slug}/a/${token}`}>Gestisci o disdici l'appuntamento</Link>
            <button className="bk-link" onClick={() => { setStep('servizio'); setService(null); setTime(null) }}>Prenota un altro servizio</button>
          </section>}
        </main>

        {step === 'dati' && <footer className="bk-foot">
          <button className="bk-primary" onClick={confirm} disabled={busy || !form.first_name || !form.last_name || !form.phone || !form.privacy}>{busy ? 'Conferma in corso…' : 'Conferma prenotazione'}</button>
          <p>Puoi disdire gratis fino a {page.cancel_hours} ore prima</p>
        </footer>}
        <p className="bk-powered"><Mark size={14} /> Prenotazioni con BluBeauty · BluCode Informatica</p>
      </div>
    </div>
  )
}

export function MyAppointment() {
  const { slug = '', token = '' } = useParams()
  const [a, setA] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { call(`${slug}/a/${token}`).then(setA).catch((e) => setError(e.message)) }, [slug, token])
  const cancel = async () => {
    setBusy(true)
    try { setA(await call(`${slug}/a/${token}/disdici`, {})); setConfirming(false) } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  if (!a) return <div className="bk-wrap"><div className="bk-app"><div className="bk-head"><h1>Il tuo appuntamento</h1></div><main className="bk-main">{error ? <p className="bk-warn">{error}</p> : null}</main></div></div>
  const cancelled = a.status === 'disdetto'
  const when = new Date(a.starts_at)
  return (
    <div className="bk-wrap">
      <div className="bk-app">
        <header className="bk-head">
          <div className="bk-top"><span className="bk-brand"><Mark /> BluBeauty</span></div>
          <h1>{a.salon}</h1>
          <p>Ciao {a.client_first_name}, ecco il tuo appuntamento</p>
        </header>
        <main className="bk-main">
          <div className={`bk-appt ${cancelled ? 'off' : ''}`}>
            <small className={cancelled ? 'red' : ''}>{cancelled ? 'Disdetto' : a.past ? 'Concluso' : 'Confermato'}</small>
            <h2 style={{ textTransform: 'capitalize' }}>{when.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Rome' })}</h2>
            <b className="bk-time">{when.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Rome' })}</b>
            {a.items.map((i: any, n: number) => <div key={n} className="bk-line"><span>{i.service}{i.staff ? ` · con ${i.staff}` : ''}</span><b>{euro(i.price)}</b></div>)}
          </div>
          {error && <p className="bk-error">{error}</p>}
          {a.can_cancel && !confirming && <button className="bk-danger-outline" onClick={() => setConfirming(true)}>Disdici appuntamento</button>}
          {confirming && <div className="bk-confirm">
            <p>Vuoi davvero disdire? Lo spazio tornerà disponibile per altri clienti.</p>
            <div className="bk-row"><button className="bk-white" onClick={() => setConfirming(false)}>No, tengo</button><button className="bk-danger" onClick={cancel} disabled={busy}>{busy ? 'Attendi…' : 'Sì, disdici'}</button></div>
          </div>}
          {!cancelled && !a.past && !a.can_cancel && <p className="bk-warn">Mancano meno di {a.cancel_hours} ore: per disdire chiama il salone.</p>}
          <Link className="bk-primary" to={`/prenota/${slug}`}>{cancelled ? 'Prenota un nuovo appuntamento' : 'Prenota un altro servizio'}</Link>
        </main>
      </div>
    </div>
  )
}

/** Il buono regalo sul telefono di chi lo riceve (link mandato su WhatsApp): valore, credito residuo, codice e QR. */
export function VoucherPage() {
  const { slug = '', token = '' } = useParams()
  const [v, setV] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [qr, setQr] = useState('')
  useEffect(() => { call(`${slug}/buono/${token}`).then(setV).catch((e) => setError(e.message)) }, [slug, token])
  useEffect(() => {
    if (v) import('qrcode').then((Q) => Q.toDataURL(v.code.replace(/-/g, ''), { margin: 1, width: 220 }).then(setQr))
  }, [v])
  if (!v) return <div className="bk-wrap"><div className="bk-app"><div className="bk-head"><h1>Buono regalo</h1></div><main className="bk-main">{error ? <p className="bk-warn">{error}</p> : null}</main></div></div>
  const off = v.status !== 'attivo'
  const label: Record<string, string> = { esaurito: 'Già utilizzato', scaduto: 'Scaduto', annullato: 'Non più valido' }
  return (
    <div className="bk-wrap">
      <div className="bk-app">
        <header className="bk-head">
          <div className="bk-top"><span className="bk-brand"><Mark /> BluBeauty</span></div>
          <h1>{v.salon}</h1>
          <p>{v.beneficiary_name ? `Per ${v.beneficiary_name}: un regalo per te` : 'Un regalo per te'} 🎁</p>
        </header>
        <main className="bk-main">
          <div className={`bk-appt ${off ? 'off' : ''}`} style={{ textAlign: 'center' }}>
            <small className={off ? 'red' : ''}>{off ? label[v.status] ?? v.status : 'Buono regalo'}</small>
            <h2 style={{ margin: '6px 0' }}>{v.service ?? euro(v.initial_amount)}</h2>
            {v.message && <p style={{ fontStyle: 'italic' }}>«{v.message}»</p>}
            {v.balance !== v.initial_amount && !off && <div className="bk-line"><span>Credito ancora disponibile</span><b>{euro(v.balance)}</b></div>}
            {qr && <img src={qr} alt="" width={180} height={180} style={{ margin: '10px auto', display: 'block' }} />}
            <div className="bk-line"><span>Codice</span><b style={{ fontFamily: 'monospace' }}>{v.code}</b></div>
            {v.expires_on && <div className="bk-line"><span>Valido fino al</span><b>{new Date(v.expires_on + 'T12:00').toLocaleDateString('it-IT')}</b></div>}
          </div>
          <p style={{ textAlign: 'center', fontSize: 14, opacity: 0.8 }}>Mostra questa pagina in salone quando vieni: si può usare anche in più volte.</p>
          {!off && <a className="bk-primary" href={v.booking_url}>Prenota il tuo appuntamento</a>}
          {(v.address || v.phone) && <p style={{ textAlign: 'center', fontSize: 14 }}>{v.address}{v.phone ? ` · Tel. ${v.phone}` : ''}</p>}
        </main>
      </div>
    </div>
  )
}
