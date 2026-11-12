"use client";

import { Button, Field, Input, Stack, Text } from "@chakra-ui/react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearSession, errorMessage } from "@/utils/api";
import { setSession } from "@/utils/session";
import useBrowserSession from "@/hooks/useBrowserSession";
import { PasswordInput } from "@/components/ui/password-input";
import MfaChallenge from "./MfaChallenge";

export default function AccountSecurity() {
  const session = useBrowserSession();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function action(kind) {
    if (saving) return;
    setSaving(true); setError("");
    try {
      if (kind === "logout-all") {
        await api.post("/api/logout-all/"); clearSession(); router.replace("/login");
      } else {
        const { data } = await api.post("/api/account/mfa/" + kind + "/", { password, code });
        setPassword(""); setCode("");
        if (kind === "remove") { clearSession(); router.replace("/login"); }
        else setSetup(data);
      }
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setSaving(false); }
  }
  if (setup) return <MfaChallenge challenge={setup.challenge} enrolmentRequired initialSetup={setup}
    onComplete={(data) => { setSession(data.user, true); setSetup(null); }} onCancel={() => setSetup(null)} cancelLabel="Cancel" />;
  return <Stack gap="4" mt="8" borderTopWidth="1px" pt="6">
    <Text fontWeight="bold">Authenticator Security</Text>
    <Text>Authenticator security is required for every account. Use the current six-digit code from your app to sign in.</Text>
    <Field.Root><Field.Label>Current Password</Field.Label><PasswordInput autoComplete="current-password" maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} disabled={saving} /></Field.Root>
    {session.mfa_enabled && <Field.Root><Field.Label>Authenticator Code</Field.Label><Input borderColor="gray.300" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} disabled={saving} /></Field.Root>}
    {error && <Text role="alert" color="red.600">{error}</Text>}
    {!session.mfa_enabled && <Button variant="outline" bg="blue.700" color="white" onClick={() => action("setup")} disabled={saving || !password}>Set up authenticator</Button>}
    {session.mfa_enabled && <><Text fontSize="sm">To replace an authenticator, provide a current code or do so within five minutes of signing in with MFA.</Text>
      <Button variant="outline" bg="blue.700" color="white" onClick={() => action("replace")} disabled={saving || !password}>Replace Authenticator</Button></>}
    <Button variant="outline" color="blue.700" borderColor="blue.700" onClick={() => action("logout-all")} loading={saving}>Log Out All Devices</Button>
  </Stack>;
}
