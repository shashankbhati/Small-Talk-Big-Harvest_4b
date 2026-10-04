// The helpline server (ngrok address of the machine running the backend), no trailing slash.
// Set VITE_API_BASE_URL at build time (Vercel project settings, or .env.local) to use another server.
export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ||
  "https://legible-goofiness-zebra.ngrok-free.dev";
export const HELPLINE_NUMBER = "+1 262 762 9483";
export const TEAM_CONTACT = "Small Talk, Big Harvest (shashankbhati@outlook.com)";
