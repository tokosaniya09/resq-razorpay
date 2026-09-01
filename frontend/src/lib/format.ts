// Formatting helpers. Money is stored as paise (integer) end-to-end.

export const rupees = (paise: number): string =>
  "₹" + (paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 });

export const pct = (x: number): string => (x * 100).toFixed(0) + "%";

export const shortId = (id: string): string =>
  id.length > 12 ? id.slice(0, 10) + "…" : id;

export const clock = (iso: string): string =>
  new Date(iso).toLocaleTimeString("en-IN", { hour12: false });
