"use client";

import { Box, Button, Center, Field, Heading, Image, Input, Link, Stack, Text } from "@chakra-ui/react";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Logo from "@/assets/ManticAI_Logo.png";
import { PasswordInput } from "@/components/ui/password-input";
import { api, errorMessage } from "@/utils/api";
import { notifySessionChange } from "@/hooks/useBrowserSession";
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
  const busy = useRef(false);
  const fields = signup
    ? ["username", "first_name", "last_name", "email", "password1", "password2"]
    : ["username", "password"];

  async function submit(event) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true; setSaving(true); setError("");
    try {
      if (signup && values.password1 !== values.password2) throw new Error("Passwords do not match.");
      const { data } = await api.post(signup ? "/users/" : "/api/token/", values);
      if (signup) {
        toaster.create({ description: "Account created. You can now log in.", type: "success" });
        router.push("/login");
      } else {
        for (const [key, value] of Object.entries({
          accessToken: data.access, refreshToken: data.refresh,
          username: data.username, id: data.id, group: data.group || "",
        })) localStorage.setItem(key, value);
        notifySessionChange();
        router.push("/editor/home");
      }
    } catch (error) {
      setError(errorMessage(error, signup ? "Unable to create your account." : "Unable to log in. Please try again."));
    } finally {
      busy.current = false; setSaving(false);
    }
  }

  return (
    <Center minH="100svh" px="4" py="6">
      <Box as="form" onSubmit={submit} w="full" maxW="lg" p={{ base: "5", md: "8" }} borderWidth="1px" rounded="lg" boxShadow="lg">
        <Stack gap="5">
          <Image src={Logo.src ?? Logo} alt="ManticAI" maxW="260px" w="full" mx="auto" />
          <Heading textAlign="center" size={{ base: "xl", md: "2xl" }}>{signup ? "Sign Up" : "Digital Asset Management"}</Heading>
          {fields.map((field) => {
            const [label, type, autoComplete] = definitions[field];
            const Component = type === "password" ? PasswordInput : Input;
            return (
              <Field.Root key={field} required>
                <Field.Label>{label}</Field.Label>
                <Component name={field} type={type} autoComplete={autoComplete} required disabled={saving}
                  minLength={signup && type === "password" ? 12 : undefined}
                  value={values[field] || ""} onChange={(event) => setValues((previous) => ({ ...previous, [field]: event.target.value }))} />
              </Field.Root>
            );
          })}
          {error && <Text role="alert" color="red.600">{error}</Text>}
          <Button type="submit" loading={saving} disabled={saving} loadingText={signup ? "Creating account…" : "Logging in…"}>
            {signup ? "Sign Up" : "Login"}
          </Button>
          <Link href={signup ? "/login" : "/signup"} alignSelf="center">
            {signup ? "Already have an account? Log in" : "Create an account"}
          </Link>
        </Stack>
      </Box>
    </Center>
  );
}
