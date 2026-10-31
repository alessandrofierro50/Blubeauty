from app.saas import logic


def test_moduli_extra_fuori_dai_pacchetti():
    for code in logic.EXTRA_MODULES:
        assert code in logic.MODULES
        assert all(code not in mods for mods in logic.PLAN_MODULES.values())
    assert "fatturapa" not in logic.tenant_modules("BASE", None, [])
    assert "fatturapa" in logic.tenant_modules("BASE", None, ["fatturapa"])
    assert "tentata_vendita" in logic.tenant_modules("PLUS", None, ["tentata_vendita"])
