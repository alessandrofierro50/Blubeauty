import "server-only";
import { cookies } from "next/headers";
import { sealData, unsealData } from "iron-session";

export type SessionData = {
  userId?: string;
  organizationId?: string;
};

const COOKIE_NAME = "bb_session";
const MAX_AGE = 60 * 60 * 12; // 12 ore: una giornata lavorativa in salone

function password() {
  const pwd = process.env.SESSION_PASSWORD;
  if (!pwd || pwd.length < 32) {
    throw new Error("SESSION_PASSWORD mancante o più corta di 32 caratteri");
  }
  return pwd;
}

export async function getSession(): Promise<SessionData> {
  const cookie = (await cookies()).get(COOKIE_NAME)?.value;
  if (!cookie) return {};
  try {
    return await unsealData<SessionData>(cookie, { password: password(), ttl: MAX_AGE });
  } catch {
    return {};
  }
}

export async function saveSession(data: SessionData) {
  const sealed = await sealData(data, { password: password(), ttl: MAX_AGE });
  (await cookies()).set(COOKIE_NAME, sealed, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE,
  });
}

export async function destroySession() {
  (await cookies()).delete(COOKIE_NAME);
}
