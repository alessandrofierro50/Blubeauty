// Impostazioni › Documenti di vendita: numerazioni (prossimo numero modificabile), sezionali e imposta di bollo.

import { ActionIcon, Alert, Button, Group, NumberInput, Paper, Radio, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { ApiError } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { S } from './shared'

const KEYS: [string, string][] = [['FT', 'Fatture e note di credito'], ['DDT', 'DDT'], ['PRV', 'Preventivi'], ['ORC', 'Ordini cliente']]

export default function SalesSettings() {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(thisYear)
  const [cfg, setCfg] = useState<any>(null)
  const [next, setNext] = useState<Record<string, number | string>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ color: string; text: string } | null>(null)
  const load = () => S(`/impostazioni?anno=${year}`).then((r) => { setCfg(r); setNext({}) }).catch(notifyError)
  useEffect(() => { load() }, [year])
  if (!cfg) return <><PageTitle title="Documenti di vendita" /><Loading /></>

  const setSeries = (k: string, list: any[]) => setCfg({ ...cfg, series: { ...cfg.series, [k]: list } })
  const fmtOf = (k: string, sc: string) => cfg.formats?.[k]?.[sc] ?? ''
  const setFmt = (k: string, sc: string, v: string) => setCfg({ ...cfg, formats: { ...cfg.formats, [k]: { ...(cfg.formats?.[k] ?? {}), [sc]: v } } })
  const sample = (f: string, sc: string) => f.split('{n}').join('3').split('{s}').join(sc).split('{aaaa}').join(String(thisYear)).split('{aa}').join(String(thisYear % 100).padStart(2, '0'))
  const FmtInput = ({ k, sc }: { k: string; sc: string }) => (
    <TextInput size="xs" w={130} placeholder={sc ? '{n}/{s}' : '{n}'} value={fmtOf(k, sc)} onChange={(e) => setFmt(k, sc, e.currentTarget.value)}
      title={fmtOf(k, sc) ? `Es. ${sample(fmtOf(k, sc), sc)}` : ''} />
  )
  async function save() {
    setBusy(true)
    try {
      const r = await S('/impostazioni', { method: 'PUT', body: { bollo_mode: cfg.bollo_mode, series: cfg.series, formats: cfg.formats, default_series: cfg.default_series } })
      setCfg({ ...cfg, ...r }); notifyOk('Impostazioni salvate'); load()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function saveCounter(c: any) {
    const id = `${c.key}|${c.series}`
    const value = Number(next[id])
    if (!value) return
    setMsg(null)
    try {
      const r = await S('/numerazioni', { method: 'PUT', body: { key: c.key, year: c.year, series: c.series, next_number: value } })
      setCfg({ ...cfg, counters: r.counters }); setNext({ ...next, [id]: '' })
      setMsg({ color: 'teal', text: `${c.label}${c.series ? ' sezionale ' + c.series : ''} ${c.year}: il prossimo numero sarà ${value}.${r.notes.length ? ' ' + r.notes.join('; ') + '.' : ''}` })
    } catch (e) {
      if (e instanceof ApiError && e.code === 'numeri_usati') setMsg({ color: 'red', text: e.message })
      else notifyError(e)
    }
  }

  return (
    <>
      <PageTitle title="Documenti di vendita" subtitle="Numerazioni, sezionali e imposta di bollo" />
      <Stack maw={900}>
        <Paper withBorder p="md">
          <Group justify="space-between" mb="xs">
            <Title order={5}>Numerazioni</Title>
            <Select w={110} data={[thisYear + 1, thisYear, thisYear - 1, thisYear - 2].map(String)} value={String(year)} onChange={(v) => setYear(Number(v))} allowDeselect={false} />
          </Group>
          <Text size="sm" c="dimmed" mb="sm">Il numero si assegna quando emetti il documento. Puoi cambiare il prossimo numero, per esempio per ripartire da 1 dopo
            le prove (prima annulla i documenti di prova) o per continuare la numerazione delle fatture fatte con un altro programma.
            Fatture immediate, differite e note di credito hanno un'unica numerazione per sezionale.</Text>
          {msg && <Alert color={msg.color} mb="sm" withCloseButton onClose={() => setMsg(null)}>{msg.text}</Alert>}
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Documenti</Table.Th><Table.Th>Sezionale</Table.Th><Table.Th ta="right">Emessi</Table.Th><Table.Th ta="right">Ultimo numero</Table.Th><Table.Th w={220}>Prossimo numero</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {cfg.counters.map((c: any) => {
                const id = `${c.key}|${c.series}`
                return (
                  <Table.Tr key={id}>
                    <Table.Td>{c.label}</Table.Td>
                    <Table.Td>{c.series || <Text span c="dimmed" size="sm">principale</Text>}</Table.Td>
                    <Table.Td ta="right">{c.documents}</Table.Td>
                    <Table.Td ta="right">{c.last_number || '—'}</Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <NumberInput size="xs" w={110} min={1} allowDecimal={false} placeholder={String(c.next_number)} value={next[id] ?? ''} onChange={(v) => setNext({ ...next, [id]: v })} />
                        <Button size="xs" variant="light" disabled={!next[id] || Number(next[id]) === c.next_number} onClick={() => saveCounter(c)}>Imposta</Button>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Paper>

        <Paper withBorder p="md">
          <Title order={5} mb={4}>Sezionali</Title>
          <Text size="sm" c="dimmed" mb="sm">Numerazioni separate, per esempio per punto vendita o attività (numero stampato come 12/A/{thisYear}).
            Il sezionale «principale» c'è sempre; quello predefinito si propone sui nuovi documenti e si può cambiare sul singolo documento.
            Nell'ultima colonna puoi dare un formato al numero (stampa e XML): {'{n}'} numero, {'{s}'} sezionale, {'{aa}'} o {'{aaaa}'} anno.
            Per esempio «FPR {'{n}'}/{'{aa}'}» diventa FPR 3/{String(thisYear % 100).padStart(2, '0')}, come nel portale Aruba.</Text>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            {KEYS.map(([k, label]) => {
              const list: any[] = cfg.series[k] ?? []
              return (
                <Paper key={k} withBorder p="sm">
                  <Text fw={600} size="sm" mb="xs">{label}</Text>
                  <Stack gap={6}>
                    <Group gap={6} wrap="nowrap">
                      <Text size="xs" w={80} c="dimmed">principale</Text>
                      <Text size="xs" c="dimmed" style={{ flex: 1 }}>{fmtOf(k, '') ? `es. ${sample(fmtOf(k, ''), '')}` : 'numero semplice (es. 3)'}</Text>
                      {FmtInput({ k, sc: '' })}
                    </Group>
                    {list.map((x, i) => (
                      <Group key={i} gap={6} wrap="nowrap">
                        <TextInput size="xs" w={80} placeholder="A" value={x.code} maxLength={10} onChange={(e) => setSeries(k, list.map((y, j) => (j === i ? { ...y, code: e.currentTarget.value.toUpperCase().replace(/[^A-Z0-9]/g, '') } : y)))} />
                        <TextInput size="xs" style={{ flex: 1 }} placeholder="Descrizione (es. Negozio di Lecce)" value={x.description} onChange={(e) => setSeries(k, list.map((y, j) => (j === i ? { ...y, description: e.currentTarget.value } : y)))} />
                        {FmtInput({ k, sc: x.code })}
                        <ActionIcon variant="subtle" color="red" onClick={() => setSeries(k, list.filter((_, j) => j !== i))}><IconTrash size={14} /></ActionIcon>
                      </Group>
                    ))}
                    <Group justify="space-between">
                      <Button size="compact-xs" variant="subtle" leftSection={<IconPlus size={12} />} onClick={() => setSeries(k, [...list, { code: '', description: '' }])}>Aggiungi sezionale</Button>
                      {list.length > 0 && <Select size="xs" w={170} label="Predefinito" data={[{ value: '_', label: 'Principale' }, ...list.filter((x) => x.code).map((x) => ({ value: x.code, label: x.code }))]}
                        value={cfg.default_series[k] || '_'} onChange={(v) => setCfg({ ...cfg, default_series: { ...cfg.default_series, [k]: v === '_' ? '' : v } })} allowDeselect={false} />}
                    </Group>
                  </Stack>
                </Paper>
              )
            })}
          </SimpleGrid>
        </Paper>

        <Paper withBorder p="md">
          <Title order={5} mb={4}>Imposta di bollo</Title>
          <Text size="sm" c="dimmed" mb="sm">Sulle fatture e note di credito con importi senza IVA (esenti, escluse, non imponibili, regime forfettario…) oltre 77,47 €
            si applica il bollo virtuale da 2,00 € (DatiBollo nell'XML). Non si applica a esportazioni, cessioni intracomunitarie (N3.1–N3.4) e reverse charge (N6).</Text>
          <Radio.Group value={cfg.bollo_mode} onChange={(v) => setCfg({ ...cfg, bollo_mode: v })}>
            <Stack gap={6}>
              <Radio value="cliente" label="Calcolo automatico, addebitato al cliente (2,00 € aggiunti al totale da pagare)" />
              <Radio value="azienda" label="Calcolo automatico, a carico dell'azienda (indicato in fattura, il totale non cambia)" />
              <Radio value="no" label="Non calcolare" />
            </Stack>
          </Radio.Group>
        </Paper>
        <Group justify="flex-end"><Button onClick={save} loading={busy}>Salva sezionali e bollo</Button></Group>
      </Stack>
    </>
  )
}
