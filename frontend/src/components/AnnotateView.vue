<template>
  <div class="annotate-view">

    <!-- ── LEFT: shelf list ───────────────────────────────────────────────── -->
    <aside class="shelf-sidebar">
      <div class="sidebar-header">
        <h3>Shelf images</h3>
        <button class="btn-upload" @click="fileInput.click()">+ Upload</button>
        <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
      </div>
      <div v-if="uploading" class="upload-status">
        <span class="mini-spin" /> Uploading…
      </div>
      <div class="shelf-list">
        <div v-for="s in shelves" :key="s.shelf_id"
             class="shelf-item" :class="{ active: activeShelf?.shelf_id === s.shelf_id }"
             @click="selectShelf(s)">
          <img :src="thumbUrl(s.shelf_id)" class="shelf-thumb" />
          <div class="shelf-meta">
            <p class="shelf-name">{{ s.original_name || (s.shelf_id.slice(0,10) + '…') }}</p>
            <p class="shelf-boxes">{{ s.box_count }} annotation{{ s.box_count !== 1 ? 's' : '' }}</p>
          </div>
        </div>
        <div v-if="!shelves.length" class="no-shelves">Upload a shelf image to begin</div>
      </div>
    </aside>

    <!-- ── CENTRE: canvas ────────────────────────────────────────────────── -->
    <main class="canvas-area" ref="viewportEl"
          :style="{ cursor: activeCursor }"
          @mousedown="onViewportMouseDown"
          @mousemove="onMouseMove"
          @mouseup="onMouseUp"
          @mouseleave="onMouseUp"
          @wheel.prevent="onWheel"
          @keydown="onKeyDown"
          tabindex="0">

      <!-- Toolbar -->
      <div class="toolbar">
        <button class="tool-btn" :class="{ active: tool === 'draw' }"
                @click="tool = 'draw'" title="Draw box  [D]">✏ Draw</button>
        <button class="tool-btn" :class="{ active: tool === 'pan' }"
                @click="tool = 'pan'"  title="Pan  [P]">✋ Pan</button>
        <div class="tsep" />
        <button class="zoom-btn" @click="zoomStep(-1)">−</button>
        <span class="zoom-label">{{ Math.round(zoom * 100) }}%</span>
        <button class="zoom-btn" @click="zoomStep(1)">+</button>
        <button class="zoom-btn" @click="fitToScreen" title="Fit to screen">⊡</button>
      </div>

      <!-- Detection bar -->
      <div v-if="activeShelf" class="detect-bar">
        <select v-model="selectedModel" class="detect-select" @change="onModelChange">
          <option v-for="m in detectionModels" :key="m.id" :value="m.id">{{ m.name }}</option>
        </select>
        <template v-if="selectedModel !== 'manual'">
          <label class="conf-label">Conf</label>
          <input v-model.number="confThreshold" type="number" min="0.05" max="0.95" step="0.05"
                 class="conf-input" />
          <template v-if="needsPrompt">
            <label class="conf-label">Prompt</label>
            <input v-model="textPrompts" class="prompt-input" placeholder="box, bottle, blister…" />
          </template>
          <div class="adv-params-wrap">
            <button class="btn-adv-params" :class="{ active: advOpen }"
                    @click="advOpen = !advOpen" title="Model parameters">⚙</button>
            <div v-if="advOpen" class="adv-popover">
              <p class="adv-title">Model parameters</p>
              <div class="adv-row">
                <label title="Non-maximum suppression — lower merges more overlapping detections">IoU (NMS)</label>
                <input v-model.number="advParams.iou" type="number" min="0.1" max="0.95" step="0.05" />
              </div>
              <div class="adv-row">
                <label title="Candidates overlapping an existing annotation more than this are hidden">Dedup overlap</label>
                <input v-model.number="advParams.dedupeIou" type="number" min="0.1" max="0.95" step="0.05" />
              </div>
              <template v-if="isSegModel">
                <div class="adv-row">
                  <label title="Inference resolution — higher finds smaller items, slower">Image size</label>
                  <input v-model.number="advParams.imgsz" type="number" min="320" max="2048" step="32" />
                </div>
                <div class="adv-row">
                  <label title="Boxes smaller than this many px² are discarded">Min box area</label>
                  <input v-model.number="advParams.minArea" type="number" min="100" max="20000" step="100" />
                </div>
                <div class="adv-row">
                  <label title="Boxes covering more than this fraction of the image are discarded">Max area ratio</label>
                  <input v-model.number="advParams.maxAreaRatio" type="number" min="0.01" max="0.5" step="0.01" />
                </div>
                <div class="adv-row">
                  <label title="Width/height ratio floor — filters extreme slivers">Min aspect</label>
                  <input v-model.number="advParams.minAspect" type="number" min="0.05" max="0.9" step="0.05" />
                </div>
              </template>
              <button class="btn-adv-reset" @click="resetAdvParams">Reset to defaults</button>
            </div>
          </div>
        </template>
        <button class="btn-detect"
                :disabled="detecting || selectedModel === 'manual'"
                @click="runDetection">
          <span v-if="detecting" class="mini-spin" />
          <span v-else>▶ Run</span>
        </button>
        <span v-if="pendingBoxes.length" class="detect-dismiss-all" @click="dismissAllPending">
          Dismiss all ({{ pendingBoxes.length }})
        </span>
        <span v-if="detectStatus" class="detect-status">{{ detectStatus }}</span>
      </div>

      <div v-if="!activeShelf" class="canvas-empty">Select a shelf image to annotate</div>

      <template v-else>
        <!-- Image + SVG overlay, transformed together -->
        <div class="canvas-content" ref="contentEl" :style="contentStyle">
          <img ref="imgEl"
               :src="imageUrl(activeShelf.shelf_id)"
               @load="onImageLoad"
               draggable="false"
               style="display:block; max-width:none; user-select:none" />

          <svg v-if="imgLoaded"
               class="box-overlay"
               :width="imgW" :height="imgH"
               style="position:absolute;top:0;left:0;overflow:visible;pointer-events:none">

            <!-- ── Existing boxes: visuals only (hit areas rendered after pending, so they stay on top) ── -->
            <g v-for="box in boxes" :key="box.id">
              <rect
                :x="liveBox(box)[0]" :y="liveBox(box)[1]"
                :width="liveBox(box)[2]-liveBox(box)[0]"
                :height="liveBox(box)[3]-liveBox(box)[1]"
                fill="transparent"
                :stroke="hue(box.label)"
                :stroke-width="selectedBox?.id === box.id ? boxSW * 1.25 : boxSW"
                :stroke-dasharray="selectedBox?.id === box.id ? `${6*invZ} ${3*invZ}` : 'none'"
                style="pointer-events:none"
              />
              <rect
                :x="liveBox(box)[0]" :y="liveBox(box)[1]"
                :width="chipW(box.label)" :height="chipH" :rx="chipRx"
                :style="{ fill: hue(box.label) }"
                style="pointer-events:none; opacity:.9"
              />
              <text :x="liveBox(box)[0] + 5*invZ" :y="liveBox(box)[1] + 13*invZ"
                    :style="{ fontSize: chipFs + 'px' }"
                    class="chip-text" style="pointer-events:none">{{ box.label }}</text>
            </g>

            <!-- ── Pending (detected, unconfirmed) boxes ── -->
            <g v-for="p in pendingBoxes" :key="p._pid">
              <rect :x="livePendingBox(p)[0]" :y="livePendingBox(p)[1]"
                    :width="livePendingBox(p)[2]-livePendingBox(p)[0]"
                    :height="livePendingBox(p)[3]-livePendingBox(p)[1]"
                    fill="rgba(230,168,23,.08)"
                    stroke="#e6a817"
                    :stroke-width="selectedPending?._pid === p._pid ? pendingSW * 1.6 : pendingSW"
                    :stroke-dasharray="`${6*invZ} ${3*invZ}`"
                    :filter="selectedPending?._pid === p._pid ? 'url(#pendingGlow)' : 'none'"
                    style="pointer-events:none" />
              <rect :x="livePendingBox(p)[0]" :y="livePendingBox(p)[1]"
                    :width="chipW(pendingChipText(p))" :height="chipH" :rx="chipRx"
                    fill="#e6a817" style="pointer-events:none; opacity:.85" />
              <text :x="livePendingBox(p)[0] + 5*invZ" :y="livePendingBox(p)[1] + 13*invZ"
                    :style="{ fontSize: chipFs + 'px', fill: '#1a1000' }"
                    style="pointer-events:none">{{ pendingChipText(p) }}</text>
              <rect v-if="selectedPending?._pid !== p._pid"
                    :x="p.x1" :y="p.y1" :width="p.x2-p.x1" :height="p.y2-p.y1"
                    fill="transparent" style="pointer-events:all; cursor:pointer"
                    @mousedown.stop="selectPending(p)" />
            </g>

            <!-- ── Existing box hit areas: rendered on top of pending so they always receive clicks ── -->
            <rect v-for="box in boxes" :key="'hit-' + box.id"
                  :x="liveBox(box)[0]" :y="liveBox(box)[1]"
                  :width="liveBox(box)[2]-liveBox(box)[0]"
                  :height="liveBox(box)[3]-liveBox(box)[1]"
                  fill="transparent"
                  style="pointer-events:all; cursor:pointer"
                  @mousedown.stop="onBoxMouseDown(box, $event)" />

            <!-- ── Resize handles (selected confirmed, selected pending, or new drawn box) ── -->
            <g v-if="selectedBox || selectedPending || pendingCoords">
              <circle v-for="h in resizeHandles" :key="h.id"
                      :cx="h.x" :cy="h.y" :r="handleR"
                      class="resize-handle"
                      :stroke-width="1.5 * invZ"
                      :style="{ cursor: h.cursor }"
                      style="pointer-events:all"
                      @mousedown.stop="onHandleMouseDown(h.id, $event)" />
            </g>

            <!-- ── Drawing preview ── -->
            <!-- While drawing: live drawRect -->
            <rect v-if="drawRect && !pendingCoords && drawRect.w > 3 && drawRect.h > 3"
                  :x="drawRect.x" :y="drawRect.y"
                  :width="drawRect.w" :height="drawRect.h"
                  fill="rgba(92,107,192,.12)" stroke="#7986cb"
                  :stroke-width="drawSW"
                  :stroke-dasharray="`${5*invZ} ${3*invZ}`"
                  style="pointer-events:none" />
            <!-- After drawing ends: box driven by editingCoords so it tracks handles -->
            <rect v-if="pendingCoords && editingCoords"
                  :x="editingCoords[0]" :y="editingCoords[1]"
                  :width="editingCoords[2]-editingCoords[0]"
                  :height="editingCoords[3]-editingCoords[1]"
                  fill="rgba(92,107,192,.08)" stroke="#7986cb"
                  :stroke-width="drawSW"
                  :stroke-dasharray="`${5*invZ} ${3*invZ}`"
                  style="pointer-events:none" />
          </svg>
        </div>

        <div class="hint-bar">
          <span class="hint-counts">
            <span class="hint-confirmed">{{ boxes.length }} confirmed</span>
            <span v-if="pendingBoxes.length" class="hint-pending">· {{ pendingBoxes.length }} pending</span>
          </span>
          <span v-if="tool==='draw'">· Click &amp; drag to draw</span>
          <span v-else>· Drag to pan</span>
          <span>· Scroll: zoom</span>
          <span>· Space+drag: pan</span>
          <span v-if="selectedBox">· ⌫ Delete</span>
        </div>
      </template>
    </main>

    <!-- ── RIGHT: label panel ─────────────────────────────────────────────── -->
    <aside class="label-panel">

      <!-- ── Pending box review ── -->
      <template v-if="selectedPending">
        <div class="review-header">
          <h3 style="margin:0">Review detection</h3>
          <button class="btn-close-review" @click="cancelEdit" title="Back to overview">✕</button>
        </div>
        <div v-if="selectedPending.label || selectedPending.confidence > 0" class="yolo-prediction-banner">
          <span class="pred-label">
            🏷 {{ selectedPending.label || '?' }}
          </span>
          <span v-if="selectedPending.confidence > 0"
                class="pred-conf"
                :class="selectedPending.confidence >= 0.7 ? 'conf-high' : selectedPending.confidence >= 0.4 ? 'conf-mid' : 'conf-low'">
            {{ Math.round(selectedPending.confidence * 100) }}%
          </span>
        </div>

        <!-- Crop preview + optional match reference side by side -->
        <div class="preview-row">
          <div class="preview-col">
            <p class="preview-lbl">Crop</p>
            <canvas ref="cropCanvas" class="crop-preview-sm" width="100" height="90" />
          </div>
          <div v-if="selectedPending.match?.match_image_b64" class="preview-col">
            <p class="preview-lbl">Best match</p>
            <img :src="'data:image/jpeg;base64,' + selectedPending.match.match_image_b64"
                 class="crop-preview-sm match-img" />
          </div>
          <div v-else-if="selectedPending.matching" class="preview-col match-searching">
            <p class="preview-lbl">Best match</p>
            <div class="match-spinner"><span class="mini-spin" /> Searching…</div>
          </div>
        </div>

        <!-- Match confidence banner + re-check button -->
        <div class="match-banner-row">
          <div v-if="selectedPending.match" class="match-banner"
               :class="'match-' + selectedPending.match.confidence_tier" style="flex:1">
            <template v-if="selectedPending.match.confidence_tier === 'strong'">
              ✓ Strong match — {{ selectedPending.match.winner }}
              <span class="match-score">({{ Math.round(selectedPending.match.vote_score * 100) }}%)</span>
            </template>
            <template v-else-if="selectedPending.match.confidence_tier === 'uncertain'">
              ~ Possible — {{ selectedPending.match.winner }}
              <span class="match-score">({{ Math.round(selectedPending.match.vote_score * 100) }}%)</span>
            </template>
            <template v-else>No match found</template>
          </div>
          <div v-else-if="selectedPending.matching" class="match-banner match-unknown" style="flex:1">
            <span class="mini-spin" /> Searching…
          </div>
          <div v-else class="match-banner match-unknown" style="flex:1">No match yet</div>
          <button class="btn-recheck" :disabled="reChecking" @click="reCheckMatch"
                  title="Re-check against Qdrant with current crop">
            <span v-if="reChecking" class="mini-spin" />
            <span v-else>↺</span>
          </button>
        </div>

        <label class="field-lbl">Product name *</label>
        <input ref="labelInput" v-model="form.product_name"
               list="lbl-sugg" class="field-inp"
               placeholder="Confirm or edit label…"
               @keydown.enter="acceptPending" />
        <datalist id="lbl-sugg">
          <option v-for="l in knownLabels" :key="l" :value="l" />
        </datalist>

        <label class="field-lbl">Pack type</label>
        <input v-model="form.pack_type" class="field-inp" placeholder="box, bottle, blister…" />

        <label class="field-lbl">Category</label>
        <input v-model="form.product_category" class="field-inp" placeholder="analgesic, vitamin…" />

        <label class="field-check">
          <input type="checkbox" v-model="form.company_product" /> Company product
        </label>

        <div v-if="saveError" class="save-err">{{ saveError }}</div>

        <div class="panel-actions">
          <button class="btn-save"
                  :disabled="saving || !form.product_name.trim()"
                  @click="acceptPending">
            {{ saving ? 'Saving…' : '✓ Accept & Save' }}
          </button>
          <button class="btn-delete" @click="dismissPending(selectedPending)">✕ Dismiss</button>
        </div>

        <div v-if="pendingBoxes.length > 1" class="pending-nav">
          <span class="pending-nav-label">{{ pendingBoxes.findIndex(p => p._pid === selectedPending._pid) + 1 }} / {{ pendingBoxes.length }}</span>
          <button class="btn-nav" @click="() => { const i = pendingBoxes.findIndex(p=>p._pid===selectedPending._pid); if(i>0) selectPending(pendingBoxes[i-1]) }">‹ Prev</button>
          <button class="btn-nav" @click="() => { const i = pendingBoxes.findIndex(p=>p._pid===selectedPending._pid); if(i<pendingBoxes.length-1) selectPending(pendingBoxes[i+1]) }">Next ›</button>
        </div>
      </template>

      <template v-else-if="pendingCoords !== null || selectedBox">
        <h3>{{ pendingCoords !== null ? 'New annotation' : 'Edit annotation' }}</h3>

        <!-- For new manual boxes: show crop + Qdrant match side by side -->
        <template v-if="pendingCoords !== null">
          <div class="preview-row">
            <div class="preview-col">
              <p class="preview-lbl">Crop</p>
              <canvas ref="cropCanvas" class="crop-preview-sm" width="100" height="90" />
            </div>
            <div v-if="manualMatch?.match_image_b64" class="preview-col">
              <p class="preview-lbl">Best match</p>
              <img :src="'data:image/jpeg;base64,' + manualMatch.match_image_b64"
                   class="crop-preview-sm match-img" />
            </div>
            <div v-else-if="manualMatching" class="preview-col match-searching">
              <p class="preview-lbl">Best match</p>
              <div class="match-spinner"><span class="mini-spin" /> Searching…</div>
            </div>
          </div>
          <div class="match-banner-row">
            <div v-if="manualMatch" class="match-banner" :class="'match-' + manualMatch.confidence_tier" style="flex:1">
              <template v-if="manualMatch.confidence_tier === 'strong'">
                ✓ Strong match — {{ manualMatch.winner }}
                <span class="match-score">({{ Math.round(manualMatch.vote_score * 100) }}%)</span>
              </template>
              <template v-else-if="manualMatch.confidence_tier === 'uncertain'">
                ~ Possible — {{ manualMatch.winner }}
                <span class="match-score">({{ Math.round(manualMatch.vote_score * 100) }}%)</span>
              </template>
              <template v-else>No match found</template>
            </div>
            <div v-else-if="manualMatching" class="match-banner match-unknown" style="flex:1">
              <span class="mini-spin" /> Searching Qdrant…
            </div>
            <div v-else class="match-banner match-unknown" style="flex:1">No match yet</div>
            <button class="btn-recheck" :disabled="reChecking || manualMatching" @click="reCheckManual"
                    title="Re-check current crop against Qdrant">
              <span v-if="reChecking" class="mini-spin" />
              <span v-else>↺</span>
            </button>
          </div>
        </template>
        <canvas v-else ref="cropCanvas" class="crop-preview" width="210" height="148" />

        <label class="field-lbl">Product name *</label>
        <input ref="labelInput" v-model="form.product_name"
               list="lbl-sugg" class="field-inp"
               placeholder="Start typing…"
               @keydown.enter="saveBox" />
        <datalist id="lbl-sugg">
          <option v-for="l in knownLabels" :key="l" :value="l" />
        </datalist>

        <label class="field-lbl">Pack type</label>
        <input v-model="form.pack_type" class="field-inp" placeholder="box, bottle, blister…" />

        <label class="field-lbl">Category</label>
        <input v-model="form.product_category" class="field-inp" placeholder="analgesic, vitamin…" />

        <label class="field-check">
          <input type="checkbox" v-model="form.company_product" /> Company product
        </label>

        <div v-if="saveError" class="save-err">{{ saveError }}</div>

        <div class="panel-actions">
          <button class="btn-save"
                  :disabled="saving || !form.product_name.trim()"
                  @click="saveBox">
            {{ saving ? 'Saving…' : pendingCoords !== null ? 'Add to Qdrant' : 'Update in Qdrant' }}
          </button>
          <button class="btn-cancel" @click="cancelEdit">Cancel</button>
          <button v-if="selectedBox" class="btn-delete" @click="deleteBox">Delete</button>
        </div>

        <p v-if="selectedBox" class="resize-hint">
          Drag corner/edge handles to resize, then click Update.
        </p>
      </template>

      <template v-else>
        <h3>Annotations <span class="count-badge">{{ boxes.length }}</span></h3>
        <div v-if="!activeShelf" class="panel-empty">Select a shelf image</div>
        <div v-else-if="loadingAnno" class="panel-empty">Loading…</div>
        <div v-else-if="!boxes.length" class="panel-empty">Draw boxes on the image to start</div>
        <div v-else class="box-list">
          <div v-for="box in boxes" :key="box.id"
               class="box-row" :class="{ active: selectedBox?.id === box.id }"
               @click="selectBoxById(box)">
            <span class="box-swatch" :style="{ background: hue(box.label) }" />
            <span class="box-lbl">{{ box.label }}</span>
          </div>
        </div>
      </template>
    </aside>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import {
  uploadShelf, listShelves, getShelfAnnotations, getAllLabels,
  shelfImageUrl, shelfThumbnailUrl, addCrop, deleteQdrantPoint,
  listDetectionModels, detectShelf, matchCrop,
} from '../api.js'

// ── DOM refs ──────────────────────────────────────────────────────────────────
const fileInput  = ref(null)
const viewportEl = ref(null)
const contentEl  = ref(null)
const imgEl      = ref(null)
const cropCanvas = ref(null)
const labelInput = ref(null)

// ── Data ──────────────────────────────────────────────────────────────────────
const shelves        = ref([])
const activeShelf    = ref(null)
const boxes          = ref([])
const knownLabels    = ref([])
const uploading      = ref(false)
const loadingAnno    = ref(false)
const saving         = ref(false)
const saveError      = ref('')

// ── Zoom to box ───────────────────────────────────────────────────────────────
function zoomToBox(x1, y1, x2, y2) {
  if (!viewportEl.value) return
  const vw = viewportEl.value.clientWidth
  const vh = viewportEl.value.clientHeight - 90   // toolbar clearance
  const bw = x2 - x1, bh = y2 - y1
  // Target: box fills ~30% of viewport so surrounding context is visible
  const newZoom = Math.max(0.15, Math.min(8, Math.min(vw / (bw * 3.2), vh / (bh * 3.2))))
  zoom.value = newZoom
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2
  panX.value = vw / 2 - cx * newZoom
  panY.value = vh / 2 - cy * newZoom + 50
}

// ── Detection ─────────────────────────────────────────────────────────────────
const detectionModels   = ref([{ id: 'manual', name: 'Manual only', type: 'manual', available: true, defaults: {} }])
const selectedModel     = ref('manual')
const confThreshold     = ref(0.25)
const textPrompts       = ref('')   // for yoloworld / groundingdino
const detecting         = ref(false)
const detectStatus      = ref('')   // human-readable result message
const pendingBoxes      = ref([])   // [{_pid, x1,y1,x2,y2,label,confidence}]
const selectedPending   = ref(null) // one item from pendingBoxes
const reChecking        = ref(false)
const manualMatch       = ref(null)   // match result for a manually drawn box
const manualMatching    = ref(false)
let   _pendingCounter   = 0

// ── IoU (frontend dedup) ──────────────────────────────────────────────────────
function _iou(a, b) {
  const ix1 = Math.max(a[0], b[0]), iy1 = Math.max(a[1], b[1])
  const ix2 = Math.min(a[2], b[2]), iy2 = Math.min(a[3], b[3])
  if (ix2 <= ix1 || iy2 <= iy1) return 0
  const inter = (ix2 - ix1) * (iy2 - iy1)
  const ua = (a[2]-a[0])*(a[3]-a[1]), ub = (b[2]-b[0])*(b[3]-b[1])
  const iou = inter / (ua + ub - inter)
  const iom = inter / Math.min(ua, ub)
  return Math.max(iou, iom)
}

const activeModelMeta = computed(() =>
  detectionModels.value.find(m => m.id === selectedModel.value) ?? {}
)
const needsPrompt = computed(() =>
  ['yoloworld', 'groundingdino'].includes(activeModelMeta.value.type)
)
const isSegModel = computed(() =>
  ['fastsam', 'yoloworld', 'groundingdino'].includes(activeModelMeta.value.type)
)

// ── Advanced model parameters (gear popover) ─────────────────────────────────
const ADV_DEFAULTS = { iou: 0.5, dedupeIou: 0.4, imgsz: 1024, minArea: 1500, maxAreaRatio: 0.12, minAspect: 0.20 }
const advOpen = ref(false)
const advParams = reactive({ ...ADV_DEFAULTS })

function resetAdvParams() {
  Object.assign(advParams, ADV_DEFAULTS)
}

// ── Image ──────────────────────────────────────────────────────────────────────
const imgLoaded = ref(false)
const imgW      = ref(0)
const imgH      = ref(0)

// ── Viewport transform ────────────────────────────────────────────────────────
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)

// ── Tools ─────────────────────────────────────────────────────────────────────
const tool = ref('draw')   // 'draw' | 'pan'

// ── Interaction state ─────────────────────────────────────────────────────────
let spaceHeld   = false
let isPanning   = false
let panStart    = null

let isDrawing   = false
let drawStart   = null      // image-space {x,y}
const drawRect  = ref(null) // {x,y,w,h} live while dragging

let resizeHandleId = null   // active handle id
let resizeOrigBox  = null   // [x1,y1,x2,y2] at resize start
let resizeStartImg = null   // image-space {x,y} at resize start

// ── Box editing ───────────────────────────────────────────────────────────────
const selectedBox   = ref(null)   // box object from boxes[]
const editingCoords = ref(null)   // [x1,y1,x2,y2] – live during resize
const pendingCoords = ref(null)   // [x1,y1,x2,y2] – new box before label

const form = ref({ product_name: '', pack_type: '', product_category: '', company_product: true })

// ── Computed ──────────────────────────────────────────────────────────────────
const contentStyle = computed(() => ({
  position: 'absolute',
  top: '0', left: '0',
  transformOrigin: '0 0',
  transform: `translate(${panX.value}px,${panY.value}px) scale(${zoom.value})`,
}))

// Cursor logic
const activeCursor = computed(() => {
  if (isPanning)               return 'grabbing'
  if (spaceHeld)               return 'grab'
  if (tool.value === 'pan')    return 'grab'
  if (isDrawing)               return 'crosshair'
  return 'crosshair'
})

// Scale-invariant sizes — divide by zoom so the value in image-space cancels
// the CSS transform scale, keeping everything the same size on screen.
const invZ      = computed(() => 1 / zoom.value)
const chipH     = computed(() => 18  * invZ.value)
const chipRx    = computed(() => 2   * invZ.value)
const chipFs    = computed(() => 11  * invZ.value)   // font-size for chip labels
const boxSW     = computed(() => 2   * invZ.value)   // confirmed box stroke-width
const pendingSW = computed(() => 1.5 * invZ.value)   // pending box stroke-width
const drawSW    = computed(() => 1.5 * invZ.value)   // drawing preview stroke-width

// Chip width in image-space for a given label string
function chipW(label) { return Math.max(60, (label || '').length * 6.8 + 12) * invZ.value }
function pendingChipText(p) {
  const lbl = p.label || '?'
  return p.confidence > 0 ? `${lbl}  ${Math.round(p.confidence * 100)}%` : lbl
}

// Resize handles for selected box
const HANDLE_SCREEN_R = 6   // fixed radius in screen pixels
const handleR = computed(() => Math.max(2, HANDLE_SCREEN_R / zoom.value))

const resizeHandles = computed(() => {
  const c = editingCoords.value
  if (!c) return []
  const [x1, y1, x2, y2] = c
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2
  return [
    { id: 'tl', x: x1, y: y1, cursor: 'nwse-resize' },
    { id: 'tc', x: mx, y: y1, cursor: 'ns-resize'   },
    { id: 'tr', x: x2, y: y1, cursor: 'nesw-resize' },
    { id: 'ml', x: x1, y: my, cursor: 'ew-resize'   },
    { id: 'mr', x: x2, y: my, cursor: 'ew-resize'   },
    { id: 'bl', x: x1, y: y2, cursor: 'nesw-resize' },
    { id: 'bc', x: mx, y: y2, cursor: 'ns-resize'   },
    { id: 'br', x: x2, y: y2, cursor: 'nwse-resize' },
  ]
})

// Return live coords for a confirmed box (uses editingCoords when selected)
function liveBox(box) {
  if (selectedBox.value?.id === box.id && editingCoords.value) return editingCoords.value
  return box.box
}

// Return live coords for a pending box (tracks resize via editingCoords)
function livePendingBox(p) {
  if (selectedPending.value?._pid === p._pid && editingCoords.value) return editingCoords.value
  return [p.x1, p.y1, p.x2, p.y2]
}

// ── Colours ───────────────────────────────────────────────────────────────────
function hue(label) {
  let h = 0
  for (const c of (label || '')) h = ((h << 5) - h) + c.charCodeAt(0)
  return `hsl(${Math.abs(h) % 360},65%,55%)`
}

// ── URL helpers ───────────────────────────────────────────────────────────────
function imageUrl(id)  { return shelfImageUrl(id) }
function thumbUrl(id)  { return shelfThumbnailUrl(id) }

// ── Load ──────────────────────────────────────────────────────────────────────
onMounted(async () => {
  await reloadShelves()
  const d = await getAllLabels().catch(() => ({ labels: [] }))
  knownLabels.value = d.labels

  // Load detection models
  listDetectionModels().then(r => {
    detectionModels.value = r.models
    // Pre-select the active archived model, else FastSAM-S
    const activeYolo = r.models.find(m => m.type === 'yolo_trained' && m.active)
    const anyYolo    = r.models.find(m => m.type === 'yolo_trained')
    const fastsam    = r.models.find(m => m.id === 'fastsam-s')
    const preferred  = activeYolo ?? anyYolo ?? fastsam
    selectedModel.value = preferred ? preferred.id : 'manual'
    const sel = r.models.find(m => m.id === selectedModel.value)
    if (sel?.defaults?.conf) confThreshold.value = sel.defaults.conf
  }).catch(() => {})

  const onKeyUp = e => { if (e.code === 'Space') spaceHeld = false }
  window.addEventListener('keyup', onKeyUp)
  onUnmounted(() => window.removeEventListener('keyup', onKeyUp))
})

async function reloadShelves() {
  const d = await listShelves().catch(() => ({ shelves: [] }))
  shelves.value = d.shelves
}

async function selectShelf(s) {
  activeShelf.value = s
  imgLoaded.value = false
  boxes.value = []
  pendingBoxes.value = []
  detectStatus.value = ''
  cancelEdit()
  loadingAnno.value = true
  const d = await getShelfAnnotations(s.shelf_id).catch(() => ({ annotations: [] }))
  boxes.value = d.annotations
  loadingAnno.value = false
}

// ── Detection ─────────────────────────────────────────────────────────────────
function onModelChange() {
  const meta = activeModelMeta.value
  if (meta?.defaults?.conf) confThreshold.value = meta.defaults.conf
  // Seed default text prompt for the newly selected model
  if (needsPrompt.value && !textPrompts.value)
    textPrompts.value = meta?.defaults?.text_prompts ?? ''
}

async function runDetection() {
  if (!activeShelf.value || detecting.value) return
  detecting.value = true
  detectStatus.value = ''
  pendingBoxes.value = []
  selectedPending.value = null
  try {
    const r = await detectShelf(activeShelf.value.shelf_id, {
      model:        selectedModel.value,
      confThreshold: confThreshold.value,
      textPrompts:  needsPrompt.value ? textPrompts.value : undefined,
      iou:          advParams.iou,
      dedupeIou:    advParams.dedupeIou,
      ...(isSegModel.value ? {
        imgsz:        advParams.imgsz,
        minArea:      advParams.minArea,
        maxAreaRatio: advParams.maxAreaRatio,
        minAspect:    advParams.minAspect,
      } : {}),
    })
    // Client-side dedup: drop candidates that overlap confirmed boxes the
    // backend may not know about (e.g. annotations without shelf_id in Qdrant)
    const confirmedBoxes = boxes.value.map(b => b.box)
    const deduped = r.candidates.filter(c => {
      const box = [c.x1, c.y1, c.x2, c.y2]
      return !confirmedBoxes.some(e => _iou(box, e) >= advParams.dedupeIou)
    })
    const backendSkipped = r.candidates.length - deduped.length

    pendingBoxes.value = deduped.map(c => ({
      ...c, _pid: ++_pendingCounter,
      match: null,
      matching: true,
    }))
    const totalSkipped = r.skipped + backendSkipped
    if (deduped.length === 0) {
      detectStatus.value = r.total_detected === 0
        ? 'No products detected'
        : `All ${r.total_detected} detections overlap existing annotations`
    } else {
      detectStatus.value = `${deduped.length} new candidate${deduped.length !== 1 ? 's' : ''}` +
        (totalSkipped ? ` · ${totalSkipped} already annotated` : '')
    }

    // Kick off DINOv2 matching for all candidates in parallel (background)
    const shelfId = activeShelf.value.shelf_id
    pendingBoxes.value.forEach(p => {
      matchCrop(shelfId, [p.x1, p.y1, p.x2, p.y2])
        .then(m => {
          const idx = pendingBoxes.value.findIndex(b => b._pid === p._pid)
          if (idx !== -1) {
            pendingBoxes.value[idx] = { ...pendingBoxes.value[idx], match: m, matching: false }
            // If this box is currently selected, update the form
            if (selectedPending.value?._pid === p._pid)
              _applyMatch(pendingBoxes.value[idx])
          }
        })
        .catch(() => {
          const idx = pendingBoxes.value.findIndex(b => b._pid === p._pid)
          if (idx !== -1)
            pendingBoxes.value[idx] = { ...pendingBoxes.value[idx], matching: false }
        })
    })
  } catch (err) {
    detectStatus.value = err?.response?.data?.detail ?? 'Detection failed'
  } finally {
    detecting.value = false
  }
}

function _applyMatch(p) {
  const m = p.match
  if (!m || m.confidence_tier === 'unknown') return
  // Only overwrite form if the user hasn't already typed something
  if (!form.value.product_name)
    form.value.product_name = m.payload?.product_name ?? ''
  if (!form.value.pack_type)
    form.value.pack_type = m.payload?.pack_type ?? ''
  if (!form.value.product_category)
    form.value.product_category = m.payload?.product_category ?? ''
  form.value.company_product = m.payload?.company_product ?? true
}

function selectPending(p) {
  selectedPending.value = p
  selectedBox.value     = null
  editingCoords.value   = [p.x1, p.y1, p.x2, p.y2]   // enables resize handles
  pendingCoords.value   = null
  drawRect.value        = null

  form.value = { product_name: p.label || '', pack_type: '', product_category: '', company_product: true }
  if (p.match) _applyMatch(p)

  nextTick(() => {
    updateCropPreviewFromCoords(editingCoords.value)
    zoomToBox(p.x1, p.y1, p.x2, p.y2)
    labelInput.value?.focus()
  })
}

// Re-check the current pending box against Qdrant (useful after resizing)
async function reCheckMatch() {
  const p = selectedPending.value
  if (!p || reChecking.value) return
  reChecking.value = true
  const coords = editingCoords.value ?? [p.x1, p.y1, p.x2, p.y2]
  try {
    const m = await matchCrop(activeShelf.value.shelf_id, coords)
    const idx = pendingBoxes.value.findIndex(b => b._pid === p._pid)
    if (idx !== -1) {
      pendingBoxes.value[idx] = { ...pendingBoxes.value[idx], match: m, matching: false }
      selectedPending.value   = pendingBoxes.value[idx]
      // Reset and re-apply so new suggestion fills the form
      form.value = { product_name: '', pack_type: '', product_category: '', company_product: true }
      _applyMatch(pendingBoxes.value[idx])
    }
  } catch { /* silently ignore */ }
  finally { reChecking.value = false }
}

async function reCheckManual() {
  if (!activeShelf.value || reChecking.value) return
  const coords = editingCoords.value ?? pendingCoords.value
  if (!coords) return
  reChecking.value = true
  try {
    const m = await matchCrop(activeShelf.value.shelf_id, coords)
    manualMatch.value = m
    if (m.confidence_tier !== 'unknown') {
      if (!form.value.product_name)     form.value.product_name     = m.payload?.product_name     ?? ''
      if (!form.value.pack_type)        form.value.pack_type        = m.payload?.pack_type        ?? ''
      if (!form.value.product_category) form.value.product_category = m.payload?.product_category ?? ''
      form.value.company_product = m.payload?.company_product ?? true
    }
  } catch { /* silently ignore */ }
  finally { reChecking.value = false }
}

function dismissPending(p) {
  const idx = pendingBoxes.value.findIndex(b => b._pid === p._pid)
  pendingBoxes.value = pendingBoxes.value.filter(b => b._pid !== p._pid)
  if (selectedPending.value?._pid === p._pid) {
    // Advance to next, or previous if this was the last one, or close if none left
    const next = pendingBoxes.value[idx] ?? pendingBoxes.value[idx - 1]
    if (next) selectPending(next)
    else selectedPending.value = null
  }
}

function dismissAllPending() {
  pendingBoxes.value = []
  selectedPending.value = null
}

async function acceptPending() {
  const p = selectedPending.value
  if (!p) return
  const name = form.value.product_name.trim()
  if (!name) return
  saving.value = true
  saveError.value = ''
  const coords = editingCoords.value ?? [p.x1, p.y1, p.x2, p.y2]
  try {
    const result = await addCrop({
      session_id:       activeShelf.value.shelf_id,
      box:              coords,
      product_name:     name,
      pack_type:        form.value.pack_type,
      product_category: form.value.product_category,
      company_product:  form.value.company_product,
      shelf_id:         activeShelf.value.shelf_id,
      shelf_box:        coords,
      shelf_w:          imgW.value,
      shelf_h:          imgH.value,
    })
    boxes.value.push({
      id:               result.point_id,
      label:            name,
      box:              coords,
      pack_type:        form.value.pack_type,
      product_category: form.value.product_category,
      company_product:  form.value.company_product,
    })
    const s = shelves.value.find(s => s.shelf_id === activeShelf.value.shelf_id)
    if (s) s.box_count = boxes.value.length
    if (!knownLabels.value.includes(name))
      knownLabels.value = [...knownLabels.value, name].sort()

    dismissPending(p)
  } catch (err) {
    saveError.value = err?.response?.data?.detail ?? 'Save failed'
  } finally {
    saving.value = false
  }
}

// ── Upload ────────────────────────────────────────────────────────────────────
async function onFileChange(e) {
  const file = e.target.files[0]; if (!file) return
  fileInput.value.value = ''
  uploading.value = true
  try {
    const result = await uploadShelf(file)
    await reloadShelves()
    const shelf = shelves.value.find(s => s.shelf_id === result.shelf_id)
    if (shelf) selectShelf(shelf)
  } catch (err) {
    alert(err?.response?.data?.detail ?? 'Upload failed')
  } finally {
    uploading.value = false
  }
}

// ── Image load + fit ──────────────────────────────────────────────────────────
function onImageLoad() {
  imgW.value = imgEl.value.naturalWidth
  imgH.value = imgEl.value.naturalHeight
  imgLoaded.value = true
  fitToScreen()
}

function fitToScreen() {
  if (!viewportEl.value || !imgW.value) return
  const vw = viewportEl.value.clientWidth
  const vh = viewportEl.value.clientHeight - 40   // leave room for toolbar
  const s  = Math.min(vw / imgW.value, vh / imgH.value) * 0.95
  zoom.value = s
  panX.value = (viewportEl.value.clientWidth  - imgW.value * s) / 2
  panY.value = (viewportEl.value.clientHeight - imgH.value * s) / 2 + 20
}

function zoomStep(dir) {
  const cx = viewportEl.value.clientWidth  / 2
  const cy = viewportEl.value.clientHeight / 2
  applyZoom(dir > 0 ? 1.25 : 0.8, cx, cy)
}

function applyZoom(factor, cx, cy) {
  const old   = zoom.value
  zoom.value  = Math.max(0.04, Math.min(10, old * factor))
  const ratio = zoom.value / old
  panX.value  = cx - ratio * (cx - panX.value)
  panY.value  = cy - ratio * (cy - panY.value)
}

function onWheel(e) {
  if (!imgLoaded.value) return
  const r = viewportEl.value.getBoundingClientRect()
  applyZoom(e.deltaY < 0 ? 1.15 : 0.87, e.clientX - r.left, e.clientY - r.top)
}

// ── Coordinate helpers ────────────────────────────────────────────────────────
function toImg(clientX, clientY) {
  const r = viewportEl.value.getBoundingClientRect()
  return {
    x: (clientX - r.left - panX.value) / zoom.value,
    y: (clientY - r.top  - panY.value) / zoom.value,
  }
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

function clampBox(x1, y1, x2, y2, minSize = 10) {
  const rx1 = clamp(Math.min(x1, x2 - minSize), 0, imgW.value - minSize)
  const rx2 = clamp(Math.max(x2, x1 + minSize), minSize, imgW.value)
  const ry1 = clamp(Math.min(y1, y2 - minSize), 0, imgH.value - minSize)
  const ry2 = clamp(Math.max(y2, y1 + minSize), minSize, imgH.value)
  return [Math.round(rx1), Math.round(ry1), Math.round(rx2), Math.round(ry2)]
}

// ── Keyboard ──────────────────────────────────────────────────────────────────
function onKeyDown(e) {
  if (e.code  === 'Space')  { spaceHeld = true; e.preventDefault(); return }
  if (e.key   === 'd' || e.key === 'D') { tool.value = 'draw'; return }
  if (e.key   === 'p' || e.key === 'P') { tool.value = 'pan';  return }
  if ((e.key  === 'Delete' || e.key === 'Backspace') && selectedBox.value) deleteBox()
  if (e.key   === 'Escape') cancelEdit()
}

// ── Mouse events ──────────────────────────────────────────────────────────────
// Called from the viewport background (NOT from boxes/handles which stop propagation)
function onViewportMouseDown(e) {
  if (!imgLoaded.value) return
  viewportEl.value.focus()
  cancelEdit()   // deselect when clicking canvas background

  const panGesture = spaceHeld || e.button === 1 || tool.value === 'pan'
  if (panGesture) {
    isPanning = true
    panStart  = { x: e.clientX - panX.value, y: e.clientY - panY.value }
    return
  }
  if (e.button !== 0) return

  // Start drawing
  const pt = toImg(e.clientX, e.clientY)
  isDrawing = true
  drawStart = pt
  drawRect.value = { x: pt.x, y: pt.y, w: 0, h: 0 }
}

// Called when user clicks an existing box
function onBoxMouseDown(box, e) {
  if (e.button !== 0) return
  const panGesture = spaceHeld || e.button === 1 || tool.value === 'pan'
  if (panGesture) {
    // let pan through
    isPanning = true
    panStart  = { x: e.clientX - panX.value, y: e.clientY - panY.value }
    return
  }
  selectBoxById(box)
}

// Called when user clicks a resize handle
function onHandleMouseDown(handleId, e) {
  if (e.button !== 0) return
  resizeHandleId = handleId
  resizeOrigBox  = [...editingCoords.value]
  resizeStartImg = toImg(e.clientX, e.clientY)
}

function onMouseMove(e) {
  // Pan
  if (isPanning && panStart) {
    panX.value = e.clientX - panStart.x
    panY.value = e.clientY - panStart.y
    return
  }

  // Resize
  if (resizeHandleId && resizeOrigBox && resizeStartImg) {
    const curr = toImg(e.clientX, e.clientY)
    const dx = curr.x - resizeStartImg.x
    const dy = curr.y - resizeStartImg.y
    const [ox1, oy1, ox2, oy2] = resizeOrigBox
    let [x1, y1, x2, y2] = [ox1, oy1, ox2, oy2]
    const h = resizeHandleId
    if (h === 'tl') { x1 = ox1+dx; y1 = oy1+dy }
    else if (h === 'tc') { y1 = oy1+dy }
    else if (h === 'tr') { x2 = ox2+dx; y1 = oy1+dy }
    else if (h === 'ml') { x1 = ox1+dx }
    else if (h === 'mr') { x2 = ox2+dx }
    else if (h === 'bl') { x1 = ox1+dx; y2 = oy2+dy }
    else if (h === 'bc') { y2 = oy2+dy }
    else if (h === 'br') { x2 = ox2+dx; y2 = oy2+dy }
    editingCoords.value = clampBox(x1, y1, x2, y2)
    nextTick(updateCropPreview)
    return
  }

  // Draw
  if (isDrawing && drawStart) {
    const pt = toImg(e.clientX, e.clientY)
    const x  = Math.min(drawStart.x, pt.x)
    const y  = Math.min(drawStart.y, pt.y)
    drawRect.value = {
      x, y,
      w: Math.abs(pt.x - drawStart.x),
      h: Math.abs(pt.y - drawStart.y),
    }
  }
}

function onMouseUp(e) {
  // End pan
  if (isPanning) { isPanning = false; panStart = null; return }

  // End resize
  if (resizeHandleId) {
    resizeHandleId = null; resizeOrigBox = null; resizeStartImg = null
    // Sync pendingCoords if this was a new drawn box being resized
    if (pendingCoords.value && editingCoords.value)
      pendingCoords.value = [...editingCoords.value]
    return
  }

  // End draw
  if (isDrawing) {
    isDrawing = false
    const r = drawRect.value
    if (!r || r.w < 8 || r.h < 8) { drawRect.value = null; return }

    pendingCoords.value  = clampBox(r.x, r.y, r.x + r.w, r.y + r.h)
    selectedBox.value    = null
    editingCoords.value  = [...pendingCoords.value]
    manualMatch.value    = null
    form.value = { product_name: '', pack_type: '', product_category: '', company_product: true }
    nextTick(() => { updateCropPreview(); labelInput.value?.focus() })

    // Auto-match drawn crop against Qdrant
    if (activeShelf.value) {
      manualMatching.value = true
      matchCrop(activeShelf.value.shelf_id, pendingCoords.value)
        .then(m => {
          manualMatch.value = m
          if (m.confidence_tier !== 'unknown') {
            if (!form.value.product_name)     form.value.product_name     = m.payload?.product_name     ?? ''
            if (!form.value.pack_type)        form.value.pack_type        = m.payload?.pack_type        ?? ''
            if (!form.value.product_category) form.value.product_category = m.payload?.product_category ?? ''
            form.value.company_product = m.payload?.company_product ?? true
          }
        })
        .catch(() => {})
        .finally(() => { manualMatching.value = false })
    }
  }
}

// ── Box selection ─────────────────────────────────────────────────────────────
function selectBoxById(box) {
  selectedBox.value     = box
  selectedPending.value = null
  editingCoords.value   = [...box.box]
  pendingCoords.value   = null
  drawRect.value        = null
  form.value = {
    product_name:     box.label,
    pack_type:        box.pack_type        || '',
    product_category: box.product_category || '',
    company_product:  box.company_product  ?? true,
  }
  nextTick(() => { updateCropPreview(); labelInput.value?.focus() })
}

function cancelEdit() {
  selectedBox.value     = null
  editingCoords.value   = null
  pendingCoords.value   = null
  drawRect.value        = null
  saveError.value       = ''
  selectedPending.value = null
  manualMatch.value     = null
  manualMatching.value  = false
}

// ── Crop preview ──────────────────────────────────────────────────────────────
function updateCropPreview() {
  const coords = pendingCoords.value ?? editingCoords.value
  if (coords) updateCropPreviewFromCoords(coords)
}

function updateCropPreviewFromCoords(coords) {
  const canvas = cropCanvas.value
  if (!canvas || !imgEl.value || !imgEl.value.complete) return
  const [x1, y1, x2, y2] = coords
  const bw = x2 - x1, bh = y2 - y1
  if (bw < 2 || bh < 2) return
  const cw = canvas.width, ch = canvas.height
  const s  = Math.min(cw / bw, ch / bh)
  const dw = bw * s,  dh = bh * s
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, cw, ch)
  ctx.fillStyle = '#0f1117'
  ctx.fillRect(0, 0, cw, ch)
  ctx.drawImage(imgEl.value, x1, y1, bw, bh, (cw - dw) / 2, (ch - dh) / 2, dw, dh)
}

// ── Save / Delete ─────────────────────────────────────────────────────────────
async function saveBox() {
  const name = form.value.product_name.trim()
  if (!name) return
  saving.value   = true
  saveError.value = ''

  const coords = pendingCoords.value ?? editingCoords.value
  if (!coords) { saving.value = false; return }

  try {
    // If editing existing box: delete old point first (re-embeds new crop)
    if (selectedBox.value) {
      await deleteQdrantPoint(selectedBox.value.id)
      boxes.value = boxes.value.filter(b => b.id !== selectedBox.value.id)
    }

    const result = await addCrop({
      session_id:       activeShelf.value.shelf_id,
      box:              coords,
      product_name:     name,
      pack_type:        form.value.pack_type,
      product_category: form.value.product_category,
      company_product:  form.value.company_product,
      shelf_id:         activeShelf.value.shelf_id,
      shelf_box:        coords,
      shelf_w:          imgW.value,
      shelf_h:          imgH.value,
    })

    const newBox = {
      id:              result.point_id,
      label:           name,
      box:             coords,
      pack_type:       form.value.pack_type,
      product_category: form.value.product_category,
      company_product: form.value.company_product,
    }
    boxes.value.push(newBox)

    // Update sidebar count
    const s = shelves.value.find(s => s.shelf_id === activeShelf.value.shelf_id)
    if (s) s.box_count = boxes.value.length

    if (!knownLabels.value.includes(name))
      knownLabels.value = [...knownLabels.value, name].sort()

    cancelEdit()
  } catch (err) {
    saveError.value = err?.response?.data?.detail ?? 'Save failed'
  } finally {
    saving.value = false
  }
}

async function deleteBox() {
  if (!selectedBox.value) return
  try {
    await deleteQdrantPoint(selectedBox.value.id)
    boxes.value = boxes.value.filter(b => b.id !== selectedBox.value.id)
    const s = shelves.value.find(s => s.shelf_id === activeShelf.value.shelf_id)
    if (s) s.box_count = boxes.value.length
    cancelEdit()
  } catch (err) {
    saveError.value = err?.response?.data?.detail ?? 'Delete failed'
  }
}
</script>

<style scoped>
.annotate-view {
  display: grid;
  grid-template-columns: 220px 1fr 250px;
  height: calc(100vh - 56px);
  overflow: hidden;
  background: #08090f;
}

/* ── Sidebar ── */
.shelf-sidebar { border-right: 1px solid #1f2338; display: flex; flex-direction: column; overflow: hidden; }
.sidebar-header { display: flex; align-items: center; gap: .5rem; padding: .7rem .8rem; border-bottom: 1px solid #1f2338; flex-shrink: 0; }
.sidebar-header h3 { font-size: .83rem; color: #aaa; flex: 1; margin: 0; }
.btn-upload { font-size: .72rem; padding: .22rem .55rem; background: #3949ab; color: #fff; border: none; border-radius: 5px; cursor: pointer; white-space: nowrap; }
.btn-upload:hover { background: #5c6bc0; }
.upload-status { font-size: .75rem; color: #7986cb; padding: .35rem .8rem; display: flex; align-items: center; gap: .4rem; }
.mini-spin { width: 11px; height: 11px; border: 2px solid #3a3f52; border-top-color: #7986cb; border-radius: 50%; animation: spin .7s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
.shelf-list { overflow-y: auto; flex: 1; padding: .35rem; }
.shelf-item { display: flex; gap: .55rem; align-items: center; padding: .45rem .55rem; border-radius: 7px; cursor: pointer; margin-bottom: .25rem; transition: background .13s; }
.shelf-item:hover { background: #13152a; }
.shelf-item.active { background: #1b1f3a; outline: 1px solid #3949ab; }
.shelf-thumb { width: 52px; height: 38px; object-fit: cover; border-radius: 4px; background: #1a1d2e; flex-shrink: 0; }
.shelf-meta { min-width: 0; }
.shelf-name { font-size: .75rem; color: #ccc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 0 0 .12rem; }
.shelf-boxes { font-size: .7rem; color: #666; margin: 0; }
.no-shelves { font-size: .78rem; color: #555; text-align: center; padding: 1.5rem .5rem; }

/* ── Canvas area ── */
.canvas-area { position: relative; overflow: hidden; background: #050609; outline: none; }
.canvas-content { display: inline-block; }

.toolbar {
  position: absolute; top: .5rem; left: 50%; transform: translateX(-50%);
  display: flex; align-items: center; gap: .35rem;
  background: rgba(12,14,24,.92); border: 1px solid #2a2e3f; border-radius: 10px;
  padding: .35rem .55rem; z-index: 10; backdrop-filter: blur(4px);
}
.tool-btn { font-size: .78rem; padding: .28rem .65rem; background: transparent; color: #888; border: 1px solid transparent; border-radius: 6px; cursor: pointer; transition: all .15s; }
.tool-btn:hover { background: #1a1d2e; color: #ccc; }
.tool-btn.active { background: #3949ab; color: #fff; border-color: #5c6bc0; }
.tsep { width: 1px; height: 18px; background: #2a2e3f; margin: 0 .15rem; }
.zoom-btn { width: 26px; height: 26px; background: transparent; border: none; color: #888; cursor: pointer; font-size: .9rem; border-radius: 5px; display: flex; align-items: center; justify-content: center; }
.zoom-btn:hover { background: #1a1d2e; color: #ccc; }
.zoom-label { font-size: .73rem; color: #666; min-width: 38px; text-align: center; }

.canvas-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #444; font-size: .9rem; }

/* SVG box styles — stroke/dash/size bound inline for zoom-invariance */
.chip-text { fill: #fff; font-family: sans-serif; }

/* Resize handles — stroke-width bound inline */
.resize-handle { fill: #fff; stroke: #3949ab; }
.resize-handle:hover { fill: #7986cb; }

/* ── Detection bar ── */
.detect-bar {
  position: absolute; top: 3rem; left: 50%; transform: translateX(-50%);
  display: flex; align-items: center; gap: .4rem;
  background: rgba(12,14,24,.92); border: 1px solid #2a2e3f; border-radius: 10px;
  padding: .28rem .55rem; z-index: 10; backdrop-filter: blur(4px);
  white-space: nowrap;
}
.detect-select { background: #0f1117; color: #ccc; border: 1px solid #2a2e3f; border-radius: 5px; font-size: .75rem; padding: .18rem .35rem; outline: none; cursor: pointer; }
.conf-label { font-size: .7rem; color: #666; }
.conf-input { width: 52px; background: #0f1117; color: #ccc; border: 1px solid #2a2e3f; border-radius: 5px; font-size: .75rem; padding: .18rem .35rem; outline: none; text-align: center; }
.prompt-input { width: 160px; background: #0f1117; color: #ccc; border: 1px solid #2a2e3f; border-radius: 5px; font-size: .75rem; padding: .18rem .45rem; outline: none; }
/* Advanced params popover */
.adv-params-wrap { position: relative; }
.btn-adv-params {
  font-size: .8rem; padding: .18rem .45rem; background: #0f1117; color: #888;
  border: 1px solid #2a2e3f; border-radius: 5px; cursor: pointer;
}
.btn-adv-params:hover { color: #ccc; }
.btn-adv-params.active { color: #7986cb; border-color: #5c6bc0; }
.adv-popover {
  position: absolute; top: calc(100% + 8px); right: 0; z-index: 30;
  background: #14172a; border: 1px solid #2a2e3f; border-radius: 9px;
  padding: .7rem .8rem; min-width: 230px;
  display: flex; flex-direction: column; gap: .45rem;
  box-shadow: 0 6px 24px rgba(0,0,0,.5);
  white-space: normal;
}
.adv-title { font-size: .7rem; color: #5c6bc0; text-transform: uppercase; letter-spacing: .05em; margin: 0; }
.adv-row { display: flex; align-items: center; gap: .5rem; justify-content: space-between; }
.adv-row label { font-size: .75rem; color: #999; cursor: help; }
.adv-row input {
  width: 70px; background: #0f1117; color: #ccc; border: 1px solid #2a2e3f;
  border-radius: 5px; font-size: .75rem; padding: .18rem .35rem; outline: none; text-align: center;
}
.adv-row input:focus { border-color: #5c6bc0; }
.btn-adv-reset {
  margin-top: .15rem; padding: .25rem .5rem; background: #1a1d2e; color: #888;
  border: 1px solid #2a2e3f; border-radius: 5px; cursor: pointer; font-size: .72rem;
}
.btn-adv-reset:hover { color: #ccc; }

.btn-detect { font-size: .75rem; padding: .22rem .6rem; background: #2e5e2e; color: #8bc88b; border: 1px solid #3a6e3a; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: .3rem; }
.btn-detect:hover:not(:disabled) { background: #3a7a3a; }
.btn-detect:disabled { opacity: .4; cursor: not-allowed; }
.detect-status { font-size: .7rem; color: #6a7090; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.detect-dismiss-all { font-size: .7rem; color: #c07830; cursor: pointer; border-bottom: 1px dashed #c07830; }
.detect-dismiss-all:hover { color: #e09040; }

/* Pending boxes — stroke/dash/size bound inline for zoom-invariance */

.hint-bar { position: absolute; bottom: .4rem; left: 50%; transform: translateX(-50%); display: flex; gap: 1rem; font-size: .68rem; color: #3a3e50; background: rgba(8,9,15,.75); padding: .22rem .8rem; border-radius: 20px; pointer-events: none; white-space: nowrap; }
.hint-confirmed { color: #4a6040; }
.hint-pending   { color: #806020; }

/* ── Label panel ── */
.label-panel { border-left: 1px solid #1f2338; padding: .85rem; overflow-y: auto; display: flex; flex-direction: column; gap: .5rem; }
.label-panel h3 { font-size: .88rem; color: #aaa; margin: 0 0 .2rem; }
.count-badge { background: #1f2338; color: #777; font-size: .7rem; padding: .1rem .38rem; border-radius: 10px; margin-left: .25rem; }
.crop-preview { width: 100%; height: 158px; background: #0a0c14; border-radius: 7px; display: block; }
.field-lbl { font-size: .72rem; color: #666; margin: 0; }
.field-inp { width: 100%; background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0; padding: .32rem .55rem; border-radius: 6px; font-size: .83rem; outline: none; box-sizing: border-box; }
.field-inp:focus { border-color: #5c6bc0; }
.field-check { display: flex; align-items: center; gap: .45rem; font-size: .8rem; color: #aaa; cursor: pointer; }
.field-check input { accent-color: #5c6bc0; }
.panel-actions { display: flex; gap: .35rem; flex-wrap: wrap; margin-top: .15rem; }
.btn-save { flex: 1; padding: .42rem .5rem; background: #3949ab; color: #fff; border: none; border-radius: 7px; cursor: pointer; font-size: .82rem; white-space: nowrap; }
.btn-save:hover:not(:disabled) { background: #5c6bc0; }
.btn-save:disabled { opacity: .4; cursor: not-allowed; }
.btn-cancel { padding: .42rem .55rem; background: #1a1d2e; color: #777; border: none; border-radius: 7px; cursor: pointer; font-size: .82rem; }
.btn-delete { padding: .42rem .55rem; background: rgba(231,76,60,.12); color: #e74c3c; border: none; border-radius: 7px; cursor: pointer; font-size: .82rem; }
.save-err { color: #ef5350; font-size: .75rem; }
.resize-hint { font-size: .72rem; color: #555; margin: 0; }
.panel-empty { color: #555; font-size: .8rem; }

.box-list { display: flex; flex-direction: column; gap: .25rem; }
.box-row { display: flex; align-items: center; gap: .45rem; padding: .32rem .45rem; border-radius: 6px; cursor: pointer; background: #0a0c14; transition: background .12s; }
.box-row:hover, .box-row.active { background: #13152a; }
.box-swatch { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.box-lbl { font-size: .8rem; color: #ccc; }

.review-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: .1rem; }
.btn-close-review { background: transparent; border: none; color: #555; font-size: .85rem; cursor: pointer; padding: .1rem .3rem; border-radius: 4px; line-height: 1; }
.btn-close-review:hover { color: #aaa; background: #1a1d2e; }

/* confidence badge on detection review header */
.conf-badge { font-size: .68rem; background: #2a2000; color: #e6a817; border: 1px solid #6a5010; padding: .08rem .4rem; border-radius: 10px; margin-left: .4rem; }
.yolo-prediction-banner { background: #1a2a1a; border: 1px solid #3a6a3a; color: #8bc98b; border-radius: 6px; padding: .4rem .6rem; font-size: .82rem; margin-bottom: .6rem; display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.pred-label { font-weight: 600; }
.pred-conf { font-size: .9rem; font-weight: 700; padding: .1rem .45rem; border-radius: 8px; font-variant-numeric: tabular-nums; }
.conf-high { background: rgba(46,204,113,.15); color: #2ecc71; }
.conf-mid  { background: rgba(243,156,18,.15); color: #f39c12; }
.conf-low  { background: rgba(231,76,60,.15);  color: #e74c3c; }

/* Crop + match reference previews */
.preview-row { display: flex; gap: .5rem; margin-bottom: .15rem; }
.preview-col { display: flex; flex-direction: column; align-items: center; gap: .2rem; flex: 1; min-width: 0; }
.preview-lbl { font-size: .65rem; color: #555; margin: 0; }
.crop-preview-sm { width: 100%; height: 90px; object-fit: contain; background: #0a0c14; border-radius: 6px; display: block; }
.match-img { border: 1px solid #3a3000; }
.match-searching { justify-content: center; }
.match-spinner { display: flex; align-items: center; gap: .35rem; font-size: .7rem; color: #666; height: 90px; }

/* Match confidence banner row */
.match-banner-row { display: flex; align-items: stretch; gap: .3rem; margin-bottom: .1rem; }
.match-banner { font-size: .73rem; padding: .3rem .55rem; border-radius: 6px; }
.btn-recheck { background: #1a1d2e; border: 1px solid #2a2e3f; color: #7986cb; border-radius: 6px; cursor: pointer; font-size: 1rem; padding: 0 .55rem; flex-shrink: 0; display: flex; align-items: center; }
.btn-recheck:hover:not(:disabled) { background: #252840; color: #aab4e8; }
.btn-recheck:disabled { opacity: .4; cursor: not-allowed; }
.match-strong   { background: rgba(46,125,50,.18); color: #81c784; border: 1px solid rgba(46,125,50,.4); }
.match-uncertain { background: rgba(230,168,23,.12); color: #e6a817; border: 1px solid rgba(230,168,23,.3); }
.match-unknown  { background: rgba(80,80,80,.12); color: #666; border: 1px solid #2a2e3f; }
.match-score { opacity: .7; margin-left: .25rem; }

/* pending nav (prev/next) */
.pending-nav { display: flex; align-items: center; gap: .35rem; margin-top: .25rem; }
.pending-nav-label { font-size: .72rem; color: #666; flex: 1; }
.btn-nav { font-size: .75rem; padding: .2rem .5rem; background: #1a1d2e; color: #888; border: none; border-radius: 6px; cursor: pointer; }
.btn-nav:hover { background: #252840; color: #ccc; }
</style>
