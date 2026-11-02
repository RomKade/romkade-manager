/** Version de démonstration (`vite build --mode demo`) : remplacée à la compilation, le code de la démo disparaît
 * de la version normale. */
export const IS_DEMO = import.meta.env.MODE === "demo";
