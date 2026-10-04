export const roundCoord = (n: number) => Math.round(n * 100) / 100;

export const AREA_STEP = 0.5;
export const AREA_MIN = 0.5;
export const AREA_MAX = 100;
export function stepArea(current: number, dir: 1 | -1) {
  const next = Math.round((current + dir * AREA_STEP) * 2) / 2;
  return Math.min(AREA_MAX, Math.max(AREA_MIN, next));
}

export const COUNTRY_CODES = ["+91", "+49"] as const;
export type CountryCode = (typeof COUNTRY_CODES)[number];

/** +91: exactly 10 digits starting 6–9. Other codes: 7 to 14 digits. */
export function isValidPhone(digits: string, code: string = "+91") {
  if (code === "+91") return /^[6-9]\d{9}$/.test(digits);
  return /^\d{7,14}$/.test(digits);
}
export const maxDigits = (code: string) => (code === "+91" ? 10 : 14);
/** Drops the national leading 0 (0151… -> +49151…) so the number matches what the phone network sends. */
export const fullPhone = (code: string, digits: string) => `${code}${digits.replace(/^0+/, "")}`;
export function splitPhone(full: string): { code: CountryCode; digits: string } {
  const code = COUNTRY_CODES.find((c) => full.startsWith(c));
  return code ? { code, digits: full.slice(code.length) } : { code: "+91", digits: full.replace(/\D/g, "") };
}

/** Demo locations in Uttar Pradesh, India. */
export const UP_PLACES = [
  { name: "Kapsaipur, Bulandshahr", lat: 28.51, lon: 78.16 },
  { name: "Bulandshahr", lat: 28.41, lon: 77.85 },
  { name: "Khurja", lat: 28.25, lon: 77.85 },
  { name: "Sikandrabad", lat: 28.45, lon: 77.7 },
  { name: "Aligarh", lat: 27.88, lon: 78.08 },
  { name: "Meerut", lat: 28.98, lon: 77.71 },
] as const;
