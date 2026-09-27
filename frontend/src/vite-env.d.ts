/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Override the API base URL. Defaults to `/api` via the dev proxy. */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
