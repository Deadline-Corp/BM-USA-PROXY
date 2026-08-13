import { useState } from "react";
import clsx from "clsx";
import { FieldShell } from "@/shared/components/form/FieldShell";
import { IconEye, IconEyeOff } from "@/shared/components/icons";

interface PasswordInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  error?: string;
  autoFocus?: boolean;
  id?: string;
}

/** A password being *set*, with a reveal toggle.
 *
 * It shows what you are typing, never what is stored. An existing password cannot be
 * displayed at all: only its argon2id hash is kept, and a hash does not run backwards.
 * Making one displayable would mean keeping the password itself, which hands every
 * operator's password to anyone holding a database dump — and people reuse passwords, so
 * the damage would not stop at this console.
 *
 * Revealing what you just typed is a different thing, and it is what avoids the "I set it,
 * sent it, and it does not work" round trip.
 *
 * Built on FieldShell rather than Input so the button can sit inside the field itself. An
 * offset measured from the top of the shell would depend on the label's line height and
 * drift the first time anything about the type scale changes.
 */
export function PasswordInput({
  label,
  value,
  onChange,
  hint,
  error,
  autoFocus,
  id,
}: PasswordInputProps) {
  const [shown, setShown] = useState(false);
  return (
    <FieldShell label={label} hint={hint} error={error} htmlFor={id}>
      <div className="relative flex items-center">
        <input
          id={id}
          type={shown ? "text" : "password"}
          autoComplete="new-password"
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={clsx(
            "h-10 w-full pl-3 pr-10 bg-surface-2 border border-border rounded-lg text-text",
            "font-body text-[.88rem] transition-colors duration-150 ease-brand",
            "placeholder:text-text-3 focus:outline-none focus:border-accent-line",
            error && "border-danger-line",
          )}
        />
        <button
          type="button"
          className="absolute right-2.5 text-text-3 hover:text-text-2 transition-colors [&_svg]:w-[18px] [&_svg]:h-[18px]"
          onClick={() => setShown((v) => !v)}
          aria-label={shown ? "Hide password" : "Show password"}
          title={shown ? "Hide" : "Show"}
        >
          {shown ? <IconEyeOff /> : <IconEye />}
        </button>
      </div>
    </FieldShell>
  );
}
