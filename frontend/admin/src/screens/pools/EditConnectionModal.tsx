import { useEffect, useState } from "react";
import { Modal } from "@/shared/components/Modal";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { useUpdateConnection } from "@/shared/hooks/usePool";
import { useLocations } from "@/shared/hooks/useLocations";
import { useToast } from "@/shared/components/Toast";
import { apiErrorMessage } from "@/shared/api/client";
import { strings } from "@/shared/strings";
import type { Connection } from "@/shared/api/types";

interface EditConnectionModalProps {
  connection: Connection | null;
  onClose: () => void;
}

export function EditConnectionModal({ connection, onClose }: EditConnectionModalProps) {
  const toast = useToast();
  const updateMutation = useUpdateConnection();
  const locationsQuery = useLocations();
  const [tier, setTier] = useState("");
  const [locationId, setLocationId] = useState("");
  const [carrier, setCarrier] = useState("");
  const [healthNote, setHealthNote] = useState("");

  useEffect(() => {
    if (connection) {
      setTier(connection.tier ?? "");
      setLocationId(connection.location_id ?? "");
      setCarrier(connection.carrier ?? "");
      setHealthNote(connection.health_note ?? "");
    }
  }, [connection]);

  async function handleSave() {
    if (!connection) return;
    try {
      await updateMutation.mutateAsync({
        id: connection.id,
        body: { tier, location_id: locationId || null, carrier, health_note: healthNote },
      });
      toast.success("Connection updated");
      onClose();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }

  const locations = locationsQuery.data ?? [];

  return (
    <Modal
      open={connection !== null}
      onClose={onClose}
      title={strings.pools.editConnection}
      subtitle={connection?.external_id}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {strings.common.cancel}
          </Button>
          <Button variant="primary" onClick={handleSave} isLoading={updateMutation.isPending}>
            {strings.common.save}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Input label="Tier" value={tier} onChange={(e) => setTier(e.target.value)} placeholder="e.g. standard, premium" />
        <Select
          label={strings.pools.locationLabel}
          value={locationId}
          onChange={(e) => setLocationId(e.target.value)}
          disabled={locationsQuery.isLoading}
        >
          <option value="">{strings.pools.noLocation}</option>
          {locations.map((loc) => (
            <option key={loc.id} value={loc.id}>
              {loc.city}, {loc.state_code}
              {loc.is_active ? "" : ` (${strings.pools.inactiveLocation})`}
            </option>
          ))}
        </Select>
        <Input label="Carrier" value={carrier} onChange={(e) => setCarrier(e.target.value)} placeholder="T-Mobile, Verizon, AT&T" />
        <Textarea label="Health note" value={healthNote} onChange={(e) => setHealthNote(e.target.value)} placeholder="Operator notes about this device's health…" rows={3} />
      </div>
    </Modal>
  );
}
