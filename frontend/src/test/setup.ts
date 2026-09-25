import "@testing-library/jest-dom/vitest";

// `crypto.randomUUID` n'existe pas dans toutes les versions de jsdom utilisées en CI.
if (!globalThis.crypto?.randomUUID) {
  Object.defineProperty(globalThis.crypto ?? (globalThis.crypto = {} as Crypto), "randomUUID", {
    value: () => "00000000-0000-4000-8000-000000000000",
    configurable: true,
  });
}
