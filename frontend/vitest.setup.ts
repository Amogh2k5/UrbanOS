/**
 * Vitest setup.
 *
 * `next/navigation` is mocked so component tests can assert that the KPI
 * insight action does NOT navigate, while the card itself does.
 */
import { vi } from "vitest";

export const mockPush = vi.fn();
export const mockReplace = vi.fn();
export const mockPathname = { value: "/" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => mockPathname.value,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

// jsdom does not implement matchMedia, which some layout code may touch.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}