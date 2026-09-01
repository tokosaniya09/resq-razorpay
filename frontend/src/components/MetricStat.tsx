export function MetricStat({
  label,
  value,
  accent = "text-fg",
  sub,
}: {
  label: string;
  value: string;
  accent?: string;
  sub?: string;
}) {
  return (
    <div className="rounded-md border border-line bg-ink-700 p-3">
      <div className="text-[11px] uppercase tracking-wide text-fg-muted">
        {label}
      </div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${accent}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-fg-faint">{sub}</div>}
    </div>
  );
}
