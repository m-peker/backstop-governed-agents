// Flat config. Next 16 removed `next lint`, so ESLint is invoked directly and the
// shared Next rule sets are composed here.

import coreWebVitals from 'eslint-config-next/core-web-vitals'
import typescript from 'eslint-config-next/typescript'

const config = [
  {
    ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts'],
  },
  ...coreWebVitals,
  ...typescript,
]

export default config
