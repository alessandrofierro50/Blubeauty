import { Box, Group, Paper, Stack, Text } from '@mantine/core'

import { KIND_LABEL, type Msg } from './lib'

const STATUS_TICKS: Record<string, string> = { inviato: '✓', consegnato: '✓✓', letto: '✓✓', simulato: '✓✓ simulato', errore: '⚠ errore', in_coda: '…' }

/** Conversazione WhatsApp nella sagoma di uno smartphone. */
export function WhatsAppChat({ title, messages, height = 380, empty = 'Nessun messaggio' }: { title: string; messages: Pick<Msg, 'id' | 'body' | 'created_at' | 'inbound' | 'status' | 'kind'>[]; height?: number; empty?: string }) {
  return (
    <Paper radius={32} p={10} bg="#0f172a" maw={320} mx="auto" w="100%" shadow="md">
      <Box style={{ borderRadius: 24, overflow: 'hidden', background: '#efeae2' }}>
        <Group gap={8} px={12} py={10} bg="#075e54" c="white" wrap="nowrap">
          <Box w={30} h={30} bg="white" style={{ borderRadius: '50%', display: 'grid', placeItems: 'center' }}>
            <img src="/logo.svg" width={22} height={22} alt="" />
          </Box>
          <div style={{ lineHeight: 1.15 }}>
            <Text size="sm" fw={600}>{title}</Text>
            <Text size="10px" c="rgba(255,255,255,.75)">Account aziendale</Text>
          </div>
        </Group>
        <Stack gap={8} p={10} h={height} justify="flex-end" style={{ overflowY: 'auto' }}>
          {messages.length === 0 && <Text size="xs" c="dimmed" ta="center">{empty}</Text>}
          {messages.map((m) => (
            <Box key={m.id} maw="86%" px={10} py={6} style={{
              alignSelf: m.inbound ? 'flex-end' : 'flex-start', background: m.inbound ? '#d9fdd3' : '#fff', borderRadius: 10,
              boxShadow: '0 1px 1px rgba(0,0,0,.12)', whiteSpace: 'pre-line', fontSize: 13, lineHeight: 1.38, color: '#111', wordBreak: 'break-word',
            }}>
              {m.body.split(/(https?:\/\/\S+)/g).map((part, i) => /^https?:\/\//.test(part)
                ? <a key={i} href={part} target="_blank" rel="noreferrer" style={{ color: '#027eb5' }}>{part}</a> : part)}
              <Text size="10px" c="#8696a0" ta="right" mt={2}>
                {!m.inbound && KIND_LABEL[m.kind] ? `${KIND_LABEL[m.kind]} · ` : ''}
                {new Date(m.created_at).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                {!m.inbound && <span style={{ color: m.status === 'letto' ? '#53bdeb' : m.status === 'errore' ? '#e03131' : undefined }}> {STATUS_TICKS[m.status] ?? ''}</span>}
              </Text>
            </Box>
          ))}
        </Stack>
      </Box>
    </Paper>
  )
}
