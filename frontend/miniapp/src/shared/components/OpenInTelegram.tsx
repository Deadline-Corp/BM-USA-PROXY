import { MessageCircle } from "lucide-react";
import { strings } from "../strings";

/** Full-screen fallback rendered when the app is opened outside Telegram (no dev bypass). */
export function OpenInTelegram() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-app px-6 text-center">
      <span className="flex h-16 w-16 items-center justify-center rounded-xl border border-accent/[.14] bg-accent/[.07] text-accent">
        <MessageCircle size={30} strokeWidth={1.5} />
      </span>
      <h1 className="font-head text-[20px] font-bold tracking-tight text-text">
        {strings.openInTelegram.title}
      </h1>
      <p className="max-w-[300px] text-[14.5px] leading-relaxed text-text-2">{strings.openInTelegram.body}</p>
    </div>
  );
}
