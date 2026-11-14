import { createSHA256 } from 'hash-wasm'
export async function hashFile(file: Blob): Promise<string> {
  const hash = await createSHA256()
  hash.init()
  const reader = file.stream().getReader()
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      hash.update(value)
    }
  } finally {
    reader.releaseLock()
  }
  return hash.digest('hex')
}
