import { useEffect, useRef, useState } from 'react'
import { RotateCw } from 'lucide-react'
import type { Page } from '../api/client'
import 'photoswipe/style.css'

export function SourceViewer({ page, revision, box }: { page: Page; revision?: number; box?: number[][] }) {
  const canvas = useRef<HTMLCanvasElement>(null), image = useRef<HTMLImageElement>(null)
  const [rotation, setRotation] = useState(0)
  useEffect(()=>setRotation(0),[page.id])
  const [error, setError] = useState(false), [ready, setReady] = useState(false)
  useEffect(() => {
    setError(false); setReady(false)
    if (page.asset.mime !== 'application/pdf' || revision) return
    let cancelled = false
    let destroy: (() => void) | undefined
    void (async () => {
      try {
        const pdfjs = await import('pdfjs-dist')
        const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default
        const task = pdfjs.getDocument({ url: `/api/v1/assets/${page.asset_id}/original`, withCredentials: true })
        destroy = () => { void task.destroy() }
        const document = await task.promise
        const pdfPage = await document.getPage(page.pdf_page_no ?? 1)
        if (cancelled || !canvas.current) return
        const base = pdfPage.getViewport({ scale: 1 })
        const viewport = pdfPage.getViewport({ scale: Math.min(2, 1600 / base.width) })
        const target = canvas.current; target.width = viewport.width; target.height = viewport.height
        await pdfPage.render({ canvas: target, canvasContext: target.getContext('2d')!, viewport }).promise
        if (!cancelled) setReady(true)
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true; destroy?.() }
  }, [page.id, page.asset_id, page.pdf_page_no, page.asset.mime, revision])
  const enlarge = async () => {
    if (!image.current) return
    const { default: PhotoSwipe } = await import('photoswipe')
    let src = image.current.src, width = image.current.naturalWidth, height = image.current.naturalHeight
    if (rotation) {
      const target = document.createElement('canvas')
      target.width = rotation % 180 ? height : width; target.height = rotation % 180 ? width : height
      const context = target.getContext('2d')!
      context.translate(target.width / 2, target.height / 2); context.rotate(rotation * Math.PI / 180)
      context.drawImage(image.current, -width / 2, -height / 2)
      src = target.toDataURL('image/png'); width = target.width; height = target.height
    }
    const viewer = new PhotoSwipe({ dataSource: [{ src, width, height, alt: 'Document source' }], showHideAnimationType: 'fade' })
    viewer.init()
  }
  if (page.asset.mime === 'application/pdf' && !revision) return <div className="pdf-source">{!ready && !error && <p className="caption">Opening PDF page…</p>}{error && <img src={`/api/v1/assets/${page.asset_id}/preview?page_id=${page.id}${revision ? `&revision=${revision}` : ''}`} alt="PDF page preview" />}<canvas ref={canvas} aria-label={`PDF page ${page.pdf_page_no ?? 1}`} style={{ display: ready ? 'block' : 'none' }} /></div>
  return <><div className="source-view-controls"><button type="button" className="text-button" onClick={()=>setRotation(value=>(value+90)%360)} aria-label="Rotate view"><RotateCw size={16}/>Rotate view</button><small>View only · OCR unchanged</small></div><button className="source-enlarge" onClick={() => { void enlarge() }} aria-label="Enlarge source image"><span className="evidence-image" style={{transform:`rotate(${rotation}deg)`,width:rotation % 180 ? '60%' : '100%'}}><img ref={image} src={`/api/v1/assets/${page.asset_id}/preview?page_id=${page.id}${revision ? `&revision=${revision}` : ''}`} alt="Source document" onError={event => { event.currentTarget.src = `/api/v1/assets/${page.asset_id}/original`; event.currentTarget.onerror = null }} />{box && <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="evidence-box" aria-label="Matching source area"><polygon points={box.map(point => point.join(',')).join(' ')} /></svg>}</span><small>Tap to look closer</small></button></>
}

