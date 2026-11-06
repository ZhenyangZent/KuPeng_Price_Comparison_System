export function formatTwd(value: number | null): string {
  return value === null ? "價格未知" : `NT$ ${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(value)}`;
}

export function formatUtc(value: string | null): string {
  if (value === null) return "尚無觀測";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "時間格式無效";
  return `${new Intl.DateTimeFormat("zh-TW", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(parsed)} UTC`;
}
