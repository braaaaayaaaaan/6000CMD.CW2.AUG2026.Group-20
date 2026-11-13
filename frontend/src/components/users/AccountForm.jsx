"use client";

import { Box, Button, Center, Field, Fieldset, Grid, Heading, Image, Input, Link } from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Logo from "@/assets/ManticAI_Logo.png";
import { PasswordInput, PasswordStrengthFeedback } from "@/components/ui/password-input";
import { API_BASE_URL, api, errorMessage } from "@/utils/api";
import { rememberVerificationEmail, setSession } from "@/utils/session";
import MfaChallenge from "./MfaChallenge";
import { toaster } from "@/styles/ui/toaster";

const definitions = {
  username: ["Username", "text", "username"],
  first_name: ["First Name", "text", "given-name"],
  last_name: ["Last Name", "text", "family-name"],
  email: ["Email", "email", "email"],
  password: ["Password", "password", "current-password"],
  password1: ["Password", "password", "new-password"],
  password2: ["Confirm Password", "password", "new-password"],
};

export default function AccountForm({ signup = false }) {
  const router = useRouter();
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [challenge, setChallenge] = useState(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    // Never allow the browser's native GET fallback to submit credentials.
    const url = new URL(window.location.href);
    let cleaned = false;
    for (const field of Object.keys(definitions)) {
      if (url.searchParams.has(field)) { url.searchParams.delete(field); cleaned = true; }
    }
    if (cleaned) window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    setReady(true);
  }, []);
  const busy = useRef(false);
  const fields = signup
    ? ["username", "email", "first_name", "last_name", "password1", "password2"]
    : ["username", "password"];

  function complete(data) {
    setSession(data.user, true);
    if (new URLSearchParams(window.location.search).get("admin") === "1") window.location.assign(API_BASE_URL + "/admin/");
    else router.push("/editor/home");
  }

  async function submit(event) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true; setSaving(true); setError("");
    try {
      if (signup && values.password1 !== values.password2) throw new Error("Passwords do not match.");
      const admin = new URLSearchParams(window.location.search).get("admin") === "1";
      const { data } = await api.post(signup ? "/users/" : "/api/token/", { ...values, admin_session: admin });
      if (signup) {
        rememberVerificationEmail(data.email || values.email.trim());
        toaster.create({ description: "Account has been successfully created! Check your email to verify your address before signing in.", type: "success" });
        router.push("/verify-email");
      } else {
        setValues({});
        if (data.mfa_required) setChallenge(data);
        else complete(data);
      }
    } catch (error) {
      if (!signup && error.response?.data?.verification_required) {
        rememberVerificationEmail(error.response.data.email);
        router.push("/verify-email");
        return;
      }
      setError(errorMessage(error, signup ? "Unable to create your account." : "Unable to log in. Please try again."));
    } finally {
      busy.current = false; setSaving(false);
    }
  }

  return (
    <Center minH="100dvh" px="4" py="4">
      <Box w={challenge?.enrolment_required ? "2xl" : "lg"} maxW="full" p={signup ? { base: 6, md: 8 } : challenge ? { base: 5, md: 6 } : 10} borderWidth="1px" borderRadius="lg" boxShadow={signup ? "sm" : "lg"} textAlign="center">
        <Heading size={challenge ? "lg" : "2xl"} color="blue.700" fontWeight="bold" marginBottom={signup || challenge ? "12px" : "50px"}>
          <Image src={Logo.src ?? Logo} alt="logo" w={signup ? "160px" : challenge ? "clamp(160px, 28dvh, 240px)" : undefined} maxW="full" mx="auto" mb={signup ? "3" : undefined} />
          {signup ? "Create your account" : "Digital Asset Management System"}
        </Heading>
        {challenge ? <MfaChallenge challenge={challenge.challenge} enrolmentRequired={challenge.enrolment_required}
          onComplete={complete} onCancel={() => setChallenge(null)} /> : <form method="post" onSubmit={submit}><Fieldset.Root size="lg" invalid={Boolean(error)} disabled={!ready || saving}>
          <Fieldset.Content gap={signup ? "3" : undefined}>
          <Grid templateColumns={signup ? "repeat(2, minmax(0, 1fr))" : "minmax(0, 1fr)"} gap={signup ? "3" : "4"}>
          {fields.map((field) => {
            const [label, type, autoComplete] = definitions[field];
            const Component = type === "password" ? PasswordInput : Input;
            return (
              <Field.Root key={field} gridColumn={signup && field !== "first_name" && field !== "last_name" ? "1 / -1" : undefined} gap={signup ? "1" : undefined} mt={!signup && field === "password" ? 4 : undefined}>
                <Field.Label>{label}</Field.Label>
                <Component name={field} type={type} borderColor="border.emphasized" autoComplete={autoComplete} required disabled={!ready || saving}
                  aria-describedby={signup && type === "password" ? "signup-password-requirements" : undefined}
                  minLength={signup && type === "password" ? 12 : undefined}
                  maxLength={signup && type === "password" ? 256 : undefined}
                  value={values[field] || ""} onChange={(event) => setValues((previous) => ({ ...previous, [field]: event.target.value }))} />
                {!signup && field === "password" && (
                  <Link href="/forgot-password" alignSelf="flex-end" fontSize="sm" mt="1">Forgot Password?</Link>
                )}
              </Field.Root>
            );
          })}
          </Grid>
          {signup && <PasswordStrengthFeedback id="signup-password-requirements" password={values.password1} confirmation={values.password2} compact />}
          <Button type="submit" marginTop={signup ? "0" : "30px"} variant="solid" loading={saving} disabled={!ready || saving} loadingText={signup ? "Creating account…" : "Logging in…"}>
            {signup ? "Sign Up" : "Login"}
          </Button>
          {error && <Fieldset.ErrorText role="alert" color="red.600" mt={signup ? 3 : undefined}>{error}</Fieldset.ErrorText>}
          <Box fontSize="sm">
            <Link variant="underline" href={signup ? "/login" : "/signup"}>
              {signup ? "Already have an account? Log in!" : "Don’t have an account? Sign up!"}
            </Link>
          </Box>
          </Fieldset.Content>
        </Fieldset.Root></form>}
        <noscript>JavaScript must be enabled to sign in securely.</noscript>
      </Box>
    </Center>
  );
}
