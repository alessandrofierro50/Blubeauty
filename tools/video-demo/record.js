// Registra le scene del video dimostrativo BluBeauty con Playwright.
// Uso: node record.js [id-scena ...]   (senza argomenti: tutte)
const { chromium } = require("playwright");
const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const B = "http://localhost:3100";
const DIR = __dirname;
const OUT = path.join(DIR, "raw");
const VIEW = { width: 1280, height: 720 };
const DSF = 1.5;
const scenes = JSON.parse(fs.readFileSync(path.join(DIR, "scenes.json"), "utf8"));
const dur = (id) =>
  parseFloat(execSync(`ffprobe -v error -show_entries format=duration -of csv=p=0 ${DIR}/audio/${id}.mp3`).toString());
const sql = (q) =>
  execSync(`psql -h localhost -U blubeauty -d blubeauty -At -c ${JSON.stringify(q)}`, { env: { ...process.env, PGPASSWORD: "blubeauty" } })
    .toString()
    .trim();
const logoDark = fs.readFileSync(path.resolve(__dirname, "../../public/brand") + "/blubeauty-logo-dark.svg", "utf8");
const logoMark = fs.readFileSync(path.resolve(__dirname, "../../public/brand") + "/blubeauty-mark.svg", "utf8");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Overlay: cursore finto + titolo del capitolo ───────────────────────
const overlayScript = ({ title, num }) => {
  if (window.top !== window) return; // solo nella pagina principale, non negli iframe
  const install = () => {
    if (document.getElementById("__cur")) return;
    const st = document.createElement("style");
    st.textContent = `
      #__cur{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;
        transform:translate(var(--x,640px),var(--y,400px));transition:transform .55s cubic-bezier(.4,.0,.2,1)}
      #__cur svg{filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
      .__rip{position:fixed;z-index:2147483646;pointer-events:none;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
        background:rgba(30,91,216,.35);animation:__r .5s ease-out forwards}
      @keyframes __r{from{transform:scale(.2);opacity:1}to{transform:scale(1.4);opacity:0}}
      #__chap{position:fixed;right:22px;bottom:20px;z-index:2147483645;pointer-events:none;display:flex;align-items:center;gap:10px;
        background:rgba(11,42,91,.92);color:#fff;font:600 16px Inter,sans-serif;padding:10px 18px 10px 10px;border-radius:999px;
        box-shadow:0 8px 24px rgba(11,42,91,.3);animation:__in .6s ease-out}
      #__chap b{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:#3B8BFF;font-size:14px}
      @keyframes __in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}`;
    document.head.appendChild(st);
    const c = document.createElement("div");
    c.id = "__cur";
    c.innerHTML = `<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l15 11-6.5 1.2L16 21l-3 1.4-3.4-6.8L4 20z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
    const p = JSON.parse(sessionStorage.getItem("__curpos") || "null");
    if (p) c.style.cssText = `--x:${p[0]}px;--y:${p[1]}px;transition:none`;
    document.body.appendChild(c);
    if (title) {
      const ch = document.createElement("div");
      ch.id = "__chap";
      ch.innerHTML = `<b>${num}</b>${title}`;
      document.body.appendChild(ch);
    }
    window.__move = (x, y) => {
      c.style.transition = "";
      c.style.setProperty("--x", x + "px");
      c.style.setProperty("--y", y + "px");
      sessionStorage.setItem("__curpos", JSON.stringify([x, y]));
    };
    window.__ripple = (x, y) => {
      const r = document.createElement("div");
      r.className = "__rip";
      r.style.left = x + "px";
      r.style.top = y + "px";
      document.body.appendChild(r);
      setTimeout(() => r.remove(), 600);
    };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
};

async function pointTo(page, locator) {
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  const bb = await locator.boundingBox();
  if (!bb) throw new Error("elemento non visibile");
  const x = bb.x + bb.width / 2;
  const y = bb.y + bb.height / 2;
  await page.evaluate(([x, y]) => window.__move && window.__move(x, y), [x, y]);
  await sleep(620);
  return [x, y];
}
async function click(page, locator, pause = 350) {
  const [x, y] = await pointTo(page, locator);
  await page.evaluate(([x, y]) => window.__ripple && window.__ripple(x, y), [x, y]);
  await sleep(120);
  await locator.click();
  await sleep(pause);
}
async function type(page, locator, text, delay = 55) {
  await click(page, locator, 150);
  await page.keyboard.press("Control+A");
  await locator.pressSequentially(text, { delay });
}
async function smoothScroll(page, y, ms = 900) {
  await page.evaluate(
    ([y, ms]) =>
      new Promise((res) => {
        const start = window.scrollY;
        const t0 = performance.now();
        const step = (t) => {
          const k = Math.min(1, (t - t0) / ms);
          window.scrollTo(0, start + (y - start) * (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2));
          k < 1 ? requestAnimationFrame(step) : res();
        };
        requestAnimationFrame(step);
      }),
    [y, ms],
  );
}

// ── Pagine "palco" servite sulla stessa origine dell'app ───────────────
const stageCss = `
  *{box-sizing:border-box;margin:0}
  body{font-family:Inter,sans-serif;width:1280px;height:720px;overflow:hidden;
    background:radial-gradient(1200px 700px at 80% 10%,#3B8BFF33,transparent),linear-gradient(135deg,#eef5ff,#ffffff 55%,#fdf2f6)}
  .wrap{display:flex;align-items:center;gap:70px;height:720px;padding:0 90px}
  .phone{flex:none;width:330px;height:680px;border-radius:52px;background:#0f172a;padding:12px;box-shadow:0 30px 70px rgba(11,42,91,.35);position:relative}
  .phone .screen{width:306px;height:656px;border-radius:42px;overflow:hidden;background:#fff;position:relative}
  .phone .notch{position:absolute;top:12px;left:50%;transform:translateX(-50%);width:110px;height:26px;background:#0f172a;border-radius:0 0 16px 16px;z-index:5}
  .phone iframe{border:0;width:390px;height:836px;transform:scale(.7846);transform-origin:0 0;position:absolute;top:0;left:0}
  .side h1{font-size:44px;line-height:1.1;color:#0B2A5B;font-weight:800;letter-spacing:-1px}
  .side h1 span{color:#1E5BD8}
  .side ul{margin-top:28px;padding:0;list-style:none}
  .side li{font-size:22px;color:#334155;margin:16px 0;display:flex;gap:14px;align-items:center;opacity:0;transform:translateX(16px);transition:all .6s}
  .side li.on{opacity:1;transform:none}
  .side li i{flex:none;width:40px;height:40px;border-radius:12px;background:#1E5BD8;color:#fff;font-style:normal;display:flex;align-items:center;justify-content:center;font-size:20px}
  .brand{position:absolute;left:90px;top:34px;display:flex;align-items:center;gap:10px;font-weight:800;color:#0B2A5B;font-size:20px}
  .brand svg{width:34px;height:34px}`;

function phoneStage({ src, title, bullets }) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>${stageCss}</style></head><body>
  <div class="brand">${logoMark}<span>Blu<span style="font-weight:300;color:#1E5BD8">Beauty</span></span></div>
  <div class="wrap">
    <div class="phone"><div class="notch"></div><div class="screen">
      <iframe id="app" src="${src}"></iframe>
      <div id="chat" style="display:none;position:absolute;inset:0"></div>
    </div></div>
    <div class="side"><h1>${title}</h1><ul>${bullets.map((b) => `<li><i>${b[0]}</i>${b[1]}</li>`).join("")}</ul></div>
  </div>
  <script>window.showBullet=(n)=>document.querySelectorAll('.side li')[n]?.classList.add('on')</script>
  </body></html>`;
}

function chatHtml(messages) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const link = (s) => esc(s).replace(/(https?:\/\/\S+)/g, '<a data-link style="color:#027eb5;text-decoration:underline;word-break:break-all">$1</a>');
  return `<div style="height:100%;display:flex;flex-direction:column;background:#efeae2;font-family:Inter,sans-serif">
    <div style="background:#075e54;color:#fff;padding:44px 14px 12px;display:flex;align-items:center;gap:10px">
      <span style="width:38px;height:38px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center">${logoMark.replace("<svg", '<svg width="26" height="26"')}</span>
      <div><div style="font-weight:600;font-size:15px">Aurora Hair &amp; Beauty</div><div style="font-size:11px;opacity:.75">Account aziendale ✓</div></div>
    </div>
    <div id="msgs" style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:8px;padding:12px">
      ${messages
        .map(
          (m, i) => `<div class="m" data-i="${i}" style="display:none;align-self:${m.inbound ? "flex-end" : "flex-start"};max-width:86%;background:${m.inbound ? "#d9fdd3" : "#fff"};
          border-radius:10px;padding:8px 10px;font-size:13.5px;line-height:1.38;color:#111;box-shadow:0 1px 1px rgba(0,0,0,.12);white-space:pre-line">${link(m.body)}
          <div style="text-align:right;font-size:10.5px;color:#8696a0;margin-top:2px">${m.at} ${m.inbound ? "" : '<span style="color:#53bdeb">✓✓</span>'}</div></div>`,
        )
        .join("")}
    </div>
    <div style="background:#f0f2f5;padding:10px 12px;display:flex;gap:8px"><div style="flex:1;background:#fff;border-radius:20px;padding:9px 14px;color:#8696a0;font-size:13px">Messaggio</div></div>
  </div>`;
}

function titleStage({ kind }) {
  const intro = kind === "intro";
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    *{margin:0;box-sizing:border-box}
    body{width:1280px;height:720px;overflow:hidden;font-family:Inter,sans-serif;color:#fff;
      background:radial-gradient(900px 600px at 20% 20%,#3B8BFF,transparent),linear-gradient(135deg,#1E5BD8,#0B2A5B 70%)}
    .c{height:720px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;text-align:center}
    .logo{width:640px;opacity:0;transform:scale(.92);animation:in 1.2s .2s ease-out forwards}
    .logo svg{width:100%;height:auto}
    p{font-size:30px;font-weight:500;opacity:0;animation:up 1s 1.1s ease-out forwards}
    .chips{display:flex;gap:12px;flex-wrap:wrap;justify-content:center;max-width:1000px}
    .chips span{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25);padding:10px 20px;border-radius:999px;font-size:21px;opacity:0;animation:up .7s ease-out forwards}
    small{font-size:20px;opacity:0;animation:up 1s 2.6s ease-out forwards;color:#cfe3ff}
    @keyframes in{to{opacity:1;transform:none}}
    @keyframes up{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
  </style></head><body><div class="c">
    <div class="logo">${logoDark}</div>
    <p>${intro ? "Il gestionale per parrucchieri e centri estetici" : "Tutto il salone in un'unica app"}</p>
    <div class="chips">${["📱 Prenotazioni online", "📅 Agenda", "👤 Clienti", "🧾 Scontrino e fattura", "💬 Marketing WhatsApp"]
      .map((t, i) => `<span style="animation-delay:${1.6 + i * 0.35}s">${t}</span>`)
      .join("")}</div>
    <small>${intro ? "Demo guidata" : "blubeauty.blucodeinformatica.it · Blu Code Informatica"}</small>
  </div></body></html>`;
}

// ── Motore delle scene ───────────────────────────────────────────────
let browser;
let storageState;
const state = JSON.parse(fs.existsSync(`${DIR}/state.json`) ? fs.readFileSync(`${DIR}/state.json`, "utf8") : "{}");
const saveState = () => fs.writeFileSync(`${DIR}/state.json`, JSON.stringify(state, null, 2));

async function scene(id, run, { auth = false } = {}) {
  const meta = scenes.find((s) => s.id === id);
  const num = scenes.filter((s) => s.title).findIndex((s) => s.id === id) + 1;
  const D = dur(id);
  const tmp = path.join(OUT, id);
  fs.rmSync(tmp, { recursive: true, force: true });
  fs.mkdirSync(tmp, { recursive: true });
  const ctx = await browser.newContext({
    viewport: VIEW,
    deviceScaleFactor: DSF,
    ...(auth ? { storageState } : {}),
    locale: "it-IT",
    timezoneId: "Europe/Rome",
  });
  const t0 = Date.now();
  await ctx.addInitScript(overlayScript, { title: meta.title, num });
  await ctx.route(`${B}/__stage/**`, (route) => route.fulfill({ contentType: "text/html", body: ctx.__stage || "" }));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error(`[${id}] pageerror`, e.message));
  // Cattura nativa 1920x1080 (viewport 1280x720 con deviceScaleFactor 1.5)
  const frames = [];
  const cdp = await ctx.newCDPSession(page);
  cdp.on("Page.screencastFrame", async (f) => {
    const n = frames.length;
    const file = path.join(tmp, `f${String(n).padStart(5, "0")}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, "base64"));
    frames.push({ file, ts: f.metadata.timestamp * 1000 });
    cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080 });
  let started = 0;
  const start = () => {
    started = Date.now();
  };
  const remaining = () => D * 1000 - (Date.now() - started);
  await run({ page, ctx, start, remaining, D });
  if (!started) throw new Error("start() non chiamato");
  const left = remaining() + 700;
  if (left > 0) await sleep(left);
  const ended = Date.now();
  const total = (ended - started) / 1000;
  await cdp.send("Page.stopScreencast").catch(() => {});
  await ctx.close();
  // Elenco fotogrammi con durate reali → video a 30 fps costanti
  let firstIdx = frames.findIndex((f) => f.ts >= started);
  if (firstIdx === -1) firstIdx = frames.length - 1;
  if (firstIdx > 0) firstIdx -= 1; // l'ultimo fotogramma prima dell'inizio è lo stato visibile all'inizio
  const used = frames.slice(firstIdx);
  let list = "ffconcat version 1.0\n";
  used.forEach((f, i) => {
    const from = i === 0 ? started : f.ts;
    const to = i + 1 < used.length ? used[i + 1].ts : ended;
    list += `file '${f.file}'\nduration ${Math.max(0.001, (to - from) / 1000).toFixed(4)}\n`;
  });
  list += `file '${used[used.length - 1].file}'\n`;
  fs.writeFileSync(path.join(tmp, "list.txt"), list);
  execSync(
    `ffmpeg -v error -y -f concat -safe 0 -i ${tmp}/list.txt -vf "scale=1920:1080:flags=lanczos,fps=30,format=yuv420p" -c:v libx264 -preset medium -crf 16 ${OUT}/${id}.mp4`,
  );
  fs.rmSync(tmp, { recursive: true, force: true });
  const offset = 0;
  state[id] = { offset, length: total, audio: D };
  saveState();
  console.log(`✓ ${id}: audio ${D.toFixed(1)}s, scena ${total.toFixed(1)}s${total > D + 1.5 ? "  ⚠ più lunga della voce" : ""}`);
}

const stage = (ctx, html) => (ctx.__stage = html);

const SCENES = {
  "01-intro": () =>
    scene("01-intro", async ({ page, ctx, start }) => {
      stage(ctx, titleStage({ kind: "intro" }));
      await page.goto(`${B}/__stage/title`);
      start();
    }),

  "02-prenota": () =>
    scene("02-prenota", async ({ page, ctx, start, remaining }) => {
      stage(
        ctx,
        phoneStage({
          src: "/prenota/aurora",
          title: "Il cliente prenota<br><span>da solo, dal telefono</span>",
          bullets: [
            ["🔗", "Link su Instagram, Google, WhatsApp"],
            ["▦", "QR code in vetrina"],
            ["🕒", "Solo orari davvero liberi"],
            ["🌙", "24 ore su 24, senza telefonare"],
          ],
        }),
      );
      await page.goto(`${B}/__stage/phone`);
      const app = page.frameLocator("#app");
      await app.getByText("Cosa desideri prenotare?").waitFor();
      start();
      await sleep(1500);
      await page.evaluate(() => showBullet(0));
      await sleep(2600);
      await page.evaluate(() => showBullet(1));
      await sleep(2600);
      await click(page, app.getByText("Manicure semipermanente"), 900);
      await click(page, app.getByTestId("staff").filter({ hasText: "Sara" }), 900);
      await page.evaluate(() => showBullet(2));
      // giorno: tra 2 giorni (disdetta online consentita), o il primo successivo con orari liberi
      let dayIdx = 2;
      for (; dayIdx < 9; dayIdx++) {
        await click(page, app.getByTestId("day").nth(dayIdx), 600);
        await app.getByTestId("slot").first().or(app.getByText("Nessun orario libero")).waitFor();
        if (await app.getByTestId("slot").count()) break;
      }
      await sleep(1600);
      const slots = app.getByTestId("slot");
      const n = await slots.count();
      const slot = slots.nth(Math.min(2, n - 1));
      state.booking = { dayIdx, time: (await slot.innerText()).trim() };
      await click(page, slot, 700);
      await page.evaluate(() => showBullet(3));
      await type(page, app.locator("input[name=firstName]"), "Giorgia", 70);
      await type(page, app.locator("input[name=lastName]"), "Ferrari", 70);
      await type(page, app.locator("input[name=phone]"), "347 123 4567", 60);
      await click(page, app.locator("input[name=privacy]"), 300);
      await click(page, app.locator("input[name=marketing]"), 500);
      // conferma nel punto giusto della frase ("...e conferma.")
      const wait = remaining() - 9000;
      if (wait > 0) await sleep(wait);
      await click(page, app.getByText("Conferma prenotazione"), 200);
      await app.getByText("Prenotazione confermata!").waitFor();
      saveState();
    }),

  "03-whatsapp": () =>
    scene("03-whatsapp", async ({ page, ctx, start, remaining }) => {
      const row = sql(
        `select m.body, a."publicToken" from "Message" m join "Appointment" a on a.id=m."appointmentId" join "Client" c on c.id=m."clientId" where c."firstName"='Giorgia' and c."lastName"='Ferrari' and m.kind='CONFIRMATION' order by m."createdAt" desc limit 1`,
      ).split("|");
      const [body, token] = row;
      const now = new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Rome" });
      const msgs = [{ body, at: now }];
      stage(
        ctx,
        phoneStage({
          src: `/prenota/aurora/a/${token}`,
          title: "Conferma su WhatsApp<br><span>e disdetta con un tocco</span>",
          bullets: [
            ["✓", "Conferma immediata"],
            ["⏰", "Promemoria il giorno prima"],
            ["✕", "Disdetta autonoma dal link"],
            ["📉", "Meno buchi e no-show"],
          ],
        }),
      );
      await page.goto(`${B}/__stage/phone`);
      await page.evaluate((html) => {
        const chat = document.getElementById("chat");
        chat.innerHTML = html;
        chat.style.display = "block";
      }, chatHtml(msgs));
      start();
      await sleep(900);
      await page.evaluate(() => {
        document.querySelector("#chat .m").style.display = "block";
        showBullet(0);
      });
      await sleep(3800);
      await page.evaluate(() => showBullet(1));
      await sleep(3000);
      await click(page, page.locator("#chat [data-link]"), 400);
      await page.evaluate(() => (document.getElementById("chat").style.display = "none"));
      await page.evaluate(() => showBullet(2));
      const app = page.frameLocator("#app");
      await app.getByText("Disdici appuntamento").waitFor();
      await sleep(1800);
      await click(page, app.getByText("Disdici appuntamento"), 1600);
      await page.evaluate(() => showBullet(3));
      await sleep(Math.max(500, remaining() - 3500));
      await click(page, app.getByText("No, tengo"), 300);
    }),

  "04-agenda": () =>
    scene(
      "04-agenda",
      async ({ page, start }) => {
        const today = state.booking?.dayIdx === 0;
        const d = new Date();
        d.setDate(d.getDate() + (state.booking?.dayIdx ?? 0));
        const iso = d.toLocaleDateString("sv-SE", { timeZone: "Europe/Rome" });
        await page.goto(`${B}/agenda?data=${iso}`);
        await page.getByText("tempo di posa").waitFor();
        start();
        await sleep(1200);
        const online = page.locator("a", { hasText: "Giorgia Ferrari" });
        await pointTo(page, online);
        await sleep(4200);
        if (!today) {
          await click(page, page.getByRole("link", { name: "Oggi" }), 1200);
        }
        await pointTo(page, page.locator("a", { hasText: "Laura Esposito" }));
        await sleep(2600);
        await pointTo(page, page.locator("a", { hasText: "Laura Esposito" }).locator(".processing"));
        await sleep(2400);
        await pointTo(page, page.locator("a", { hasText: "Alessia Ricci" }));
      },
      { auth: true },
    ),

  "05-nuovo": () =>
    scene(
      "05-nuovo",
      async ({ page, start, remaining }) => {
        await page.goto(`${B}/agenda`);
        await page.getByText("tempo di posa").waitFor();
        start();
        await sleep(600);
        await click(page, page.getByRole("link", { name: "+ Appuntamento" }), 600);
        await page.getByText("Nuovo appuntamento").first().waitFor();
        await pointTo(page, page.locator("select[name=clientId]"));
        await page.selectOption("select[name=clientId]", { label: "Mancini Elena · +393338888888" });
        await sleep(700);
        await pointTo(page, page.locator("select[name=serviceId]"));
        const opt = await page.locator("select[name=serviceId] option", { hasText: "Taglio donna" }).getAttribute("value");
        await page.selectOption("select[name=serviceId]", opt);
        await sleep(700);
        await click(page, page.getByRole("button", { name: "Marco" }), 500);
        await page.getByRole("button", { name: /^\d\d:\d\d$/ }).first().waitFor();
        await sleep(600);
        const times = page.getByRole("button", { name: /^\d\d:\d\d$/ });
        await click(page, times.nth(Math.min(3, (await times.count()) - 1)), 400);
        await type(page, page.locator("input[name=notes]"), "Ha telefonato", 45);
        await click(page, page.getByText("Salva appuntamento"), 300);
        await page.getByText("Messaggi WhatsApp al cliente").waitFor();
        await sleep(Math.max(0, remaining() - 2500));
        await pointTo(page, page.locator("aside").getByText(/Il tuo appuntamento/).first());
      },
      { auth: true },
    ),

  "06-cliente": () =>
    scene(
      "06-cliente",
      async ({ page, start }) => {
        await page.goto(`${B}/clienti`);
        await page.getByText("Nuovo cliente").waitFor();
        start();
        await type(page, page.locator("input[name=q]"), "Esposito", 70);
        await click(page, page.getByRole("button", { name: "Cerca" }), 500);
        await click(page, page.getByText("Esposito Laura"), 300);
        await page.getByText("Schede tecniche").waitFor();
        await pointTo(page, page.getByText("punti fidelity"));
        await sleep(1300);
        await pointTo(page, page.getByText("Formula colore — Colore abituale"));
        await sleep(1800);
        await smoothScroll(page, 400, 1400);
        await pointTo(page, page.getByText("Conversazione WhatsApp"));
      },
      { auth: true },
    ),

  "07-scontrino": () =>
    scene(
      "07-scontrino",
      async ({ page, start }) => {
        await page.goto(`${B}/agenda`);
        await page.getByText("tempo di posa").waitFor();
        start();
        await sleep(500);
        await click(page, page.locator("a", { hasText: "Laura Esposito" }), 300);
        await page.getByText("Messaggi WhatsApp al cliente").waitFor();
        await sleep(1400);
        await click(page, page.getByText("✓ Cliente arrivato"), 300);
        await page.getByTestId("status").filter({ hasText: "In salone" }).waitFor();
        await sleep(1300);
        await click(page, page.getByText("💳 Vai alla cassa"), 300);
        await page.getByText("Aggiungi prodotti").waitFor();
        await sleep(2200);
        await click(page, page.locator("div", { hasText: /^Olio sublimante/ }).getByTestId("add-product"), 900);
        await type(page, page.locator("input[type=number]"), "4", 120);
        await sleep(600);
        await click(page, page.getByRole("button", { name: "💳 Carta / POS" }), 900);
        await pointTo(page, page.getByTestId("total"));
        await sleep(1500);
        await click(page, page.getByText("Incassa ed emetti scontrino"), 200);
        await page.getByTestId("receipt").waitFor();
        await sleep(1500);
        await pointTo(page, page.getByText("TOTALE COMPLESSIVO"));
        await sleep(2000);
        await pointTo(page, page.getByText(/Punti fidelity/));
      },
      { auth: true },
    ),

  "08-fattura": () =>
    scene(
      "08-fattura",
      async ({ page, start }) => {
        await page.goto(`${B}/cassa`);
        await page.getByText("Da incassare oggi").waitFor();
        start();
        await sleep(500);
        await click(page, page.locator("li", { hasText: "Francesca Romano" }).getByText("Incassa"), 400);
        await page.getByText("Aggiungi prodotti").waitFor();
        await click(page, page.getByTestId("doc-invoice"), 900);
        await pointTo(page, page.locator("input[name=fiscalCode]"));
        await sleep(1400);
        await click(page, page.getByText("Incassa ed emetti fattura"), 200);
        await page.getByTestId("invoice").waitFor();
        await sleep(1500);
        await pointTo(page, page.getByText("Pronta per l'invio allo SDI"));
        await sleep(1500);
        await pointTo(page, page.getByText("⬇ XML FatturaPA"));
      },
      { auth: true },
    ),

  "09-marketing": () =>
    scene(
      "09-marketing",
      async ({ page, start }) => {
        await page.goto(`${B}/marketing`);
        await page.getByText("Messaggi automatici").first().waitFor();
        start();
        await sleep(2500);
        await smoothScroll(page, 230, 1200);
        const items = ["Conferma prenotazione", "Promemoria", "Grazie + recensione", "Richiamo colore", "Compleanno"];
        for (const t of items) {
          await pointTo(page, page.locator("li").filter({ hasText: t }).getByRole("switch"));
          await sleep(1650);
        }
        await smoothScroll(page, 420, 900);
        const sw = page.locator("li").filter({ hasText: "Clienti persi" }).getByRole("switch");
        await sleep(800);
        await click(page, sw, 400);
      },
      { auth: true },
    ),

  "10-campagna": () =>
    scene(
      "10-campagna",
      async ({ page, start, remaining }) => {
        await page.goto(`${B}/marketing`);
        await page.getByText("Nuova campagna WhatsApp").waitFor();
        await page.evaluate(() => document.querySelector("section.card.grid")?.scrollIntoView({ block: "start" }));
        await page.evaluate(() => window.scrollBy(0, -20));
        start();
        await sleep(900);
        await click(page, page.getByText("Clienti che non vengono da 60+ giorni"), 900);
        await click(page, page.getByText("💡 Promo martedì e mercoledì"), 1200);
        await pointTo(page, page.getByText("Anteprima"));
        await sleep(3800);
        await click(page, page.getByRole("button", { name: /^Invia a \d+ clienti$/ }), 300);
        await page.getByTestId("campaign-sent").waitFor();
        await sleep(1800);
        await smoothScroll(page, 120, 1400);
        await pointTo(page, page.locator("div.mx-auto.w-44"));
        await sleep(Math.max(0, remaining() - 5000));
        await pointTo(page, page.locator("a[href=\"/prenota/aurora\"]"));
      },
      { auth: true },
    ),

  "11-outro": () =>
    scene("11-outro", async ({ page, ctx, start }) => {
      stage(ctx, titleStage({ kind: "outro" }));
      await page.goto(`${B}/__stage/title`);
      start();
    }),
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  browser = await chromium.launch();
  // login una volta sola
  const lc = await browser.newContext({ viewport: VIEW });
  const lp = await lc.newPage();
  await lp.goto(`${B}/login`);
  await lp.fill("input[name=email]", "demo@blubeauty.it");
  await lp.fill("input[name=password]", "demo1234");
  await lp.click("button");
  await lp.waitForURL("**/dashboard");
  storageState = await lc.storageState();
  await lc.close();

  const wanted = process.argv.slice(2);
  for (const id of Object.keys(SCENES)) {
    if (wanted.length && !wanted.includes(id)) continue;
    await SCENES[id]();
  }
  await browser.close();
})().catch((e) => {
  console.error("ERRORE", e);
  process.exit(1);
});
