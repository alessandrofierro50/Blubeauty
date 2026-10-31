// Dati demo per sviluppo e video dimostrativi.
//   npx prisma db seed                → crea i dati se mancano
//   SEED_RESET=1 npx prisma db seed   → cancella e ricrea l'organizzazione demo
import "dotenv/config";
import bcrypt from "bcryptjs";
import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "../src/generated/prisma/client";
import type { MessageKind } from "../src/generated/prisma/enums";

const db = new PrismaClient({ adapter: new PrismaPg({ connectionString: process.env.DATABASE_URL! }) });
const SLUG = "aurora";
const DEMO_EMAIL = "demo@blubeauty.it";

const TEMPLATES: { kind: MessageKind; offset: number | null; enabled: boolean; template: string }[] = [
  {
    kind: "CONFIRMATION",
    offset: null,
    enabled: true,
    template:
      "Ciao {nome}! ✨ Il tuo appuntamento da {salone} è confermato per {data} alle {ora} ({servizio}).\nPer vederlo o disdirlo: {link}",
  },
  {
    kind: "REMINDER",
    offset: 24,
    enabled: true,
    template:
      "Ciao {nome}, ti ricordiamo l'appuntamento di domani alle {ora} da {salone} ({servizio}). Ti aspettiamo! 💙\nNon puoi venire? Disdici qui: {link}",
  },
  {
    kind: "CANCELLATION",
    offset: null,
    enabled: true,
    template: "Ciao {nome}, il tuo appuntamento del {data} alle {ora} è stato disdetto. Prenota di nuovo quando vuoi: {link}",
  },
  {
    kind: "THANK_YOU",
    offset: null,
    enabled: true,
    template: "Grazie {nome} per essere passata da {salone}! 🌸 Se ti sei trovata bene, ci lasci una recensione? Ci aiuta tantissimo: {link}",
  },
  {
    kind: "RECALL",
    offset: 35,
    enabled: true,
    template: "Ciao {nome}, sono passate 5 settimane dal tuo ultimo colore 🎨 È il momento giusto per il ritocco! Prenota in un tap: {link}",
  },
  {
    kind: "BIRTHDAY",
    offset: 0,
    enabled: true,
    template: "Tanti auguri {nome}! 🎂 Per il tuo compleanno hai il 20% di sconto su un trattamento a scelta questo mese. Prenota: {link}",
  },
  {
    kind: "WIN_BACK",
    offset: 60,
    enabled: false,
    template: "Ciao {nome}, ci manchi! 💙 Torna a trovarci entro fine mese: per te una piega in omaggio con qualsiasi servizio. Prenota: {link}",
  },
];

async function main() {
  const existing = await db.organization.findUnique({ where: { slug: SLUG } });
  if (existing && process.env.SEED_RESET !== "1") {
    console.log("Seed già presente (usa SEED_RESET=1 per ricrearlo).");
    return;
  }
  if (process.env.SEED_RESET === "1") {
    const orgs = await db.organization.findMany({ where: { slug: { in: [SLUG, "salone-demo"] } } });
    const organizationId = { in: orgs.map((o) => o.id) };
    // Prima le tabelle con vincoli non a cascata, poi l'organizzazione (cascade sul resto)
    await db.sale.deleteMany({ where: { organizationId } });
    await db.appointment.deleteMany({ where: { organizationId } });
    await db.clientPackage.deleteMany({ where: { organizationId } });
    await db.organization.deleteMany({ where: { id: organizationId } });
    await db.user.deleteMany({ where: { email: DEMO_EMAIL } });
  }

  const org = await db.organization.create({
    data: {
      name: "Aurora Hair & Beauty",
      slug: SLUG,
      businessType: "MIXED",
      phone: "+39 06 1234567",
      whatsappNumber: "+39 333 0000000",
      email: "info@aurora-demo.it",
      vatNumber: "01234567890",
      address: "Via Roma 12",
      zip: "00185",
      city: "Roma",
      province: "RM",
      automations: { create: TEMPLATES },
    },
  });

  const allDay: [string, string][] = [["09:00", "19:30"]];
  const location = await db.location.create({
    data: {
      organizationId: org.id,
      name: "Sede principale",
      address: "Via Roma 12",
      city: "Roma",
      openingHours: { mon: allDay, tue: allDay, wed: allDay, thu: [["09:00", "20:30"]], fri: [["09:00", "20:30"]], sat: [["08:30", "18:00"]] },
    },
  });

  const owner = await db.user.create({
    data: {
      email: DEMO_EMAIL,
      name: "Alessandra Titolare",
      passwordHash: await bcrypt.hash("demo1234", 10),
      memberships: { create: { organizationId: org.id, role: "OWNER" } },
    },
  });

  const mkStaff = (firstName: string, lastName: string, color: string, extra = {}) =>
    db.staffMember.create({ data: { organizationId: org.id, locationId: location.id, firstName, lastName, color, serviceCommissionPct: 10, ...extra } });
  const giulia = await mkStaff("Giulia", "Rossi", "#2563eb", { userId: owner.id });
  const marco = await mkStaff("Marco", "Bianchi", "#0891b2");
  const sara = await mkStaff("Sara", "Verdi", "#db2777");

  const cabina = await db.resource.create({ data: { organizationId: org.id, locationId: location.id, name: "Cabina 1", type: "CABIN" } });

  const capelli = await db.serviceCategory.create({ data: { organizationId: org.id, name: "Capelli", sortOrder: 1 } });
  const estetica = await db.serviceCategory.create({ data: { organizationId: org.id, name: "Estetica", sortOrder: 2 } });

  const svc = async (name: string, categoryId: string, price: number, durationMin: number, staff: string[], extra = {}) => {
    const s = await db.service.create({ data: { organizationId: org.id, categoryId, name, price, durationMin, ...extra } });
    await db.staffService.createMany({ data: staff.map((staffId) => ({ staffId, serviceId: s.id })) });
    return s;
  };
  const piega = await svc("Shampoo e piega", capelli.id, 22, 30, [giulia.id, marco.id]);
  const taglio = await svc("Taglio donna", capelli.id, 35, 45, [giulia.id, marco.id]);
  const taglioUomo = await svc("Taglio uomo", capelli.id, 20, 30, [marco.id]);
  const colore = await svc("Colore + piega", capelli.id, 65, 80, [giulia.id], { processingStartMin: 20, processingMin: 35 });
  await svc("Balayage", capelli.id, 120, 150, [giulia.id], { processingStartMin: 45, processingMin: 40 });
  const manicure = await svc("Manicure semipermanente", estetica.id, 30, 50, [sara.id]);
  await svc("Pulizia viso", estetica.id, 55, 60, [sara.id], { requiredResources: { connect: { id: cabina.id } } });
  await svc("Ceretta gambe complete", estetica.id, 28, 40, [sara.id], { requiredResources: { connect: { id: cabina.id } } });
  const presso = await svc("Pressoterapia", estetica.id, 40, 45, [sara.id], { requiredResources: { connect: { id: cabina.id } } });

  await db.product.createMany({
    data: [
      { organizationId: org.id, name: "Shampoo riparatore 250 ml", brand: "Aurora Lab", price: 18, cost: 7, stock: 24, minStock: 6, usage: "RETAIL" },
      { organizationId: org.id, name: "Maschera nutriente 200 ml", brand: "Aurora Lab", price: 24, cost: 9, stock: 15, minStock: 4, usage: "RETAIL" },
      { organizationId: org.id, name: "Olio sublimante 100 ml", brand: "Aurora Lab", price: 29, cost: 11, stock: 9, minStock: 3, usage: "RETAIL" },
      { organizationId: org.id, name: "Crema viso idratante", brand: "Aurora Skin", price: 35, cost: 14, stock: 7, minStock: 3, usage: "RETAIL" },
      { organizationId: org.id, name: "Colore 6.3 tubo 60 ml", brand: "—", cost: 6, stock: 30, minStock: 10, usage: "INTERNAL", unit: "pz" },
    ],
  });

  const pkg = await db.packageTemplate.create({
    data: { organizationId: org.id, serviceId: presso.id, name: "10 sedute pressoterapia", sessions: 10, price: 350, validityDays: 180 },
  });

  const now = new Date();
  const daysAgo = (n: number) => new Date(now.getTime() - n * 86_400_000);
  const month = now.getMonth();
  type C = [string, string, string, { marketing?: boolean; birthMonth?: number; billing?: boolean }?];
  const people: C[] = [
    ["Laura", "Esposito", "+39 333 1111111", { marketing: true }],
    ["Francesca", "Romano", "+39 333 2222222", { marketing: true, billing: true }],
    ["Chiara", "Colombo", "+39 333 3333333", { marketing: true, birthMonth: month }],
    ["Alessia", "Ricci", "+39 333 4444444", { marketing: true }],
    ["Martina", "Gallo", "+39 333 5555555", { marketing: true }],
    ["Valentina", "Conti", "+39 333 6666666", { marketing: true, birthMonth: month }],
    ["Giorgia", "De Luca", "+39 333 7777777", { marketing: true }],
    ["Elena", "Mancini", "+39 333 8888888", { marketing: false }],
    ["Sofia", "Costa", "+39 333 9999999", { marketing: true }],
    ["Federica", "Giordano", "+39 334 1010101", { marketing: true }],
    ["Silvia", "Rizzo", "+39 334 2020202", { marketing: true }],
    ["Paola", "Lombardi", "+39 334 3030303", { marketing: false }],
    ["Luca", "Moretti", "+39 334 4040404", { marketing: true }],
    ["Davide", "Barbieri", "+39 334 5050505", { marketing: true }],
  ];
  const clients = [];
  for (const [firstName, lastName, phone, o = {}] of people) {
    clients.push(
      await db.client.create({
        data: {
          organizationId: org.id,
          firstName,
          lastName,
          phone: phone.replace(/\s/g, ""),
          privacyConsentAt: daysAgo(200),
          marketingConsentAt: o.marketing ? daysAgo(200) : null,
          birthDate: o.birthMonth != null ? new Date(1990, o.birthMonth, 14) : null,
          ...(o.billing
            ? { fiscalCode: "RMNFNC85M41H501Z", address: "Via Appia Nuova 100", zip: "00183", city: "Roma", province: "RM", sdiCode: "0000000" }
            : {}),
        },
      }),
    );
  }
  const [laura, francesca, chiara, alessia, martina, valentina, giorgia, , sofia, federica, silvia, , luca, davide] = clients;

  await db.technicalCard.create({
    data: { clientId: laura.id, type: "COLOR", title: "Colore abituale", data: { Marca: "Aurora Color", "Tonalità": "6.3 biondo scuro dorato", Ossidante: "20 vol", "Posa (min)": 35 } },
  });
  await db.technicalCard.create({
    data: { clientId: francesca.id, type: "ANAMNESIS", title: "Anamnesi pressoterapia", data: { "Controindicazioni": "Nessuna", "Pressione": "Nella norma", Firmato: "Sì, su tablet" }, signedAt: daysAgo(30) },
  });
  await db.clientPackage.create({
    data: { organizationId: org.id, clientId: francesca.id, packageTemplateId: pkg.id, sessionsTotal: 10, sessionsUsed: 3 },
  });

  // Storico: visite passate già incassate (per statistiche e segmenti)
  const at = (d: Date, h: number, m = 0) => {
    const x = new Date(d);
    x.setHours(h, m, 0, 0);
    return x;
  };
  const addMin = (d: Date, min: number) => new Date(d.getTime() + min * 60_000);
  type Plan = { client: (typeof clients)[number]; service: typeof piega; staffId: string; start: Date; status?: "CONFIRMED" | "BOOKED" | "PAID"; channel?: "ONLINE" | "STAFF"; resourceId?: string };
  const plans: Plan[] = [
    { client: giorgia, service: taglio, staffId: giulia.id, start: at(daysAgo(75), 10), status: "PAID" },
    { client: federica, service: manicure, staffId: sara.id, start: at(daysAgo(90), 15), status: "PAID" },
    { client: davide, service: taglioUomo, staffId: marco.id, start: at(daysAgo(68), 17), status: "PAID" },
    { client: laura, service: colore, staffId: giulia.id, start: at(daysAgo(35), 9), status: "PAID" },
    { client: sofia, service: piega, staffId: marco.id, start: at(daysAgo(12), 11), status: "PAID", channel: "ONLINE" },
    { client: silvia, service: manicure, staffId: sara.id, start: at(daysAgo(6), 16), status: "PAID", channel: "ONLINE" },
    { client: luca, service: taglioUomo, staffId: marco.id, start: at(daysAgo(3), 18), status: "PAID", channel: "ONLINE" },
    // Oggi
    { client: laura, service: colore, staffId: giulia.id, start: at(now, 9, 0), status: "CONFIRMED" },
    { client: alessia, service: piega, staffId: giulia.id, start: at(now, 9, 30), status: "CONFIRMED", channel: "ONLINE" },
    { client: chiara, service: taglio, staffId: marco.id, start: at(now, 10, 0), status: "CONFIRMED" },
    { client: francesca, service: presso, staffId: sara.id, start: at(now, 11, 0), status: "CONFIRMED", resourceId: cabina.id },
    { client: martina, service: manicure, staffId: sara.id, start: at(now, 15, 0), status: "CONFIRMED", channel: "ONLINE" },
    { client: valentina, service: taglio, staffId: giulia.id, start: at(now, 16, 0), status: "BOOKED" },
  ];
  for (const p of plans) {
    const end = addMin(p.start, p.service.durationMin);
    const a = await db.appointment.create({
      data: {
        organizationId: org.id,
        locationId: location.id,
        clientId: p.client.id,
        startsAt: p.start,
        endsAt: end,
        status: p.status ?? "CONFIRMED",
        channel: p.channel ?? "STAFF",
        createdAt: p.start < now ? addMin(p.start, -3 * 24 * 60) : daysAgo(2),
        items: { create: { serviceId: p.service.id, staffId: p.staffId, resourceId: p.resourceId, startsAt: p.start, endsAt: end, price: p.service.price } },
      },
    });
    const link = `${process.env.APP_URL ?? "http://localhost:3000"}/prenota/${SLUG}/a/${a.publicToken}`;
    const dateStr = p.start.toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long" });
    const timeStr = p.start.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    await db.message.create({
      data: {
        organizationId: org.id,
        clientId: p.client.id,
        appointmentId: a.id,
        kind: "CONFIRMATION",
        to: p.client.phone!,
        status: "READ",
        createdAt: addMin(p.start, -3 * 24 * 60),
        sentAt: addMin(p.start, -3 * 24 * 60),
        body: `Ciao ${p.client.firstName}! ✨ Il tuo appuntamento da ${org.name} è confermato per ${dateStr} alle ${timeStr} (${p.service.name}).\nPer vederlo o disdirlo: ${link}`,
      },
    });
    if (p.start > daysAgo(1)) {
      await db.message.create({
        data: {
          organizationId: org.id,
          clientId: p.client.id,
          appointmentId: a.id,
          kind: "REMINDER",
          to: p.client.phone!,
          status: "READ",
          createdAt: addMin(p.start, -24 * 60),
          sentAt: addMin(p.start, -24 * 60),
          body: `Ciao ${p.client.firstName}, ti ricordiamo l'appuntamento di domani alle ${timeStr} da ${org.name} (${p.service.name}). Ti aspettiamo! 💙\nNon puoi venire? Disdici qui: ${link}`,
        },
      });
      await db.message.create({
        data: {
          organizationId: org.id,
          clientId: p.client.id,
          appointmentId: a.id,
          kind: "REMINDER",
          to: p.client.phone!,
          inbound: true,
          status: "READ",
          createdAt: addMin(p.start, -23 * 60),
          body: "Perfetto, a domani! 😊",
        },
      });
    }
    if (p.status === "PAID") {
      await db.sale.create({
        data: {
          organizationId: org.id,
          locationId: location.id,
          clientId: p.client.id,
          appointmentId: a.id,
          status: "PAID",
          total: p.service.price,
          fiscalDocType: "RECEIPT",
          fiscalDocRef: `0000-${a.id.slice(-4)}`,
          fiscalDocAt: end,
          createdAt: end,
          closedAt: end,
          lines: { create: { kind: "SERVICE", description: p.service.name, staffId: p.staffId, unitPrice: p.service.price, vatRate: 22 } },
          payments: { create: { method: "CARD", amount: p.service.price } },
        },
      });
    }
  }

  // Una campagna già inviata
  const camp = await db.campaign.create({
    data: {
      organizationId: org.id,
      name: "Promo autunno colore",
      segment: "ALL",
      status: "SENT",
      sentAt: daysAgo(9),
      createdAt: daysAgo(9),
      body: "Ciao {nome}! 🍂 Ad ottobre colore + piega a 55 € invece di 65 €. Prenota qui: {link}",
    },
  });
  for (const c of clients.filter((c) => c.marketingConsentAt)) {
    await db.message.create({
      data: {
        organizationId: org.id,
        clientId: c.id,
        campaignId: camp.id,
        kind: "CAMPAIGN",
        to: c.phone!,
        status: Math.random() > 0.2 ? "READ" : "DELIVERED",
        createdAt: daysAgo(9),
        sentAt: daysAgo(9),
        body: `Ciao ${c.firstName}! 🍂 Ad ottobre colore + piega a 55 € invece di 65 €. Prenota qui: ${process.env.APP_URL ?? "http://localhost:3000"}/prenota/${SLUG}`,
      },
    });
  }

  console.log(`Seed completato: /prenota/${SLUG} · login ${DEMO_EMAIL} / demo1234`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => db.$disconnect());
