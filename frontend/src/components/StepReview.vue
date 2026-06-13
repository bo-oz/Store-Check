<template>
  <div class="review-step">
    <div class="header-row">
      <h2>Review detections</h2>
      <div class="summary-chips">
        <span class="chip correct">✅ {{ tally.correct }}</span>
        <span class="chip noise">🚫 {{ tally.noise }}</span>
        <span class="chip added">➕ {{ tally.added }}</span>
        <span class="chip skip">⏭ {{ tally.skip }}</span>
        <span class="chip total">{{ decisions.filter(d=>d).length }} / {{ results.length }}</span>
      </div>
    </div>

    <div v-if="searching" class="search-progress">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: `${searchProgress}%` }" />
      </div>
      <p>Searching Qdrant… {{ searchDone }} / {{ results.length }}
        <span v-if="autoApproved > 0" class="auto-note">· {{ autoApproved }} auto-approved</span>
      </p>
    </div>

    <div class="layout">
      <div class="canvas-col">
        <SegmentCanvas
          v-if="imageUrl"
          :imageUrl="imageUrl"
          :imageW="imageW"
          :imageH="imageH"
          :boxes="boxes"
          :results="results"
          v-model:current="currentIdx"
        />
        <div class="legend">
          <span class="dot" style="background:#f1c40f"></span> Selected
          <span class="dot" style="background:#2ecc71"></span> Matched ({{ matchTally.matched }})
          <span class="dot" style="background:#e74c3c"></span> No match ({{ matchTally.noMatch }})
          <span class="dot" style="background:#5c6bc0"></span> Pending ({{ matchTally.pending }})
        </div>
      </div>

      <div class="panel-col">
        <CropReviewPanel
          :result="results[currentIdx]"
          :newImage="newImage"
          @decide="onDecide"
        />
      </div>
    </div>

    <AddModal
      v-if="showAddModal && addModalResult"
      :imageUrl="imageUrl"
      :imageW="imageW"
      :imageH="imageH"
      :originalBox="addModalResult.box"
      :sessionId="sessionId"
      @cancel="showAddModal = false"
      @added="onAdded"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { runSearch, addCrop } from '../api.js'
import SegmentCanvas from './SegmentCanvas.vue'
import CropReviewPanel from './CropReviewPanel.vue'
import AddModal from './AddModal.vue'

const props = defineProps({
  sessionId: String,
  imageUrl: String,
  imageW: Number,
  imageH: Number,
  boxes: Array,
  labels: { type: Array, default: null },
  confidences: { type: Array, default: null },
  searchParams: Object,
  newImage: { type: Boolean, default: false },
})

const currentIdx = ref(0)
// If labels are provided (YOLOv8-SKU mode), pre-populate results as pre-labeled
const results = ref(props.boxes.map((box, i) => {
  if (props.labels) {
    return {
      box,
      crop_b64: null,
      top_score: props.confidences?.[i] ?? 1,
      matched: true,
      pre_labeled: true,
      label: props.labels[i],
      confidence: props.confidences?.[i] ?? null,
      hits: [],
    }
  }
  return null
}))
const decisions = ref(props.boxes.map(() => null))
const showAddModal = ref(false)

// Snapshot of the result when Add modal is opened — avoids reactive expression issues in props
const addModalResult = ref(null)

const searching = ref(false)
const searchDone = ref(0)
const searchProgress = computed(() =>
  props.boxes.length ? (searchDone.value / props.boxes.length) * 100 : 0
)

const autoApproved = computed(() => decisions.value.filter(x => x === 'correct').length)

const tally = computed(() => {
  const d = decisions.value
  return {
    correct: d.filter(x => x === 'correct').length,
    noise:   d.filter(x => x === 'noise').length,
    added:   d.filter(x => x === 'added').length,
    skip:    d.filter(x => x === 'skip').length,
  }
})

const matchTally = computed(() => {
  const r = results.value
  return {
    matched: r.filter(x => x?.matched === true).length,
    noMatch: r.filter(x => x?.matched === false).length,
    pending: r.filter(x => x === null).length,
  }
})

async function searchAll() {
  searching.value = true
  searchDone.value = 0
  // Run searches in chunks of 5 to show progress
  const CHUNK = 5
  for (let i = 0; i < props.boxes.length; i += CHUNK) {
    const chunk = props.boxes.slice(i, i + CHUNK)
    try {
      const resp = await runSearch({
        session_id: props.sessionId,
        boxes: chunk,
        top_k: props.searchParams.top_k,
        score_threshold: props.searchParams.score_threshold,
      })
      resp.results.forEach((r, j) => {
        results.value[i + j] = r
        // Auto-approve strong matches only when NOT in newImage mode
        if (!props.newImage && r.confidence_tier === 'strong') {
          decisions.value[i + j] = 'correct'
        }
      })
    } catch (e) {
      chunk.forEach((_, j) => {
        results.value[i + j] = { box: chunk[j], crop_b64: null, top_score: 0, matched: false, hits: [], error: true }
      })
    }
    searchDone.value = Math.min(i + CHUNK, props.boxes.length)
  }
  searching.value = false
}

async function onDecide(decision) {
  const idx = currentIdx.value
  const result = results.value[idx]

  if (decision === 'add') {
    addModalResult.value = result
    showAddModal.value = true
    return
  }

  // In newImage mode, "correct" on a matched crop → silently save to Qdrant
  if (decision === 'correct' && props.newImage && result?.winner) {
    try {
      await addCrop({
        session_id: props.sessionId,
        box: result.box,
        product_name: result.winner,
      })
      decisions.value[idx] = 'added'
    } catch {
      decisions.value[idx] = 'correct'
    }
  } else {
    decisions.value[idx] = decision
  }

  const next = findNextUndecided(idx)
  if (next !== null) currentIdx.value = next
}

function onAdded(result) {
  decisions.value[currentIdx.value] = 'added'
  showAddModal.value = false
  const next = findNextUndecided(currentIdx.value)
  if (next !== null) currentIdx.value = next
}

function findNextUndecided(from) {
  for (let i = from + 1; i < props.boxes.length; i++) {
    if (!decisions.value[i]) return i
  }
  for (let i = 0; i < from; i++) {
    if (!decisions.value[i]) return i
  }
  return null
}

onMounted(() => {
  if (!props.labels) {
    searchAll().then(() => {
      // After search, jump to first item that needs review
      const first = decisions.value.findIndex(d => !d)
      if (first !== -1) currentIdx.value = first
    })
  }
})
</script>

<style scoped>
.review-step { padding: 1.5rem; max-width: 1400px; margin: 0 auto; }
.header-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; flex-wrap: wrap; gap: .75rem; }
h2 { font-size: 1.4rem; color: #fff; }

.summary-chips { display: flex; gap: .5rem; flex-wrap: wrap; }
.chip { padding: .25rem .6rem; border-radius: 20px; font-size: .8rem; }
.chip.correct { background: rgba(46,204,113,.15); color: #2ecc71; }
.chip.noise   { background: rgba(231,76,60,.15);  color: #e74c3c; }
.chip.added   { background: rgba(241,196,15,.15); color: #f1c40f; }
.chip.skip    { background: rgba(92,107,192,.15); color: #7986cb; }
.chip.total   { background: #1a1d2e; color: #aaa; }

.search-progress { margin-bottom: 1rem; }
.progress-bar { background: #1a1d2e; border-radius: 4px; height: 6px; overflow: hidden; margin-bottom: .4rem; }
.progress-fill { background: #5c6bc0; height: 100%; transition: width .3s; }
.search-progress p { font-size: .8rem; color: #888; }
.auto-note { color: #43a047; }

.layout { display: grid; grid-template-columns: 1fr 420px; gap: 1.25rem; }
@media (max-width: 960px) { .layout { grid-template-columns: 1fr; } }

.legend { display: flex; align-items: center; gap: .75rem; margin-top: .75rem; font-size: .78rem; color: #888; flex-wrap: wrap; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
</style>
