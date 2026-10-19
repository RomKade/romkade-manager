/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Clé du projet PostHog (phc_…) : statistiques anonymes, proposées seulement si elle est fournie au build. */
  readonly VITE_POSTHOG_KEY?: string;
  readonly VITE_POSTHOG_HOST?: string;
}
