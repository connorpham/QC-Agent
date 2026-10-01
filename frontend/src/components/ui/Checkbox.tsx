import { useId, type InputHTMLAttributes } from "react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type"> & { label: string };

export function Checkbox({ label, ...input }: Props) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <input id={id} type="checkbox" className="h-4 w-4 accent-brand" {...input} />
      <label htmlFor={id} className="text-sm">
        {label}
      </label>
    </div>
  );
}
