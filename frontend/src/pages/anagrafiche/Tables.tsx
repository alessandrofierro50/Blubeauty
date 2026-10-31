import { ActionIcon, Badge, Button, Checkbox, Group, Modal, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Table, Tabs, TagsInput, Text, TextInput } from '@mantine/core'
import { IconPencil, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { A, categoryOptions, invalidateLookups } from './shared'

type Col = { key: string; label: string; type?: 'text' | 'number' | 'bool' | 'select' | 'tags' | 'installments'; options?: { value: string; label: string }[]; width?: number }

const METHODS = [
  { value: 'MP01', label: 'MP01 Contanti' }, { value: 'MP02', label: 'MP02 Assegno' }, { value: 'MP05', label: 'MP05 Bonifico' },
  { value: 'MP08', label: 'MP08 Carta di pagamento' }, { value: 'MP12', label: 'MP12 RIBA' }, { value: 'MP19', label: 'MP19 SEPA Direct Debit' },
  { value: 'MP23', label: 'MP23 PagoPA' },
]
const NATURES = ['N1', 'N2.1', 'N2.2', 'N3.1', 'N3.2', 'N3.3', 'N3.4', 'N3.5', 'N3.6', 'N4', 'N5', 'N6.1', 'N6.2', 'N6.3', 'N6.4', 'N6.5', 'N6.6', 'N6.7', 'N6.8', 'N6.9', 'N7']

const DEFS: Record<string, { title: string; cols: Col[] }> = {
  'aliquote-iva': { title: 'Aliquote IVA', cols: [
    { key: 'code', label: 'Codice', width: 90 }, { key: 'description', label: 'Descrizione' }, { key: 'rate', label: 'Aliquota %', type: 'number', width: 100 },
    { key: 'nature', label: 'Natura', type: 'select', options: NATURES.map((n) => ({ value: n, label: n })), width: 100 },
    { key: 'legal_reference', label: 'Riferimento normativo' }, { key: 'active', label: 'Attiva', type: 'bool' }] },
  pagamenti: { title: 'Pagamenti', cols: [
    { key: 'code', label: 'Codice', width: 90 }, { key: 'description', label: 'Descrizione' },
    { key: 'method', label: 'Modalità', type: 'select', options: METHODS, width: 200 },
    { key: 'installments', label: 'Rate (giorni)', type: 'installments' }, { key: 'end_of_month', label: 'Fine mese', type: 'bool' },
    { key: 'active', label: 'Attivo', type: 'bool' }] },
  'unita-misura': { title: 'Unità di misura', cols: [
    { key: 'code', label: 'Codice', width: 90 }, { key: 'description', label: 'Descrizione' }, { key: 'decimals', label: 'Decimali', type: 'number', width: 90 }] },
  categorie: { title: 'Categorie', cols: [{ key: 'name', label: 'Nome' }, { key: 'parent_id', label: 'Categoria padre', type: 'select' }] },
  marche: { title: 'Marche', cols: [{ key: 'name', label: 'Nome' }] },
  'categorie-clienti': { title: 'Categorie clienti', cols: [{ key: 'name', label: 'Nome' }] },
  listini: { title: 'Listini', cols: [
    { key: 'code', label: 'Codice', width: 110 }, { key: 'name', label: 'Nome' }, { key: 'vat_included', label: 'IVA inclusa', type: 'bool' },
    { key: 'markup_percent', label: 'Ricarico standard %', type: 'number', width: 140 }, { key: 'is_default', label: 'Predefinito', type: 'bool' }] },
  'campi-personalizzati': { title: 'Campi personalizzati', cols: [
    { key: 'entity', label: 'Anagrafica', type: 'select', options: [{ value: 'item', label: 'Articoli' }, { value: 'party', label: 'Clienti e fornitori' }], width: 160 },
    { key: 'label', label: 'Etichetta' }, { key: 'key', label: 'Chiave', width: 140 },
    { key: 'field_type', label: 'Tipo', type: 'select', options: [{ value: 'text', label: 'Testo' }, { value: 'number', label: 'Numero' }, { value: 'date', label: 'Data' }, { value: 'list', label: 'Elenco' }, { value: 'bool', label: 'Sì/No' }], width: 120 },
    { key: 'options', label: 'Valori (per elenco)', type: 'tags' }, { key: 'sort_order', label: 'Ordine', type: 'number', width: 80 }] },
}

export default function Tables() {
  return (
    <>
      <PageTitle title="Tabelle e impostazioni" subtitle="Aliquote, pagamenti, unità di misura, categorie, listini e campi" />
      <Tabs defaultValue="campi" keepMounted={false}>
        <Tabs.List mb="md" style={{ flexWrap: 'wrap' }}>
          <Tabs.Tab value="campi">Campi articolo</Tabs.Tab>
          {Object.entries(DEFS).map(([k, d]) => <Tabs.Tab key={k} value={k}>{d.title}</Tabs.Tab>)}
        </Tabs.List>
        <Tabs.Panel value="campi"><FieldGroups /></Tabs.Panel>
        {Object.keys(DEFS).map((k) => <Tabs.Panel key={k} value={k}><TableEditor kind={k} /></Tabs.Panel>)}
      </Tabs>
    </>
  )
}

const GROUP_LABELS: Record<string, [string, string]> = {
  varianti: ['Varianti (taglie, colori, formati)', 'Abbigliamento, calzature, accessori'],
  lotti: ['Lotti e scadenze', 'Alimentare, farmaceutico, cosmetico'],
  matricole: ['Matricole e garanzia', 'Elettronica, elettroutensili, macchinari'],
  dimensioni: ['Pesi e dimensioni', 'Spedizioni, logistica'],
  intrastat: ['Dati Intrastat', 'Acquisti e vendite con l\'estero'],
  distinta_base: ['Distinta base e kit', 'Confezioni regalo, kit, assemblaggi'],
}

function FieldGroups() {
  const [g, setG] = useState<Record<string, boolean> | null>(null)
  useEffect(() => { A('/settings').then((s) => setG(s.field_groups)).catch(notifyError) }, [])
  if (!g) return <Loading />
  async function save() {
    try {
      await A('/settings/field-groups', { method: 'PUT', body: { field_groups: g } })
      invalidateLookups()
      notifyOk('Impostazioni salvate')
    } catch (e) { notifyError(e) }
  }
  return (
    <Paper withBorder p="md" maw={640}>
      <Text size="sm" c="dimmed" mb="md">Mostra nella scheda articolo solo i campi che servono alla tua attività. Puoi cambiarli quando vuoi: i dati non vengono persi.</Text>
      <Stack>
        {Object.entries(GROUP_LABELS).map(([k, [label, hint]]) => (
          <Switch key={k} label={label} description={hint} checked={!!g[k]} onChange={(e) => setG({ ...g, [k]: e.currentTarget.checked })} />
        ))}
      </Stack>
      <Group justify="flex-end" mt="md"><Button onClick={save}>Salva</Button></Group>
    </Paper>
  )
}

function TableEditor({ kind }: { kind: string }) {
  const def = DEFS[kind]
  const [rows, setRows] = useState<any[] | null>(null)
  const [edit, setEdit] = useState<any>(null)
  const load = () => A(`/tabelle/${kind}`).then(setRows).catch(notifyError)
  useEffect(() => { load() }, [kind])
  if (!rows) return <Loading />

  const parentOpts = kind === 'categorie' ? categoryOptions(rows.filter((r) => !r.parent_id)) : []
  const display = (c: Col, r: any) => {
    const v = r[c.key]
    if (c.type === 'bool') return v ? <Badge size="sm" variant="light" color="green">sì</Badge> : <Text size="sm" c="dimmed">—</Text>
    if (c.type === 'installments') return (v ?? []).map((x: any) => `${x.days}gg${x.percent !== 100 ? ` (${x.percent}%)` : ''}`).join(' · ')
    if (c.type === 'tags') return (v ?? []).join(', ')
    if (c.key === 'parent_id') return rows.find((x) => x.id === v)?.name ?? '—'
    if (c.type === 'select') return c.options?.find((o) => o.value === v)?.label ?? v ?? '—'
    return v ?? '—'
  }

  async function save() {
    try {
      const body = { ...edit }
      if (body.installments && typeof body.installments === 'string') body.installments = parseInstallments(body.installments)
      if (edit.id) await A(`/tabelle/${kind}/${edit.id}`, { method: 'PUT', body })
      else await A(`/tabelle/${kind}`, { body })
      invalidateLookups()
      notifyOk('Salvato')
      setEdit(null)
      load()
    } catch (e) { notifyError(e) }
  }

  async function remove(r: any) {
    if (!confirm('Eliminare questo elemento?')) return
    try { await A(`/tabelle/${kind}/${r.id}`, { method: 'DELETE' }); invalidateLookups(); load() } catch (e) { notifyError(e) }
  }

  const blank = Object.fromEntries(def.cols.map((c) => [c.key, c.type === 'bool' ? (c.key === 'active') : c.type === 'tags' ? [] : c.type === 'installments' ? '30' : '']))
  return (
    <Paper withBorder>
      <Group justify="space-between" p="sm"><Text fw={600}>{def.title}</Text>
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEdit(blank)}>Nuovo</Button></Group>
      <Table.ScrollContainer minWidth={600}>
        <Table highlightOnHover>
          <Table.Thead><Table.Tr>{def.cols.map((c) => <Table.Th key={c.key}>{c.label}</Table.Th>)}<Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.id}>
                {def.cols.map((c) => <Table.Td key={c.key} fz="sm">{display(c, r)}</Table.Td>)}
                <Table.Td>
                  <Group gap={2} justify="flex-end" wrap="nowrap">
                    <ActionIcon variant="subtle" onClick={() => setEdit({ ...r, installments: r.installments ? formatInstallments(r.installments) : undefined })}><IconPencil size={16} /></ActionIcon>
                    <ActionIcon variant="subtle" color="red" onClick={() => remove(r)}><IconTrash size={16} /></ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Modal opened={!!edit} onClose={() => setEdit(null)} title={edit?.id ? 'Modifica' : 'Nuovo'}>
        {edit && (
          <Stack>
            <SimpleGrid cols={1}>
              {def.cols.map((c) => {
                const v = edit[c.key]
                const on = (x: any) => setEdit({ ...edit, [c.key]: x })
                if (c.type === 'bool') return <Checkbox key={c.key} label={c.label} checked={!!v} onChange={(e) => on(e.currentTarget.checked)} />
                if (c.type === 'number') return <NumberInput key={c.key} label={c.label} value={v === null ? '' : v} onChange={on} decimalScale={2} />
                if (c.type === 'tags') return <TagsInput key={c.key} label={c.label} value={v ?? []} onChange={on} />
                if (c.type === 'installments') return <TextInput key={c.key} label={c.label} description="Giorni separati da trattino, es. 30-60-90 (rate uguali)" value={v ?? ''} onChange={(e) => on(e.currentTarget.value)} />
                if (c.type === 'select') return <Select key={c.key} label={c.label} data={c.key === 'parent_id' ? parentOpts.filter((o) => o.value !== edit.id) : c.options ?? []} value={v || null} onChange={on} clearable />
                return <TextInput key={c.key} label={c.label} value={v ?? ''} onChange={(e) => on(e.currentTarget.value)} />
              })}
            </SimpleGrid>
            <Group justify="flex-end"><Button variant="default" onClick={() => setEdit(null)}>Annulla</Button><Button onClick={save}>Salva</Button></Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  )
}

function formatInstallments(list: any[]) {
  return list.map((x) => x.days).join('-')
}

function parseInstallments(text: string) {
  const days = text.split(/[-,;\s]+/).filter(Boolean).map(Number).filter((n) => !isNaN(n))
  if (!days.length) return [{ days: 0, percent: 100 }]
  const base = Math.floor((100 / days.length) * 100) / 100
  return days.map((d, i) => ({ days: d, percent: i === days.length - 1 ? Math.round((100 - base * (days.length - 1)) * 100) / 100 : base }))
}
