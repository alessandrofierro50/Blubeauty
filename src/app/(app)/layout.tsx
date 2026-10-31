import { Suspense } from "react";
import { Logo } from "@/components/logo";
import { Nav, NavLinks } from "@/components/nav";
import { getCurrentUser } from "@/lib/auth";
import { logout } from "@/app/login/actions";

// Area riservata: la shell (sidebar) è statica, i contenuti che leggono
// la sessione o il database arrivano in streaming dentro i <Suspense>.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col justify-between border-r border-slate-200 bg-white p-4 md:flex">
        <div className="space-y-6">
          <Logo className="px-2" />
          <Suspense fallback={<NavLinks />}>
            <Nav />
          </Suspense>
        </div>
        <Suspense fallback={<div className="h-14" />}>
          <UserBox />
        </Suspense>
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-8">
        <Suspense fallback={<p className="text-sm text-slate-400">Caricamento…</p>}>{children}</Suspense>
      </main>
    </div>
  );
}

async function UserBox() {
  const user = await getCurrentUser();
  return (
    <div className="space-y-2 border-t border-slate-200 pt-4 text-sm">
      <div>
        <p className="font-semibold text-slate-800">{user.name}</p>
        <p className="text-xs text-slate-500">{user.organizationName}</p>
      </div>
      <form action={logout}>
        <button className="text-xs font-medium text-brand-600 hover:underline">Esci</button>
      </form>
    </div>
  );
}
