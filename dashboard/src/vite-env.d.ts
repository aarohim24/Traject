/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TRAJECT_API_KEY?: string;
  readonly VITE_TRAJECT_BACKEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
