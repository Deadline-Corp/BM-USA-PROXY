import { ShieldX, Send } from "lucide-react";
import { strings } from "../strings";
import { Button } from "./Button";

/** Full-screen block shown when the backend reports the account as banned.
 *  Replaces the generic "Something went wrong" so the user knows what happened
 *  and how to reach a human. */
export function BannedScreen() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-app px-6 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-xl border border-danger/[.22] bg-danger/10 text-danger">
        <ShieldX size={26} strokeWidth={1.5} aria-hidden="true" />
      </span>
      <h1 className="font-head text-[18px] font-semibold tracking-tight text-text">
        {strings.banned.title}
      </h1>
      <p className="max-w-[300px] text-[13.5px] leading-relaxed text-text-2">{strings.banned.body}</p>
      <a
        href="https://t.me/usproxy_support"
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 no-underline"
      >
        <Button variant="primary" size="sm">
          <Send size={15} aria-hidden="true" />
          {strings.banned.cta}
        </Button>
      </a>
    </div>
  );
}
