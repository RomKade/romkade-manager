/** Prénom de l'assistant IA : « Duke » par défaut, modifiable dans Paramètres > Assistant IA (aucune liste imposée). */
export const DEFAULT_ASSISTANT_NAME = "Duke";

/** Même règle que le serveur : lettres, chiffres, espace, apostrophe, tiret ; 20 caractères au plus. */
export const isValidName = (name: string) => /^[\p{L}\p{N}][\p{L}\p{N} '-]{0,19}$/u.test(name.trim());
