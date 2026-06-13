<template>
  <div class="label-detail">
    <div class="detail-head">
      <button class="btn-back" @click="$emit('close')">← Back</button>
      <h3>{{ label }}</h3>
      <span class="detail-count">{{ points.length }} entries</span>
      <div class="click-mode">
        <button :class="{ active: clickMode === 'seed' }" @click="clickMode = 'seed'"
                title="Clicking crops assigns them as split seeds">🌱 Seed</button>
        <button :class="{ active: clickMode === 'select' }" @click="clickMode = 'select'"
                title="Clicking crops selects them for batch operations">☑ Select</button>
      </div>
      <div class="detail-opts">
        <select v-model="mode" class="mode-select">
          <option value="hybrid">🎨+👁 Hybrid</option>
          <option value="color">🎨 Colour</option>
          <option value="visual">👁 Visual</option>
        </select>
        <label class="shape-toggle" title="Include box aspect ratio (square vs portrait packs)">
          <input type="checkbox" v-model="useShape" /> 📐 Shape
        </label>
      </div>
    </div>

    <div v-if="loading" class="loading">Loading crops…</div>

    <template v-else>
      <!-- Seed groups -->
      <div v-if="clickMode === 'seed'" class="groups-bar">
        <div v-for="(g, gi) in groups" :key="gi" class="group-chip"
             :class="{ 'group-active': activeGroup === gi }"
             :style="{ '--gcolor': groupColors[gi % groupColors.length] }"
             @click="activeGroup = gi">
          <span class="group-dot"></span>
          <input v-model="g.name" @click.stop class="group-name-input" />
          <span class="group-seed-count">{{ g.ids.size }} seed{{ g.ids.size === 1 ? '' : 's' }}</span>
          <button v-if="groups.length > 2" class="btn-remove-group" @click.stop="removeGroup(gi)">✕</button>
        </div>
        <button class="btn-add-group" @click="addGroup">+ Group</button>
        <button class="btn-preview" :disabled="!canPreview || previewing" @click="preview">
          {{ previewing ? 'Splitting…' : '⚡ Preview split' }}
        </button>
      </div>
      <p class="seed-hint">
        {{ clickMode === 'seed'
           ? 'Select a group, then click example crops that belong to it. All other crops will be assigned to the most similar group.'
           : 'Click crops to select them, then move, edit or delete the selection in one go.' }}
      </p>

      <!-- Batch action bar -->
      <div v-if="clickMode === 'select' && selectedIds.size" class="batch-bar">
        <span class="batch-info">{{ selectedIds.size }} selected</span>
        <button class="btn-mini" @click="selectAll">All</button>
        <button class="btn-mini" @click="clearSelection">None</button>
        <span class="batch-sep"></span>
        <input v-model="batchTarget" list="all-label-names" placeholder="Move to class…"
               class="batch-input" @keyup.enter="batchMove" />
        <button class="btn-batch-move" :disabled="!batchTarget.trim() || batchBusy" @click="batchMove">↪ Move</button>
        <button class="btn-mini" :class="{ active: batchEditOpen }" @click="batchEditOpen = !batchEditOpen">✎ Edit</button>
        <button class="btn-batch-delete" :disabled="batchBusy" @click="batchDelete">
          {{ confirmingBatchDelete ? 'Really delete?' : '🗑 Delete' }}
        </button>
      </div>
      <div v-if="clickMode === 'select' && selectedIds.size && batchEditOpen" class="batch-edit">
        <input v-model="batchEdit.pack_type" placeholder="Pack type (blank = keep)" />
        <input v-model="batchEdit.product_category" placeholder="Category (blank = keep)" />
        <select v-model="batchEdit.company_product">
          <option value="">Own brand: keep</option>
          <option value="true">Own brand: yes</option>
          <option value="false">Own brand: no</option>
        </select>
        <button class="btn-batch-move" :disabled="batchBusy || !batchEditDirty" @click="batchApplyEdit">Apply to {{ selectedIds.size }}</button>
      </div>

      <!-- Preview result -->
      <div v-if="result" class="preview-result">
        <div v-for="(g, gi) in result.groups" :key="gi" class="result-row"
             :style="{ '--gcolor': groupColors[gi % groupColors.length] }">
          <div class="result-info">
            <span class="group-dot"></span>
            <span class="result-name">{{ g.name }}</span>
            <span class="result-size">{{ g.size }}×</span>
          </div>
          <div class="result-thumbs">
            <img v-for="(t, ti) in g.thumbs" :key="ti" :src="t" />
          </div>
        </div>
        <div class="apply-bar">
          <span class="apply-note">
            Applying renames {{ applySummary }}
          </span>
          <button class="btn-apply" :disabled="applying" @click="applySplit">
            {{ applying ? 'Applying…' : '✓ Apply split' }}
          </button>
          <button class="btn-cancel-preview" @click="result = null">Discard</button>
        </div>
      </div>

      <div v-if="message" class="msg" :class="messageType">{{ message }}</div>

      <!-- Crop grid -->
      <div class="crop-grid">
        <div v-for="p in points" :key="p.id" class="crop-cell"
             :class="{ seeded: clickMode === 'seed' && seedGroupOf(p.id) !== null,
                       selected: clickMode === 'select' && selectedIds.has(p.id) }"
             :style="clickMode === 'seed' && seedGroupOf(p.id) !== null ? { '--gcolor': groupColors[seedGroupOf(p.id) % groupColors.length] } : {}"
             @click="onCellClick(p.id)">
          <img :src="p.thumb" loading="lazy" />
          <span v-if="clickMode === 'seed' && seedGroupOf(p.id) !== null" class="seed-badge">{{ seedGroupOf(p.id) + 1 }}</span>
          <span v-if="clickMode === 'select' && selectedIds.has(p.id)" class="select-badge">✓</span>
          <span v-if="p.aspect" class="aspect-badge">{{ p.aspect >= 1.2 ? '▭' : (p.aspect <= 0.83 ? '▯' : '□') }}</span>
          <button class="btn-inspect" title="Inspect — zoom, edit, move, delete"
                  @click.stop="openInspector(p)">🔍</button>
        </div>
      </div>
    </template>

    <!-- Shared label autocomplete (used by batch move + inspector) -->
    <datalist id="all-label-names">
      <option v-for="n in allLabels" :key="n" :value="n" />
    </datalist>

    <!-- Inspector modal -->
    <div v-if="inspected" class="inspector-overlay" @mousedown.self="closeInspector">
      <div class="inspector">
        <div class="inspector-img-wrap"
             @wheel.prevent="onZoomWheel"
             @mousedown.prevent="startPan"
             @dblclick="resetZoom">
          <img :src="inspected.thumb" :style="zoomStyle" draggable="false" />
          <div class="zoom-controls">
            <button @click="zoomBy(1.5)">＋</button>
            <button @click="zoomBy(1 / 1.5)">－</button>
            <button @click="resetZoom" title="Reset (or double-click)">⟲</button>
            <span class="zoom-level">{{ Math.round(zoom * 100) }}%</span>
          </div>
          <p class="zoom-hint">scroll to zoom · drag to pan</p>
        </div>
        <div class="inspector-form">
          <h4>Entry {{ inspected.id }}</h4>
          <label class="ifield">
            <span>Product name</span>
            <input v-model="draft.product_name" list="all-label-names" />
          </label>
          <p v-if="draft.product_name.trim() && draft.product_name.trim() !== label" class="move-note">
            ↪ Saving moves this entry to "{{ draft.product_name.trim() }}"
          </p>
          <label class="ifield">
            <span>Pack type</span>
            <input v-model="draft.pack_type" />
          </label>
          <label class="ifield">
            <span>Category</span>
            <input v-model="draft.product_category" />
          </label>
          <label class="ifield checkbox">
            <input type="checkbox" v-model="draft.company_product" />
            <span>Own brand</span>
          </label>
          <div v-if="inspectorError" class="msg error">{{ inspectorError }}</div>
          <div class="inspector-actions">
            <button class="btn-save" :disabled="saving || !draft.product_name.trim()" @click="saveInspected">
              {{ saving ? 'Saving…' : (draft.product_name.trim() !== label ? '↪ Save & move' : 'Save') }}
            </button>
            <button class="btn-delete" :disabled="saving" @click="deleteInspected">
              {{ confirmingDelete ? 'Really delete?' : 'Delete' }}
            </button>
            <button class="btn-close" @click="closeInspector">Close</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { getLabelPoints, seededSplit, assignPoints, getAllLabels,
         updateQdrantPoint, deleteQdrantPoint,
         batchUpdatePoints, batchDeletePoints } from '../api.js'

const props = defineProps({ label: String })
const emit = defineEmits(['close', 'changed'])

const groupColors = ['#42a5f5', '#ef5350', '#66bb6a', '#ffa726', '#ab47bc', '#26c6da']

const loading = ref(true)
const points = ref([])
const mode = ref('hybrid')
const useShape = ref(true)
const groups = reactive([])
const activeGroup = ref(0)
const previewing = ref(false)
const result = ref(null)
const applying = ref(false)
const message = ref('')
const messageType = ref('ok')

const canPreview = computed(() => groups.filter(g => g.ids.size > 0).length >= 2)

const applySummary = computed(() => {
  if (!result.value) return ''
  return result.value.groups
    .filter(g => g.name.trim() && g.name.trim() !== props.label)
    .map(g => `${g.size} → "${g.name.trim()}"`)
    .join(', ') || 'nothing (all groups keep the current label)'
})

function addGroup() {
  groups.push({ name: `${props.label} ${groups.length + 1}`, ids: new Set() })
  activeGroup.value = groups.length - 1
}

function removeGroup(gi) {
  groups.splice(gi, 1)
  if (activeGroup.value >= groups.length) activeGroup.value = groups.length - 1
}

function seedGroupOf(id) {
  for (let i = 0; i < groups.length; i++) if (groups[i].ids.has(id)) return i
  return null
}

function toggleSeed(id) {
  const current = seedGroupOf(id)
  if (current === activeGroup.value) {
    groups[current].ids.delete(id)
  } else {
    if (current !== null) groups[current].ids.delete(id)
    groups[activeGroup.value].ids.add(id)
  }
  // Sets aren't deeply reactive — force update
  groups[activeGroup.value].ids = new Set(groups[activeGroup.value].ids)
}

async function preview() {
  previewing.value = true
  message.value = ''
  try {
    result.value = await seededSplit({
      label: props.label,
      groups: groups.filter(g => g.ids.size > 0)
                    .map(g => ({ name: g.name.trim(), point_ids: [...g.ids] })),
      mode: mode.value,
      useShape: useShape.value,
    })
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Split preview failed'
    messageType.value = 'error'
  } finally {
    previewing.value = false
  }
}

async function applySplit() {
  if (!result.value) return
  applying.value = true
  message.value = ''
  try {
    let moved = 0
    for (const g of result.value.groups) {
      const target = g.name.trim()
      if (!target || target === props.label) continue
      const res = await assignPoints(g.point_ids, target)
      moved += res.updated
    }
    message.value = `Done — ${moved} entries reassigned.`
    messageType.value = 'ok'
    result.value = null
    emit('changed')
    await load()
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Apply failed'
    messageType.value = 'error'
  } finally {
    applying.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const d = await getLabelPoints(props.label)
    points.value = d.points
  } finally {
    loading.value = false
  }
}

// ── Batch selection mode ─────────────────────────────────────────────────────
const clickMode = ref('seed')
const selectedIds = ref(new Set())
const batchTarget = ref('')
const batchBusy = ref(false)
const confirmingBatchDelete = ref(false)
const batchEditOpen = ref(false)
const batchEdit = reactive({ pack_type: '', product_category: '', company_product: '' })

const batchEditDirty = computed(() =>
  batchEdit.pack_type.trim() !== '' || batchEdit.product_category.trim() !== '' || batchEdit.company_product !== ''
)

function onCellClick(id) {
  if (clickMode.value === 'seed') { toggleSeed(id); return }
  const s = new Set(selectedIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selectedIds.value = s
  confirmingBatchDelete.value = false
}

function selectAll() { selectedIds.value = new Set(points.value.map(p => p.id)) }
function clearSelection() { selectedIds.value = new Set(); confirmingBatchDelete.value = false }

function removeFromGrid(ids) {
  const gone = new Set(ids)
  points.value = points.value.filter(p => !gone.has(p.id))
  groups.forEach(g => { ids.forEach(id => g.ids.delete(id)); g.ids = new Set(g.ids) })
  clearSelection()
}

async function batchMove() {
  const target = batchTarget.value.trim()
  if (!target || !selectedIds.value.size) return
  batchBusy.value = true
  message.value = ''
  try {
    const ids = [...selectedIds.value]
    const res = await assignPoints(ids, target)
    if (target !== props.label) removeFromGrid(ids)
    message.value = `Moved ${res.updated} entries → "${target}".`
    messageType.value = 'ok'
    batchTarget.value = ''
    emit('changed')
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Batch move failed'
    messageType.value = 'error'
  } finally {
    batchBusy.value = false
  }
}

async function batchApplyEdit() {
  if (!selectedIds.value.size || !batchEditDirty.value) return
  batchBusy.value = true
  message.value = ''
  try {
    const payload = {}
    if (batchEdit.pack_type.trim()) payload.pack_type = batchEdit.pack_type.trim()
    if (batchEdit.product_category.trim()) payload.product_category = batchEdit.product_category.trim()
    if (batchEdit.company_product !== '') payload.company_product = batchEdit.company_product === 'true'
    const ids = [...selectedIds.value]
    const res = await batchUpdatePoints(ids, payload)
    points.value.forEach(p => { if (selectedIds.value.has(p.id)) p.payload = { ...p.payload, ...payload } })
    message.value = `Updated ${res.updated} entries.`
    messageType.value = 'ok'
    batchEdit.pack_type = ''; batchEdit.product_category = ''; batchEdit.company_product = ''
    batchEditOpen.value = false
    emit('changed')
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Batch edit failed'
  } finally {
    batchBusy.value = false
  }
}

async function batchDelete() {
  if (!confirmingBatchDelete.value) { confirmingBatchDelete.value = true; return }
  batchBusy.value = true
  message.value = ''
  try {
    const ids = [...selectedIds.value]
    const res = await batchDeletePoints(ids)
    removeFromGrid(ids)
    message.value = `Deleted ${res.deleted} entries.`
    messageType.value = 'ok'
    emit('changed')
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Batch delete failed'
    messageType.value = 'error'
  } finally {
    batchBusy.value = false
    confirmingBatchDelete.value = false
  }
}

// ── Inspector (zoom, edit, move, delete) ─────────────────────────────────────
const inspected = ref(null)
const draft = reactive({ product_name: '', pack_type: '', product_category: '', company_product: true })
const allLabels = ref([])
const saving = ref(false)
const confirmingDelete = ref(false)
const inspectorError = ref('')

// Zoom / pan state
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const zoomStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
  cursor: zoom.value > 1 ? 'grab' : 'zoom-in',
}))

function openInspector(p) {
  inspected.value = p
  const pl = p.payload || {}
  draft.product_name = pl.product_name ?? props.label
  draft.pack_type = pl.pack_type ?? ''
  draft.product_category = pl.product_category ?? ''
  draft.company_product = pl.company_product ?? true
  confirmingDelete.value = false
  inspectorError.value = ''
  resetZoom()
}

function closeInspector() { inspected.value = null }

function zoomBy(f) {
  zoom.value = Math.min(12, Math.max(1, zoom.value * f))
  if (zoom.value === 1) { panX.value = 0; panY.value = 0 }
}

function resetZoom() { zoom.value = 1; panX.value = 0; panY.value = 0 }

function onZoomWheel(e) {
  zoomBy(e.deltaY < 0 ? 1.2 : 1 / 1.2)
}

function startPan(e) {
  if (zoom.value <= 1) { zoomBy(2); return }
  const sx = e.clientX - panX.value
  const sy = e.clientY - panY.value
  const move = ev => { panX.value = ev.clientX - sx; panY.value = ev.clientY - sy }
  const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

async function saveInspected() {
  if (!inspected.value) return
  saving.value = true
  inspectorError.value = ''
  const target = draft.product_name.trim()
  try {
    await updateQdrantPoint(inspected.value.id, {
      product_name: target,
      pack_type: draft.pack_type.trim(),
      product_category: draft.product_category.trim(),
      company_product: draft.company_product,
    })
    if (target !== props.label) {
      // Moved to another class — drop from this grid and any seed groups
      points.value = points.value.filter(p => p.id !== inspected.value.id)
      groups.forEach(g => { g.ids.delete(inspected.value.id); g.ids = new Set(g.ids) })
      message.value = `Entry moved to "${target}".`
      messageType.value = 'ok'
      emit('changed')
    } else {
      inspected.value.payload = { ...inspected.value.payload, ...draft }
      message.value = 'Entry updated.'
      messageType.value = 'ok'
    }
    closeInspector()
  } catch (e) {
    inspectorError.value = e?.response?.data?.detail ?? 'Save failed'
  } finally {
    saving.value = false
  }
}

async function deleteInspected() {
  if (!confirmingDelete.value) { confirmingDelete.value = true; return }
  saving.value = true
  inspectorError.value = ''
  try {
    await deleteQdrantPoint(inspected.value.id)
    points.value = points.value.filter(p => p.id !== inspected.value.id)
    groups.forEach(g => { g.ids.delete(inspected.value.id); g.ids = new Set(g.ids) })
    message.value = 'Entry deleted.'
    messageType.value = 'ok'
    emit('changed')
    closeInspector()
  } catch (e) {
    inspectorError.value = e?.response?.data?.detail ?? 'Delete failed'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  groups.push({ name: props.label, ids: new Set() })
  groups.push({ name: `${props.label} variant`, ids: new Set() })
  await load()
  try {
    const d = await getAllLabels()
    allLabels.value = d.labels ?? []
  } catch { }
})
</script>

<style scoped>
.label-detail { display: flex; flex-direction: column; gap: .85rem; }
.loading { color: #888; padding: 3rem 0; text-align: center; }

.detail-head { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.detail-head h3 { font-size: 1.1rem; color: #fff; margin: 0; }
.detail-count { font-size: .8rem; color: #666; }
.btn-back {
  padding: .3rem .7rem; background: #1a1d2e; color: #9aa6d4; border: 1px solid #2a2e3f;
  border-radius: 6px; cursor: pointer; font-size: .82rem;
}
.btn-back:hover { background: #232738; }
.detail-opts { margin-left: auto; display: flex; align-items: center; gap: .6rem; }
.mode-select {
  background: #12151f; border: 1px solid #2a2e3f; color: #9aa6d4;
  padding: .25rem .5rem; border-radius: 5px; font-size: .78rem; outline: none; cursor: pointer;
}
.shape-toggle { display: flex; align-items: center; gap: .3rem; font-size: .78rem; color: #9aa6d4; cursor: pointer; }
.shape-toggle input { accent-color: #5c6bc0; }

/* Groups bar */
.groups-bar { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.group-chip {
  display: flex; align-items: center; gap: .45rem;
  background: #12151f; border: 2px solid #2a2e3f; border-radius: 8px;
  padding: .35rem .6rem; cursor: pointer; transition: border-color .15s;
}
.group-chip.group-active { border-color: var(--gcolor); }
.group-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--gcolor); flex-shrink: 0; }
.group-name-input {
  background: transparent; border: none; outline: none; color: #ddd;
  font-size: .85rem; width: 140px; border-bottom: 1px dashed #2a2e3f;
}
.group-name-input:focus { border-bottom-color: #5c6bc0; }
.group-seed-count { font-size: .72rem; color: #666; white-space: nowrap; }
.btn-remove-group { background: none; border: none; color: #666; cursor: pointer; font-size: .75rem; padding: 0 .1rem; }
.btn-remove-group:hover { color: #ef5350; }
.btn-add-group {
  padding: .35rem .7rem; background: #1a1d2e; color: #9aa6d4; border: 1px dashed #2a2e3f;
  border-radius: 8px; cursor: pointer; font-size: .8rem;
}
.btn-preview {
  margin-left: auto; padding: .4rem .9rem; background: #5c6bc0; color: #fff; border: none;
  border-radius: 8px; cursor: pointer; font-size: .85rem; font-weight: 600;
}
.btn-preview:hover:not(:disabled) { background: #7986cb; }
.btn-preview:disabled { opacity: .4; cursor: not-allowed; }
.seed-hint { font-size: .75rem; color: #666; }

/* Click mode toggle */
.click-mode { display: flex; gap: 0; border: 1px solid #2a2e3f; border-radius: 7px; overflow: hidden; }
.click-mode button {
  padding: .3rem .7rem; background: #12151f; color: #888; border: none;
  cursor: pointer; font-size: .78rem; transition: all .12s;
}
.click-mode button.active { background: #2a2e3f; color: #fff; }
.click-mode button:hover:not(.active) { color: #ccc; }

/* Batch bar */
.batch-bar {
  position: sticky; top: 0; z-index: 5;
  display: flex; align-items: center; gap: .5rem; flex-wrap: wrap;
  background: #1a2433; border: 1px solid #2a4a6a; border-radius: 8px; padding: .55rem .8rem;
}
.batch-info { font-size: .84rem; color: #90caf9; font-weight: 600; white-space: nowrap; }
.batch-sep { width: 1px; height: 18px; background: #2a4a6a; }
.btn-mini {
  padding: .28rem .6rem; background: #12151f; color: #9aa6d4; border: 1px solid #2a2e3f;
  border-radius: 6px; cursor: pointer; font-size: .75rem;
}
.btn-mini:hover { background: #1f2433; }
.btn-mini.active { border-color: #5c6bc0; color: #fff; }
.batch-input {
  flex: 1; min-width: 160px; background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .32rem .6rem; border-radius: 6px; font-size: .82rem; outline: none;
}
.batch-input:focus { border-color: #5c6bc0; }
.btn-batch-move {
  padding: .32rem .7rem; background: #43a047; color: #fff; border: none;
  border-radius: 6px; cursor: pointer; font-size: .78rem; font-weight: 600; white-space: nowrap;
}
.btn-batch-move:hover:not(:disabled) { background: #4caf50; }
.btn-batch-move:disabled { opacity: .4; cursor: not-allowed; }
.btn-batch-delete {
  padding: .32rem .7rem; background: rgba(231,76,60,.15); color: #e74c3c; border: none;
  border-radius: 6px; cursor: pointer; font-size: .78rem; white-space: nowrap;
}
.btn-batch-delete:hover:not(:disabled) { background: rgba(231,76,60,.3); }
.batch-edit {
  display: flex; align-items: center; gap: .5rem; flex-wrap: wrap;
  background: #12151f; border: 1px solid #1f2338; border-radius: 8px; padding: .5rem .8rem;
}
.batch-edit input, .batch-edit select {
  background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .3rem .55rem; border-radius: 6px; font-size: .78rem; outline: none;
}
.batch-edit input:focus, .batch-edit select:focus { border-color: #5c6bc0; }

/* Selected cells */
.crop-cell.selected { border-color: #64b5f6; }
.select-badge {
  position: absolute; top: 3px; left: 3px;
  width: 18px; height: 18px; border-radius: 50%;
  background: #1976d2; color: #fff; font-size: .68rem; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}

/* Preview result */
.preview-result {
  background: #0d1018; border: 1px solid #2a3450; border-radius: 8px;
  padding: .75rem; display: flex; flex-direction: column; gap: .6rem;
}
.result-row {
  display: flex; align-items: center; gap: .75rem;
  background: #12151f; border: 1px solid #1f2338; border-left: 3px solid var(--gcolor);
  border-radius: 7px; padding: .5rem .65rem;
}
.result-info { display: flex; align-items: center; gap: .5rem; min-width: 180px; }
.result-name { font-size: .85rem; color: #ddd; font-weight: 600; }
.result-size { font-size: .8rem; color: #888; }
.result-thumbs { display: flex; gap: .35rem; flex: 1; overflow-x: auto; }
.result-thumbs img { height: 72px; width: 72px; object-fit: contain; border-radius: 4px; background: #0a0c12; flex-shrink: 0; }
.apply-bar { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.apply-note { font-size: .78rem; color: #90caf9; flex: 1; }
.btn-apply {
  padding: .4rem .9rem; background: #43a047; color: #fff; border: none;
  border-radius: 7px; cursor: pointer; font-size: .82rem; font-weight: 600;
}
.btn-apply:hover:not(:disabled) { background: #4caf50; }
.btn-apply:disabled { opacity: .4; cursor: not-allowed; }
.btn-cancel-preview {
  padding: .4rem .8rem; background: #2a2e3f; color: #aaa; border: none;
  border-radius: 7px; cursor: pointer; font-size: .8rem;
}

/* Crop grid */
.crop-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: .5rem;
}
.crop-cell {
  position: relative; background: #12151f; border: 2px solid #1f2338;
  border-radius: 6px; cursor: pointer; aspect-ratio: 1; overflow: hidden;
  transition: border-color .12s;
}
.crop-cell:hover { border-color: #4a5580; }
.crop-cell.seeded { border-color: var(--gcolor); }
.crop-cell img { width: 100%; height: 100%; object-fit: contain; }
.seed-badge {
  position: absolute; top: 3px; left: 3px;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--gcolor); color: #fff; font-size: .68rem; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.aspect-badge {
  position: absolute; bottom: 2px; right: 4px; font-size: .72rem; color: #667;
}
.btn-inspect {
  position: absolute; top: 3px; right: 3px;
  width: 22px; height: 22px; border-radius: 5px; border: none; cursor: pointer;
  background: rgba(10,12,18,.75); font-size: .7rem; padding: 0;
  opacity: 0; transition: opacity .12s;
  display: flex; align-items: center; justify-content: center;
}
.crop-cell:hover .btn-inspect { opacity: 1; }
.btn-inspect:hover { background: rgba(92,107,192,.6); }

/* Inspector modal */
.inspector-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.72); z-index: 300;
  display: flex; align-items: center; justify-content: center; padding: 2rem;
}
.inspector {
  background: #141722; border: 1px solid #2a2e3f; border-radius: 12px;
  display: flex; gap: 0; max-width: 980px; width: 100%; max-height: 86vh; overflow: hidden;
}
.inspector-img-wrap {
  flex: 1.6; position: relative; background: #0a0c12; overflow: hidden;
  display: flex; align-items: center; justify-content: center; min-height: 420px;
  user-select: none;
}
.inspector-img-wrap img {
  max-width: 100%; max-height: 82vh; object-fit: contain;
  transition: transform .08s ease-out; transform-origin: center center;
  image-rendering: auto;
}
.zoom-controls {
  position: absolute; top: .6rem; left: .6rem; display: flex; gap: .3rem; align-items: center;
  background: rgba(10,12,18,.8); border-radius: 7px; padding: .25rem .4rem;
}
.zoom-controls button {
  width: 26px; height: 26px; border: none; border-radius: 5px; cursor: pointer;
  background: #2a2e3f; color: #ddd; font-size: .85rem;
  display: flex; align-items: center; justify-content: center;
}
.zoom-controls button:hover { background: #3a3f52; }
.zoom-level { font-size: .72rem; color: #888; min-width: 38px; text-align: center; }
.zoom-hint {
  position: absolute; bottom: .5rem; left: 0; right: 0; text-align: center;
  font-size: .7rem; color: #556; pointer-events: none;
}
.inspector-form {
  flex: 1; padding: 1.1rem; display: flex; flex-direction: column; gap: .65rem;
  overflow-y: auto; border-left: 1px solid #1f2338;
}
.inspector-form h4 { font-size: .82rem; color: #667; font-weight: 500; margin: 0; }
.ifield { display: flex; flex-direction: column; gap: .25rem; }
.ifield > span { font-size: .75rem; color: #9aa6d4; }
.ifield input:not([type=checkbox]) {
  background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .4rem .6rem; border-radius: 6px; font-size: .85rem; outline: none;
}
.ifield input:focus { border-color: #5c6bc0; }
.ifield.checkbox { flex-direction: row; align-items: center; gap: .45rem; cursor: pointer; }
.ifield.checkbox span { color: #ccc; font-size: .82rem; }
.ifield.checkbox input { accent-color: #5c6bc0; }
.move-note {
  font-size: .75rem; color: #f39c12; background: rgba(243,156,18,.08);
  border: 1px solid rgba(243,156,18,.2); border-radius: 5px; padding: .3rem .5rem;
}
.inspector-actions { display: flex; gap: .5rem; margin-top: auto; padding-top: .75rem; flex-wrap: wrap; }
.btn-save {
  flex: 1; padding: .5rem .8rem; background: #43a047; color: #fff; border: none;
  border-radius: 7px; cursor: pointer; font-size: .82rem; font-weight: 600; white-space: nowrap;
}
.btn-save:hover:not(:disabled) { background: #4caf50; }
.btn-save:disabled { opacity: .4; cursor: not-allowed; }
.btn-delete {
  padding: .5rem .8rem; background: rgba(231,76,60,.15); color: #e74c3c; border: none;
  border-radius: 7px; cursor: pointer; font-size: .82rem; white-space: nowrap;
}
.btn-delete:hover:not(:disabled) { background: rgba(231,76,60,.3); }
.btn-close {
  padding: .5rem .8rem; background: #2a2e3f; color: #aaa; border: none;
  border-radius: 7px; cursor: pointer; font-size: .82rem;
}

.msg { font-size: .82rem; padding: .45rem .7rem; border-radius: 6px; }
.msg.ok { background: rgba(67,160,71,.12); color: #81c784; }
.msg.error { background: rgba(231,76,60,.12); color: #ef5350; }
</style>
