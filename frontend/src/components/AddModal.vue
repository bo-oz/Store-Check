<template>
  <div class="overlay" @mousedown.self="$emit('cancel')">
    <div class="modal">
      <div class="modal-header">
        <h3>Add to Qdrant</h3>
        <button class="close" @click="$emit('cancel')">✕</button>
      </div>

      <div class="modal-body">
        <div class="canvas-section">
          <div class="canvas-toolbar">
            <span class="hint">Drag handles to resize the selection. Yellow box = what gets uploaded.</span>
            <div class="zoom-controls">
              <button @click="zoomIn"  title="Zoom in (less context)">🔍+</button>
              <button @click="zoomOut" title="Zoom out (more context)">🔍−</button>
              <button @click="resetZoom" title="Reset">↺</button>
            </div>
          </div>

          <canvas
            ref="canvas"
            :width="CANVAS_W"
            :height="canvasH"
            class="sel-canvas"
            :style="{ cursor: dragCursor }"
            @mousedown="onMouseDown"
            @mousemove="onMouseMove"
            @mouseup="onMouseUp"
            @mouseleave="onMouseUp"
          />

          <p class="coords">
            Selection (full image): ({{ Math.round(sel[0]) }}, {{ Math.round(sel[1]) }}) →
            ({{ Math.round(sel[2]) }}, {{ Math.round(sel[3]) }})
            &nbsp;·&nbsp; {{ Math.round(sel[2]-sel[0]) }} × {{ Math.round(sel[3]-sel[1]) }} px
          </p>
        </div>

        <div class="form-section">
          <h4>Product details</h4>
          <label>Product name <span class="req">*</span></label>
          <input v-model="form.product_name" placeholder="e.g. Angileptol" />
          <label>Pack type</label>
          <input v-model="form.pack_type" placeholder="e.g. Angileptol Miel 30 comp" />
          <label>Category</label>
          <input v-model="form.category" placeholder="e.g. Bucofaríngeos" />
          <label class="checkbox-label">
            <input type="checkbox" v-model="form.company_product" />
            Own brand
          </label>
          <div v-if="error"   class="error">{{ error }}</div>
          <div v-if="success" class="success">{{ success }}</div>
          <div class="form-actions">
            <button class="btn-cancel" @click="$emit('cancel')">Cancel</button>
            <button class="btn-upload" :disabled="loading" @click="upload">
              <span v-if="loading">Uploading…</span>
              <span v-else>⬆ Upload</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { addCrop } from '../api.js'

const props = defineProps({
  imageUrl:    String,
  imageW:      Number,
  imageH:      Number,
  originalBox: Array,   // [x1,y1,x2,y2] in full-image coords
  sessionId:   String,
})
const emit = defineEmits(['cancel', 'added'])

// ── Canvas constants ──────────────────────────────────────────────────────────
const CANVAS_W  = 560   // fixed canvas pixel width
const HANDLE_R  = 6     // handle radius in canvas pixels (stays fixed regardless of zoom)
const PAD_STEP  = 0.15  // how much to change padFactor per zoom step
const PAD_MIN   = 0.05
const PAD_MAX   = 2.0
const PAD_DEFAULT = 0.40

// ── Viewport state ────────────────────────────────────────────────────────────
const padFactor = ref(PAD_DEFAULT)  // fraction of box dims added as margin on each side

// Viewport = region of full image shown in canvas
const viewport = computed(() => {
  const [bx1, by1, bx2, by2] = props.originalBox
  const bw = bx2 - bx1, bh = by2 - by1
  const px = bw * padFactor.value
  const py = bh * padFactor.value
  const vx1 = Math.max(0,           bx1 - px)
  const vy1 = Math.max(0,           by1 - py)
  const vx2 = Math.min(props.imageW, bx2 + px)
  const vy2 = Math.min(props.imageH, by2 + py)
  return { x: vx1, y: vy1, w: vx2 - vx1, h: vy2 - vy1 }
})

// Scale: how many canvas pixels per full-image pixel
const imgScale = computed(() => CANVAS_W / viewport.value.w)
const canvasH  = computed(() => Math.round(viewport.value.h * imgScale.value))

// ── Selection in full-image coords ────────────────────────────────────────────
const sel = ref([...props.originalBox])

// ── Drag state ────────────────────────────────────────────────────────────────
const canvas      = ref(null)
const img         = ref(null)
const dragCursor  = ref('default')
let drag = null

const CURSOR_MAP = {
  tl: 'nw-resize', tr: 'ne-resize', bl: 'sw-resize', br: 'se-resize',
  tm: 'n-resize',  bm: 's-resize',  ml: 'w-resize',  mr: 'e-resize',
}

// ── Coordinate helpers ────────────────────────────────────────────────────────
// full-image → canvas display
function imgToCanvas(ix, iy) {
  const vp = viewport.value, s = imgScale.value
  return [(ix - vp.x) * s, (iy - vp.y) * s]
}
// canvas display → full-image
function canvasToImg(cx, cy) {
  const vp = viewport.value, s = imgScale.value
  return [vp.x + cx / s, vp.y + cy / s]
}

// ── Handles in canvas coords ──────────────────────────────────────────────────
function handles() {
  const [cx1, cy1] = imgToCanvas(sel.value[0], sel.value[1])
  const [cx2, cy2] = imgToCanvas(sel.value[2], sel.value[3])
  const mx = (cx1 + cx2) / 2, my = (cy1 + cy2) / 2
  return { tl:[cx1,cy1], tr:[cx2,cy1], bl:[cx1,cy2], br:[cx2,cy2],
           tm:[mx,cy1],  bm:[mx,cy2],  ml:[cx1,my],  mr:[cx2,my] }
}

function hitHandle(cx, cy) {
  for (const [key, [hx, hy]] of Object.entries(handles())) {
    if (Math.abs(cx - hx) <= HANDLE_R + 3 && Math.abs(cy - hy) <= HANDLE_R + 3) return key
  }
  return null
}

// ── Draw ──────────────────────────────────────────────────────────────────────
function draw() {
  const ctx = canvas.value?.getContext('2d')
  if (!ctx || !img.value) return
  const vp = viewport.value
  const s  = imgScale.value
  const h  = canvasH.value

  ctx.clearRect(0, 0, CANVAS_W, h)

  // Draw the viewport region of the full image
  ctx.drawImage(img.value,
    vp.x, vp.y, vp.w, vp.h,
    0,    0,    CANVAS_W, h)

  // Dim outside selection
  const [cx1, cy1] = imgToCanvas(sel.value[0], sel.value[1])
  const [cx2, cy2] = imgToCanvas(sel.value[2], sel.value[3])
  const sw = cx2 - cx1, sh = cy2 - cy1

  ctx.fillStyle = 'rgba(0,0,0,0.45)'
  ctx.fillRect(0, 0, CANVAS_W, h)
  if (sw > 0 && sh > 0) {
    ctx.clearRect(cx1, cy1, sw, sh)
    // Re-draw selected region undimmed
    ctx.drawImage(img.value,
      sel.value[0], sel.value[1], sel.value[2] - sel.value[0], sel.value[3] - sel.value[1],
      cx1, cy1, sw, sh)
  }

  // Selection border
  ctx.strokeStyle = '#f1c40f'
  ctx.lineWidth = 2
  ctx.strokeRect(cx1, cy1, sw, sh)

  // Handles — drawn in canvas pixels, always fixed size
  for (const [hx, hy] of Object.values(handles())) {
    ctx.beginPath()
    ctx.arc(hx, hy, HANDLE_R, 0, Math.PI * 2)
    ctx.fillStyle = '#f1c40f'
    ctx.fill()
    ctx.strokeStyle = '#1a1d2e'
    ctx.lineWidth = 1.5
    ctx.stroke()
  }
}

// ── Mouse events ──────────────────────────────────────────────────────────────
function canvasCoords(e) {
  const rect = canvas.value.getBoundingClientRect()
  // Account for CSS scaling (canvas pixel : CSS pixel ratio)
  const scaleX = CANVAS_W / rect.width
  const scaleY = canvasH.value / rect.height
  return [
    (e.clientX - rect.left) * scaleX,
    (e.clientY - rect.top)  * scaleY,
  ]
}

function onMouseDown(e) {
  const [cx, cy] = canvasCoords(e)
  const hit = hitHandle(cx, cy)
  if (hit) drag = { handle: hit, startSel: [...sel.value], startCx: cx, startCy: cy }
}

function onMouseMove(e) {
  const [cx, cy] = canvasCoords(e)
  if (!drag) {
    const hit = hitHandle(cx, cy)
    dragCursor.value = hit ? (CURSOR_MAP[hit] || 'pointer') : 'default'
    return
  }
  // Convert drag delta to image-pixel delta
  const s = imgScale.value
  const dix = (cx - drag.startCx) / s
  const diy = (cy - drag.startCy) / s
  const [ox1, oy1, ox2, oy2] = drag.startSel
  let [nx1, ny1, nx2, ny2]   = [ox1, oy1, ox2, oy2]
  const h = drag.handle
  if (h==='tl'||h==='ml'||h==='bl') nx1 = Math.min(ox1+dix, nx2-5)
  if (h==='tr'||h==='mr'||h==='br') nx2 = Math.max(ox2+dix, nx1+5)
  if (h==='tl'||h==='tm'||h==='tr') ny1 = Math.min(oy1+diy, ny2-5)
  if (h==='bl'||h==='bm'||h==='br') ny2 = Math.max(oy2+diy, ny1+5)
  sel.value = [
    Math.max(0,           nx1), Math.max(0,           ny1),
    Math.min(props.imageW, nx2), Math.min(props.imageH, ny2),
  ]
  draw()
}

function onMouseUp() { drag = null }

// ── Zoom ──────────────────────────────────────────────────────────────────────
function zoomIn()    { padFactor.value = Math.max(PAD_MIN, padFactor.value - PAD_STEP) }
function zoomOut()   { padFactor.value = Math.min(PAD_MAX, padFactor.value + PAD_STEP) }
function resetZoom() { padFactor.value = PAD_DEFAULT; sel.value = [...props.originalBox] }

// Redraw whenever viewport changes (zoom) or selection changes
watch([viewport, sel], () => { if (img.value) draw() }, { deep: true })

// ── Upload ────────────────────────────────────────────────────────────────────
const form    = ref({ product_name: '', pack_type: '', category: '', company_product: true })
const loading = ref(false)
const error   = ref('')
const success = ref('')

async function upload() {
  if (!form.value.product_name.trim()) { error.value = 'Product name is required.'; return }
  loading.value = true; error.value = ''; success.value = ''
  try {
    const box = sel.value.map(Math.round)
    const result = await addCrop({
      session_id:       props.sessionId,
      box,
      product_name:     form.value.product_name.trim(),
      pack_type:        form.value.pack_type.trim(),
      product_category: form.value.category.trim(),
      company_product:  form.value.company_product,
    })
    success.value = `✅ Uploaded "${result.product_name}" (id ${result.point_id})`
    setTimeout(() => emit('added', result), 900)
  } catch (e) {
    error.value = e?.response?.data?.detail ?? 'Upload failed'
  } finally {
    loading.value = false
  }
}

// ── Load image ────────────────────────────────────────────────────────────────
onMounted(() => {
  const i = new Image()
  i.onload = () => { img.value = i; nextTick(() => draw()) }
  i.onerror = (e) => console.error('AddModal image load error', e)
  i.src = props.imageUrl
})
</script>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.75);
  display: flex; align-items: center; justify-content: center;
  z-index: 100; padding: 1rem;
}
.modal {
  background: #1a1d2e; border-radius: 12px; width: 100%; max-width: 1020px;
  max-height: 92vh; overflow-y: auto; display: flex; flex-direction: column;
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1rem 1.25rem; border-bottom: 1px solid #2a2e3f;
}
.modal-header h3 { font-size: 1.1rem; }
.close { background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer; }

.modal-body { display: grid; grid-template-columns: 1fr 320px; gap: 1.25rem; padding: 1.25rem; }
@media (max-width: 720px) { .modal-body { grid-template-columns: 1fr; } }

.canvas-section { display: flex; flex-direction: column; gap: .5rem; min-width: 0; }
.canvas-toolbar { display: flex; align-items: center; justify-content: space-between; gap: .5rem; flex-wrap: wrap; }
.hint { font-size: .78rem; color: #888; }
.zoom-controls { display: flex; gap: .4rem; }
.zoom-controls button {
  background: #2a2e3f; border: none; color: #ccc;
  padding: .3rem .65rem; border-radius: 6px; cursor: pointer; font-size: .85rem;
  transition: background .15s;
}
.zoom-controls button:hover { background: #3a3f52; }

.sel-canvas {
  display: block; width: 100%; max-width: 560px;
  border-radius: 6px; background: #0f1117;
}
.coords { font-size: .75rem; color: #5c6bc0; font-variant-numeric: tabular-nums; }

.form-section { display: flex; flex-direction: column; gap: .55rem; }
h4 { font-size: .95rem; color: #ccc; margin-bottom: .15rem; }
label { font-size: .82rem; color: #aaa; }
.req { color: #ef5350; }
input[type=text], input:not([type=checkbox]) {
  width: 100%; background: #0f1117; border: 1px solid #2a2e3f;
  color: #e0e0e0; padding: .45rem .7rem; border-radius: 6px; font-size: .88rem;
  outline: none; transition: border-color .15s;
}
input:focus { border-color: #5c6bc0; }
.checkbox-label { display: flex; align-items: center; gap: .5rem; }
.checkbox-label input { width: auto; }
.error   { color: #ef5350; font-size: .82rem; }
.success { color: #2ecc71; font-size: .82rem; }
.form-actions { display: flex; gap: .75rem; margin-top: .4rem; }
.btn-cancel {
  flex: 1; padding: .55rem; background: #2a2e3f; color: #ccc;
  border: none; border-radius: 7px; cursor: pointer;
}
.btn-upload {
  flex: 2; padding: .55rem; background: #f1c40f; color: #0f1117;
  border: none; border-radius: 7px; font-weight: 700; cursor: pointer;
}
.btn-upload:hover:not(:disabled) { opacity: .85; }
.btn-upload:disabled { opacity: .4; cursor: not-allowed; }
</style>
