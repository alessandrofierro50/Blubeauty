// Etichette: editor dei modelli (trascina gli elementi sull'etichetta) e stampa per articoli o da un documento di carico,
// sulla stampante di etichette (ZPL) oppure su fogli A4 con una stampante normale.

import {
  ActionIcon, Alert, Badge, Button, Group, Modal, NumberInput, Paper, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Text,
  TextInput,
} from '@mantine/core'
import { IconBarcode, IconCopy, IconLetterT, IconPlus, IconPrinter, IconQrcode, IconSquare, IconTrash } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { appApi } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { LabelEl, LabelView, PER, SAMPLE_FIELDS, Template } from './LabelView'

const FIELD_OPTS = (fields: Record<string, string>) => Object.entries(fields).map(([value, label]) => ({ value, label }))

export function LabelTemplates() {
  const [rows, setRows] = useState<Template[] | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [cur, setCur] = useState<Template | null>(null)
  const [sel, setSel] = useState<number | null>(null)
  const load = (keep?: string) => PER('/etichette/modelli').then((r) => { setRows(r); setCur(r.find((t: any) => t.id === keep) ?? r[0] ?? null) }).catch(notifyError)
  useEffect(() => { load(); PER('/etichette/campi').then((r) => setFields(r.fields)).catch(() => {}) }, [])
  if (!rows) return <Loading />
  const el = cur && sel !== null ? cur.elements[sel] : null
  const setTpl = (patch: Partial<Template>) => setCur((c) => (c ? { ...c, ...patch } : c))
  const setEl = (patch: Partial<LabelEl>) => setCur((c) => (c && sel !== null ? { ...c, elements: c.elements.map((e, i) => (i === sel ? { ...e, ...patch } : e)) } : c))
  const add = (e: LabelEl) => { if (!cur) return; setCur({ ...cur, elements: [...cur.elements, e] }); setSel(cur.elements.length) }
  async function save() {
    if (!cur) return
    try {
      const body = { name: cur.name, width_mm: cur.width_mm, height_mm: cur.height_mm, dpi: cur.dpi, gap_mm: cur.gap_mm, elements: cur.elements, is_default: !!cur.is_default }
      const r = await (cur.id ? PER(`/etichette/modelli/${cur.id}`, { method: 'PUT', body }) : PER('/etichette/modelli', { body }))
      notifyOk('Modello salvato'); load(r.id)
    } catch (e) { notifyError(e) }
  }
  async function remove() {
    if (!cur?.id || !window.confirm(`Eliminare il modello «${cur.name}»?`)) return
    try { await PER(`/etichette/modelli/${cur.id}`, { method: 'DELETE' }); load() } catch (e) { notifyError(e) }
  }
  const scale = cur ? Math.min(6, 520 / cur.width_mm / 3.78, 420 / cur.height_mm / 3.78) : 1
  return (
    <>
      <PageTitle title="Modelli di etichette" subtitle="Disegna le etichette per prezzi, scaffali e capi: trascina gli elementi e scegli cosa stampare" />
      <Group align="flex-start" wrap="nowrap" gap="md">
        <Paper withBorder w={220} p="xs">
          <Stack gap={4}>
            {rows.map((t) => (
              <Button key={t.id} variant={cur?.id === t.id ? 'light' : 'subtle'} justify="space-between" onClick={() => { setCur(t); setSel(null) }}
                rightSection={t.is_default ? <Badge size="xs">predefinito</Badge> : null}>{t.name}</Button>
            ))}
            <Button variant="default" leftSection={<IconPlus size={16} />} onClick={() => { setCur({ name: 'Nuovo modello', width_mm: 50, height_mm: 30, dpi: 203, gap_mm: 3, elements: [] }); setSel(null) }}>Nuovo modello</Button>
          </Stack>
        </Paper>
        {cur && (
          <Stack style={{ flex: 1 }}>
            <Paper withBorder p="sm">
              <Group align="flex-end">
                <TextInput label="Nome" value={cur.name} onChange={(e) => setTpl({ name: e.currentTarget.value })} w={200} />
                <NumberInput label="Larghezza (mm)" value={cur.width_mm} onChange={(v) => setTpl({ width_mm: Number(v) || 10 })} min={10} max={200} w={120} />
                <NumberInput label="Altezza (mm)" value={cur.height_mm} onChange={(v) => setTpl({ height_mm: Number(v) || 10 })} min={10} max={200} w={120} />
                <Select label="Risoluzione" data={[{ value: '203', label: '203 dpi' }, { value: '300', label: '300 dpi' }]} value={String(cur.dpi)} onChange={(v) => setTpl({ dpi: Number(v) })} w={110} />
                <Switch label="Predefinito" checked={!!cur.is_default} onChange={(e) => setTpl({ is_default: e.currentTarget.checked })} mb={8} />
              </Group>
            </Paper>
            <Group align="flex-start" wrap="nowrap">
              <Paper withBorder p="md" style={{ flex: 1, background: 'var(--mantine-color-gray-1)', minHeight: 460 }}>
                <Group gap={6} mb="sm">
                  <Button size="xs" variant="light" leftSection={<IconLetterT size={14} />} onClick={() => add({ type: 'text', field: 'description', x: 2, y: 2, w: cur.width_mm - 4, size: 3, lines: 1, align: 'left' })}>Testo</Button>
                  <Button size="xs" variant="light" leftSection={<IconBarcode size={14} />} onClick={() => add({ type: 'barcode', field: 'barcode', x: 2, y: Math.max(0, cur.height_mm - 12), h: 8, module: 2, text: 'si' as any })}>Codice a barre</Button>
                  <Button size="xs" variant="light" leftSection={<IconQrcode size={14} />} onClick={() => add({ type: 'qr', field: 'code', x: 2, y: 2, size: 3 })}>QR</Button>
                  <Button size="xs" variant="light" leftSection={<IconSquare size={14} />} onClick={() => add({ type: 'box', x: 0.5, y: 0.5, w: cur.width_mm - 1, h: cur.height_mm - 1, thickness: 0.3 })}>Riquadro</Button>
                </Group>
                <div style={{ width: `${cur.width_mm * scale}mm`, height: `${cur.height_mm * scale}mm`, margin: '20px auto' }}>
                  <LabelView tpl={cur} fields={SAMPLE_FIELDS} selected={sel} onSelect={setSel} scale={scale}
                    onMove={(i, x, y) => setCur((c) => (c ? { ...c, elements: c.elements.map((e, n) => (n === i ? { ...e, x: x / 1, y: y / 1 } : e)) } : c))} />
                </div>
                <Text size="xs" c="dimmed" ta="center">Anteprima con dati di esempio · trascina gli elementi per spostarli</Text>
              </Paper>
              <Paper withBorder p="sm" w={280}>
                {!el ? <Text size="sm" c="dimmed">Seleziona un elemento sull'etichetta per modificarlo, oppure aggiungine uno.</Text> : (
                  <Stack gap="xs">
                    <Group justify="space-between"><Text fw={600}>{{ text: 'Testo', barcode: 'Codice a barre', qr: 'QR', box: 'Riquadro' }[el.type]}</Text>
                      <Group gap={2}>
                        <ActionIcon variant="subtle" onClick={() => add({ ...el, x: el.x + 2, y: el.y + 2 })}><IconCopy size={16} /></ActionIcon>
                        <ActionIcon variant="subtle" color="red" onClick={() => { setCur({ ...cur, elements: cur.elements.filter((_, i) => i !== sel) }); setSel(null) }}><IconTrash size={16} /></ActionIcon>
                      </Group>
                    </Group>
                    {el.type !== 'box' && <Select label="Contenuto" data={FIELD_OPTS(fields)} value={el.field} onChange={(v) => setEl({ field: v ?? 'description' })} allowDeselect={false} />}
                    {el.field === 'custom' && <TextInput label="Testo" value={el.text ?? ''} onChange={(e) => setEl({ text: e.currentTarget.value })} />}
                    {el.type === 'text' && el.field !== 'custom' && <TextInput label="Prefisso" placeholder="es. Cod. " value={el.prefix ?? ''} onChange={(e) => setEl({ prefix: e.currentTarget.value })} />}
                    <SimpleGrid cols={2} spacing="xs">
                      <NumberInput label="X (mm)" value={el.x} step={0.5} decimalScale={1} onChange={(v) => setEl({ x: Number(v) || 0 })} />
                      <NumberInput label="Y (mm)" value={el.y} step={0.5} decimalScale={1} onChange={(v) => setEl({ y: Number(v) || 0 })} />
                      {(el.type === 'text' || el.type === 'box') && <NumberInput label="Larghezza" value={el.w ?? 10} step={0.5} decimalScale={1} onChange={(v) => setEl({ w: Number(v) || 1 })} />}
                      {(el.type === 'barcode' || el.type === 'box') && <NumberInput label="Altezza" value={el.h ?? 8} step={0.5} decimalScale={1} onChange={(v) => setEl({ h: Number(v) || 1 })} />}
                      {el.type === 'text' && <NumberInput label="Carattere (mm)" value={el.size ?? 3} step={0.5} decimalScale={1} min={1} onChange={(v) => setEl({ size: Number(v) || 3 })} />}
                      {el.type === 'text' && <NumberInput label="Righe" value={el.lines ?? 1} min={1} max={5} onChange={(v) => setEl({ lines: Number(v) || 1 })} />}
                      {el.type === 'qr' && <NumberInput label="Grandezza" value={el.size ?? 3} min={1} max={10} onChange={(v) => setEl({ size: Number(v) || 3 })} />}
                      {el.type === 'barcode' && <NumberInput label="Spessore barre" value={el.module ?? 2} min={1} max={5} onChange={(v) => setEl({ module: Number(v) || 2 })} />}
                      {el.type === 'box' && <NumberInput label="Spessore (mm)" value={el.thickness ?? 0.3} step={0.1} decimalScale={1} onChange={(v) => setEl({ thickness: Number(v) || 0.3 })} />}
                    </SimpleGrid>
                    {el.type === 'text' && (
                      <>
                        <SegmentedControl size="xs" value={el.align ?? 'left'} onChange={(v) => setEl({ align: v as any })} data={[{ value: 'left', label: 'Sinistra' }, { value: 'center', label: 'Centro' }, { value: 'right', label: 'Destra' }]} />
                        <Switch label="Grassetto" checked={!!el.bold} onChange={(e) => setEl({ bold: e.currentTarget.checked })} />
                      </>
                    )}
                    {el.type === 'barcode' && <Switch label="Numeri sotto il codice" checked={el.text !== undefined ? !!el.text : true} onChange={(e) => setEl({ text: e.currentTarget.checked ? 'si' : '' })} />}
                  </Stack>
                )}
              </Paper>
            </Group>
            <Group justify="space-between">
              {cur.id ? <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} onClick={remove}>Elimina modello</Button> : <span />}
              <Button onClick={save}>Salva modello</Button>
            </Group>
          </Stack>
        )}
      </Group>
    </>
  )
}

// ====================================================================== stampa

export function PrintLabels() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [tpls, setTpls] = useState<Template[] | null>(null)
  const [tplId, setTplId] = useState<string | null>(null)
  const [printers, setPrinters] = useState<any[]>([])
  const [lists, setLists] = useState<any[]>([])
  const [listId, setListId] = useState<string | null>(null)
  const [rows, setRows] = useState<{ item_id: string; variant_id?: string | null; quantity: number; label?: string }[]>([])
  const [data, setData] = useState<any[]>([])
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  const savedTarget = (() => { try { return localStorage.getItem('blubeauty_label_target') } catch { return null } })()
  const [target, setTargetState] = useState<string>(savedTarget ?? 'a4')
  const setTarget = (v: string) => { setTargetState(v); try { localStorage.setItem('blubeauty_label_target', v) } catch { /* memoria non disponibile */ } }
  const [roll, setRoll] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sheet, setSheet] = useState(false)
  useEffect(() => {
    PER('/etichette/modelli').then((r) => { setTpls(r); setTplId(r[0]?.id ?? null) }).catch(notifyError)
    PER('/dispositivi?kind=etichette').then((d) => {
      const act = d.filter((x: any) => x.active)
      setPrinters(act)
      // la scelta resta quella dell'ultima volta; se era una stampante che non c'è più si torna ai fogli A4
      if (savedTarget && !['a4', 'termica'].includes(savedTarget) && !act.some((x: any) => x.id === savedTarget)) setTarget(act[0]?.id ?? 'a4')
      if (!savedTarget && act.length) setTarget(act[0].id)
    }).catch(() => {})
    appApi('/api/anagrafiche/tabelle/listini').then((l) => { setLists(l); setListId(l.find((x: any) => x.is_default)?.id ?? null) }).catch(() => {})
    const doc = params.get('doc')
    if (doc) PER(`/etichette/da-documento/${doc}`).then(setRows).catch(notifyError)
  }, [])
  useEffect(() => {
    if (q.trim().length < 2) { setFound([]); return }
    const t = setTimeout(() => appApi(`/api/anagrafiche/articoli?q=${encodeURIComponent(q)}&page_size=12`).then((r) => setFound(r.rows)).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => {
    const rs = rows.filter((r) => r.quantity > 0)
    if (!rs.length) { setData([]); return }
    PER('/etichette/dati', { body: { rows: rs, price_list_id: listId } }).then((d: any[]) => {
      // articoli a taglie e colori: una riga per variante, così si sceglie quante etichette per ognuna
      const toExpand = rows.filter((r) => !r.variant_id && d.some((x) => x.item_id === r.item_id && x.variant_id))
      if (toExpand.length) {
        setRows(rows.flatMap((r) => (toExpand.includes(r) ? d.filter((x) => x.item_id === r.item_id && x.variant_id)
          .map((x) => ({ item_id: x.item_id, variant_id: x.variant_id, quantity: r.quantity })) : [r])))
        return
      }
      setData(d)
    }).catch(notifyError)
  }, [rows, listId])
  const tpl = tpls?.find((t) => t.id === tplId)
  const total = rows.reduce((a, r) => a + (r.quantity || 0), 0)
  const labels = useMemo(() => data.flatMap((d) => Array.from({ length: Math.min(d.quantity, 500) }, () => d.fields)), [data])
  async function printZpl() {
    setBusy(true)
    try {
      const r = await PER('/etichette/stampa', { body: { rows: rows.filter((x) => x.quantity > 0), price_list_id: listId, template_id: tplId, device_id: target } })
      notifyOk(`${r.labels} etichette inviate alla stampante`)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  if (!tpls) return <Loading />
  return (
    <>
      <PageTitle title="Stampa etichette" subtitle="Prezzi e codici a barre per scaffali, capi e merce appena arrivata"
        right={<Button variant="subtle" onClick={() => nav('/etichette-modelli')}>Modelli di etichette</Button>} />
      <Group align="flex-start" wrap="nowrap">
        <Stack style={{ flex: 1 }}>
          <Paper withBorder p="sm">
            <Select placeholder="Cerca un articolo da aggiungere" searchable searchValue={q} onSearchChange={setQ} value={null}
              data={found.map((i) => ({ value: i.id, label: `${i.code} · ${i.description}` }))} nothingFoundMessage={q.length >= 2 ? 'Nessun articolo' : 'Scrivi almeno 2 caratteri'}
              onChange={(v) => { const f = found.find((x) => x.id === v); if (f) setRows((r) => [...r, { item_id: f.id, quantity: 1, label: `${f.code} · ${f.description}` }]); setQ('') }} />
          </Paper>
          <Paper withBorder>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th>Prezzo</Table.Th><Table.Th w={110}>Etichette</Table.Th><Table.Th w={40} /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r, i) => {
                  const d = data.find((x) => x.item_id === r.item_id && (x.variant_id ?? null) === (r.variant_id ?? null))
                  return (
                    <Table.Tr key={i}>
                      <Table.Td><Text size="sm">{d ? `${d.fields.code} · ${d.fields.description}` : r.label ?? '…'}</Text>{d?.fields.variant && <Text size="xs" c="dimmed">{d.fields.variant}</Text>}</Table.Td>
                      <Table.Td>{d?.fields.price || <Text span size="xs" c="dimmed">senza prezzo</Text>}</Table.Td>
                      <Table.Td><NumberInput size="xs" min={0} max={999} value={r.quantity} onChange={(v) => setRows(rows.map((x, n) => (n === i ? { ...x, quantity: Number(v) || 0 } : x)))} /></Table.Td>
                      <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => setRows(rows.filter((_, n) => n !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>
                    </Table.Tr>
                  )
                })}
                {!rows.length && <Table.Tr><Table.Td colSpan={4}><Text c="dimmed" ta="center" py="lg">Aggiungi gli articoli o apri questa pagina da un DDT o una fattura del fornitore</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
        </Stack>
        <Paper withBorder p="md" w={360}>
          <Stack>
            <Select label="Modello" data={tpls.map((t) => ({ value: t.id!, label: `${t.name} (${t.width_mm}×${t.height_mm} mm)` }))} value={tplId} onChange={setTplId} allowDeselect={false} />
            <Select label="Listino" data={lists.map((l) => ({ value: l.id, label: l.name }))} value={listId} onChange={setListId} />
            <Select label="Stampa su" value={target} onChange={(v) => setTarget(v ?? 'a4')} allowDeselect={false}
              data={[
                ...(printers.length ? [{ group: 'Stampanti di etichette collegate (ZPL)', items: printers.map((p) => ({ value: p.id, label: `${p.name}${p.agent_online ? '' : ' (computer spento)'}` })) }] : []),
                { group: 'Da questo computer', items: [{ value: 'termica', label: 'Stampante termica di etichette (rotolo)' }, { value: 'a4', label: 'Fogli A4 (stampante normale)' }] },
              ]} />
            <Text size="xs" c="dimmed">{target === 'a4' ? 'Le etichette vengono affiancate su fogli A4 da ritagliare o adesivi.'
              : target === 'termica' ? `Una etichetta per pagina da ${tpl?.width_mm ?? '…'}×${tpl?.height_mm ?? '…'} mm: va bene qualsiasi stampante di etichette installata su questo computer (Zebra, Dymo, Brother…).`
                : 'Stampa diretta in ZPL tramite BluBeauty Agent: la più veloce e precisa.'}</Text>
            {tpl && data[0] && <div style={{ display: 'flex', justifyContent: 'center' }}><LabelView tpl={tpl} fields={data[0].fields} /></div>}
            <Button leftSection={<IconPrinter size={16} />} disabled={!total || !tpl} loading={busy} onClick={() => (target === 'a4' ? setSheet(true) : target === 'termica' ? setRoll(true) : printZpl())}>
              Stampa {total} etichette
            </Button>
            {!printers.length && <Alert color="gray" variant="light">Per le stampanti di etichette (Zebra e compatibili) collega il computer in «Computer e periferiche».</Alert>}
          </Stack>
        </Paper>
      </Group>
      {sheet && tpl && <SheetPrint tpl={tpl} labels={labels} onClose={() => setSheet(false)} />}
      {roll && tpl && <RollPrint tpl={tpl} labels={labels} onClose={() => setRoll(false)} />}
    </>
  )
}

function SheetPrint({ tpl, labels, onClose }: { tpl: Template; labels: Record<string, string>[]; onClose: () => void }) {
  const [margin, setMargin] = useState(8)
  const [gap, setGap] = useState(2)
  const [cut, setCut] = useState(true)
  const sheetStyle = { display: 'flex', flexWrap: 'wrap' as const, gap: `${gap}mm`, width: `${210 - 2 * margin}mm`, background: 'white' }
  return (
    <Modal opened onClose={onClose} title={`Fogli A4 · ${labels.length} etichette`} size="auto">
      <PrintOnly id="label-sheet-print" page={`A4; margin: ${margin}mm`}>
        <div style={sheetStyle}>{labels.map((f, i) => <LabelView key={i} tpl={tpl} fields={f} border={cut} />)}</div>
      </PrintOnly>
      <Group mb="sm" align="flex-end">
        <NumberInput label="Margine (mm)" w={120} value={margin} onChange={(v) => setMargin(Number(v) || 0)} />
        <NumberInput label="Spazio fra etichette (mm)" w={170} value={gap} onChange={(v) => setGap(Number(v) || 0)} />
        <Switch label="Bordo per ritagliare" checked={cut} onChange={(e) => setCut(e.currentTarget.checked)} mb={8} />
        <Button leftSection={<IconPrinter size={16} />} onClick={() => window.print()}>Stampa</Button>
      </Group>
      <ScrollArea h="70vh" style={{ background: 'var(--mantine-color-gray-1)' }}>
        <div style={{ ...sheetStyle, margin: '0 auto' }}>
          {labels.map((f, i) => <LabelView key={i} tpl={tpl} fields={f} border={cut} />)}
        </div>
      </ScrollArea>
    </Modal>
  )
}

function RollPrint({ tpl, labels, onClose }: { tpl: Template; labels: Record<string, string>[]; onClose: () => void }) {
  // una pagina per etichetta, grande quanto l'etichetta: la stampante termica stampa sul rotolo senza sprechi
  return (
    <Modal opened onClose={onClose} title={`Stampante termica · ${labels.length} etichette`} size="lg">
      <PrintOnly id="label-roll-print" page={`${tpl.width_mm}mm ${tpl.height_mm}mm; margin: 0`}>
        {labels.map((f, i) => <div key={i} style={{ breakAfter: 'page', pageBreakAfter: 'always', overflow: 'hidden', width: `${tpl.width_mm}mm`, height: `${tpl.height_mm}mm` }}><LabelView tpl={tpl} fields={f} border={false} /></div>)}
      </PrintOnly>
      <Alert color="blue" variant="light" mb="sm">
        Nella finestra di stampa scegli la stampante di etichette, formato carta {tpl.width_mm}×{tpl.height_mm} mm (o quello del rotolo caricato),
        margini «nessuno» e scala 100%. La prima volta conviene provare con una sola etichetta.
      </Alert>
      <Group justify="flex-end" mb="sm"><Button leftSection={<IconPrinter size={16} />} onClick={() => window.print()}>Stampa</Button></Group>
      <ScrollArea h="55vh" style={{ background: 'var(--mantine-color-gray-1)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
          {labels.map((f, i) => <div key={i} style={{ marginBottom: 4 }}><LabelView tpl={tpl} fields={f} border={false} /></div>)}
        </div>
      </ScrollArea>
    </Modal>
  )
}

// Copia da stampare messa direttamente nel body: a video non si vede, in stampa resta solo lei (niente tagli dovuti a finestre e scorrimenti).
function PrintOnly({ id, page, children }: { id: string; page: string; children: React.ReactNode }) {
  const css = `#${id} { display: none } @media print { @page { size: ${page} } body > *:not(#${id}) { display: none !important } #${id} { display: block } html, body { margin: 0; padding: 0; background: white } }`
  return createPortal(<div id={id}><style>{css}</style>{children}</div>, document.body)
}
