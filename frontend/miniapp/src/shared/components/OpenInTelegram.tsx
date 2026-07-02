import { MessageCircle } from "lucide-react";
import { strings } from "../strings";

/** Full-screen fallback rendered when the app is opened outside Telegram (no dev bypass). */
export function OpenInTelegram() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-app px-6 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-xl border border-accent/[.22] bg-accent/10 text-accent">
        <MessageCircle size={26} strokeWidth={1.5} />
      </span>
      <h1 className="font-head text-[18px] font-semibold tracking-tight text-text">
        {strings.openInTelegram.title}
      </h1>
      <p className="max-w-[280px] text-[13.5px] leading-relaxed text-text-2">{strings.openInTelegram.body}</p>
    </div>
  );
}
