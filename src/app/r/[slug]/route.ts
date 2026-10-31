import { db } from "@/lib/db";

// Link breve per la richiesta di recensione: in produzione punta alla scheda Google del salone.
export async function GET(req: Request, ctx: RouteContext<"/r/[slug]">) {
  const { slug } = await ctx.params;
  const org = await db.organization.findUnique({ where: { slug } });
  const target = org ? `https://www.google.com/search?q=${encodeURIComponent(org.name + " recensioni")}` : "/";
  return Response.redirect(new URL(target, req.url), 302);
}
