import { ActionIcon, Anchor, Badge, Button, Checkbox, Grid, Group, Paper, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Text, Textarea, TextInput, Title, Tooltip } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconArrowLeft, IconDownload, IconEyeOff, IconPlus, IconPrinter, IconTrash, IconX } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { brand } from '../../brand'
import { PrintFooter, PrintHeader } from '../app/CompanySettings'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { A, downloadCsv, opts, useItemSearch, useLookups } from './shared'

export function CatalogsList() {
  const nav = useNavigate()
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { A('/cataloghi').then(setRows).catch(notifyError) }, [])
  return (
    <>
      <PageTitle title="Cataloghi e listini" subtitle="Scegli categorie e articoli, poi stampa o esporta"
        right={<Button leftSection={<IconPlus size={16} />} onClick={() => nav('/cataloghi/nuovo')}>Nuovo catalogo</Button>} />
      {!rows ? <Loading /> : rows.length === 0 ? (
        <Paper withBorder p="xl"><Stack align="center" gap="xs"><Text c="dimmed">Non hai ancora creato cataloghi.</Text>
          <Button variant="light" onClick={() => nav('/cataloghi/nuovo')}>Crea il primo</Button></Stack></Paper>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          {rows.map((c) => (
            <Paper key={c.id} withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => nav(`/cataloghi/${c.id}`)}>
              <Group justify="space-between"><Text fw={700}>{c.name}</Text><Badge variant="light">{c.layout === 'griglia' ? 'catalogo' : 'listino'}</Badge></Group>
              <Text size="sm" c="dimmed" mt={4}>{c.category_ids.length} categorie · {c.include_item_ids.length} articoli aggiunti{c.exclude_item_ids.length ? ` · ${c.exclude_item_ids.length} esclusi` : ''}</Text>
              {c.valid_until && <Text size="xs" c="dimmed" mt={4}>Valido fino al {fmtDate(c.valid_until)}</Text>}
            </Paper>
          ))}
        </SimpleGrid>
      )}
    </>
  )
}

const EMPTY = {
  name: '', title: '', layout: 'griglia', price_list_id: null, party_id: null, show_prices: true, vat_included: true,
  show_codes: true, group_by_category: true, category_ids: [] as string[], include_item_ids: [] as string[],
  exclude_item_ids: [] as string[], valid_until: '', notes: '',
}

export function CatalogEditor() {
  const { id } = useParams()
  const isNew = id === 'nuovo'
  const nav = useNavigate()
  const L = useLookups()
  const search = useItemSearch()
  const [c, setC] = useState<any>(isNew ? EMPTY : null)
  const [customers, setCustomers] = useState<any[]>([])
  const [preview, setPreview] = useState<any>(null)
  const [names, setNames] = useState<Record<string, string>>({})
  const [dc] = useDebouncedValue(c, 400)

  useEffect(() => {
    A('/soggetti?tipo=clienti&page_size=200').then((r) => setCustomers(r.rows)).catch(() => {})
    if (!isNew) A(`/cataloghi/${id}`).then((r) => setC({ ...r, valid_until: r.valid_until ?? '', title: r.title ?? '', notes: r.notes ?? '' })).catch(notifyError)
  }, [id])

  useEffect(() => {
    if (!dc) return
    A('/cataloghi/anteprima', { body: body(dc) }).then((p) => {
      setPreview(p)
      const n: Record<string, string> = {}
      p.groups.forEach((g: any) => g.items.forEach((i: any) => { n[i.id] = i.description }))
      setNames((old) => ({ ...old, ...n }))
    }).catch(() => {})
  }, [dc])

  if (!c || !L) return <Loading />
  const set = (k: string, v: any) => setC({ ...c, [k]: v })

  function body(x: any) {
    return { ...x, name: x.name || 'Senza nome', title: x.title || null, notes: x.notes || null, valid_until: x.valid_until || null }
  }

  async function save() {
    if (!c.name) return notifyError(new Error('Dai un nome al catalogo'))
    try {
      const { id: _id, updated_at: _u, ...rest } = c
      const r = isNew ? await A('/cataloghi', { body: body(rest) }) : await A(`/cataloghi/${id}`, { method: 'PUT', body: body(rest) })
      notifyOk('Catalogo salvato')
      if (isNew) nav(`/cataloghi/${r.id}`, { replace: true })
      return r.id
    } catch (e) { notifyError(e) }
  }

  async function print() {
    const cid = isNew ? await save() : (await save(), id)
    if (cid) window.open(`/stampa/catalogo/${cid}`, '_blank')
  }

  async function remove() {
    if (!confirm('Eliminare il catalogo?')) return
    try { await A(`/cataloghi/${id}`, { method: 'DELETE' }); nav('/cataloghi') } catch (e) { notifyError(e) }
  }

  const toggleCat = (cid: string, on: boolean) => set('category_ids', on ? [...c.category_ids, cid] : c.category_ids.filter((x: string) => x !== cid))
  const roots = L.categories.filter((x) => !x.parent_id)
  const children = (pid: string) => L.categories.filter((x) => x.parent_id === pid)

  return (
    <>
      <Anchor size="sm" onClick={() => nav('/cataloghi')}><Group gap={4}><IconArrowLeft size={14} />Cataloghi e listini</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <Title order={2}>{isNew ? 'Nuovo catalogo' : c.name}</Title>
        <Group>
          {!isNew && <ActionIcon variant="subtle" color="red" size="lg" onClick={remove}><IconTrash size={18} /></ActionIcon>}
          {!isNew && <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => downloadCsv(`/cataloghi/${id}/export.csv`, `${c.name}.csv`)}>Excel</Button>}
          <Button variant="default" leftSection={<IconPrinter size={16} />} onClick={print}>Stampa / PDF</Button>
          <Button onClick={save}>Salva</Button>
        </Group>
      </Group>

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, md: 5, lg: 4 }}>
          <Stack>
            <Paper withBorder p="md">
              <Stack gap="sm">
                <TextInput label="Nome" placeholder="es. Listino rivenditori 2027" value={c.name} onChange={(e) => set('name', e.currentTarget.value)} />
                <TextInput label="Titolo in stampa" placeholder="uguale al nome" value={c.title} onChange={(e) => set('title', e.currentTarget.value)} />
                <SegmentedControl value={c.layout} onChange={(v) => set('layout', v)} data={[{ value: 'griglia', label: 'Catalogo con foto' }, { value: 'elenco', label: 'Listino a elenco' }]} />
                <Switch label="Mostra i prezzi" checked={c.show_prices} onChange={(e) => set('show_prices', e.currentTarget.checked)} />
                {c.show_prices && (
                  <>
                    <Select label="Prezzi di un cliente" description="Con i suoi prezzi netti, sconti e promozioni" data={opts(customers, (x) => x.name)}
                      value={c.party_id} onChange={(v) => setC({ ...c, party_id: v, price_list_id: v ? null : c.price_list_id })} clearable searchable />
                    {!c.party_id && <Select label="Oppure un listino" data={opts(L.lists, (l) => `${l.code} — ${l.name}`)} value={c.price_list_id} onChange={(v) => set('price_list_id', v)} clearable placeholder="predefinito" />}
                    <Switch label="Prezzi IVA inclusa" checked={c.vat_included} onChange={(e) => set('vat_included', e.currentTarget.checked)} />
                  </>
                )}
                <Switch label="Mostra i codici articolo" checked={c.show_codes} onChange={(e) => set('show_codes', e.currentTarget.checked)} />
                <Switch label="Raggruppa per categoria" checked={c.group_by_category} onChange={(e) => set('group_by_category', e.currentTarget.checked)} />
                <TextInput type="date" label="Valido fino al" value={c.valid_until} onChange={(e) => set('valid_until', e.currentTarget.value)} />
                <Textarea label="Note in fondo" autosize value={c.notes} onChange={(e) => set('notes', e.currentTarget.value)} />
              </Stack>
            </Paper>

            <Paper withBorder p="md">
              <Text fw={600} mb="xs">Categorie incluse</Text>
              <ScrollArea.Autosize mah={300}>
                <Stack gap={6}>
                  {roots.map((r) => (
                    <div key={r.id}>
                      <Checkbox label={r.name} checked={c.category_ids.includes(r.id)} onChange={(e) => toggleCat(r.id, e.currentTarget.checked)} />
                      {children(r.id).map((ch) => (
                        <Checkbox key={ch.id} ml={28} mt={4} size="sm" label={ch.name}
                          checked={c.category_ids.includes(ch.id) || c.category_ids.includes(r.id)} disabled={c.category_ids.includes(r.id)}
                          onChange={(e) => toggleCat(ch.id, e.currentTarget.checked)} />
                      ))}
                    </div>
                  ))}
                  {roots.length === 0 && <Text size="sm" c="dimmed">Nessuna categoria: aggiungi gli articoli uno per uno.</Text>}
                </Stack>
              </ScrollArea.Autosize>
            </Paper>

            <Paper withBorder p="md">
              <Text fw={600} mb="xs">Articoli aggiunti singolarmente</Text>
              <Select placeholder="Cerca per nome o codice" searchable searchValue={search.q} onSearchChange={search.setQ} data={search.options} value={null}
                nothingFoundMessage={search.q.length >= 2 ? 'Nessun articolo' : 'Scrivi almeno 2 caratteri'}
                onChange={(v) => {
                  const f = search.found.find((x) => x.id === v)
                  if (f) { setNames({ ...names, [f.id]: f.description }); setC({ ...c, include_item_ids: [...new Set([...c.include_item_ids, f.id])], exclude_item_ids: c.exclude_item_ids.filter((x: string) => x !== f.id) }) }
                  search.setQ('')
                }} />
              <Group gap={6} mt="sm">
                {c.include_item_ids.map((iid: string) => (
                  <Badge key={iid} variant="light" rightSection={<IconX size={12} style={{ cursor: 'pointer' }} onClick={() => set('include_item_ids', c.include_item_ids.filter((x: string) => x !== iid))} />}>{names[iid] ?? '…'}</Badge>
                ))}
              </Group>
              {c.exclude_item_ids.length > 0 && (
                <>
                  <Text fw={600} mt="md" mb="xs" size="sm">Esclusi</Text>
                  <Group gap={6}>
                    {c.exclude_item_ids.map((iid: string) => (
                      <Badge key={iid} color="gray" variant="outline" rightSection={<IconX size={12} style={{ cursor: 'pointer' }} onClick={() => set('exclude_item_ids', c.exclude_item_ids.filter((x: string) => x !== iid))} />}>{names[iid] ?? '…'}</Badge>
                    ))}
                  </Group>
                </>
              )}
            </Paper>
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 7, lg: 8 }}>
          <Paper withBorder p="md" pos="sticky" top={76}>
            <Group justify="space-between" mb="sm"><Text fw={600}>Anteprima</Text><Text size="sm" c="dimmed">{preview?.items_count ?? 0} articoli</Text></Group>
            {!preview ? <Loading /> : preview.items_count === 0 ? (
              <Text c="dimmed" ta="center" py="xl">Seleziona almeno una categoria o un articolo.</Text>
            ) : (
              <ScrollArea.Autosize mah="70vh">
                {preview.groups.map((g: any) => (
                  <div key={g.name}>
                    {g.name && <Text fw={700} c="blu.7" mt="sm" mb={4}>{g.name}</Text>}
                    <Table verticalSpacing={4}>
                      <Table.Tbody>
                        {g.items.map((i: any) => (
                          <Table.Tr key={i.id}>
                            <Table.Td w={44}>{i.thumb_url ? <img src={i.thumb_url} alt="" style={{ width: 36, height: 36, objectFit: 'cover', borderRadius: 6 }} /> : <div style={{ width: 36, height: 36, borderRadius: 6, background: 'var(--mantine-color-gray-1)' }} />}</Table.Td>
                            <Table.Td><Text size="sm">{c.show_codes && <Text span ff="monospace" size="xs" c="dimmed">{i.code} </Text>}{i.description}</Text></Table.Td>
                            <Table.Td ta="right" fw={600}>{c.show_prices && i.price != null ? fmtEuro(i.price) : ''}{i.promo && <Badge size="xs" color="red" ml={6}>promo</Badge>}</Table.Td>
                            <Table.Td w={36}>
                              <Tooltip label="Escludi dal catalogo">
                                <ActionIcon variant="subtle" color="gray" onClick={() => setC({ ...c, exclude_item_ids: [...c.exclude_item_ids, i.id], include_item_ids: c.include_item_ids.filter((x: string) => x !== i.id) })}><IconEyeOff size={16} /></ActionIcon>
                              </Tooltip>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </div>
                ))}
              </ScrollArea.Autosize>
            )}
          </Paper>
        </Grid.Col>
      </Grid>
    </>
  )
}

/** Pagina di stampa pulita (fuori dal layout dell'app): Stampa → Salva come PDF. */
export function CatalogPrint() {
  const { id } = useParams()
  const [d, setD] = useState<any>(null)
  const [company, setCompany] = useState<any>(null)
  useEffect(() => {
    A(`/cataloghi/${id}/contenuto`).then(setD).catch(notifyError)
    appApi('/api/app/intestazione').then(setCompany).catch(() => {})
  }, [id])
  useEffect(() => {
    if (d) { document.title = d.catalog.title || d.catalog.name; setTimeout(() => window.print(), 600) }
  }, [d])
  const cat = d?.catalog
  const accent = company?.print_settings?.primary_color || brand.colors.primary
  const css = useMemo(() => `
    @page { size: A4; margin: 14mm 12mm; }
    body { background: #fff !important; }
    .cp { font-family: Inter, Arial, sans-serif; color: #1b2b45; max-width: 190mm; margin: 0 auto; padding: 16px; }
    .cp h1 { margin: 0; font-size: 24px; color: ${brand.colors.dark}; }
    .cp .head { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 3px solid ${brand.colors.primary}; padding-bottom: 10px; margin-bottom: 14px; }
    .cp .grp { font-weight: 700; color: ${accent}; font-size: 15px; margin: 18px 0 8px; break-after: avoid; }
    .cp .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .cp .card { border: 1px solid #dfe5ef; border-radius: 8px; padding: 8px; break-inside: avoid; }
    .cp .card img, .cp .card .ph { width: 100%; height: 120px; object-fit: contain; background: #f4f6fa; border-radius: 6px; }
    .cp .code { font-family: monospace; font-size: 10px; color: #4a5b75; }
    .cp .price { font-weight: 800; font-size: 15px; margin-top: 4px; }
    .cp .promo { background: #e03131; color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 4px; margin-left: 4px; vertical-align: middle; }
    .cp table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .cp td { padding: 5px 4px; border-bottom: 1px solid #eef1f6; }
    .cp td.r { text-align: right; font-weight: 700; white-space: nowrap; }
    .cp .foot { margin-top: 18px; font-size: 11px; color: #4a5b75; border-top: 1px solid #dfe5ef; padding-top: 8px; }
    @media print { .noprint { display: none; } }
  `, [accent])
  if (!d) return <Loading />
  return (
    <div className="cp">
      <style>{css}</style>
      <div className="noprint" style={{ textAlign: 'right', marginBottom: 8 }}><Button size="xs" leftSection={<IconPrinter size={14} />} onClick={() => window.print()}>Stampa / Salva PDF</Button></div>
      {company ? (
        <PrintHeader c={company} title={cat.title || cat.name}
          subtitle={[d.party_name ? `Riservato a ${d.party_name}` : '', cat.show_prices ? (cat.vat_included ? 'Prezzi IVA inclusa' : 'Prezzi IVA esclusa') : '', cat.valid_until ? `Valido fino al ${fmtDate(cat.valid_until)}` : ''].filter(Boolean).join(' · ')} />
      ) : <h1>{cat.title || cat.name}</h1>}
      {d.groups.map((g: any) => (
        <div key={g.name}>
          {g.name && <div className="grp">{g.name}</div>}
          {cat.layout === 'griglia' ? (
            <div className="grid">
              {g.items.map((i: any) => (
                <div className="card" key={i.id}>
                  {i.url ? <img src={i.url} alt="" /> : <div className="ph" />}
                  {cat.show_codes && <div className="code">{i.code}</div>}
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{i.description}</div>
                  {cat.show_prices && i.price != null && <div className="price">{fmtEuro(i.price)}{i.promo && <span className="promo">PROMO</span>}</div>}
                </div>
              ))}
            </div>
          ) : (
            <table><tbody>
              {g.items.map((i: any) => (
                <tr key={i.id}>
                  {cat.show_codes && <td className="code" style={{ width: 90 }}>{i.code}</td>}
                  <td>{i.description}{i.brand ? <span style={{ color: '#4a5b75' }}> · {i.brand}</span> : null}</td>
                  <td style={{ width: 40, color: '#4a5b75' }}>{i.unit}</td>
                  {cat.show_prices && <td className="r">{i.price != null ? fmtEuro(i.price) : '—'}{i.promo && <span className="promo">PROMO</span>}</td>}
                </tr>
              ))}
            </tbody></table>
          )}
        </div>
      ))}
      <div className="foot">{cat.notes}{cat.notes ? ' · ' : ''}Prezzi aggiornati al {new Date().toLocaleDateString('it-IT')}</div>
      {company && <PrintFooter c={company} />}
    </div>
  )
}
