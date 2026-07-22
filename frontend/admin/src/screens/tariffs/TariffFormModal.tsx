import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { Select } from "@/shared/components/form/Select";
import { useCreateTariff, useUpdateTariff } from "@/shared/hooks/useTariffs";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Tariff } from "@/shared/api/types";

const DURATION_UNITS = ["minute", "hour", "day", "week", "month"] as const;
type DurationUnit = (typeof DURATION_UNITS)[number];
const UNIT_MINUTES: Record<DurationUnit, number> = {
  minute: 1,
  hour: 60,
  day: 1440,
  week: 10080,
  month: 43200, // 30 days
};
const UNIT_LABEL: Record<DurationUnit, string> = {
  minute: "Minutes",
  hour: "Hours",
  day: "Days",
  week: "Weeks",
  month: "Months",
};

/** Reverse a stored duration_minutes into the largest whole unit that divides it
 *  (e.g. 43200 → 1 month, 21600 → 15 days, 60 → 1 hour, 30 → 30 minutes). */
function minutesToDuration(mins: number): { value: number; unit: DurationUnit } {
  for (const unit of [...DURATION_UNITS].reverse()) {
    const f = UNIT_MINUTES[unit];
    if (mins > 0 && mins % f === 0) return { value: mins / f, unit };
  }
  return { value: mins, unit: "minute" };
}

const tariffSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  price_usd: z.coerce.number().min(0, "Must be 0 or more"),
  duration_value: z.coerce.number().int().min(1, "Must be at least 1"),
  duration_unit: z.enum(DURATION_UNITS),
  max_user_swaps: z.coerce.number().int().min(0, "Must be 0 or more"),
  is_active: z.boolean(),
});

type TariffForm = z.infer<typeof tariffSchema>;

interface TariffFormModalProps {
  open: boolean;
  onClose: () => void;
  tariff: Tariff | null;
}

export function TariffFormModal({ open, onClose, tariff }: TariffFormModalProps) {
  const toast = useToast();
  const createMutation = useCreateTariff();
  const updateMutation = useUpdateTariff();
  const isEdit = tariff !== null;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<TariffForm>({
    resolver: zodResolver(tariffSchema),
    defaultValues: { code: "", name: "", price_usd: 0, duration_value: 1, duration_unit: "day", max_user_swaps: 0, is_active: true },
  });

  useEffect(() => {
    if (!open) return;
    if (tariff) {
      const d = minutesToDuration(tariff.duration_minutes);
      reset({
        code: tariff.code,
        name: tariff.name,
        price_usd: tariff.price_usd,
        duration_value: d.value,
        duration_unit: d.unit,
        max_user_swaps: tariff.max_user_swaps,
        is_active: tariff.is_active,
      });
    } else {
      reset({ code: "", name: "", price_usd: 0, duration_value: 1, duration_unit: "day", max_user_swaps: 0, is_active: true });
    }
  }, [open, tariff, reset]);

  async function onSubmit(values: TariffForm) {
    const payload = {
      code: values.code,
      name: values.name,
      price_usd: values.price_usd,
      duration_minutes: values.duration_value * UNIT_MINUTES[values.duration_unit],
      max_user_swaps: values.max_user_swaps,
      is_active: values.is_active,
    };
    try {
      if (isEdit && tariff) {
        await updateMutation.mutateAsync({ id: tariff.id, body: payload });
        toast.success("Tariff updated");
      } else {
        await createMutation.mutateAsync(payload);
        toast.success("Tariff created");
      }
      onClose();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? strings.tariffs.edit : strings.tariffs.create}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {strings.common.cancel}
          </Button>
          <Button variant="primary" onClick={handleSubmit(onSubmit)} isLoading={isSubmitting}>
            {isEdit ? strings.common.save : strings.common.create}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        <div className="grid grid-cols-2 gap-4">
          <Input label={strings.tariffs.code} error={errors.code?.message} {...register("code")} />
          <Input label={strings.tariffs.name} error={errors.name?.message} {...register("name")} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Input
            type="number"
            step="0.01"
            min={0}
            label={strings.tariffs.priceUsd}
            error={errors.price_usd?.message}
            {...register("price_usd")}
          />
          <Input
            type="number"
            min={0}
            label={strings.tariffs.maxUserSwaps}
            hint="Max self-service IP swaps the client can do"
            error={errors.max_user_swaps?.message}
            {...register("max_user_swaps")}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Input
            type="number"
            min={1}
            label={strings.tariffs.duration}
            error={errors.duration_value?.message}
            {...register("duration_value")}
          />
          <Select
            label={strings.tariffs.durationUnit}
            error={errors.duration_unit?.message}
            {...register("duration_unit")}
          >
            {DURATION_UNITS.map((u) => (
              <option key={u} value={u}>
                {UNIT_LABEL[u]}
              </option>
            ))}
          </Select>
        </div>
        <Checkbox id="tariff-active" label={strings.tariffs.active} {...register("is_active")} />
      </form>
    </Modal>
  );
}
