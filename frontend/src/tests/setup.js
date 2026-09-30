/**
 * Vitest global test setup.
 * Runs before every test file.
 */
import '@testing-library/jest-dom';

// Make import.meta.env available in tests
// Vite/Vitest automatically handles this in the jsdom environment.
// Set defaults so tests don't need real environment variables.
if (!globalThis.import?.meta?.env) {
  // In Vitest with jsdom this is handled automatically.
  // If a test needs a specific env value, use vi.stubEnv().
}
