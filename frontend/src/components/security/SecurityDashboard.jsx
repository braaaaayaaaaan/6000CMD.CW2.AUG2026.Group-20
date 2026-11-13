"use client";

import { useRef, useState } from "react";
import { Badge, Box, Button, CloseButton, Dialog, Flex, Heading, Icon, Input, NativeSelect, Portal, Spinner, Stack, Table, Tabs, Text } from "@chakra-ui/react";
import { FaArrowRight, FaBan, FaCalendarDays, FaChartLine, FaCheck, FaDownload, FaListUl, FaTriangleExclamation, FaUserLock, FaXmark } from "react-icons/fa6";
import ListPagination from "@/components/ListPagination";
import useApiResource from "@/hooks/useApiResource";
import useDebouncedValue from "@/hooks/useDebouncedValue";
import { api, errorMessage } from "@/utils/api";
import { formatDateTime, formatMalaysiaDateTime } from "@/utils/dateTime";
import { toaster } from "@/styles/ui/toaster";
import SecurityActivityChart from "./SecurityActivityChart";
import { buildActivityTimeline } from "@/utils/securityActivity.mjs";
import styles from "./SecurityDashboard.module.css";

const title = (value) => String(value || "").split("_").map((word) => word.toLowerCase() === "mfa" ? "MFA" : word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
const who = (row) => row.username || row.account_identifier || (row.actor_reference || row.actor || row.affected_user ? "Deleted Account" : "Anonymous");
const defaultFilters = { search: "", severity: "", status: "", alert_type: "", event_type: "", category: "", outcome: "", resource: "", start: "", end: "" };
const panel = { bg: "white", borderWidth: "1px", borderColor: "#dbeafe", borderRadius: "18px", shadow: "none", p: { base: "4", md: "6" } };
const summaryCards = [
  { key: "failed_logins", series: "login_failed", label: "Failed Sign-ins", description: "Attempts that did not succeed", color: "#2563eb" },
  { key: "access_denials", series: "access_denied", label: "Blocked Access", description: "Requests without permission", color: "#19a99a" },
  { key: "asset_downloads", series: "asset_downloaded", label: "Asset Downloads", description: "Successful library downloads", color: "#d59328" },
];
const auditPageSizeKey = "security.activityLog.pageSize";
const allowedPageSizes = [10, 25, 40, 50, 100];
function savedAuditPageSize() {
  try {
    const saved = Number(window.localStorage.getItem(auditPageSizeKey));
    return allowedPageSizes.includes(saved) ? saved : 40;
  } catch {
    return 40;
  }
}
const ruleLabels = {
  login_failed: { title: "Repeated Failed Logins", activity: "failed logins", icon: FaUserLock },
  asset_downloaded: { title: "Bulk Downloads", activity: "successful downloads", icon: FaDownload },
  access_denied: { title: "Repeated Access Denials", activity: "access denials", icon: FaBan },
};

function TimeRange({ start, end, hours, onHoursChange }) {
  return <div className={styles.period}>
    <div className={styles.periodLabel}><FaCalendarDays aria-hidden="true" /><span>{start && end ? <><time dateTime={start}>{formatMalaysiaDateTime(start)}</time><span className={styles.dateDash}> - </span><time dateTime={end}>{formatMalaysiaDateTime(end)}</time><small>Malaysia Time</small></> : "Loading activity period..."}</span></div>
    <div className={styles.range} role="group" aria-label="Activity period">{[["24", "24 Hours"], ["168", "7 Days"], ["720", "30 Days"]].map(([value, label]) => <button type="button" key={value} aria-pressed={hours === value} onClick={() => onHoursChange(value)}>{label}</button>)}</div>
  </div>;
}

function Sparkline({ rows, series, color }) {
  const maximum = Math.max(1, ...rows.map((row) => row[series]));
  const points = rows.map((row, index) => (index / Math.max(1, rows.length - 1) * 120) + "," + (34 - row[series] / maximum * 29)).join(" ");
  return <svg viewBox="0 0 120 38" className={styles.sparkline} aria-hidden="true"><polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /></svg>;
}

function StatusBadge({ value }) {
  const palette = { success: "green", failure: "red", denied: "orange", open: "orange", resolved: "green", high: "red", medium: "orange", info: "blue" }[value] || "gray";
  const StatusIcon = { success: FaCheck, failure: FaXmark, denied: FaBan, resolved: FaCheck, high: FaTriangleExclamation }[value];
  return <Badge colorPalette={palette} variant="subtle" bg={`${palette}.50`} color={`${palette}.700`} borderWidth="1px" borderColor={`${palette}.200`} borderRadius="full" px="2.5" py="0.5" whiteSpace="nowrap">
    {StatusIcon ? <Icon asChild boxSize="3" aria-hidden="true"><StatusIcon /></Icon> : <Box boxSize="1.5" borderRadius="full" bg={`${palette}.500`} aria-hidden="true" />}{title(value)}
  </Badge>;
}

function DetectionRules({ rules }) {
  return <section className={styles.rules}><div className={styles.sectionHeader}><h2>Detection Rules</h2><span>{rules.length} detection rules</span></div><p className={styles.rulesIntro}>Alerts are created when an account or user reaches these limits.</p>
    {rules.map((rule) => {
      const labels = ruleLabels[rule.event_type] || { title: title(rule.type), activity: "events", icon: FaTriangleExclamation };
      return <div className={styles.ruleRow} key={rule.type}><div className={styles.ruleIcon}><labels.icon aria-hidden="true" /></div><div><h3>{labels.title}</h3><p>{rule.threshold} {labels.activity} within {rule.seconds / 60} minutes</p></div><Severity value={rule.severity} /></div>;
    })}
    <p className={styles.rulesFootnote}>Check the event details to decide whether further action is needed.</p>
  </section>;
}

function Severity({ value }) {
  return <StatusBadge value={value} />;
}

function SelectFilter({ label, value, onChange, options, all = true }) {
  return <Stack as="label" gap="1" minW="150px" flex="1">
    <Text fontWeight="medium" fontSize="xs" color="gray.600">{label}</Text>
    <NativeSelect.Root><NativeSelect.Field value={value} onChange={(event) => onChange(event.target.value)}>
      {all && <option value="">All</option>}
      {options.map((option) => <option key={typeof option === "string" ? option : option.value} value={typeof option === "string" ? option : option.value}>{typeof option === "string" ? title(option) : option.label}</option>)}
    </NativeSelect.Field><NativeSelect.Indicator /></NativeSelect.Root>
  </Stack>;
}

function ResourceState({ resource, children }) {
  if (resource.loading) return <Flex justify="center" py="10"><Spinner color="#173da6" aria-label="Loading security activity" /></Flex>;
  if (resource.error) return <Stack py="6" align="start"><Text role="alert">{resource.error}</Text><Button variant="outline" onClick={resource.refresh}>Retry</Button></Stack>;
  return children;
}

function Overview({ resource, hours, onHoursChange, onReview, recentAlerts, inspect, onAudit }) {
  const data = resource.data;
  const rows = data ? buildActivityTimeline(data) : [];
  const total = data ? summaryCards.reduce((sum, card) => sum + data.counts[card.key], 0) : 0;
  return <div>
    <TimeRange start={data?.start} end={data?.end} hours={hours} onHoursChange={onHoursChange} />
    <ResourceState resource={resource}>{data && <>
      <div className={styles.workspace}>
        <section className={styles.analytics} aria-label="Activity analytics">
          <div className={styles.metrics}>{summaryCards.map((card) => <div key={card.key} className={styles.metric}>
            <span className={styles.metricLabel}><i style={{ background: card.color }} />{card.label}</span>
            <div className={styles.metricValue}><strong>{new Intl.NumberFormat("en-GB").format(data.counts[card.key])}</strong><Sparkline rows={rows} series={card.series} color={card.color} /></div>
            <span className={styles.metricDescription}>{card.description}</span>
          </div>)}</div>
          <div className={styles.chartPanel}><SecurityActivityChart key={data.start + ":" + data.hours} overview={data} /></div>
        </section>
        <aside className={styles.review}>
          <div className={styles.sectionEyebrow}><span className={styles.statusDot} /> SECURITY ALERTS</div>
          <div className={styles.reviewCount}>{new Intl.NumberFormat("en-GB").format(data.counts.open_alerts)}<span>open {data.counts.open_alerts === 1 ? "alert" : "alerts"}</span></div>
          <h2>{data.counts.open_alerts ? "Alerts to Review" : "No Open Alerts"}</h2>
          <p>{data.counts.open_alerts ? "Check the details, then resolve alerts you have handled." : "New alerts will appear here when a detection rule is triggered."}</p>
          <button className={styles.primaryButton} onClick={onReview}>Review Alerts<FaArrowRight aria-hidden="true" /></button>
          <span className={styles.scopeNote}>Includes open alerts from all dates</span>
          <div className={styles.queueList}><div className={styles.queueTitle}>Recent Open Alerts</div>
            <ResourceState resource={recentAlerts}>{recentAlerts.data?.results?.length ? recentAlerts.data.results.slice(0, 3).map((row) => <button key={row.id} className={styles.queueItem} onClick={() => inspect({ kind: "alerts", id: row.id })}><span className={styles.queueItemTop}><span>{title(row.alert_type)}</span><FaArrowRight aria-hidden="true" /></span><span className={styles.queueItemBottom}>{who(row)}<StatusBadge value={row.severity} /></span></button>) : <div className={styles.queueEmpty}><FaCheck aria-hidden="true" /><span>No Alerts to Display</span></div>}</ResourceState>
          </div>
        </aside>
      </div>
      <div className={styles.lowerGrid}>
        <section className={styles.breakdown}><div className={styles.sectionHeader}><h2>Activity Breakdown</h2><span>{new Intl.NumberFormat("en-GB").format(total)} tracked events</span></div>
          <div className={styles.distribution} aria-hidden="true">{summaryCards.map((card) => <span key={card.key} style={{ flex: total ? data.counts[card.key] : 1, background: total ? card.color : "#eef0f2" }} />)}</div>
          {summaryCards.map((card) => <div className={styles.breakdownRow} key={card.key}><span><i style={{ background: card.color }} />{card.label}</span><strong>{total ? Math.round(data.counts[card.key] / total * 100) : 0}%<small>{new Intl.NumberFormat("en-GB").format(data.counts[card.key])}</small></strong></div>)}
          <button className={styles.textButton} onClick={onAudit}>View Activity Log<FaArrowRight aria-hidden="true" /></button>
        </section>
        <DetectionRules rules={data.rules} />
      </div>
    </>}</ResourceState>
  </div>;
}

function Filters({ kind, values, update, eventTypes, alertTypes }) {
  const alert = kind === "alerts";
  return <Box {...panel} className={styles.filtersPanel}><Flex gap="3" wrap="wrap" align="end">
    <Stack as="label" gap="1" flex="2" minW="200px"><Text fontWeight="medium" fontSize="xs" color="gray.600">Search</Text><Input placeholder={alert ? "Username or account identifier" : "User, event or resource"} value={values.search} onChange={(e) => update("search", e.target.value)} /></Stack>
    <SelectFilter label="Severity" value={values.severity} onChange={(value) => update("severity", value)} options={["info", "medium", "high"]} />
    <SelectFilter label={alert ? "Alert Type" : "Event Type"} value={values[alert ? "alert_type" : "event_type"]} onChange={(value) => update(alert ? "alert_type" : "event_type", value)} options={alert ? alertTypes : eventTypes} />
    <SelectFilter label={alert ? "Status" : "Outcome"} value={values[alert ? "status" : "outcome"]} onChange={(value) => update(alert ? "status" : "outcome", value)} options={alert ? ["open", "resolved"] : ["success", "failure", "denied"]} />
    {!alert && <SelectFilter label="Event Category" value={values.category} onChange={(value) => update("category", value)} options={["authentication", "authorization", "asset", "account", "management"]} />}
    {[['start', 'From'], ['end', 'To']].map(([key, label]) => <Stack as="label" key={key} gap="1" flex="1" minW="200px"><Text fontWeight="medium" fontSize="xs" color="gray.600">{label}</Text><Input type="datetime-local" value={values[key]} onChange={(e) => update(key, e.target.value)} /></Stack>)}
    <Button size="sm" variant="outline" onClick={() => update(null)}>Clear Filters</Button>
  </Flex></Box>;
}

function EventTable({ kind, resource, page, setPage, pageSize, setPageSize, inspect, resolve, saving }) {
  const alert = kind === "alerts";
  const headings = alert ? ["Severity", "Alert Type", "Affected User", "Description", "Event Count", "Detected Time", "Status", "Actions"] : ["Timestamp", "User", "Event", "Resource", "IP Address", "Outcome", "Severity", "Actions"];
  return <ResourceState resource={resource}><Box {...panel} className={styles.tablePanel} p="0" overflow="hidden"><Box overflowX="auto">
    <Table.Root variant="line" color="gray.800"><Table.Header><Table.Row bg="#eff6ff">{headings.map((label) => <Table.ColumnHeader key={label} color="gray.600" whiteSpace="nowrap">{label}</Table.ColumnHeader>)}</Table.Row></Table.Header>
      <Table.Body>{resource.data?.results?.length ? resource.data.results.map((row) => <Table.Row key={row.id} _hover={{ bg: "#f8fbff" }}>
        {alert ? <>
          <Table.Cell><Severity value={row.severity} /></Table.Cell><Table.Cell>{title(row.alert_type)}</Table.Cell><Table.Cell>{who(row)}</Table.Cell>
          <Table.Cell minW="220px">{row.description}</Table.Cell><Table.Cell>{row.event_count}</Table.Cell><Table.Cell whiteSpace="nowrap">{formatDateTime(row.last_detected_at)}</Table.Cell>
          <Table.Cell><StatusBadge value={row.status} /></Table.Cell>
        </> : <>
          <Table.Cell whiteSpace="nowrap">{formatDateTime(row.timestamp)}</Table.Cell><Table.Cell>{who(row)}</Table.Cell><Table.Cell>{title(row.event_type)}</Table.Cell>
          <Table.Cell maxW="220px" overflowWrap="anywhere">{title(row.resource_type)} {row.resource_id || ""}</Table.Cell><Table.Cell whiteSpace="nowrap">{row.ip_address || "Unavailable"}</Table.Cell>
          <Table.Cell><StatusBadge value={row.outcome} /></Table.Cell><Table.Cell><Severity value={row.severity} /></Table.Cell>
        </>}
        <Table.Cell><Flex gap="2"><Button size="xs" variant="outline" onClick={() => inspect({ kind, id: row.id })}>Details</Button>{alert && row.status === "open" && <Button size="xs" className={styles.resolveButton} onClick={() => resolve(row.id)} disabled={saving} loading={saving}>Resolve</Button>}</Flex></Table.Cell>
      </Table.Row>) : <Table.Row><Table.Cell colSpan={8} textAlign="center" py="10">{alert ? "No alerts match these filters." : "No audit events match these filters."}</Table.Cell></Table.Row>}</Table.Body>
    </Table.Root>
  </Box><Box className={styles.pagination}><ListPagination page={page} count={resource.data?.count || 0} pageSize={alert ? 40 : pageSize} onPageSizeChange={alert ? undefined : setPageSize} onPageChange={setPage} disabled={resource.loading || saving} /></Box></Box></ResourceState>;
}

function Details({ selected, close, resource }) {
  const row = resource.data;
  const alert = selected?.kind === "alerts";
  const details = row ? alert ? [["Alert Type", title(row.alert_type)], ["Affected User", who(row)], ["Severity", title(row.severity)], ["Description", row.description], ["Event Count", row.event_count], ["Detection Window", `${row.window_seconds / 60} minutes`], ["Window Start", formatDateTime(row.window_started_at)], ["First Detected", formatDateTime(row.first_detected_at)], ["Most Recent Detection", formatDateTime(row.last_detected_at)], ["Status", title(row.status)], ["Resolved At", row.resolved_at ? formatDateTime(row.resolved_at) : "Unresolved"], ["Resolved By", row.resolved_by_username || "Unassigned"]]
    : [["Timestamp", formatDateTime(row.timestamp)], ["User", who(row)], ["User Identifier", row.actor_reference || row.actor || "Anonymous"], ["Event", title(row.event_type)], ["Category", title(row.category)], ["Resource Type", title(row.resource_type)], ["Resource Identifier", row.resource_id || "Unavailable"], ["IP Address", row.ip_address || "Unavailable"], ["User Agent", row.user_agent || "Unavailable"], ["Outcome", title(row.outcome)], ["Severity", title(row.severity)]] : [];
  return <Dialog.Root open={Boolean(selected)} onOpenChange={({ open }) => { if (!open) close(); }} size="lg" scrollBehavior="inside" lazyMount unmountOnExit><Portal><Dialog.Backdrop /><Dialog.Positioner><Dialog.Content className={styles.detailsPanel} colorPalette="blue" bg="white" color="#25243b" borderWidth="1px" borderColor="#dbeafe" borderRadius="18px" w="calc(100% - 2rem)">
    <Dialog.Header><Dialog.Title>{alert ? "Security Alert Details" : "Audit Event Details"}</Dialog.Title></Dialog.Header><Dialog.Body>
      <ResourceState resource={resource}>{row && <Stack gap="4"><Box as="dl">{details.map(([label, value]) => <Box key={label} mb="3"><Text as="dt" fontWeight="semibold">{label}</Text><Text as="dd" overflowWrap="anywhere">{value}</Text></Box>)}</Box>
        <Box><Heading size="sm" mb="2">Supporting Metadata</Heading><Box as="pre" whiteSpace="pre-wrap" overflowWrap="anywhere" bg="#eff6ff" p="3" borderRadius="lg" fontSize="sm">{JSON.stringify(row.metadata, null, 2)}</Box></Box>
      </Stack>}</ResourceState>
    </Dialog.Body><Dialog.Footer><Button variant="outline" onClick={close}>Close</Button></Dialog.Footer><Dialog.CloseTrigger asChild><CloseButton size="sm" /></Dialog.CloseTrigger>
  </Dialog.Content></Dialog.Positioner></Portal></Dialog.Root>;
}

export default function SecurityDashboard() {
  const [tab, setTab] = useState("overview");
  const [hours, setHours] = useState("24");
  const [filters, setFilters] = useState({ alerts: { ...defaultFilters }, audit: { ...defaultFilters } });
  const [pages, setPages] = useState({ alerts: 1, audit: 1 });
  const [revision, setRevision] = useState(0);
  const [auditPageSize, setAuditPageSize] = useState(savedAuditPageSize);
  const [selected, setSelected] = useState(null);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);
  const overview = useApiResource(`/api/security/overview/?hours=${hours}`, { refreshKey: revision });
  const recentAlerts = useApiResource("/api/security/alerts/?status=open&page=1", { enabled: tab === "overview", refreshKey: revision });
  const kind = tab === "alerts" ? "alerts" : "audit";
  const values = filters[kind];
  const debounced = useDebouncedValue(JSON.stringify(values));
  const query = new URLSearchParams({ page: String(pages[kind]) });
  if (kind === "audit") query.set("page_size", String(auditPageSize));
  for (const [key, value] of Object.entries(JSON.parse(debounced))) {
    if (value && (kind === "alerts" ? !["event_type", "category", "outcome", "resource"].includes(key) : !["alert_type", "status"].includes(key))) {
      if (key === "start" || key === "end") {
        const date = new Date(value);
        if (!Number.isNaN(date.getTime())) query.set(key, date.toISOString());
      } else query.set(key, value);
    }
  }
  const listPath = kind === "alerts" ? "alerts" : "audit-events";
  const listing = useApiResource(`/api/security/${listPath}/?${query}`, { enabled: tab !== "overview" && debounced === JSON.stringify(values), refreshKey: revision });
  const details = useApiResource(selected ? `/api/security/${selected.kind === "alerts" ? "alerts" : "audit-events"}/${selected.id}/` : null, { refreshKey: revision });
  function changeAuditPageSize(size) {
    if (!allowedPageSizes.includes(size)) return;
    setAuditPageSize(size);
    setPages((previous) => ({ ...previous, audit: 1 }));
    try {
      window.localStorage.setItem(auditPageSizeKey, String(size));
    } catch {
      // Pagination still works when browser storage is unavailable.
    }
  }
  function update(key, value) {
    setFilters((previous) => ({ ...previous, [kind]: key ? { ...previous[kind], [key]: value } : { ...defaultFilters } }));
    setPages((previous) => ({ ...previous, [kind]: 1 }));
  }
  async function resolve(id) {
    if (busy.current) return;
    busy.current = true; setSaving(true);
    try {
      await api.post(`/api/security/alerts/${id}/resolve/`);
      setPages((previous) => ({ ...previous, alerts: 1 }));
      setRevision((previous) => previous + 1);
      toaster.create({ description: "Security alert resolved.", type: "success" });
    } catch (error) { toaster.create({ description: errorMessage(error), type: "error" }); }
    finally { busy.current = false; setSaving(false); }
  }
  return <main className={styles.dashboard}>
    <header className={styles.pageHeader}><div><div className={styles.breadcrumb}>Workspace <span>/</span> Security</div><h1>Security Dashboard</h1><p>View account activity and review security alerts.</p></div></header>
    <Stack gap="5">

    <Tabs.Root value={tab} onValueChange={({ value }) => setTab(value)} colorPalette="blue" variant="line">
      <Tabs.List flexWrap="wrap" borderBottomWidth="1px" borderColor="gray.200" gap={{ base: "0", md: "5" }} w="full">
        {[["overview", "Overview", FaChartLine], ["alerts", "Alerts", FaTriangleExclamation], ["audit", "Activity Log", FaListUl]].map(([value, label, TabIcon]) => <Tabs.Trigger key={value} value={value} color="gray.500" px={{ base: "2", md: "3" }} py="4" fontSize="sm" _selected={{ color: "#173da6", borderColor: "#2563eb" }}><Icon asChild boxSize="3.5" aria-hidden="true"><TabIcon /></Icon>{label}</Tabs.Trigger>)}
      </Tabs.List>
      <Tabs.Content value="overview" pt="5"><Overview resource={overview} hours={hours} onHoursChange={setHours} onReview={() => setTab("alerts")} recentAlerts={recentAlerts} inspect={setSelected} onAudit={() => setTab("audit")} /></Tabs.Content>
      {[['alerts', 'Security Alerts'], ['audit', 'Activity Log']].map(([value, label]) => <Tabs.Content key={value} value={value} pt="5">{tab === value && <Stack gap="5"><Box className={styles.listHeader}><Heading size="md" color="#25243b">{label}</Heading><Text color="gray.600" mt="1">{value === "alerts" ? "Review unusual activity. Open Details to investigate, then resolve alerts you have handled." : "A searchable record of who did what and when. Use filters to find a specific action."}</Text></Box>
        <Filters kind={kind} values={values} update={update} eventTypes={overview.data?.event_types || []} alertTypes={overview.data?.alert_types || []} />
        <EventTable kind={kind} resource={{ ...listing, loading: listing.loading || debounced !== JSON.stringify(values) }} page={pages[kind]} pageSize={auditPageSize} setPageSize={changeAuditPageSize} setPage={(page) => setPages((previous) => ({ ...previous, [kind]: page }))} inspect={setSelected} resolve={resolve} saving={saving} />
      </Stack>}</Tabs.Content>)}
    </Tabs.Root>
    <Details selected={selected} close={() => setSelected(null)} resource={details} />
    </Stack>
  </main>;
}


