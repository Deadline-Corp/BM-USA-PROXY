import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Select } from "@/shared/components/form/Select";
import { useCreatePromoCode } from "@/shared/hooks/usePromos";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";

/** A date an operator typed, as an instant.
 *
 *  The "end" edge lands on the last second of that day rather than its midnight: somebody
 *  typing 30 Sep into Expires means the code still works on 30 Sep. Taken as midnight it
 *  would die the moment the day began, and the operator would find out from a client.
 */
function dayToIso(value: string, edge: "start" | "end"): string | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return null;
  const at =
    edge === "end" ? new Date(y, m - 1, d, 23, 59, 59) : new Date(y, m - 1, d, 0, 0, 0);
  return at.toISOString();
}

/** Today, as the value an <input type="date"> holds.
 *
 *  Built from the operator's own calendar, not from an ISO instant: the browser is the
 *  only place that knows what day it is where they are sitting, and a UTC-derived "today"
 *  is yesterday for half the world. Date strings in this format compare correctly as
 *  strings, so every check below is a plain <.
 */
function todayLocal(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const promoSchema = z
  .object({
    code: z.string().trim().min(1, "Code is required"),
    percent_off: z.coerce.number().int().min(1, "1–100").max(100, "1–100"),
    // Dates and the use limit are kept as strings because empty is a real answer for all
    // three — "no start", "no expiry", "unlimited" — and a coerced number turns "" into 0.
    starts_at: z.string(),
    expires_at: z.string(),
    max_uses: z.string(),
    applies_to: z.enum(["any", "purchase"]),
    note: z.string(),
  })
  .superRefine((v, ctx) => {
    // A code cannot start before it exists. The client dated one 1 September on the 9th
    // and it went live backdated — nothing in the form said no, and the server's floor is
    // deliberately a day wide because it does not know the operator's timezone. This is
    // the check that actually knows what day it is here.
    const today = todayLocal();
    if (v.starts_at && v.starts_at < today) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["starts_at"],
        message: "Cannot start in the past",
      });
    }
    if (v.expires_at && v.expires_at < today) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["expires_at"],
        message: "Already in the past",
      });
    }
    if (v.max_uses !== "") {
      const n = Number(v.max_uses);
      if (!Number.isInteger(n) || n < 1) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["max_uses"],
          message: "A whole number, or empty for unlimited",
        });
      }
    }
    // Caught here as well as by the database, so the operator sees which field is wrong
    // instead of a constraint name.
    if (v.starts_at && v.expires_at && v.expires_at < v.starts_at) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["expires_at"],
        message: "Must be on or after the start date",
      });
    }
  });

type PromoForm = z.input<typeof promoSchema>;

const EMPTY: PromoForm = {
  code: "",
  percent_off: 10,
  starts_at: "",
  expires_at: "",
  max_uses: "",
  applies_to: "any",
  note: "",
};

interface PromoFormModalProps {
  open: boolean;
  onClose: () => void;
}

export function PromoFormModal({ open, onClose }: PromoFormModalProps) {
  const toast = useToast();
  const createMutation = useCreatePromoCode();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<PromoForm>({
    resolver: zodResolver(promoSchema),
    defaultValues: EMPTY,
  });

  useEffect(() => {
    if (open) reset(EMPTY);
  }, [open, reset]);

  // Recomputed on every open rather than once per mount: the console is a tab somebody
  // leaves open, and a `min` fixed at the day it was loaded starts refusing today.
  const today = useMemo(() => todayLocal(), [open]);

  async function onSubmit(values: PromoForm) {
    try {
      await createMutation.mutateAsync({
        // Upper-cased here as well as on the server so the list shows what the operator
        // will read out to a client, not what they happened to type.
        code: String(values.code).trim().toUpperCase(),
        percent_off: Number(values.percent_off),
        starts_at: dayToIso(values.starts_at, "start"),
        expires_at: dayToIso(values.expires_at, "end"),
        max_uses: values.max_uses === "" ? null : Number(values.max_uses),
        applies_to: values.applies_to,
        note: values.note.trim() || null,
      });
      toast.success(strings.promos.created);
      onClose();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={strings.promos.create}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {strings.common.cancel}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit(onSubmit)}
            isLoading={createMutation.isPending}
          >
            {strings.common.create}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        <div className="grid grid-cols-2 gap-4">
          <Input
            label={strings.promos.code}
            hint={strings.promos.codeHint}
            error={errors.code?.message}
            className="font-mono uppercase"
            autoComplete="off"
            spellCheck={false}
            {...register("code")}
          />
          <Input
            type="number"
            min={1}
            max={100}
            label={strings.promos.percentOff}
            error={errors.percent_off?.message}
            {...register("percent_off")}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          {/* `min` so the picker will not offer a past day at all — the validation above
              is for a date typed straight into the field, which the browser still allows. */}
          <Input
            type="date"
            min={today}
            label={strings.promos.startsAt}
            hint={strings.promos.startsAtHint}
            error={errors.starts_at?.message}
            {...register("starts_at")}
          />
          <Input
            type="date"
            min={today}
            label={strings.promos.expiresAt}
            hint={strings.promos.expiresAtHint}
            error={errors.expires_at?.message}
            {...register("expires_at")}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Input
            type="number"
            min={1}
            placeholder={strings.promos.unlimited}
            label={strings.promos.maxUses}
            hint={strings.promos.maxUsesHint}
            error={errors.max_uses?.message}
            {...register("max_uses")}
          />
          <Select
            label={strings.promos.appliesTo}
            error={errors.applies_to?.message}
            {...register("applies_to")}
          >
            <option value="any">{strings.promos.appliesToAny}</option>
            <option value="purchase">{strings.promos.appliesToPurchase}</option>
          </Select>
        </div>
        <Input
          label={strings.promos.note}
          hint={strings.promos.noteHint}
          error={errors.note?.message}
          {...register("note")}
        />
      </form>
    </Modal>
  );
}
