import type { LucideIcon } from "lucide-react";
import { Briefcase, GraduationCap, Hammer, HandCoins, HeartPulse, Landmark, ShieldCheck, Sprout } from "lucide-react";

/** A recognisable icon per scheme category, from its tags. */
export function schemeIcon(tags: string[]): { icon: LucideIcon; tint: string } {
  const has = (...names: string[]) => names.some((n) => tags.includes(n));
  if (has("farmer")) return { icon: Sprout, tint: "bg-emerald-100 text-emerald-700" };
  if (has("scholarship", "education")) return { icon: GraduationCap, tint: "bg-sky-100 text-sky-700" };
  if (has("insurance", "life-cover", "accident-cover")) return { icon: ShieldCheck, tint: "bg-indigo-100 text-indigo-700" };
  if (has("pension")) return { icon: HandCoins, tint: "bg-saffron-100 text-saffron-600" };
  if (has("artisan", "skills")) return { icon: Hammer, tint: "bg-orange-100 text-orange-700" };
  if (has("loan", "business", "msme")) return { icon: Briefcase, tint: "bg-violet-100 text-violet-700" };
  if (has("health")) return { icon: HeartPulse, tint: "bg-rose-100 text-rose-700" };
  return { icon: Landmark, tint: "bg-brand-100 text-brand-700" };
}
