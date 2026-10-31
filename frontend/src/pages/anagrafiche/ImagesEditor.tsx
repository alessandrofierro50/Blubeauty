import { ActionIcon, Badge, Card, FileButton, Group, Image, Loader, SimpleGrid, Stack, Text, Tooltip } from '@mantine/core'
import { IconPhotoPlus, IconStar, IconTrash } from '@tabler/icons-react'
import { useState } from 'react'

import { tokens } from '../../api'
import { notifyError } from '../../components'
import { A } from './shared'

export default function ImagesEditor({ itemId, images, onChange }: { itemId?: string; images: any[]; onChange: (imgs: any[]) => void }) {
  const [busy, setBusy] = useState(false)
  if (!itemId) return <Text c="dimmed" size="sm">Salva l'articolo per aggiungere le immagini.</Text>

  async function upload(files: File[]) {
    if (!files.length) return
    setBusy(true)
    try {
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f))
      const res = await fetch(`/api/anagrafiche/articoli/${itemId}/immagini`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${tokens.get('user')}` } })
      const data = await res.json()
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Caricamento non riuscito')
      onChange(data)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  const act = (path: string, method: string) => A(`/articoli/${itemId}/immagini/${path}`, { method }).then(onChange).catch(notifyError)

  return (
    <SimpleGrid cols={{ base: 2, sm: 3, lg: 5 }}>
      {images.map((img, i) => (
        <Card key={img.id} withBorder padding={0} radius="md">
          <Image src={img.thumb_url} h={150} fit="contain" bg="var(--mantine-color-gray-0)" alt="" />
          <Group justify="space-between" p={6}>
            {i === 0 ? <Badge size="sm" variant="light">principale</Badge> : (
              <Tooltip label="Rendi principale"><ActionIcon variant="subtle" onClick={() => act(`${img.id}/principale`, 'POST')}><IconStar size={16} /></ActionIcon></Tooltip>
            )}
            <Tooltip label="Elimina"><ActionIcon variant="subtle" color="red" onClick={() => confirm('Eliminare l\'immagine?') && act(img.id, 'DELETE')}><IconTrash size={16} /></ActionIcon></Tooltip>
          </Group>
        </Card>
      ))}
      <FileButton onChange={upload} accept="image/png,image/jpeg,image/webp,image/heic" multiple>
        {(props) => (
          <Card {...props} withBorder radius="md" h={196} style={{ cursor: 'pointer', borderStyle: 'dashed' }}>
            <Stack align="center" justify="center" h="100%" gap={6}>
              {busy ? <Loader size="sm" /> : <IconPhotoPlus size={30} color="var(--mantine-color-blu-6)" />}
              <Text size="sm" c="dimmed" ta="center">Aggiungi immagini<br />(anche dalla fotocamera)</Text>
            </Stack>
          </Card>
        )}
      </FileButton>
    </SimpleGrid>
  )
}
