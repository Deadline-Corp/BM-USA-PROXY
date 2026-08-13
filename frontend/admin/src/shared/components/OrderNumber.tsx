import { CopyInline } from "@/shared/components/CopyInline";

/** An order as an operator refers to it: `#412`.
 *
 * The order's real identifier is a UUID, and it stays one — `/pay/{public_id}` is opened
 * from an external browser with no session to check, so its only protection is being
 * unguessable. But a UUID is not something a person can read down the phone or hold in
 * their head between two screens, and truncating it to `6c7476ed…cd48` makes it unreadable
 * without making it shorter to say.
 *
 * So the console shows the row's own sequence number and resolves it back to the id
 * itself. One component for all six places it appears, so the format cannot drift between
 * the table you copy it from and the screen you paste it into.
 */
export function OrderNumber({
  value,
  className,
}: {
  value: number | string | null | undefined;
  className?: string;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-text-3">—</span>;
  }
  // Copyable because the next move is pasting it into a search box, which accepts the
  // leading "#" the same as it accepts the bare digits.
  return <CopyInline value={`#${value}`} className={className} />;
}
