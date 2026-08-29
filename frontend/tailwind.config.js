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
          bg: '#0B0F19',     // Deep space slate
          card: '#161F30',   // Darker card background
          border: '#24334C'  // Slate accent borders
        }
      }
    },
  },
  plugins: [],
}
