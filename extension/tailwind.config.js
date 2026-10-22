// YouTube sets html { font-size: 10px }, so rem-based utilities would shrink inside the overlay.
// Spacing, type and radii are therefore defined in px.
const spacing = Object.fromEntries(
  [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 10, 12, 16].map((n) => [n, `${n * 4}px`]),
);

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{ts,tsx,html}", "./options.html"],
  darkMode: ["class", ".vco-dark"],
  corePlugins: { preflight: false },
  theme: {
    extend: {},
    spacing: { px: "1px", ...spacing },
    fontSize: {
      xs: ["11px", "16px"],
      sm: ["12px", "18px"],
      base: ["14px", "20px"],
      lg: ["16px", "22px"],
    },
    borderRadius: { none: "0", sm: "4px", DEFAULT: "6px", md: "8px", lg: "12px", full: "9999px" },
  },
  plugins: [],
};
