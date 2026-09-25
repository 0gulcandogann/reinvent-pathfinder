import type { SVGProps } from "react";

type Name = "calendar" | "search" | "chart" | "spark" | "arrow" | "reset" | "check" | "clock" | "pin" | "shield" | "sliders" | "send" | "close";

const paths: Record<Name, React.ReactNode> = {
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4M17 3v4M3 10h18" /></>,
  search: <><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 5 5" /></>,
  chart: <><path d="M4 20V11m5 9V5m5 15v-8m5 8V8" /></>,
  spark: <><path d="m12 2 1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2Z" /><path d="m20 17 .6 1.4L22 19l-1.4.6L20 21l-.6-1.4L18 19l1.4-.6L20 17Z" /></>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  reset: <><path d="M3 11a9 9 0 1 1 2.8 6.5" /><path d="M3 4v7h7" /></>,
  check: <path d="m4 12 5 5L20 6" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  pin: <><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" /><circle cx="12" cy="10" r="2" /></>,
  shield: <><path d="M12 2 4 5v6c0 5 3.3 8.5 8 11 4.7-2.5 8-6 8-11V5l-8-3Z" /><path d="m9 12 2 2 4-4" /></>,
  sliders: <><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="9" cy="6" r="2" fill="white" /><circle cx="16" cy="12" r="2" fill="white" /><circle cx="8" cy="18" r="2" fill="white" /></>,
  send: <><path d="m22 2-7 20-3-9-9-3L22 2Z" /><path d="M12 13 22 2" /></>,
  close: <path d="M5 5 19 19M19 5 5 19" />,
};

export function Icon({ name, size = 18, ...props }: SVGProps<SVGSVGElement> & { name: Name; size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>{paths[name]}</svg>;
}
