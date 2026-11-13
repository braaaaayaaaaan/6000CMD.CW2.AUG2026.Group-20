"use client";

import { Box, Button, Center, Field, Heading, Image, Input, Link, Stack, Text } from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Logo from "@/assets/ManticAI_Logo.png";
import { api, errorMessage } from "@/utils/api";
import { getVerificationEmail, rememberVerificationEmail, setSession } from "@/utils/session";
import { PasswordInput, PasswordStrengthFeedback } from "@/components/ui/password-input";
import MfaChallenge from "./MfaChallenge";

export default function AccountRecoveryForm({ mode }) {
  const router = useRouter();
  const [challenge, setChallenge] = useState(null);
  const [link, setLink] = useState({});
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [verified, setVerified] = useState(false);
  const [ready, setReady] = useState(false);
  const verification = mode === "verify-email";
  const forgotPassword = mode === "forgot-password";
  const themedCard = verification || forgotPassword;
  useEffect(() => {
    function readLink() {
      const params = new URLSearchParams(window.location.hash.slice(1));
      if (mode === "verify-email") {
        if (params.get("token") && params.get("email")) rememberVerificationEmail(params.get("email"));
        setEmail(getVerificationEmail());
      }
      setLink(params.get("token") ? { token: params.get("token"), uid: params.get("uid") || "" } : {});
      setReady(true);
    }
    // Keep the fragment until the action succeeds so refreshes cannot lose it.
    // Fragments are never sent to the web server or in Referer headers.
    readLink();
    // A different email link must start a fresh flow, including any MFA state.
    const restartFromLink = () => window.location.reload();
    window.addEventListener("hashchange", restartFromLink);
    return () => window.removeEventListener("hashchange", restartFromLink);
  }, [mode]);
  const verifying = verification && Boolean(link.token);
  const title = mode === "forgot-password" ? "Forgot Password" : mode === "reset-password" ? "Reset Password" : "Verify Your Email";
  const fields = mode === "reset-password" ? ["password1", "password2"] : verification ? [] : ["email"];
  async function submit(event, resend = false) {
    event.preventDefault();
    if (saving || verified) return;
    setSaving(true); setError(""); setMessage("");
    try {
      if (mode === "reset-password" && (!link.uid || !link.token)) throw new Error("Open the reset link from your email first.");
      const resending = verification && (resend || !verifying);
      if (resending && !email) throw new Error("Sign in first so we can resend the link to your account email.");
      const path = resending ? "resend-verification" : mode;
      const { data } = await api.post("/api/account/" + path + "/", resending ? { email } : { ...values, ...link });
      if (verification || mode === "reset-password") {
        window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
      }
      if (verification) {
        if (resending) setLink({}); // A resend replaces the previous verification token.
        else { setVerified(true); rememberVerificationEmail(); setChallenge(data); }
      }
      setValues({}); setMessage(data.detail);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setSaving(false); }
  }
  return <Center minH="100dvh" px="4" py="4">
    <Box maxW="full" w={challenge?.enrolment_required ? "2xl" : "lg"} p={challenge ? { base: 5, md: 6 } : themedCard ? 10 : 8} borderWidth="1px" borderRadius="lg" boxShadow={themedCard ? "lg" : undefined} textAlign={themedCard ? "center" : undefined}>
    {themedCard && <Image src={Logo.src ?? Logo} alt="ManticAI" w={challenge ? "clamp(160px, 28dvh, 240px)" : undefined} mx="auto" mb={challenge ? "3" : "6"} />}
    <Heading mb={challenge ? "3" : "6"} size={themedCard ? "2xl" : undefined} color={themedCard ? "blue.700" : undefined} fontWeight="bold">{challenge ? "Email Verified" : title}</Heading>
    {challenge ? <MfaChallenge challenge={challenge.challenge} enrolmentRequired={challenge.enrolment_required} passwordRequired={challenge.password_required}
      onComplete={(data) => { setSession(data.user, true); router.replace("/editor/home"); }} onCancel={() => router.replace("/login")} /> : <form method="post" onSubmit={submit}><Stack gap="4">
      {!ready && <Text role="status">Loading Secure Form...</Text>}
      {ready && verification && !verified && <Text color="fg.muted" fontSize="xs" lineHeight="tall" textWrap="balance">
        {verifying ? "Confirm your email address to finish setting up your account." : email ? "Check your inbox and open the verification link to activate your account." : "Open the verification link in your inbox, or sign in to request a new link."}
        {email && <Text as="span" display="block" fontSize="sm" fontWeight="medium" bg="blue.50" color="blue.700" borderWidth="1px" borderColor="blue.200" borderRadius="md" px="4" py="3" mt="3" overflowWrap="anywhere">{email}</Text>}
      </Text>}
      {fields.map((field) => {
        const Component = field === "email" ? Input : PasswordInput;
        return <Field.Root key={field}><Field.Label>{field === "email" ? "Email" : field === "password1" ? "New Password" : "Confirm New Password"}</Field.Label>
          <Component required type={field === "email" ? "email" : "password"} autoComplete={field === "email" ? "email" : "new-password"}
            aria-describedby={mode === "reset-password" ? "reset-password-requirements" : undefined}
            borderColor={forgotPassword ? "border.emphasized" : undefined} textAlign={forgotPassword ? "left" : undefined}
            minLength={field === "email" ? undefined : 12} maxLength={field === "email" ? 254 : 256}
            value={values[field] || ""} disabled={!ready || saving} onChange={(event) => setValues((previous) => ({ ...previous, [field]: event.target.value }))} />
        </Field.Root>;
      })}
      {mode === "reset-password" && <PasswordStrengthFeedback id="reset-password-requirements" password={values.password1} confirmation={values.password2} />}
      {error && <Text role="alert" color="fg.error">{error}</Text>}
      {message && <Text role="status">{message}</Text>}
      {!verified && (!verification || verifying || email) && <Button type="submit" loading={saving} loadingText={forgotPassword ? "Sending..." : undefined} disabled={!ready || saving}>
        {verifying ? "Verify Email" : verification ? "Resend Verification Email" : forgotPassword ? "Send Reset Link" : "Continue"}
      </Button>}
      {verifying && email && !verified && <Button type="button" variant="outline" color="blue.700" disabled={saving} onClick={(event) => submit(event, true)}>Resend Verification Email</Button>}
      <Link href="/login" variant="underline" fontSize={forgotPassword ? "sm" : undefined} alignSelf={themedCard ? "center" : undefined}>{verified ? "Login" : forgotPassword ? "Back To Login" : "Go Back"}</Link>
    </Stack></form>}
    <noscript>JavaScript must be enabled to use this secure form.</noscript>
  </Box></Center>;
}
