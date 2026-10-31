import type { Metadata } from "next";
import { Logo } from "@/components/logo";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Accedi" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-b from-brand-50 to-white px-4">
      <div className="w-full max-w-sm space-y-6 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
        <div className="flex justify-center">
          <Logo />
        </div>
        <LoginForm />
        {process.env.NODE_ENV !== "production" && (
          <p className="text-center text-xs text-slate-400">Demo: demo@blubeauty.it / demo1234</p>
        )}
      </div>
    </main>
  );
}
