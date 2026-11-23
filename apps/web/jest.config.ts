import type { Config } from "jest";

// Jest unit-test harness for the web app (ts-jest transform, jsdom env).
// Harness dependencies (jest, ts-jest, jsdom env, testing-library) are
// pinned in package.json and documented in docs/DECISIONS.md as test
// plumbing, not product dependencies.
const config: Config = {
  testEnvironment: "jsdom",
  moduleFileExtensions: ["ts", "tsx", "js", "jsx"],
  transform: {
    "^.+\\.(t|j)sx?$": [
      "ts-jest",
      {
        tsconfig: {
          module: "commonjs",
          moduleResolution: "node",
          jsx: "react-jsx",
          esModuleInterop: true,
          target: "ES2022",
          strict: true,
        },
      },
    ],
  },
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testMatch: ["<rootDir>/src/tests/**/*.test.ts", "<rootDir>/src/tests/**/*.test.tsx"],
  clearMocks: true,
};

export default config;
