"use client";

import { Box, Button, Field, Grid, Heading, Image, Input, Stack, Text } from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { api, errorMessage } from "@/utils/api";
import { PasswordInput } from "@/components/ui/password-input";

export default function MfaChallenge({ challenge, enrolmentRequired, passwordRequired = false, initialSetup, onComplete, onCancel, cancelLabel = "Back To Login" }) {
  const [setup, setSetup] = useState(initialSetup || null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState("");
  const [enrolmentChallenge, setEnrolmentChallenge] = useState(challenge);
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const needsPasswordForSetup = passwordRequired && enrolmentRequired && !setup;
  const validChallenge = typeof challenge === "string" && challenge.length > 0 && typeof enrolmentRequired === "boolean";
  useEffect(() => {
    if (!validChallenge || !enrolmentRequired || initialSetup || passwordRequired) return;
    const controller = new AbortController();
    api.post("/api/account/mfa/enrol/", { challenge }, { signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) setSetup(data); })
      .catch((failure) => { if (!controller.signal.aborted) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [challenge, enrolmentRequired, initialSetup, validChallenge, passwordRequired]);

  async function submit(event) {
    event.preventDefault();
    if (saving) return;
    setSaving(true); setError("");
    try {
      if (needsPasswordForSetup) {
        const { data } = await api.post("/api/account/mfa/enrol/", { challenge, password });
        setSetup(data); setEnrolmentChallenge(data.challenge); setPassword("");
        return;
      }
      const { data } = await api.post("/api/account/mfa/" + (enrolmentRequired ? "confirm/" : "verify/"), { challenge: enrolmentChallenge, code, ...(passwordRequired && !enrolmentRequired ? { password } : {}) });
      setCode(""); setPassword("");
      onComplete(data);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setSaving(false); }
  }

  if (!validChallenge) return <Stack gap="4">
    <Text role="alert">Unable to load authenticator setup. Return to login to continue.</Text>
    {onCancel && <Button type="button" variant="outline" borderColor="blue.700" color="blue.700" onClick={onCancel}>{cancelLabel}</Button>}
  </Stack>;

  return <form method="post" onSubmit={submit}><Stack gap="3" textAlign="left">
    <Heading size="lg" color="blue.700" textAlign="center">{enrolmentRequired ? "Authenticator Setup" : "Authenticator Verification"}</Heading>
    <Text color="fg.muted" fontSize="sm" textAlign="center">{needsPasswordForSetup ? "Confirm your account password to securely prepare your QR code." : enrolmentRequired ? "Scan the QR code with your authenticator app, then enter its six-digit code." : "Enter the current code from your authenticator app, or use a previously issued recovery code."}</Text>
    {enrolmentRequired && !setup && !error && !needsPasswordForSetup && <Text role="status" textAlign="center">Preparing Your QR Code...</Text>}
    <Grid templateColumns={setup ? { base: "minmax(0, 1fr)", md: "minmax(0, 1fr) minmax(0, 1fr)" } : "minmax(0, 1fr)"} gap={{ base: "4", md: "6" }} alignItems="center">
    {setup && <Stack gap="2" minW="0">
      <Box p="2" bg="white" borderWidth="1px" borderColor="gray.300" borderRadius="lg" alignSelf="center" maxW="full">
        <Image src={setup.qr_code} alt="Scan this QR code with your authenticator app" w="180px" maxW="full" aspectRatio="1" />
      </Box>
      <Text fontSize="xs" color="fg.muted" textAlign="center">New codes appear every 30 seconds.</Text>
      <Box as="details" fontSize="sm"><Box as="summary" cursor="pointer" color="blue.700">Cannot Scan The QR Code?</Box>
        <Text mt="2">Add an account manually in your app using this setup key:</Text>
        <Text mt="1" fontFamily="mono" overflowWrap="anywhere">{setup.secret}</Text>
      </Box>
    </Stack>}
    <Stack gap="3" minW="0">
    {passwordRequired && (!enrolmentRequired || needsPasswordForSetup) && <Field.Root gap="1"><Field.Label>Account Password</Field.Label>
      <PasswordInput required autoComplete="current-password" borderColor="gray.300" maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} disabled={saving} />
      <Field.HelperText>Confirm your password to finish signing in securely.</Field.HelperText>
    </Field.Root>}
    {!needsPasswordForSetup && <Field.Root gap="1"><Field.Label>{useRecoveryCode ? "Previously Issued Recovery Code" : "Authenticator Code"}</Field.Label>
      <Input autoComplete="one-time-code" inputMode={useRecoveryCode ? "text" : "numeric"} pattern={useRecoveryCode ? undefined : "[0-9]{6}"} minLength={useRecoveryCode ? 1 : 6} maxLength={useRecoveryCode ? 64 : 6} borderColor="gray.300" placeholder={useRecoveryCode ? "Recovery Code" : "6-Digit Code"} value={code} onChange={(event) => setCode(useRecoveryCode ? event.target.value : event.target.value.replace(/\D/g, "").slice(0, 6))} required disabled={saving || (enrolmentRequired && !setup)} />
    </Field.Root>}
    {!enrolmentRequired && <Button type="button" variant="plain" color="blue.700" onClick={() => { setUseRecoveryCode(!useRecoveryCode); setCode(""); }} disabled={saving}>{useRecoveryCode ? "Use Authenticator App" : "Use A Previously Issued Recovery Code"}</Button>}
    {error && <Text role="alert" color="red.600">{error}</Text>}
    <Button type="submit" variant="outline" bg="blue.700" color="white" loading={saving} loadingText="Verifying..." disabled={saving || (enrolmentRequired && !setup && !needsPasswordForSetup)}>{needsPasswordForSetup ? "Continue To QR Setup" : enrolmentRequired ? "Verify And Continue" : "Verify And Sign In"}</Button>
    {onCancel && <Button type="button" variant="outline" borderColor="blue.700" color="blue.700" onClick={onCancel} disabled={saving}>{cancelLabel}</Button>}
    </Stack>
    </Grid>
  </Stack></form>;
}
