"use client";

import { Box, Button, Card, CloseButton, Container, Dialog, Field, Grid, GridItem, Heading, Input, Portal, Spinner, Stack, Tabs, Text } from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { CgUserlane } from "react-icons/cg";
import { useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import { PasswordInput, PasswordStrengthFeedback } from "@/components/ui/password-input";
import useBrowserSession from "@/hooks/useBrowserSession";
import useApiResource from "@/hooks/useApiResource";
import { api, clearSession, errorMessage } from "@/utils/api";
import { toaster } from "@/styles/ui/toaster";
import AccountSecurity from "@/components/users/AccountSecurity";

export default function UserProfile() {
  const router = useRouter();
  const session = useBrowserSession();
  const resource = useApiResource("/users/" + session.id + "/", {
    enabled: session.ready && Boolean(session.authenticated && session.id),
  });
  const [draft, setDraft] = useState({ id: null, values: {} });
  const [passwords, setPasswords] = useState({ current: "", next: "", confirm: "" });
  const [profilePassword, setProfilePassword] = useState("");
  const [saving, setSaving] = useState("");
  const [saveError, setSaveError] = useState("");
  const busy = useRef(false);
  const ready = session.ready && Boolean(session.authenticated && resource.data) && !resource.loading && !resource.error;
  const profile = { ...resource.data, ...(draft.id === session.id ? draft.values : {}) };

  useEffect(() => {
    if (session.ready && !session.authenticated) router.replace("/login");
  }, [session.ready, session.authenticated, router]);

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
        ? { first_name: profile.first_name || "", last_name: profile.last_name || "", email: profile.email || "", current_password: profilePassword }
        : { current_password: passwords.current, password1: passwords.next, password2: passwords.confirm };
      const response = await api.patch("/users/" + session.id + "/", data);
      resource.mutate(response.data);
      setDraft({ id: null, values: {} });
      setProfilePassword("");
      if (kind === "password" || !response.data.email_verified) {
        setPasswords({ current: "", next: "", confirm: "" });
        clearSession();
        router.replace(kind === "password" ? "/login" : "/verify-email");
      }
      toaster.create({ description: kind === "profile" ? "Profile changes have been successfully saved! Please sign in again." : "Password has been successfully changed! Please sign in again.", type: "success" });
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
    <Container>
      <NavBar />
      <Tabs.Root defaultValue="info" orientation="vertical" variant="subtle">
        <Grid w="full" templateColumns={{ base: "minmax(0, 1fr)", lg: "repeat(4, minmax(0, 1fr))" }} gap="30px" p={{ base: "15px", md: "30px" }}>
          <GridItem colSpan={1}>
            <Card.Root w="100%" p="30px" alignItems="center" gap="2px" flexDirection="column">
              <Box borderRadius="70px" bg="blue.700" w="120px" p="30px" marginBottom="8px">
                <CgUserlane size="60px" color="white" />
              </Box>
              <Heading>Hello, {session.username || "there"}!</Heading>
              <Text fontSize="md" color="fg.muted" overflowWrap="anywhere" maxW="full">{profile.email}</Text>
              <Text fontSize="sm" color="fg.muted">{session.group}</Text>
              <Dialog.Root role="alertdialog">
                <Dialog.Trigger asChild>
                  <Button variant="solid" mt="10px" width="180px" maxW="full" disabled={Boolean(saving)}>Log Out</Button>
                </Dialog.Trigger>
                <Portal>
                  <Dialog.Backdrop /><Dialog.Positioner>
                    <Dialog.Content w="calc(100% - 2rem)">
                      <Dialog.Header><Dialog.Title>Are You Sure?</Dialog.Title></Dialog.Header>
                      <Dialog.Body>You will be logged out. Are you sure?</Dialog.Body>
                      <Dialog.Footer>
                        <Dialog.ActionTrigger asChild><Button variant="outline">Cancel</Button></Dialog.ActionTrigger>
                        <Button variant="solid" onClick={logout} disabled={Boolean(saving)} loading={saving === "logout"}>Log Out</Button>
                      </Dialog.Footer>
                      <Dialog.CloseTrigger asChild><CloseButton size="sm" /></Dialog.CloseTrigger>
                    </Dialog.Content>
                  </Dialog.Positioner>
                </Portal>
              </Dialog.Root>
              <Box borderTopWidth="1px" width="100%" marginTop="40px" paddingTop="20px">
                <Tabs.List width="100%">
                  <Tabs.Trigger value="info" width="100%">Personal Info</Tabs.Trigger>
                  <Tabs.Trigger value="security" width="100%">Password And Security</Tabs.Trigger>
                </Tabs.List>
              </Box>
            </Card.Root>
          </GridItem>
          <GridItem colSpan={{ base: 1, lg: 3 }} minW="0">
            <Card.Root p="30px">
              {(!session.ready || resource.loading) && <Box role="status"><Spinner size="sm" mr="2" />Loading Profile…</Box>}
              {session.ready && session.authenticated && !session.id && <Text role="alert">Your profile ID is unavailable. Log out and sign in again.</Text>}
              {resource.error && <Stack><Text role="alert" color="fg.error">{resource.error}</Text><Button variant="outline" onClick={resource.refresh}>Retry Profile</Button></Stack>}
              {saveError && <Text role="alert" color="fg.error" mb="4">{saveError}</Text>}
              <Tabs.Content value="info">
                <Heading size="2xl">Personal Info</Heading>
                <Box as="form" onSubmit={(event) => submit(event, "profile")} mt="20px" display="flex" flexDirection="column" gap="20px">
                  {[
                    ["first_name", "First Name", "Enter Your First Name", "given-name"],
                    ["last_name", "Last Name", "Enter Your Last Name", "family-name"],
                    ["email", "Email", "Your Email", "email"],
                  ].map(([field, label, placeholder, autoComplete]) => (
                    <Field.Root key={field} gap="0">
                      <Field.Label fontWeight="bold" mb="4px">{label}</Field.Label>
                      <Input type={field === "email" ? "email" : "text"} placeholder={placeholder} value={profile[field] || ""}
                        disabled={!ready || Boolean(saving)} onChange={(event) => edit(field, event.target.value)} autoComplete={autoComplete} />
                    </Field.Root>
                  ))}
                  {profile.email !== resource.data?.email && <Field.Root><Field.Label>Current Password</Field.Label>
                    <PasswordInput required autoComplete="current-password" value={profilePassword} onChange={(event) => setProfilePassword(event.target.value)} />
                    <Text fontSize="sm">Changing your email signs out all devices and requires verification of the new address.</Text></Field.Root>}
                  <Button type="submit" variant="solid" mt="10px" width="150px" disabled={!ready || Boolean(saving)} loading={saving === "profile"} loadingText="Saving…">Save Changes</Button>
                </Box>
              </Tabs.Content>
              <Tabs.Content value="security">
                <Heading size="2xl">Password And Security</Heading>
                <Box as="form" onSubmit={(event) => submit(event, "password")} mt="20px" display="flex" flexDirection="column" gap="20px">
                  {[
                    ["current", "Current Password", "Enter Current Password"],
                    ["next", "New Password", "Enter New Password"],
                    ["confirm", "Confirm New Password", "Re-Enter New Password"],
                  ].map(([field, label, placeholder]) => (
                    <Field.Root key={field} gap="0">
                      <Field.Label fontWeight="bold" mb="4px">{label}</Field.Label>
                      <PasswordInput required placeholder={placeholder} disabled={!ready || Boolean(saving)} value={passwords[field]}
                        minLength={field === "current" ? undefined : 12} maxLength={256}
                        aria-describedby={field === "current" ? undefined : "change-password-requirements"}
                        autoComplete={field === "current" ? "current-password" : "new-password"}
                        onChange={(event) => setPasswords((previous) => ({ ...previous, [field]: event.target.value }))} />
                    </Field.Root>
                  ))}
                  <PasswordStrengthFeedback id="change-password-requirements" password={passwords.next} confirmation={passwords.confirm} />
                  <Button type="submit" variant="solid" mt="10px" width="180px" disabled={!ready || Boolean(saving)} loading={saving === "password"} loadingText="Saving…">Update Password</Button>
                </Box>
                <AccountSecurity />
              </Tabs.Content>
            </Card.Root>
          </GridItem>
        </Grid>
      </Tabs.Root>
    </Container>
  );
}
