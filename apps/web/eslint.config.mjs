import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescriptConfig from "eslint-config-next/typescript";

// eslint-config-next v16 ships flat-config arrays directly.
const eslintConfig = [
  ...coreWebVitals,
  ...typescriptConfig,
  {
    ignores: ["node_modules/**", ".next/**", "out/**", "next-env.d.ts", "coverage/**"],
  },
];

export default eslintConfig;
