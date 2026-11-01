// Schermate di BluBeauty per il video e il manuale: martedì 3 novembre 2026, ore 10:20, salone «Aurora Hair & Beauty».
const { chromium } = require("playwright");
const B = "http://localhost:3300";
const REG = process.argv[3];
(async () => {
  const sp = process.argv[2];
  const b = await chromium.launch();
  const errors = [], done = [];
  const ctx = await b.newContext({ viewport: { width: 1440, height: 810 }, deviceScaleFactor: 4 / 3, locale: "it-IT", timezoneId: "Europe/Rome", colorScheme: "light" });
  const p = await ctx.newPage();
  await p.clock.setFixedTime(new Date("2026-11-03T10:20:00+01:00"));
  p.on("pageerror", (e) => errors.push(e.message));
  const shot = async (name, page = p) => { await page.waitForTimeout(700); await page.screenshot({ path: `${sp}/shots/${name}.png` }); done.push(name); };
  const step = async (label, fn) => { try { await fn(); } catch (e) { errors.push(`${label}: ${e.message.split("\n")[0]}`); } };

  await step("login", async () => {
    await p.goto(`${B}/login`);
    await p.fill('input[type=email]', "salone@demo.blubeauty.it");
    await p.fill('input[type=password]', "Demo2026!");
    await shot("01-accesso");
    await p.getByRole("button", { name: /accedi/i }).click();
    await p.getByText("Oggi in salone").waitFor();
    await shot("02-oggi");
  });
  await step("menu completo", async () => {
    await p.getByText("Mostra tutte le funzioni").click();
    await p.waitForTimeout(800);
    await shot("03-menu-completo");
    await p.locator("[data-testid=cerca-funzione]").fill("ferie");
    await shot("04-cerca-funzione");
    await p.locator("[data-testid=cerca-funzione]").fill("");
    await p.getByText("Modalità semplice").click();
  });
  await step("nuovo appuntamento", async () => {
    await p.goto(`${B}/nuovo`);
    await p.locator("[data-testid=cerca-cliente]").fill("Sofia");
    await p.waitForTimeout(800);
    await shot("05-nuovo-per-chi");
    await p.getByText("Costa Sofia").first().click();
    await p.locator("[data-testid=servizio]").first().waitFor();
    await shot("06-nuovo-cosa");
    await p.getByText("Colore + piega").first().click();
    await p.locator("[data-testid=operatore]").first().waitFor();
    await shot("07-nuovo-con-chi");
    await p.locator("[data-testid=operatore]").first().click();
    await p.waitForTimeout(800);
    if (!(await p.locator("[data-testid=orario]").count())) { await p.getByRole("button", { name: /Domani/ }).click(); await p.waitForTimeout(800); }
    await p.locator("[data-testid=orario]").nth(3).click();
    await shot("08-nuovo-quando");
    await p.locator("[data-testid=conferma-alto]").click();
    await p.getByText("Un altro appuntamento").waitFor();
    await shot("09-nuovo-fatto");
  });
  await step("agenda", async () => {
    await p.goto(`${B}/agenda?giorno=2026-11-03`);
    await p.waitForTimeout(1500);
    await shot("10-agenda");
    await p.getByText(/^\d\d:\d\d · /).first().click();
    await p.waitForTimeout(800);
    await shot("11-appuntamento");
    await p.keyboard.press("Escape");
  });
  await step("incasso con ricevuta non fiscale", async () => {
    await p.goto(`${B}/`);
    await p.getByText("Oggi in salone").waitFor();
    await p.locator("[data-testid=today-appt]").getByRole("button", { name: "Incassa" }).first().click();
    await p.getByText("Come paga?").waitFor();
    await shot("12-incasso");
    await p.locator("[data-testid=tipo-documento]").getByText("Ricevuta non fiscale").click();
    await shot("13-incasso-ricevuta-non-fiscale");
    await p.locator("[data-testid=tipo-documento]").getByText("Scontrino fiscale").click();
    await p.getByRole("button", { name: "Carta" }).click();
    await p.getByText(/^Fatto!/).waitFor();
    await p.waitForTimeout(1500);
    await shot("14-incasso-fatto");
    await p.getByRole("button", { name: "Chiudi" }).click();
  });
  await step("turni", async () => {
    await p.goto(`${B}/agenda/turni`);
    await p.getByText("Assenze e chiusure in questo periodo").waitFor();
    await shot("15-turni");
    const cells = p.locator("[data-testid=turno]");
    const days = (await p.locator("thead th").count()) - 1;
    await cells.nth(days + 3).click();  // Marco, giovedì
    await p.locator(".mantine-Modal-content").getByRole("button", { name: "Ferie", exact: true }).click();
    await shot("16-turni-assenza");
    await p.locator("[data-testid=salva-assenza]").click();
    await p.waitForTimeout(1200);
    await shot("17-turni-da-spostare");
    const fatto = p.getByRole("button", { name: "Fatto" });
    if (await fatto.count()) await fatto.click();
    await p.waitForTimeout(500);
    await shot("18-turni-dopo");
  });
  await step("clienti", async () => {
    await p.goto(`${B}/agenda/clienti`);
    await p.waitForTimeout(1500);
    await shot("19-clienti");
    await p.getByText("Esposito Laura").first().click();
    await p.waitForTimeout(1500);
    await shot("20-scheda-cliente");
  });
  await step("marketing", async () => {
    await p.goto(`${B}/marketing`);
    await p.waitForTimeout(1500);
    await shot("21-marketing");
    const tabs = p.getByRole("tab");
    const n = await tabs.count();
    for (let i = 1; i < Math.min(n, 4); i++) { await tabs.nth(i).click(); await shot(`22-marketing-${i}`); }
  });
  await step("cassa", async () => {
    await p.goto(`${B}/cassa/${REG}`);
    await p.waitForTimeout(2500);
    const keys = p.locator("button", { hasText: /€/ });
    await shot("23-cassa");
    await p.getByText("Shampoo riparatore", { exact: false }).first().click();
    await p.getByText("Maschera nutriente", { exact: false }).first().click();
    await shot("24-cassa-prodotti");
    await p.keyboard.press("F12");
    await p.getByText("Da pagare").waitFor();
    await p.locator("[data-testid=tipo-documento]").getByText("Ricevuta non fiscale").click();
    await p.getByRole("button", { name: "Contanti esatti" }).click();
    await shot("25-cassa-ricevuta-non-fiscale");
    await p.getByRole("button", { name: /Stampa ricevuta non fiscale/ }).click();
    await p.waitForTimeout(2500);
    await shot("26-cassa-dopo");
  });
  await step("ricevute", async () => {
    await p.goto(`${B}/pos/ricevute`);
    await p.locator("[data-testid=anteprima-ricevuta]").waitFor();
    await p.waitForTimeout(1200);
    await shot("27-ricevute");
  });
  await step("impostazioni", async () => {
    await p.goto(`${B}/agenda/impostazioni`);
    await p.waitForTimeout(1500);
    await shot("28-impostazioni-salone");
    await p.goto(`${B}/agenda/servizi`);
    await p.waitForTimeout(1500);
    await shot("29-servizi");
    await p.goto(`${B}/periferiche`);
    await p.waitForTimeout(1500);
    await shot("30-periferiche");
  });
  // prenotazione online dal telefono della cliente
  await step("prenotazione online", async () => {
    const m = await (await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: "it-IT", timezoneId: "Europe/Rome", isMobile: true, hasTouch: true })).newPage();
    await m.goto(`${B}/prenota/aurora`);
    await m.getByText("Cosa desideri prenotare?").waitFor();
    await shot("31-prenota-servizi", m);
    await m.getByText("Piega").first().click();
    await m.waitForTimeout(600);
    await shot("32-prenota-operatore", m);
    await m.getByText("Giulia").first().click().catch(() => {});
    await m.locator("[data-testid=day]").nth(2).click();
    await m.locator("[data-testid=slot]").first().waitFor();
    await shot("33-prenota-orari", m);
    await m.locator("[data-testid=slot]").nth(1).click();
    await m.fill("input[name=first_name]", "Giorgia");
    await m.fill("input[name=last_name]", "Ferrari");
    await m.fill("input[name=phone]", "347 123 4567");
    await m.check("input[name=privacy]");
    await m.check("input[name=marketing]");
    await shot("34-prenota-dati", m);
    await m.getByText("Conferma prenotazione").click();
    await m.getByText("Prenotazione confermata!").waitFor();
    await shot("35-prenota-confermata", m);
    await m.getByText("Gestisci o disdici").click();
    await m.waitForTimeout(800);
    await shot("36-prenota-gestisci", m);
  });
  console.log("fatte:", done.length, done.join(" "));
  console.log("errori:", JSON.stringify(errors, null, 1));
  await b.close();
})();
