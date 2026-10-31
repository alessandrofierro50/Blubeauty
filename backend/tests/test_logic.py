from datetime import date

from app.saas import logic
from app.saas.logic import SubscriptionLike as S

T = date(2026, 10, 28)


def test_stati_abbonamento():
    sub = S(date(2026, 1, 1), date(2026, 12, 31))
    assert logic.subscription_status(sub, T) == "attivo"
    assert logic.subscription_status(sub, date(2026, 12, 1)) == "in_scadenza"
    assert logic.subscription_status(sub, date(2026, 12, 31)) == "in_scadenza"
    assert logic.subscription_status(sub, date(2027, 1, 10)) == "tolleranza"      # entro 15 giorni
    assert logic.subscription_status(sub, date(2027, 1, 20)) == "sola_lettura"    # dopo la tolleranza
    assert logic.subscription_status(sub, date(2027, 3, 1)) == "sospeso"          # oltre tolleranza + 30
    assert logic.subscription_status(sub, T, suspended=True) == "sospeso"
    assert logic.subscription_status(S(date(2026, 10, 1), date(2026, 10, 31), is_trial=True), T) == "prova"
    assert logic.subscription_status(S(date(2026, 11, 1), date(2027, 10, 31)), T) == "programmato"


def test_livelli_di_accesso():
    assert logic.access_level("tolleranza") == "full"
    assert logic.access_level("sola_lettura") == "readonly"
    assert logic.access_level("sospeso") == "none"


def test_rinnovo_gia_inserito_estende_la_scadenza():
    subs = [S(date(2025, 11, 1), date(2026, 10, 31)), S(date(2026, 11, 1), date(2027, 10, 31))]
    cur = logic.current_subscription(subs, T)
    assert cur.end_date == date(2026, 10, 31)
    end = logic.effective_end(subs, T)
    assert end == date(2027, 10, 31)
    assert logic.subscription_status(cur, T, end=end) == "attivo"


def test_periodi():
    assert logic.next_period(date(2026, 1, 1), "annuale") == date(2026, 12, 31)
    assert logic.next_period(date(2026, 1, 31), "mensile") == date(2026, 2, 27)
    assert logic.next_period(date(2026, 3, 1), "mensile") == date(2026, 3, 31)


def test_regola_avviso_con_recupero():
    rules = [30, 15, 7, 1, 0]
    assert logic.reminder_to_send(30, rules) == 30
    assert logic.reminder_to_send(29, rules) == 30   # job saltato ieri: parte oggi
    assert logic.reminder_to_send(14, rules) == 15
    assert logic.reminder_to_send(0, rules) == 0
    assert logic.reminder_to_send(45, rules) is None
    assert logic.reminder_to_send(-1, rules) is None


def test_moduli_per_pacchetto():
    # pacchetti BluBeauty: AGENDA (agenda e clienti) e SALONE (+ cassa, registratore, magazzino, marketing…)
    agenda = logic.tenant_modules("AGENDA", None, [])
    assert "agenda" in agenda and "anagrafiche" in agenda and "pos" not in agenda and "marketing" not in agenda
    salone = logic.tenant_modules("SALONE", None, [])
    assert {"agenda", "pos", "periferiche", "marketing", "magazzino", "vendite"} <= set(salone)
    assert "fatturapa" not in salone and "fatturapa" in logic.tenant_modules("SALONE", None, ["fatturapa"])  # modulo extra
    assert logic.EXTRA_MODULES == ["fatturapa"]
    assert "tentata_vendita" not in logic.CATALOG_MODULES and "statistiche_avanzate" not in logic.CATALOG_MODULES
    assert logic.render_placeholders("Ciao {nome}", {"nome": "Anna"}) == "Ciao Anna"
