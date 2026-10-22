import * as Popover from "@radix-ui/react-popover";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Smartphone } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import { useT } from "../i18n";
import { onPhone } from "../lib/phone";
import { errorMessage } from "./ui";

/** Barre du haut : QR code pour ouvrir le Manager sur le téléphone, par le Wi-Fi de la maison. Pas sur le téléphone. */
export function PhoneButton() {
  const t = useT();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const pair = useMutation({ mutationFn: api.phonePair });
  const status = useQuery({ queryKey: ["phone"], queryFn: api.phone, enabled: open, refetchInterval: open ? 3000 : false });
  const disconnect = useMutation({
    mutationFn: api.phoneDisconnect,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["phone"] }); pair.mutate(); },
  });
  if (onPhone()) return null;
  const devices = status.data?.devices ?? pair.data?.devices ?? 0;
  return (
    <Popover.Root open={open} onOpenChange={(o) => { setOpen(o); if (o) pair.mutate(); }}>
      <Popover.Trigger className="lang-switch phone-switch" aria-label={t("common.phone.open")} title={t("common.phone.open")}>
        <Smartphone size={17} aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="popover phone-pop" align="end" sideOffset={6}>
          <p className="phone-pop__title">{t("common.phone.open")}</p>
          {pair.isError ? <p className="text-error">{errorMessage(pair.error)}</p>
            : !pair.data ? <p className="phone-pop__hint" role="status">{t("common.phone.loading")}</p>
            : (
              <>
                <img className="phone-pop__qr" src={pair.data.qr} alt={pair.data.url} width={200} height={200} />
                <p className="phone-pop__hint">{t("common.phone.scan")} {t("common.phone.wifi")}</p>
                <p className="phone-pop__fine">{t("common.phone.expires", { min: Math.round(pair.data.expires_in / 60) })}</p>
              </>
            )}
          {devices > 0 && (
            <p className="phone-pop__devices">
              <span>{t("common.phone.devices", { count: devices })}</span>
              <button type="button" className="phone-pop__out" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
                {t("common.phone.disconnect")}
              </button>
            </p>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
