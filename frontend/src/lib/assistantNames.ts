/**
 * Prénoms proposés pour l'assistant IA (Paramètres > Assistant IA), chacun avec son petit portrait de joueur
 * (textes : assistant.persona.<clé>). « Duke » par défaut ; un autre prénom libre est aussi accepté.
 */
export const DEFAULT_ASSISTANT_NAME = "Duke";

export const PERSONAS = [
  { name: "Duke", key: "duke" },
  { name: "Axel", key: "axel" },
  { name: "Nova", key: "nova" },
  { name: "Max", key: "max" },
  { name: "Luna", key: "luna" },
  { name: "Rex", key: "rex" },
  { name: "Kenji", key: "kenji" },
  { name: "Zoé", key: "zoe" },
  { name: "Sam", key: "sam" },
  { name: "Iris", key: "iris" },
] as const;

/** Même règle que le serveur : lettres, espace, apostrophe, tiret ; 20 caractères au plus. */
export const isValidName = (name: string) => /^[\p{L}\p{N}][\p{L}\p{N} '-]{0,19}$/u.test(name.trim());
