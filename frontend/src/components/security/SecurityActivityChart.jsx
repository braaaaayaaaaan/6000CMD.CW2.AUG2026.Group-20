"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Box, Button, Flex, Heading, Icon, Table, Text } from "@chakra-ui/react";
import { FaChevronDown, FaCircleInfo } from "react-icons/fa6";
import { ACTIVITY_SERIES, activityScale, activityTickIndexes, buildActivityTimeline } from "@/utils/securityActivity.mjs";

const hourLabel = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const dayLabel = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", month: "short" });
const fullLabel = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const number = new Intl.NumberFormat("en-GB");

export default function SecurityActivityChart({ overview }) {
  const container = useRef(null);
  const [width, setWidth] = useState(900);
  const [selected, setSelected] = useState(null);
  const [hidden, setHidden] = useState([]);
  const [view, setView] = useState("lines");
  const gradientId = useId().replaceAll(":", "");
  const timeline = buildActivityTimeline(overview);
  const hourly = Number(overview.hours) === 24;
  const visible = ACTIVITY_SERIES.filter((series) => !hidden.includes(series.key));
  const total = timeline.reduce((sum, row) => sum + ACTIVITY_SERIES.reduce((count, series) => count + row[series.key], 0), 0);
  const totals = Object.fromEntries(ACTIVITY_SERIES.map((series) => [series.key, timeline.reduce((sum, row) => sum + row[series.key], 0)]));
  const maximum = Math.max(0, ...timeline.flatMap((row) => visible.map((series) => row[series.key])));
  const scale = activityScale(maximum);
  const height = 300;
  const margin = { top: 24, right: 22, bottom: 56, left: 44 };
  const plotWidth = Math.max(1, width - margin.left - margin.right);
  const baseline = height - margin.bottom;
  const plotHeight = baseline - margin.top;
  const x = (index) => margin.left + (timeline.length <= 1 ? plotWidth / 2 : index / (timeline.length - 1) * plotWidth);
  const y = (value) => baseline - value / scale.top * plotHeight;
  const activeIndex = selected === null ? null : Math.max(0, Math.min(selected, timeline.length - 1));
  const active = timeline[activeIndex];

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.round(entry.contentRect.width))));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  function inspect(event) {
    if (!timeline.length) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const position = (event.clientX - bounds.left) / bounds.width * width;
    setSelected(Math.max(0, Math.min(timeline.length - 1, Math.round((position - margin.left) / plotWidth * (timeline.length - 1)))));
  }

  function keyboard(event) {
    if (!timeline.length) return;
    const current = activeIndex ?? timeline.length - 1;
    if (event.key === "ArrowLeft") setSelected(Math.max(0, current - 1));
    else if (event.key === "ArrowRight") setSelected(Math.min(timeline.length - 1, current + 1));
    else if (event.key === "Home") setSelected(0);
    else if (event.key === "End") setSelected(timeline.length - 1);
    else if (event.key === "Escape") setSelected(null);
    else return;
    event.preventDefault();
  }

  return <Box bg="transparent" overflow="hidden">
    <Flex p={{ base: "4", md: "6" }} pb="3" justify="space-between" align="start" gap="3" wrap="wrap">
      <Box><Heading size="sm" fontWeight="semibold" color="#25243b">Activity Over Time</Heading><Text color="gray.600" fontSize="sm" mt="1">{hourly ? "Hourly" : "Daily"} counts in UTC. Hover to explore.</Text></Box>
      <Flex role="group" aria-label="Chart view" borderWidth="1px" borderColor="gray.200" borderRadius="lg" bg="#eff6ff" p="1">{[["bars", "Bars"], ["lines", "Lines"]].map(([value, label]) => <Button key={value} size="xs" variant="ghost" colorPalette="gray" bg={view === value ? "#173da6" : "transparent"} color={view === value ? "white" : "gray.500"} aria-pressed={view === value} onClick={() => setView(value)}>{label}</Button>)}</Flex>
    </Flex>
    <Flex px={{ base: "4", md: "6" }} gap="2" wrap="wrap" mb="2" aria-label="Chart series">
      {ACTIVITY_SERIES.map((series) => {
        const enabled = !hidden.includes(series.key);
        return <Button key={series.key} size="xs" variant="ghost" colorPalette="gray" borderRadius="md" bg="white" color="gray.700" opacity={enabled ? 1 : 0.55} aria-pressed={enabled}
          onClick={() => setHidden((previous) => enabled ? visible.length > 1 ? [...previous, series.key] : previous : previous.filter((key) => key !== series.key))}>
          <Box w="2" h="0" borderTopWidth="3px" borderStyle={series.dash ? "dashed" : "solid"} borderColor={series.color} aria-hidden="true" />{series.label}<Text as="span" color="gray.500">{number.format(totals[series.key])}</Text>
        </Button>;
      })}
    </Flex>
    <Box px={{ base: "2", md: "4" }}>
      <Box ref={container} position="relative" role="group" aria-label="Security activity chart. Use the left and right arrow keys to inspect event counts." tabIndex={0} onKeyDown={keyboard} onPointerMove={inspect} onPointerLeave={() => setSelected(null)} onClick={inspect} onBlur={() => setSelected(null)} _focusVisible={{ outline: "2px solid", outlineColor: "#2563eb", outlineOffset: "2px", borderRadius: "md" }}>
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={`${hourly ? "Hourly" : "Daily"} event counts for failed logins, access denials and asset downloads`} style={{ display: "block", touchAction: "pan-y" }}>
          <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2563eb" stopOpacity="0.12" /><stop offset="100%" stopColor="#2563eb" stopOpacity="0.01" /></linearGradient></defs>
          <text x={margin.left} y="12" fill="#64748b" fontSize="11" fontFamily="inherit">Events</text>
          {scale.ticks.map((tick) => <g key={tick}><line x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} stroke="#dbeafe" /><text x={margin.left - 12} y={y(tick) + 4} textAnchor="end" fill="#64748b" fontSize="12" fontFamily="inherit">{number.format(tick)}</text></g>)}
          {activityTickIndexes(timeline.length, plotWidth).map((index) => <g key={index}><line x1={x(index)} x2={x(index)} y1={baseline} y2={baseline + 5} stroke="#cbd5e1" /><text x={x(index)} y={baseline + 22} textAnchor={index === 0 ? "start" : index === timeline.length - 1 ? "end" : "middle"} fill="#64748b" fontSize="12" fontFamily="inherit">{hourly ? hourLabel.format(timeline[index].time) : dayLabel.format(timeline[index].time)}</text>{hourly && <text x={x(index)} y={baseline + 40} textAnchor={index === 0 ? "start" : index === timeline.length - 1 ? "end" : "middle"} fill="#94a3b8" fontSize="11" fontFamily="inherit">{dayLabel.format(timeline[index].time)}</text>}</g>)}
          {total > 0 && visible.map((series) => {
            const points = timeline.map((row, index) => `${x(index)},${y(row[series.key])}`).join(" ");
            if (view === "bars") {
              const slot = plotWidth / Math.max(1, timeline.length);
              const barWidth = Math.max(1, Math.min(12, slot * 0.72 / visible.length));
              const seriesIndex = visible.indexOf(series);
              return <g key={series.key}>{timeline.map((row, index) => row[series.key] > 0 && <rect key={index} x={Math.max(margin.left, Math.min(width - margin.right - barWidth, x(index) + (seriesIndex - (visible.length - 1) / 2) * (barWidth + 1) - barWidth / 2))} y={y(row[series.key])} width={barWidth} height={baseline - y(row[series.key])} rx="2" fill={series.color} opacity={activeIndex === null || activeIndex === index ? 0.9 : 0.3} />)}</g>;
            }
            return <g key={series.key}>
              {series.key === "login_failed" && <polygon points={`${x(0)},${baseline} ${points} ${x(timeline.length - 1)},${baseline}`} fill={`url(#${gradientId})`} />}
              <polyline points={points} fill="none" stroke={series.color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={series.dash} />
              {timeline.map((row, index) => row[series.key] > 0 && <circle key={index} cx={x(index)} cy={y(row[series.key])} r="3" fill="white" stroke={series.color} strokeWidth="2" />)}
            </g>;
          })}
          {active && <g><line x1={x(activeIndex)} x2={x(activeIndex)} y1={margin.top} y2={baseline} stroke="#94a3b8" strokeDasharray="4 4" />{visible.map((series) => <circle key={series.key} cx={x(activeIndex)} cy={y(active[series.key])} r="4.5" fill={series.color} stroke="white" strokeWidth="2" />)}</g>}
        </svg>
        {active && <Box position="absolute" top="7" left={`${Math.max(6, Math.min(width - 230, x(activeIndex) > width / 2 ? x(activeIndex) - 228 : x(activeIndex) + 14))}px`} w="220px" bg="white" borderWidth="1px" borderColor="gray.200" borderRadius="lg" shadow="lg" p="3" pointerEvents="none">
          <Text fontSize="sm" fontWeight="semibold" color="gray.900" mb="2">{fullLabel.format(active.time)} UTC</Text>
          {visible.map((series) => <Flex key={series.key} justify="space-between" gap="3" align="center" mb="1"><Flex align="center" gap="2"><Box w="2" h="2" borderRadius="full" bg={series.color} /><Text fontSize="sm" color="gray.600">{series.label}</Text></Flex><Text fontSize="sm" fontWeight="semibold" color="gray.900">{number.format(active[series.key])}</Text></Flex>)}
        </Box>}
        <Text srOnly aria-live="polite">{active ? `${fullLabel.format(active.time)} UTC. ${visible.map((series) => `${series.label} ${active[series.key]}`).join(". ")}` : ""}</Text>
      </Box>
    </Box>
    {total === 0 && <Flex mx={{ base: "4", md: "6" }} mb="4" gap="2" align="center" bg="gray.50" borderColor="gray.200" borderWidth="1px" borderRadius="lg" px="3" py="2.5" color="gray.600"><Icon asChild boxSize="4" aria-hidden="true"><FaCircleInfo /></Icon><Text fontSize="sm">No security activity in this period.</Text></Flex>}
    <Flex justify="space-between" px={{ base: "4", md: "6" }} pb="3" color="gray.400" fontSize="10px"><Text>{number.format(total)} tracked events</Text><Text>Use arrow keys to inspect</Text></Flex>
    <Box as="details" borderTopWidth="1px" borderColor="gray.100" px={{ base: "4", md: "6" }} py="3">
      <Flex as="summary" align="center" justify="space-between" cursor="pointer" color="gray.600" fontWeight="medium" fontSize="sm">View Underlying Data<Icon asChild boxSize="3" aria-hidden="true"><FaChevronDown /></Icon></Flex>
      <Box overflowX="auto" mt="3"><Table.Root variant="line" size="sm"><Table.Header><Table.Row><Table.ColumnHeader>Period (UTC)</Table.ColumnHeader>{ACTIVITY_SERIES.map((series) => <Table.ColumnHeader key={series.key} textAlign="right">{series.label}</Table.ColumnHeader>)}</Table.Row></Table.Header><Table.Body>{timeline.map((row) => <Table.Row key={row.time}><Table.Cell whiteSpace="nowrap">{fullLabel.format(row.time)}</Table.Cell>{ACTIVITY_SERIES.map((series) => <Table.Cell key={series.key} textAlign="right">{row[series.key]}</Table.Cell>)}</Table.Row>)}</Table.Body></Table.Root></Box>
    </Box>
  </Box>;
}

