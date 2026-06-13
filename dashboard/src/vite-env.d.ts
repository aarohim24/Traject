/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AXON_API_KEY?: string;
  readonly VITE_AXON_BACKEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
