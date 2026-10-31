import type { MetadataRoute } from "next";

// Permette di aggiungere BluBeauty alla schermata Home dello smartphone come un'app
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "BluBeauty",
    short_name: "BluBeauty",
    description: "Prenota e gestisci i tuoi appuntamenti dal parrucchiere e dall'estetista",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#1E5BD8",
    lang: "it",
    icons: [
      { src: "/brand/blubeauty-icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/brand/blubeauty-icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/brand/blubeauty-icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
