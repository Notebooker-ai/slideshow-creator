// AntV Infographic SSR sidecar for slideshow-creator.
//
// Reads JSON `{ theme, specs: [dsl, ...] }` on stdin and prints a JSON array
// `[{ svg, png_b64, error }, ...]` aligned to `specs`. Each AntV DSL spec is
// rendered headlessly to SVG (via @antv/infographic's /ssr export) and rasterized
// to PNG (via sharp) so data slides appear in static PPTX/PDF exports too.
//
// Invoked by the Python creator as: `node render.mjs` with cwd = this directory,
// so `@antv/infographic` and `sharp` resolve from this package's own node_modules.

import { renderToString } from '@antv/infographic/ssr'
import sharp from 'sharp'

async function main() {
  const chunks = []
  for await (const c of process.stdin) chunks.push(c)
  let input = {}
  try {
    input = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
  } catch (e) {
    process.stderr.write('invalid sidecar input JSON: ' + e.message)
    process.exit(1)
  }
  const theme = input.theme || 'light'
  const specs = Array.isArray(input.specs) ? input.specs : []

  const out = []
  for (const spec of specs) {
    try {
      const svg = await renderToString(spec, { theme })
      let png_b64 = null
      let error = null
      try {
        const png = await sharp(Buffer.from(svg), { density: 200 }).png().toBuffer()
        png_b64 = png.toString('base64')
      } catch (e) {
        error = 'png: ' + (e && e.message ? e.message : String(e))
      }
      out.push({ svg, png_b64, error })
    } catch (e) {
      out.push({ svg: null, png_b64: null, error: String(e && e.message ? e.message : e) })
    }
  }
  process.stdout.write(JSON.stringify(out))
}

main().catch(e => {
  process.stderr.write(String(e && e.stack ? e.stack : e))
  process.exit(1)
})
