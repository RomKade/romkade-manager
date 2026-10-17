/** Drapeau de chaque région du catalogue (libellés du serveur, classify.REGION_TAGS). */
const FLAGS: Record<string, string> = {
  USA: "🇺🇸", Europe: "🇪🇺", Japon: "🇯🇵", Monde: "🌍", France: "🇫🇷", Allemagne: "🇩🇪", Espagne: "🇪🇸",
  Italie: "🇮🇹", Corée: "🇰🇷", Brésil: "🇧🇷", Asie: "🌏", Australie: "🇦🇺", Chine: "🇨🇳",
};

export const regionFlag = (region: string): string => FLAGS[region] ?? "🏳️";
