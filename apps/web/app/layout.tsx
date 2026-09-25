import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Pathfinder — re:Invent 2026",
  description: "Pathfinder builds an explainable, conflict-free re:Invent itinerary around your interests and existing schedule.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-pathfinder-mode="demo">
      <body>{children}</body>
    </html>
  );
}
