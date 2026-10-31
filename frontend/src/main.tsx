import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import '@mantine/dates/styles.css'
import '@mantine/dropzone/styles.css'
import '@mantine/charts/styles.css'
import 'dayjs/locale/it'
// Caratteri del brand BluCode (comune/brand.md): Archivo per i titoli, Source Sans 3 per il testo
import '@fontsource/archivo/700.css'
import '@fontsource/archivo/800.css'
import '@fontsource/source-sans-3/400.css'
import '@fontsource/source-sans-3/600.css'
import '@fontsource/source-sans-3/700.css'

import { createTheme, MantineProvider } from '@mantine/core'
import { DatesProvider } from '@mantine/dates'
import { Notifications } from '@mantine/notifications'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import { bluScale } from './brand'

const theme = createTheme({
  primaryColor: 'blu',
  colors: { blu: bluScale },
  fontFamily: "'Source Sans 3', system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  defaultRadius: 'md',
  headings: { fontWeight: '700', fontFamily: "Archivo, 'Source Sans 3', system-ui, sans-serif" },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <DatesProvider settings={{ locale: 'it', firstDayOfWeek: 1 }}>
        <Notifications position="top-right" />
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </DatesProvider>
    </MantineProvider>
  </React.StrictMode>,
)
