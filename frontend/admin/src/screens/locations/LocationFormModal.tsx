import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Checkbox } from "@/shared/components/form/Checkbox";
import { useCreateLocation, useUpdateLocation } from "@/shared/hooks/useLocations";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Location } from "@/shared/api/types";

const locationSchema = z.object({
  city: z.string().min(1, "City is required"),
  state_code: z
    .string()
    .trim()
    .min(2, "Two-letter state code")
    .max(2, "Two-letter state code"),
  sort_order: z.coerce.number().int().min(0, "Must be 0 or more"),
  is_active: z.boolean(),
});

type LocationForm = z.infer<typeof locationSchema>;

interface LocationFormModalProps {
  open: boolean;
  onClose: () => void;
  location: Location | null;
}

export function LocationFormModal({ open, onClose, location }: LocationFormModalProps) {
  const toast = useToast();
  const createMutation = useCreateLocation();
  const updateMutation = useUpdateLocation();
  const isEdit = location !== null;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<LocationForm>({
    resolver: zodResolver(locationSchema),
    defaultValues: { city: "", state_code: "", sort_order: 100, is_active: true },
  });

  useEffect(() => {
    if (!open) return;
    if (location) {
      reset({
        city: location.city,
        state_code: location.state_code,
        sort_order: location.sort_order,
        is_active: location.is_active,
      });
    } else {
      reset({ city: "", state_code: "", sort_order: 100, is_active: true });
    }
  }, [open, location, reset]);

  async function onSubmit(values: LocationForm) {
    const payload = {
      city: values.city,
      state_code: values.state_code.toUpperCase(),
      sort_order: values.sort_order,
      is_active: values.is_active,
    };
    try {
      if (isEdit && location) {
        await updateMutation.mutateAsync({ id: location.id, body: payload });
        toast.success("City updated");
      } else {
        await createMutation.mutateAsync(payload);
        toast.success("City created");
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
      title={isEdit ? strings.locations.edit : strings.locations.create}
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
        <div className="grid grid-cols-[1fr,120px] gap-4">
          <Input label={strings.locations.city} error={errors.city?.message} {...register("city")} />
          <Input
            label={strings.locations.stateCode}
            hint={strings.locations.stateCodeHint}
            error={errors.state_code?.message}
            maxLength={2}
            style={{ textTransform: "uppercase" }}
            {...register("state_code")}
          />
        </div>
        <Input
          type="number"
          min={0}
          label={strings.locations.sortOrder}
          hint={strings.locations.sortOrderHint}
          error={errors.sort_order?.message}
          {...register("sort_order")}
        />
        <Checkbox id="location-active" label={strings.locations.active} {...register("is_active")} />
      </form>
    </Modal>
  );
}
