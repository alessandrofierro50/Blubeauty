import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Controllo "ottimistico": se manca il cookie di sessione rimanda al login.
// La verifica vera avviene nel Data Access Layer (src/lib/auth.ts).
export function proxy(request: NextRequest) {
  if (!request.cookies.has("bb_session")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/agenda/:path*", "/clienti/:path*", "/servizi/:path*", "/cassa/:path*", "/marketing/:path*"],
};
