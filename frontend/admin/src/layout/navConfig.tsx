import type { ReactNode } from "react";
import {
  IconBroadcasts,
  IconClients,
  IconDashboard,
  IconFaq,
  IconNotifications,
  IconPackages,
  IconPools,
  IconPublications,
  IconReferrals,
  IconRequests,
  IconSettings,
  IconTariffs,
} from "@/shared/components/icons";
import { strings } from "@/shared/strings";

export interface NavItemConfig {
  to: string;
  label: string;
  icon: ReactNode;
  /** "badge" shows a count pill, "dot" shows a small live-activity dot. */
  accessory?: "badge" | "dot";
}

export interface NavGroupConfig {
  label: string;
  items: NavItemConfig[];
}

export const navGroups: NavGroupConfig[] = [
  {
    label: strings.nav.groupOperations,
    items: [
      { to: "/", label: strings.nav.dashboard, icon: <IconDashboard /> },
      { to: "/clients", label: strings.nav.clients, icon: <IconClients /> },
      { to: "/requests", label: strings.nav.requests, icon: <IconRequests />, accessory: "badge" },
      { to: "/pools", label: strings.nav.pools, icon: <IconPools />, accessory: "dot" },
      { to: "/packages", label: strings.nav.packages, icon: <IconPackages /> },
      { to: "/tariffs", label: strings.nav.tariffs, icon: <IconTariffs /> },
      { to: "/referrals", label: strings.nav.referrals, icon: <IconReferrals /> },
    ],
  },
  {
    label: strings.nav.groupContent,
    items: [
      { to: "/broadcasts", label: strings.nav.broadcasts, icon: <IconBroadcasts /> },
      { to: "/publications", label: strings.nav.publications, icon: <IconPublications /> },
      { to: "/faq", label: strings.nav.faq, icon: <IconFaq /> },
    ],
  },
  {
    label: strings.nav.groupSystem,
    items: [
      { to: "/notifications", label: strings.nav.notifications, icon: <IconNotifications /> },
      { to: "/settings", label: strings.nav.settings, icon: <IconSettings /> },
    ],
  },
];
