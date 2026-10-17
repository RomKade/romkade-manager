import * as Checkbox from "@radix-ui/react-checkbox";
import * as Popover from "@radix-ui/react-popover";
import * as Select from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";

import { useT } from "../i18n";
import { count } from "../lib/format";

export type Option = { value: string; label: string; count?: number };

/** Filtre à choix multiples dans une fenêtre surgissante. */
export function MultiFilter({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: Option[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const t = useT();
  const toggle = (v: string) => onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  const summary =
    selected.length === 0
      ? label
      : selected.length === 1
        ? options.find((o) => o.value === selected[0])?.label ?? selected[0]
        : `${label} (${selected.length})`;
  return (
    <Popover.Root>
      <Popover.Trigger className={`chip ${selected.length ? "is-on" : ""}`}>
        {summary}
        <ChevronDown size={14} aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="popover" align="start" sideOffset={6}>
          <div className="popover__list" role="group" aria-label={label}>
            {options.length === 0 && <p className="muted">{t("library.filter.none")}</p>}
            {options.map((o) => {
              const id = `f-${label}-${o.value}`;
              return (
                <label key={o.value} htmlFor={id} className="check-row">
                  <Checkbox.Root id={id} className="checkbox" checked={selected.includes(o.value)} onCheckedChange={() => toggle(o.value)}>
                    <Checkbox.Indicator>
                      <Check size={12} strokeWidth={3} aria-hidden />
                    </Checkbox.Indicator>
                  </Checkbox.Root>
                  <span className="check-row__label">{o.label}</span>
                  {o.count != null && <span className="check-row__count num">{count(o.count)}</span>}
                </label>
              );
            })}
          </div>
          {selected.length > 0 && (
            <button type="button" className="link-button popover__reset" onClick={() => onChange([])}>
              {t("library.filter.showAll")}
            </button>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function SelectField({
  label,
  value,
  options,
  onChange,
  placeholder,
}: {
  label: string;
  value: string | undefined;
  options: Option[];
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <Select.Root value={value} onValueChange={onChange}>
      <Select.Trigger className={`chip ${value ? "" : "is-placeholder"}`} aria-label={label}>
        <Select.Value placeholder={placeholder} />
        <Select.Icon>
          <ChevronDown size={14} aria-hidden />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="popover select" position="popper" sideOffset={6}>
          <Select.Viewport>
            {options.map((o) => (
              <Select.Item key={o.value} value={o.value} className="select__item">
                <Select.ItemText>{o.label}</Select.ItemText>
                <Select.ItemIndicator>
                  <Check size={14} aria-hidden />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
