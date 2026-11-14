import { describe, expect, it } from 'vitest'
import { hashFile } from '../src/features/upload'

describe('upload checksum', () => {
  it('hashes a blob stream using SHA-256', async () => {
    expect(await hashFile(new Blob(['abc']))).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
  })
})
