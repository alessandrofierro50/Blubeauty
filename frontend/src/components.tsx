import { AspectRatio, Badge, Button, Center, Group, Loader, Modal, Paper, Stack, Text, ThemeIcon, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconPlayerPlayFilled } from '@tabler/icons-react'
import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { appApi } from './api'
import { brand } from './brand'

export function Logo({ size = 32, withName = true }: { size?: number; withName?: boolean }) {
  return (
    <Group gap={10} wrap="nowrap">
      <img src={brand.logo} width={size} height={size} alt="" />
      {withName && (
        <Text fw={800} size={size > 36 ? 'xl' : 'lg'} c={`light-dark(${brand.colors.dark}, #FFFFFF)`} style={{ letterSpacing: -0.3, fontFamily: 'Archivo, sans-serif' }}>
          Blu<span style={{ color: `light-dark(${brand.colors.primary}, #7FB2F0)`, fontWeight: 400 }}>Beauty</span>
        </Text>
      )}
    </Group>
  )
}

const STATUS_COLORS: Record<string, string> = {
  prova: 'cyan',
  attivo: 'green',
  in_scadenza: 'yellow',
  tolleranza: 'orange',
  sola_lettura: 'red',
  sospeso: 'gray',
  prova_scaduta: 'gray',
  programmato: 'blue',
}

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <Badge color={STATUS_COLORS[status] ?? 'gray'} variant="light">
      {label}
    </Badge>
  )
}

export function PlanBadge({ code }: { code?: string | null }) {
  if (!code) return <Badge variant="outline" color="gray">—</Badge>
  const color = code === 'SALONE' ? 'blu' : code === 'AGENDA' ? 'teal' : 'gray'
  return <Badge color={color}>{code}</Badge>
}

export function PageTitle({ title, subtitle, right, video }: { title: string; subtitle?: string; right?: ReactNode; video?: HelpVideoKey }) {
  return (
    <Group justify="space-between" align="flex-end" mb="lg" wrap="wrap">
      <Stack gap={2}>
        <Group gap="sm" wrap="wrap">
          <Title order={2}>{title}</Title>
          {video && <VideoButton video={video} />}
        </Group>
        {subtitle && <Text c="dimmed" size="sm">{subtitle}</Text>}
      </Stack>
      {right}
    </Group>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Paper withBorder p="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text fz={28} fw={800} mt={4}>{value}</Text>
      {hint && <Text size="xs" c="dimmed">{hint}</Text>}
    </Paper>
  )
}

export function Loading() {
  return (
    <Center h={200}>
      <Loader />
    </Center>
  )
}

export function notifyError(e: unknown) {
  notifications.show({ color: 'red', title: 'Errore', message: e instanceof Error ? e.message : String(e) })
}

export function notifyOk(message: string) {
  notifications.show({ color: 'green', message })
}


/** Posto nella barra in alto (accanto al pacchetto) dove una pagina può mettere il suo pulsante principale. */
export const HEADER_ACTION_ID = 'header-action'

export function HeaderAction({ children }: { children: ReactNode }) {
  const [el, setEl] = useState<HTMLElement | null>(null)
  useEffect(() => { setEl(document.getElementById(HEADER_ACTION_ID)) }, [])
  return el ? createPortal(children, el) : null
}


// ---------------------------------------------------------------- video di aiuto («Guarda il video»)

/** Le otto schermate della prima serie di video (backend: app/saas/help_videos.py). */
export type HelpVideoKey = 'agenda' | 'scheda_cliente' | 'servizi' | 'cassa' | 'prenotazione_whatsapp' | 'articoli'
  | 'chiusura_conto' | 'buoni_abbonamenti'

type HelpVideos = Record<string, { title: string; url: string | null }>
let videosCache: Promise<HelpVideos> | null = null
function loadVideos(): Promise<HelpVideos> {
  // una sola richiesta per sessione; se fallisce si riprova alla prossima apertura
  videosCache ??= appApi<HelpVideos>('/api/app/video-aiuto').catch((e) => { videosCache = null; throw e })
  return videosCache
}

/** Indirizzo da mettere nella finestra: YouTube e Vimeo come player incorporato, altrimenti file video (.mp4, .webm). */
export function videoEmbed(url: string): { kind: 'iframe' | 'file'; src: string } {
  try {
    const u = new URL(url)
    const host = u.hostname.replace(/^www\.|^m\./, '')
    let yt: string | null = null
    if (host === 'youtu.be') yt = u.pathname.slice(1)
    else if (host.endsWith('youtube.com') || host === 'youtube-nocookie.com') {
      yt = u.searchParams.get('v') ?? u.pathname.match(/^\/(?:embed|shorts|live)\/([^/]+)/)?.[1] ?? null
    }
    if (yt) return { kind: 'iframe', src: `https://www.youtube-nocookie.com/embed/${encodeURIComponent(yt)}?autoplay=1&rel=0` }
    if (host === 'vimeo.com' || host === 'player.vimeo.com') {
      const id = u.pathname.match(/(\d+)/)?.[1]
      if (id) return { kind: 'iframe', src: `https://player.vimeo.com/video/${id}?autoplay=1` }
    }
  } catch { /* indirizzo relativo: file sul server */ }
  return { kind: 'file', src: url }
}

/** Pulsante «Guarda il video»: apre, in una finestra sopra la schermata, il tutorial su come si usa la pagina. */
export function VideoButton({ video, size = 'xs', variant = 'light' }: { video: HelpVideoKey; size?: 'xs' | 'sm' | 'md'; variant?: 'light' | 'white' }) {
  const [open, setOpen] = useState(false)
  const [info, setInfo] = useState<{ title: string; url: string | null } | null | undefined>(undefined)
  useEffect(() => {
    if (!open) return
    loadVideos().then((v) => setInfo(v[video] ?? null)).catch(() => setInfo(null))
  }, [open, video])
  const embed = info?.url ? videoEmbed(info.url) : null
  return (
    <>
      <Button size={size} variant={variant} radius="xl" leftSection={<IconPlayerPlayFilled size={14} />}
        onClick={() => setOpen(true)} aria-label="Guarda il video di questa pagina">
        Guarda il video
      </Button>
      <Modal opened={open} onClose={() => setOpen(false)} size={embed ? "80%" : "md"} centered zIndex={400}
        title={<Text fw={700}>{info?.title ?? 'Video di aiuto'}</Text>}>
        {info === undefined ? <Loading /> : embed ? (
          <AspectRatio ratio={16 / 9}>
            {embed.kind === 'iframe'
              ? <iframe src={embed.src} title={info?.title ?? 'Video'} style={{ border: 0 }}
                  allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowFullScreen />
              : <video src={embed.src} controls autoPlay style={{ background: '#000' }} />}
          </AspectRatio>
        ) : (
          <Stack align="center" gap="sm" py="xl">
            <ThemeIcon size={56} radius="xl" variant="light"><IconPlayerPlayFilled size={28} /></ThemeIcon>
            <Text fw={600}>Il video di questa pagina è in preparazione</Text>
            <Text size="sm" c="dimmed" ta="center" maw={420}>
              Sarà disponibile qui a breve. Nel frattempo, per qualsiasi dubbio, contatta l'assistenza BluCode.
            </Text>
          </Stack>
        )}
      </Modal>
    </>
  )
}
