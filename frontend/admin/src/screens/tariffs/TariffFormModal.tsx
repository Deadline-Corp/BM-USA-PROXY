import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { useCreateTariff, useUpdateTariff } from "@/shared/hooks/useTariffs";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Tariff } from "@/shared/api/types";

const tariffSchema = z.object({
  code: z.string().min(1, "Code is required"),
  name: z.string().min(1, "Name is required"),
  price_usd: z.coerce.number().min(0, "Must be 0 or more"),
  duration_days: z.coerce.number().int().min(1, "Must be at least 1 day"),
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
    defaultValues: { code: "", name: "", price_usd: 0, duration_days: 30, max_user_swaps: 0, is_active: true },
  });

  useEffect(() => {
    if (open) {
      reset(
        tariff
          ? {
              code: tariff.code,
              name: tariff.name,
              price_usd: tariff.price_usd,
              duration_days: tariff.duration_days,
              max_user_swaps: tariff.max_user_swaps,
              is_active: tariff.is_active,
            }
          : { code: "", name: "", price_usd: 0, duration_days: 30, max_user_swaps: 0, is_active: true },
      );
    }
  }, [open, tariff, reset]);

  async function onSubmit(values: TariffForm) {
    try {
      if (isEdit && tariff) {
        await updateMutation.mutateAsync({ id: tariff.id, body: values });
        toast.success("Tariff updated");
      } else {
        await createMutation.mutateAsync(values);
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
            min={1}
            label={strings.tariffs.durationDays}
            error={errors.duration_days?.message}
            {...register("duration_days")}
          />
        </div>
        <Input
          type="number"
          min={0}
          label={strings.tariffs.maxUserSwaps}
          hint="Max number of times the client can self-service swap their own IP"
          error={errors.max_user_swaps?.message}
          {...register("max_user_swaps")}
        />
        <Checkbox id="tariff-active" label={strings.tariffs.active} {...register("is_active")} />
      </form>
    </Modal>
  );
}
