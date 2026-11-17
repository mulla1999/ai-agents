/** Indian mobile number input with a fixed +91 prefix. */
export function PhoneInput({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="flex rounded-xl shadow-sm focus-within:ring-4 focus-within:ring-brand-100">
      <span className="inline-flex items-center rounded-l-xl border border-r-0 border-stone-200 bg-stone-50 px-3 text-sm font-semibold text-stone-600">
        +91
      </span>
      <input
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        required
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="98765 43210"
        className="w-full rounded-r-xl border border-stone-200 bg-white px-3.5 py-3 text-base tracking-wide focus:border-brand-500 focus:outline-none disabled:bg-stone-50"
      />
    </div>
  );
}
