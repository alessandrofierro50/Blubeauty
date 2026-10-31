// Identità del prodotto in un unico punto: cambiando questi valori cambia tutta l'interfaccia.
export const brand = {
  name: 'BluBeauty',
  tagline: 'Il gestionale semplice per la tua azienda',
  logo: '/logo.svg',
  colors: {
    primary: '#2340a8',
    dark: '#0b2147',
    accent: '#6ec1e4',
    // Palette del sito BluCode Informatica
    primaryDark: '#1a3185',
    text: '#1b2b45',
    muted: '#4a5b75',
    yellow: '#ffc83d',
    background: '#f4f7fa',
    border: '#c8d6e6',
  },
}

// Scala di 10 tonalità per Mantine, dal più chiaro al più scuro (6 = colore principale).
export const bluScale: [string, string, string, string, string, string, string, string, string, string] = [
  '#edf0f8', '#dce0f1', '#b9c2e3', '#91a0d4', '#697dc4', '#445db5', '#2340a8', '#1a3185', '#122966', '#0b2147',
]
