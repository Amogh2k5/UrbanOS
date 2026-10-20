const SG_TIME_ZONE = "Asia/Singapore";

function dateParts(value: Date | string | number, options: Intl.DateTimeFormatOptions) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-SG", { timeZone: SG_TIME_ZONE, ...options })
    .formatToParts(date)
    .reduce<Record<string, string>>((parts, part) => {
      if (part.type !== "literal") parts[part.type] = part.value;
      return parts;
    }, {});
}

export function formatSingaporeTime(value: Date | string | number): string {
  const p = dateParts(value, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return p ? `${p.hour}:${p.minute}` : "—";
}

export function formatSingaporeDateTime(value: Date | string | number): string {
  const p = dateParts(value, {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  return p ? `${p.day} ${p.month} ${p.year}, ${p.hour}:${p.minute}` : "—";
}

export function formatSingaporeDate(value: Date | string | number): string {
  const p = dateParts(value, { day: "2-digit", month: "short", year: "numeric" });
  return p ? `${p.day} ${p.month} ${p.year}` : "—";
}

export function formatSingaporeClock(value: Date): string {
  const p = dateParts(value, {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  return p ? `${p.hour}:${p.minute}:${p.second} | ${p.day} ${p.month} ${p.year}` : "—";
}
