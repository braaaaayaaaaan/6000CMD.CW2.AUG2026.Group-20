"use client";

import { Box, Button, Card, CloseButton, Container, Dialog, Field, Grid, Heading, Input, Portal, Spinner, Stack, Tabs, Text } from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import { PasswordInput } from "@/components/ui/password-input";
import useBrowserSession from "@/hooks/useBrowserSession";
import useApiResource from "@/hooks/useApiResource";
import { api, clearSession, errorMessage } from "@/utils/api";
import { toaster } from "@/styles/ui/toaster";

export default function UserProfile() {
  const router = useRouter();
  const session = useBrowserSession();
  const resource = useApiResource("/users/" + session.id + "/", {
    enabled: session.ready && Boolean(session.accessToken && session.id),
    accessToken: session.accessToken,
  });
  const [draft, setDraft] = useState({ id: null, values: {} });
  const [passwords, setPasswords] = useState({ current: "", next: "", confirm: "" });
  const [saving, setSaving] = useState("");
  const [saveError, setSaveError] = useState("");
  const busy = useRef(false);
  const ready = session.ready && Boolean(session.accessToken && resource.data) && !resource.loading && !resource.error;
  const profile = { ...resource.data, ...(draft.id === session.id ? draft.values : {}) };

  useEffect(() => {
    if (session.ready && !session.accessToken) router.replace("/login");
  }, [session.ready, session.accessToken, router]);

  function edit(field, value) {
    setDraft((previous) => ({
      id: session.id,
      values: { ...(previous.id === session.id ? previous.values : {}), [field]: value },
    }));
  }

  async function submit(event, kind) {
    event.preventDefault();
    if (!ready || busy.current) return;
    busy.current = true;
    setSaving(kind);
    setSaveError("");
    try {
      if (kind === "password" && passwords.next !== passwords.confirm) throw new Error("New passwords do not match.");
      const data = kind === "profile"
        ? { first_name: profile.first_name || "", last_name: profile.last_name || "", email: profile.email || "" }
        : { current_password: passwords.current, password1: passwords.next, password2: passwords.confirm };
      const response = await api.patch("/users/" + session.id + "/", data, {
        headers: { Authorization: "Bearer " + session.accessToken },
      });
      resource.mutate(response.data);
      setDraft({ id: null, values: {} });
      if (kind === "password") {
        setPasswords({ current: "", next: "", confirm: "" });
        clearSession();
        router.replace("/login");
      }
      toaster.create({ description: kind === "profile" ? "Profile saved." : "Password changed.", type: "success" });
    } catch (error) {
      setSaveError(errorMessage(error));
    } finally {
      busy.current = false;
      setSaving("");
    }
  }

  async function logout() {
    if (busy.current) return;
    busy.current = true; setSaving("logout"); setSaveError("");
    try {
      await api.post("/api/logout/");
      clearSession();
      router.replace("/login");
    } catch (error) {
      setSaveError(errorMessage(error, "Unable to log out. Please retry."));
    } finally {
      busy.current = false; setSaving("");
    }
  }

  return (
    <Container maxW="7xl" px={{ base: "4", md: "8" }} pb="8">
      <NavBar />
      <Grid templateColumns={{ base: "minmax(0, 1fr)", md: "minmax(180px, 1fr) minmax(0, 3fr)" }} gap="6">
        <Card.Root p="6" h="fit-content">
          <Heading>Hello, {session.username || "there"}!</Heading>
          <Text overflowWrap="anywhere">{profile.email}</Text>
          <Text color="fg.muted">{session.group}</Text>
          <Dialog.Root role="alertdialog">
            <Dialog.Trigger asChild><Button mt="4" disabled={Boolean(saving)}>Log Out</Button></Dialog.Trigger>
            <Portal>
              <Dialog.Backdrop /><Dialog.Positioner>
                <Dialog.Content w="calc(100% - 2rem)">
                  <Dialog.Header><Dialog.Title>Log out?</Dialog.Title></Dialog.Header>
                  <Dialog.Body>You will return to the login screen.</Dialog.Body>
                  <Dialog.Footer>
                    <Dialog.ActionTrigger asChild><Button variant="outline">Cancel</Button></Dialog.ActionTrigger>
                    <Button onClick={logout} disabled={Boolean(saving)} loading={saving === "logout"}>Log Out</Button>
                  </Dialog.Footer>
                  <Dialog.CloseTrigger asChild><CloseButton /></Dialog.CloseTrigger>
                </Dialog.Content>
              </Dialog.Positioner>
            </Portal>
          </Dialog.Root>
        </Card.Root>
        <Card.Root p={{ base: "4", md: "6" }} minW="0">
          {(!session.ready || resource.loading) && <Box role="status"><Spinner size="sm" mr="2" />Loading profile…</Box>}
          {session.ready && session.accessToken && !session.id && <Text role="alert">Your profile ID is unavailable. Log out and sign in again.</Text>}
          {resource.error && <Stack><Text role="alert" color="red.600">{resource.error}</Text><Button onClick={resource.refresh}>Retry profile</Button></Stack>}
          {saveError && <Text role="alert" color="red.600" mb="4">{saveError}</Text>}
          <Tabs.Root defaultValue="info">
            <Tabs.List flexWrap="wrap"><Tabs.Trigger value="info">Personal Info</Tabs.Trigger><Tabs.Trigger value="security">Password &amp; Security</Tabs.Trigger></Tabs.List>
            <Tabs.Content value="info">
              <Stack as="form" onSubmit={(event) => submit(event, "profile")} gap="4">
                {["first_name", "last_name", "email"].map((field) => (
                  <Field.Root key={field}>
                    <Field.Label>{field === "first_name" ? "First Name" : field === "last_name" ? "Last Name" : "Email"}</Field.Label>
                    <Input type={field === "email" ? "email" : "text"} value={profile[field] || ""}
                      disabled={!ready || Boolean(saving)} onChange={(event) => edit(field, event.target.value)}
                      autoComplete={field === "first_name" ? "given-name" : field === "last_name" ? "family-name" : "email"} />
                  </Field.Root>
                ))}
                <Button type="submit" disabled={!ready || Boolean(saving)} loading={saving === "profile"} loadingText="Saving…">Save Changes</Button>
              </Stack>
            </Tabs.Content>
            <Tabs.Content value="security">
              <Stack as="form" onSubmit={(event) => submit(event, "password")} gap="4">
                {["current", "next", "confirm"].map((field) => (
                  <Field.Root key={field} required>
                    <Field.Label>{field === "current" ? "Current Password" : field === "next" ? "New Password" : "Confirm New Password"}</Field.Label>
                    <PasswordInput required disabled={!ready || Boolean(saving)} value={passwords[field]}
                      autoComplete={field === "current" ? "current-password" : "new-password"}
                      onChange={(event) => setPasswords((previous) => ({ ...previous, [field]: event.target.value }))} />
                  </Field.Root>
                ))}
                <Button type="submit" disabled={!ready || Boolean(saving)} loading={saving === "password"} loadingText="Saving…">Change Password</Button>
              </Stack>
            </Tabs.Content>
          </Tabs.Root>
        </Card.Root>
      </Grid>
    </Container>
  );
}
