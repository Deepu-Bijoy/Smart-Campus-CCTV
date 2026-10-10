/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          bg: '#F7F9FC',     // Modern light page background
          card: '#FFFFFF',   // Pure white card background
          border: '#E5E7EB'  // Crisp light border
        }
      }
    },
  },
  plugins: [],
}
