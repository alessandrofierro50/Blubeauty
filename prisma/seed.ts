// Dati demo per sviluppo: `npx prisma db seed`
import "dotenv/config";
import bcrypt from "bcryptjs";
import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "../src/generated/prisma/client";

const db = new PrismaClient({ adapter: new PrismaPg({ connectionString: process.env.DATABASE_URL! }) });

async function main() {
  const existing = await db.organization.findUnique({ where: { slug: "salone-demo" } });
  if (existing) {
    console.log("Seed già presente, nulla da fare.");
    return;
  }

  const org = await db.organization.create({
    data: { name: "Salone Demo", slug: "salone-demo", businessType: "MIXED", phone: "+39 000 0000000" },
  });

  const location = await db.location.create({
    data: {
      organizationId: org.id,
      name: "Sede principale",
      city: "Roma",
      openingHours: {
        tue: [["09:00", "19:00"]], wed: [["09:00", "19:00"]], thu: [["09:00", "20:00"]],
        fri: [["09:00", "20:00"]], sat: [["08:30", "18:00"]],
      },
    },
  });

  const owner = await db.user.create({
    data: {
      email: "demo@blubeauty.it",
      name: "Titolare Demo",
      passwordHash: await bcrypt.hash("demo1234", 10),
      memberships: { create: { organizationId: org.id, role: "OWNER" } },
    },
  });

  const [giulia, marco, sara] = await Promise.all([
    db.staffMember.create({ data: { organizationId: org.id, locationId: location.id, firstName: "Giulia", lastName: "Rossi", color: "#2563eb", userId: owner.id, serviceCommissionPct: 10 } }),
    db.staffMember.create({ data: { organizationId: org.id, locationId: location.id, firstName: "Marco", lastName: "Bianchi", color: "#0891b2", serviceCommissionPct: 10 } }),
    db.staffMember.create({ data: { organizationId: org.id, locationId: location.id, firstName: "Sara", lastName: "Verdi", color: "#db2777", serviceCommissionPct: 12 } }),
  ]);

  const cabina = await db.resource.create({ data: { organizationId: org.id, locationId: location.id, name: "Cabina 1", type: "CABIN" } });

  const capelli = await db.serviceCategory.create({ data: { organizationId: org.id, name: "Capelli", sortOrder: 1 } });
  const estetica = await db.serviceCategory.create({ data: { organizationId: org.id, name: "Estetica", sortOrder: 2 } });

  const piega = await db.service.create({ data: { organizationId: org.id, categoryId: capelli.id, name: "Piega", price: 22, durationMin: 30 } });
  const taglio = await db.service.create({ data: { organizationId: org.id, categoryId: capelli.id, name: "Taglio donna", price: 35, durationMin: 45 } });
  const colore = await db.service.create({
    data: { organizationId: org.id, categoryId: capelli.id, name: "Colore + piega", price: 65, durationMin: 80, processingStartMin: 20, processingMin: 35 },
  });
  const manicure = await db.service.create({ data: { organizationId: org.id, categoryId: estetica.id, name: "Manicure semipermanente", price: 30, durationMin: 50 } });
  const presso = await db.service.create({
    data: { organizationId: org.id, categoryId: estetica.id, name: "Pressoterapia", price: 40, durationMin: 45, requiredResources: { connect: { id: cabina.id } } },
  });

  await db.staffService.createMany({
    data: [
      { staffId: giulia.id, serviceId: piega.id }, { staffId: giulia.id, serviceId: taglio.id }, { staffId: giulia.id, serviceId: colore.id },
      { staffId: marco.id, serviceId: piega.id }, { staffId: marco.id, serviceId: taglio.id },
      { staffId: sara.id, serviceId: manicure.id }, { staffId: sara.id, serviceId: presso.id },
    ],
  });

  const pkg = await db.packageTemplate.create({
    data: { organizationId: org.id, serviceId: presso.id, name: "10 sedute pressoterapia", sessions: 10, price: 350, validityDays: 180 },
  });

  const clients = await Promise.all(
    [
      ["Laura", "Esposito", "+39 333 1111111"],
      ["Francesca", "Romano", "+39 333 2222222"],
      ["Chiara", "Colombo", "+39 333 3333333"],
      ["Alessia", "Ricci", "+39 333 4444444"],
    ].map(([firstName, lastName, phone]) =>
      db.client.create({ data: { organizationId: org.id, firstName, lastName, phone, privacyConsentAt: new Date() } }),
    ),
  );

  await db.technicalCard.create({
    data: {
      clientId: clients[0].id,
      type: "COLOR",
      title: "Colore abituale",
      data: { Marca: "—", "Tonalità": "6.3", Ossidante: "20 vol", "Posa (min)": 35 },
    },
  });

  await db.clientPackage.create({
    data: { organizationId: org.id, clientId: clients[1].id, packageTemplateId: pkg.id, sessionsTotal: 10, sessionsUsed: 3 },
  });

  // Appuntamenti di oggi
  const at = (h: number, m = 0) => {
    const d = new Date();
    d.setHours(h, m, 0, 0);
    return d;
  };
  const addMin = (d: Date, min: number) => new Date(d.getTime() + min * 60_000);

  const plan = [
    { client: clients[0], service: colore, staff: giulia, start: at(9, 0) },
    { client: clients[2], service: taglio, staff: marco, start: at(9, 30) },
    { client: clients[3], service: piega, staff: giulia, start: at(9, 30) }, // durante la posa del colore
    { client: clients[1], service: presso, staff: sara, start: at(11, 0), resource: cabina },
    { client: clients[2], service: manicure, staff: sara, start: at(15, 0) },
  ];
  for (const p of plan) {
    const end = addMin(p.start, p.service.durationMin);
    await db.appointment.create({
      data: {
        organizationId: org.id,
        locationId: location.id,
        clientId: p.client.id,
        startsAt: p.start,
        endsAt: end,
        status: "CONFIRMED",
        items: {
          create: {
            serviceId: p.service.id,
            staffId: p.staff.id,
            resourceId: p.resource?.id,
            startsAt: p.start,
            endsAt: end,
            price: p.service.price,
          },
        },
      },
    });
  }

  console.log("Seed completato. Login: demo@blubeauty.it / demo1234");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => db.$disconnect());
