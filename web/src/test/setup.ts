import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Sem test.globals no vite.config.ts, o cleanup automatico do Testing
// Library entre testes nao se registra sozinho -- precisa ser explicito
// aqui, senao um teste ve o DOM deixado pelo teste anterior.
afterEach(() => {
  cleanup();
});
