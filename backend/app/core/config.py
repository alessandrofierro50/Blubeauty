from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurazione letta dalle variabili d'ambiente (file .env in sviluppo)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Prodotto
    brand_name: str = "BluBeauty"
    public_url: str = "http://localhost:5173"
    timezone: str = "Europe/Rome"

    # Database: l'app usa un ruolo SENZA privilegi di proprietario, così la RLS vale sempre.
    database_url: str = "postgresql+psycopg://blubeauty_app:app@localhost:5432/blubeauty"
    # Le migrazioni usano il ruolo proprietario.
    database_owner_url: str = "postgresql+psycopg://blubeauty_owner:owner@localhost:5432/blubeauty"

    redis_url: str = "redis://localhost:6379/0"

    # Cartella dei file caricati (immagini articoli, allegati)
    media_dir: str = "./media"
    # Cartella con BluBeauty Agent da scaricare dal gestionale (in Docker: ./agent montata in /agent)
    agent_dir: str = ""

    # Sicurezza
    secret_key: str = "cambiami-in-produzione"
    access_token_minutes: int = 60 * 12
    admin_token_minutes: int = 60 * 4
    rate_limits: bool = True  # limite di tentativi su login, recupero password e prova gratuita (spento nei test)

    # Super amministratore iniziale (creato dal seed)
    superadmin_email: str = "admin@blubeauty.local"
    superadmin_password: str = "cambiami"

    # Prova gratuita dal sito (pagina /prova): pacchetto e durata; vuoto TRIAL_PLAN = iscrizione disattivata
    trial_plan: str = "SALONE"
    trial_days: int = 7  # come promesso sul sito (content.py PROVA_GIORNI)
    trial_extra_modules: str = ""  # es. "fatturapa,tentata_vendita"
    website_url: str = "https://blucodeinformatica.it"
    # Termini di utilizzo accettati nell'iscrizione (contratto comune: progetto_blucode_informatica/comune/prova-gratuita.md)
    terms_version: str = "1.0"  # deve coincidere con quella mostrata dal modulo del sito
    terms_url: str = "https://blucodeinformatica.it/termini/"
    terms_pdf_url: str = "https://blucodeinformatica.it/termini/termini-di-utilizzo-v1.0.pdf"  # allegato all'email

    # Email
    # Standard comune (progetto_blucode_informatica/comune/abbonamenti.md §6): SMTP Aruba smtps.aruba.it:465 SSL,
    # utente = indirizzo completo; la password solo nel .env del server.
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True  # STARTTLS sulle porte diverse da 465 (con la 465 la connessione è già SSL)
    smtp_from: str = "info@blucodeinformatica.it"  # mittente di tutte le email ai clienti
    mail_from_name: str = "BluBeauty · BluCode Informatica"  # nome visualizzato del mittente
    # Comunicazioni a BluCode: nuove prove, copia degli avvisi di scadenza, riepilogo settimanale
    admin_notify_email: str = "blubeauty@blucodeinformatica.it"

    # Contatti per rinnovare, mostrati nella pagina «Abbonamento» e negli avvisi ({contatti})
    support_email: str = "info@blucodeinformatica.it"
    support_phone: str = "379 233 3492"

    # Riepilogo per la BluCode Console (GET /api/console/riepilogo): vuota = endpoint disattivato (404)
    console_api_key: str = ""
    # Cambio credenziali del super amministratore dalla Console (POST /api/console/super-admin/credenziali):
    # seconda chiave, diversa dalla prima; vuota = comando disattivato (404)
    console_admin_key: str = ""
    # super amministratore da cambiare se ce n'è più d'uno (vuoto = il primo creato)
    console_superadmin_email: str = ""

    # Fatturazione elettronica Aruba (modulo extra "fatturapa")
    aruba_env: str = "demo"  # demo | produzione
    aruba_username: str = ""  # utenza Premium della piattaforma (le aziende clienti sono suoi cedenti)
    aruba_password: str = ""
    aruba_callback_key: str = ""  # api-key scelta nel pannello Aruba per le callback (header Authorization)

    # Pagamenti online degli abbonamenti (contratto comune: progetto_blucode_informatica/comune/pagamenti.md).
    # Un metodo compare solo se è in PAGAMENTI_METODI e ha le sue chiavi; le chiavi stanno solo nel .env del server.
    pagamenti_metodi: str = "carta,paypal,bonifico"
    stripe_secret_key: str = ""  # sk_test_... / sk_live_...
    stripe_webhook_secret: str = ""  # whsec_... dell'endpoint /api/pagamenti/webhook/stripe
    paypal_client_id: str = ""
    paypal_secret: str = ""
    paypal_webhook_id: str = ""  # id del webhook /api/pagamenti/webhook/paypal (serve a verificarne la firma)
    paypal_mode: str = "sandbox"  # sandbox | live
    bonifico_intestatario: str = "BluCode Informatica"
    bonifico_iban: str = ""  # vuoto = bonifico nascosto (si può impostare anche dal pannello)
    # Cedente delle fatture degli abbonamenti (BluCode): solo da .env, nessun dato fiscale nel codice
    cedente_denominazione: str = ""
    cedente_piva: str = ""
    cedente_cf: str = ""
    cedente_indirizzo: str = ""
    cedente_cap: str = ""
    cedente_comune: str = ""
    cedente_provincia: str = ""
    regime_fiscale: str = "RF19"  # forfettario: righe a 0% con Natura N2.2
    bollo_a_carico: str = "cliente"  # cliente (riga «Rimborso imposta di bollo») | cedente
    fatture_sezionale: str = "BB"  # numeri N/BB, progressivo per anno solare
    fatture_invio: str = "manuale"  # manuale (XML a ADMIN_NOTIFY_EMAIL) | sdi (invio tramite Aruba, utenza ARUBA_*)


@lru_cache
def get_settings() -> Settings:
    return Settings()
