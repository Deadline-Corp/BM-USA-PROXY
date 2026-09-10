import { strings } from "../strings";
import type { AccessStatus } from "../api/types";

/** How an access reads in the list and on its own screen — one vocabulary for both.
 *
 *  This is the state of what the customer BOUGHT, not of the phone behind it. The detail
 *  header used to label the same field "Online", which reads as a device that is up; a
 *  customer whose access had days left saw a word about hardware they do not own.
 */
export const STATUS_TONE: Record<string, "success" | "warn" | "default" | "danger"> = {
  active: "success",
  provisioning: "warn",
  expiring: "warn",
  expired: "default",
  cancelled: "danger",
  revoked: "danger",
  failed: "danger",
};

export function statusLabel(status: AccessStatus): string {
  switch (status) {
    case "active":
      return strings.access.statusActive;
    case "expiring":
      return strings.access.statusExpiring;
    case "provisioning":
      return strings.access.statusProvisioning;
    case "expired":
      return strings.access.statusExpired;
    case "cancelled":
      return strings.access.statusCancelled;
    case "revoked":
      return strings.access.statusRevoked;
    case "failed":
      return strings.access.statusFailed;
    default:
      return status;
  }
}
