<template>
  <div class="label-manager">
    <LabelDetail v-if="detailLabel" :label="detailLabel"
                 @close="detailLabel = null"
                 @changed="onDetailChanged" />

    <div v-else-if="loading" class="loading">Analysing labels…</div>

    <template v-else>
      <!-- Duplicate suggestions -->
      <section v-if="suggestions.length" class="suggestions">
        <p class="section-title">⚠ Possible duplicates ({{ suggestions.length }})</p>
        <div v-for="(s, i) in suggestions" :key="i" class="suggestion-card">
          <div class="sugg-row">
            <div class="sugg-labels">
              <span class="sugg-reason" :class="s.reason">
                {{ s.reason === 'normalized' ? 'same text' : `${Math.round(s.similarity * 100)}% similar` }}
              </span>
              <label v-for="name in s.labels" :key="name" class="sugg-label"
                     :class="{ 'sugg-keep': suggTarget[i] === name }">
                <input type="radio" :name="'sugg-' + i" :value="name" v-model="suggTarget[i]" />
                <span class="sugg-name">{{ name }}</span>
                <span class="sugg-count">{{ countOf(name) }}</span>
              </label>
            </div>
            <button class="btn-expand" @click="expanded[i] = !expanded[i]">
              {{ expanded[i] ? '▲ Hide' : '▼ Compare' }}
            </button>
            <button class="btn-merge" :disabled="merging" @click="mergeSuggestion(i)">
              Merge → "{{ suggTarget[i] }}"
            </button>
          </div>
          <div v-if="expanded[i]" class="sugg-compare">
            <figure v-for="name in s.labels" :key="name" class="compare-fig"
                    :class="{ 'sugg-keep': suggTarget[i] === name }"
                    @click="suggTarget[i] = name">
              <img v-if="thumbs[name]" :src="thumbs[name]" :alt="name" />
              <div v-else class="no-thumb">no image</div>
              <figcaption>{{ name }} <span class="sugg-count">({{ countOf(name) }})</span></figcaption>
            </figure>
          </div>
        </div>
      </section>

      <!-- Manual merge bar -->
      <div v-if="selected.size" class="merge-bar">
        <span class="merge-info">{{ selected.size }} selected ({{ selectedPointCount }} entries)</span>
        <input v-model="mergeTarget" list="label-names" placeholder="Rename to… (pick or type new)" />
        <datalist id="label-names">
          <option v-for="l in labels" :key="l.name" :value="l.name" />
        </datalist>
        <button class="btn-merge" :disabled="!mergeTarget.trim() || merging" @click="mergeSelected">
          {{ merging ? 'Renaming…' : 'Rename' }}
        </button>
        <button class="btn-clear-sel" @click="selected.clear()">✕</button>
      </div>

      <!-- Label table -->
      <div class="table-head">
        <p class="section-title">All labels ({{ labels.length }} · {{ nPoints }} entries)</p>
        <input v-model="filter" class="filter-input" placeholder="Filter labels…" />
      </div>
      <table class="label-table">
        <thead>
          <tr><th class="col-check"></th><th>Label</th><th class="col-count">Entries</th><th class="col-analyse"></th></tr>
        </thead>
        <tbody>
          <template v-for="l in filteredLabels" :key="l.name">
            <tr :class="{ 'row-selected': selected.has(l.name) }" @click="toggle(l.name)">
              <td class="col-check"><input type="checkbox" :checked="selected.has(l.name)" @click.stop="toggle(l.name)" /></td>
              <td class="col-name">
                <a class="label-link" @click.stop="detailLabel = l.name"
                   title="Open detail view — browse crops, seeded split">{{ l.name }}</a>
              </td>
              <td class="col-count">{{ l.count }}</td>
              <td class="col-analyse">
                <button class="btn-analyse" :disabled="analysing === l.name"
                        @click.stop="analyse(l.name)"
                        title="Cluster this label's images to find sub-groups (e.g. SKU variants)">
                  {{ analysing === l.name ? '…' : (analysis?.label === l.name ? '▲' : '🔬') }}
                </button>
              </td>
            </tr>
            <tr v-if="analysis && analysis.label === l.name" class="analysis-row">
              <td colspan="4">
                <div class="analysis-panel">
                  <div class="analysis-head">
                    <span v-if="analysis.verdict === 'split_suggested'" class="verdict split">
                      ⚠ Sub-groups detected — consider splitting
                    </span>
                    <span v-else-if="analysis.verdict === 'not_enough_data'" class="verdict neutral">
                      {{ analysis.message }}
                    </span>
                    <span v-else class="verdict ok">✓ Looks coherent</span>
                    <span v-if="analysis.silhouette !== undefined && analysis.clusters.length > 1" class="analysis-meta">
                      {{ analysis.clusters.length }} clusters · separation {{ Math.round(analysis.silhouette * 100) }}%
                    </span>
                    <select v-model="clusterMode" class="mode-select" @change="analyse(l.name, true)"
                            title="What to cluster on: pack colour, overall appearance, or a blend">
                      <option value="hybrid">🎨+👁 Hybrid</option>
                      <option value="color">🎨 Colour</option>
                      <option value="visual">👁 Visual</option>
                    </select>
                    <button class="btn-close-analysis" @click="analysis = null">✕</button>
                  </div>
                  <div v-for="(c, ci) in analysis.clusters" :key="ci" class="cluster-row">
                    <div class="cluster-info">
                      <span class="cluster-size">{{ c.size }}×</span>
                      <span v-if="c.size <= 2" class="cluster-outlier">outlier — check for mis-tag</span>
                    </div>
                    <div class="cluster-thumbs">
                      <img v-for="(t, ti) in c.thumbs" :key="ti" :src="t" />
                    </div>
                    <div class="cluster-actions">
                      <input v-model="splitNames[ci]" :placeholder="`e.g. ${analysis.label} blue`"
                             @click.stop @keyup.enter="splitCluster(ci)" />
                      <button class="btn-split" :disabled="!splitNames[ci]?.trim() || splitting"
                              @click="splitCluster(ci)">Split off</button>
                    </div>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div v-if="message" class="msg" :class="messageType">{{ message }}</div>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { getLabels, renameLabels, clusterLabel, assignPoints } from '../api.js'
import LabelDetail from './LabelDetail.vue'

const emit = defineEmits(['changed'])

const loading = ref(true)
const labels = ref([])
const nPoints = ref(0)
const suggestions = ref([])
const thumbs = ref({})
const suggTarget = reactive({})   // suggestion index → label to keep
const expanded = reactive({})     // suggestion index → compare panel open
const selected = reactive(new Set())
const mergeTarget = ref('')
const merging = ref(false)
const filter = ref('')
const message = ref('')
const messageType = ref('ok')

const filteredLabels = computed(() => {
  const t = filter.value.trim().toLowerCase()
  if (!t) return labels.value
  return labels.value.filter(l => l.name.toLowerCase().includes(t))
})

const selectedPointCount = computed(() =>
  labels.value.filter(l => selected.has(l.name)).reduce((s, l) => s + l.count, 0)
)

function countOf(name) {
  return labels.value.find(l => l.name === name)?.count ?? 0
}

function toggle(name) {
  if (selected.has(name)) selected.delete(name)
  else selected.add(name)
}

async function load() {
  loading.value = true
  message.value = ''
  try {
    const d = await getLabels()
    labels.value = d.labels
    nPoints.value = d.n_points
    suggestions.value = d.suggestions
    thumbs.value = d.thumbs ?? {}
    // Default keep-target: the label with the most entries (first in group)
    Object.keys(expanded).forEach(k => delete expanded[k])
    d.suggestions.forEach((s, i) => { suggTarget[i] = s.labels[0] })
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Failed to load labels'
    messageType.value = 'error'
  } finally {
    loading.value = false
  }
}

async function doRename(fromLabels, toLabel) {
  merging.value = true
  message.value = ''
  try {
    const res = await renameLabels(fromLabels, toLabel)
    message.value = `Renamed ${res.updated} entries → "${toLabel}"`
    messageType.value = 'ok'
    selected.clear()
    mergeTarget.value = ''
    await load()
    emit('changed')
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Rename failed'
    messageType.value = 'error'
  } finally {
    merging.value = false
  }
}

function mergeSuggestion(i) {
  const s = suggestions.value[i]
  const keep = suggTarget[i]
  doRename(s.labels.filter(n => n !== keep), keep)
}

// Cluster analysis
const analysis = ref(null)
const analysing = ref(null)
const splitNames = reactive({})
const splitting = ref(false)
const clusterMode = ref('hybrid')
const detailLabel = ref(null)

async function onDetailChanged() {
  await load()
  emit('changed')
}

async function analyse(name, rerun = false) {
  if (!rerun && analysis.value?.label === name) { analysis.value = null; return }
  analysing.value = name
  message.value = ''
  try {
    analysis.value = await clusterLabel(name, clusterMode.value)
    Object.keys(splitNames).forEach(k => delete splitNames[k])
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Cluster analysis failed'
    messageType.value = 'error'
  } finally {
    analysing.value = null
  }
}

async function splitCluster(ci) {
  const target = splitNames[ci]?.trim()
  if (!target || !analysis.value) return
  splitting.value = true
  try {
    const res = await assignPoints(analysis.value.clusters[ci].point_ids, target)
    message.value = `Moved ${res.updated} entries → "${target}"`
    messageType.value = 'ok'
    analysis.value = null
    await load()
    emit('changed')
  } catch (e) {
    message.value = e?.response?.data?.detail ?? 'Split failed'
    messageType.value = 'error'
  } finally {
    splitting.value = false
  }
}

function mergeSelected() {
  const target = mergeTarget.value.trim()
  doRename([...selected].filter(n => n !== target), target)
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.label-manager { display: flex; flex-direction: column; gap: 1rem; }
.loading { color: #888; padding: 3rem 0; text-align: center; }
.section-title { font-size: .78rem; color: #5c6bc0; text-transform: uppercase; letter-spacing: .05em; }

/* Suggestions */
.suggestions { display: flex; flex-direction: column; gap: .6rem; }
.suggestion-card {
  background: #1f1a12; border: 1px solid #4a3a1a; border-radius: 8px;
  padding: .65rem .85rem; display: flex; flex-direction: column; gap: .65rem;
}
.sugg-row { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.sugg-labels { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; flex: 1; }
.sugg-reason { font-size: .7rem; padding: .12rem .45rem; border-radius: 8px; white-space: nowrap; }
.sugg-reason.normalized { background: rgba(243,156,18,.18); color: #f39c12; }
.sugg-reason.fuzzy { background: rgba(92,107,192,.18); color: #7986cb; }
.sugg-label {
  display: flex; align-items: center; gap: .35rem; cursor: pointer;
  background: #12151f; border: 1px solid #2a2e3f; border-radius: 6px; padding: .25rem .55rem;
}
.sugg-label.sugg-keep { border-color: #43a047; background: #0d1f10; }
.sugg-label input { accent-color: #43a047; }
.btn-expand {
  padding: .3rem .65rem; background: #12151f; color: #9aa6d4; border: 1px solid #2a2e3f;
  border-radius: 6px; cursor: pointer; font-size: .75rem; white-space: nowrap;
}
.btn-expand:hover { background: #1a1d2e; }

/* Compare fold-out */
.sugg-compare {
  display: flex; gap: 1rem; flex-wrap: wrap;
  border-top: 1px solid #3a2e14; padding-top: .65rem;
}
.compare-fig {
  display: flex; flex-direction: column; gap: .35rem; align-items: center;
  background: #12151f; border: 2px solid #2a2e3f; border-radius: 8px;
  padding: .5rem; cursor: pointer; transition: border-color .15s;
}
.compare-fig:hover { border-color: #4a5580; }
.compare-fig.sugg-keep { border-color: #43a047; background: #0d1f10; }
.compare-fig img {
  height: 220px; max-width: 280px; object-fit: contain; border-radius: 4px;
  background: #0a0c12;
}
.no-thumb {
  height: 220px; width: 160px; display: flex; align-items: center; justify-content: center;
  color: #555; font-size: .78rem; background: #0a0c12; border-radius: 4px;
}
.compare-fig figcaption { font-size: .82rem; color: #ddd; }
.sugg-name { font-size: .82rem; color: #ddd; }
.sugg-count { font-size: .72rem; color: #666; }

/* Merge bar */
.merge-bar {
  position: sticky; top: 0; z-index: 5;
  display: flex; align-items: center; gap: .6rem;
  background: #1a2433; border: 1px solid #2a4a6a; border-radius: 8px; padding: .6rem .85rem;
}
.merge-info { font-size: .82rem; color: #90caf9; white-space: nowrap; }
.merge-bar input {
  flex: 1; background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .35rem .6rem; border-radius: 6px; font-size: .85rem; outline: none;
}
.merge-bar input:focus { border-color: #5c6bc0; }
.btn-merge {
  padding: .35rem .8rem; background: #43a047; color: #fff; border: none;
  border-radius: 6px; cursor: pointer; font-size: .8rem; white-space: nowrap;
}
.btn-merge:hover:not(:disabled) { background: #4caf50; }
.btn-merge:disabled { opacity: .4; cursor: not-allowed; }
.btn-clear-sel {
  padding: .35rem .6rem; background: #2a2e3f; color: #aaa; border: none;
  border-radius: 6px; cursor: pointer; font-size: .8rem;
}

/* Table */
.table-head { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
.filter-input {
  background: #1a1d2e; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .35rem .65rem; border-radius: 6px; font-size: .82rem; outline: none; width: 200px;
}
.filter-input:focus { border-color: #5c6bc0; }
.label-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.label-table th {
  text-align: left; color: #555; font-weight: 500; font-size: .75rem;
  padding: .35rem .6rem; border-bottom: 1px solid #2a2e3f;
}
.label-table td { padding: .4rem .6rem; border-bottom: 1px solid #181b28; color: #ccc; }
.label-table tbody tr { cursor: pointer; transition: background .1s; }
.label-table tbody tr:hover { background: #1a1d2e; }
.row-selected { background: #16213a !important; }
.col-check { width: 32px; }
.col-check input { accent-color: #5c6bc0; }
.col-count { text-align: right; font-variant-numeric: tabular-nums; color: #888; width: 80px; }

.label-link { color: #c5cae9; cursor: pointer; border-bottom: 1px dotted #3a4060; }
.label-link:hover { color: #7986cb; border-bottom-color: #7986cb; }

.col-analyse { width: 44px; text-align: right; }
.btn-analyse {
  padding: .2rem .5rem; background: transparent; border: 1px solid #2a2e3f;
  border-radius: 5px; cursor: pointer; font-size: .8rem; color: #9aa6d4;
}
.btn-analyse:hover:not(:disabled) { background: #1a1d2e; }

/* Cluster analysis fold-out */
.analysis-row td { padding: 0 !important; }
.analysis-panel {
  background: #0d1018; border: 1px solid #2a3450; border-radius: 8px;
  margin: .35rem 0 .6rem; padding: .75rem; display: flex; flex-direction: column; gap: .6rem;
}
.analysis-head { display: flex; align-items: center; gap: .75rem; }
.verdict { font-size: .82rem; font-weight: 600; }
.verdict.split { color: #f39c12; }
.verdict.ok { color: #81c784; }
.verdict.neutral { color: #888; font-weight: 400; }
.analysis-meta { font-size: .75rem; color: #555; }
.mode-select {
  margin-left: auto; background: #12151f; border: 1px solid #2a2e3f; color: #9aa6d4;
  padding: .2rem .45rem; border-radius: 5px; font-size: .75rem; outline: none; cursor: pointer;
}
.mode-select:focus { border-color: #5c6bc0; }
.btn-close-analysis {
  padding: .15rem .5rem; background: #1a1d2e; color: #888;
  border: none; border-radius: 5px; cursor: pointer; font-size: .75rem;
}
.cluster-row {
  display: flex; align-items: center; gap: .75rem;
  background: #12151f; border: 1px solid #1f2338; border-radius: 7px; padding: .5rem .65rem;
}
.cluster-info { display: flex; flex-direction: column; gap: .2rem; min-width: 60px; }
.cluster-size { font-size: .95rem; font-weight: 700; color: #c5cae9; }
.cluster-outlier { font-size: .68rem; color: #ef9a9a; max-width: 90px; }
.cluster-thumbs { display: flex; gap: .35rem; flex: 1; overflow-x: auto; }
.cluster-thumbs img {
  height: 84px; width: 84px; object-fit: contain; border-radius: 4px;
  background: #0a0c12; flex-shrink: 0;
}
.cluster-actions { display: flex; gap: .4rem; align-items: center; flex-shrink: 0; }
.cluster-actions input {
  width: 180px; background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .3rem .55rem; border-radius: 6px; font-size: .8rem; outline: none;
}
.cluster-actions input:focus { border-color: #5c6bc0; }
.btn-split {
  padding: .3rem .65rem; background: #3949ab; color: #fff; border: none;
  border-radius: 6px; cursor: pointer; font-size: .78rem; white-space: nowrap;
}
.btn-split:hover:not(:disabled) { background: #5c6bc0; }
.btn-split:disabled { opacity: .4; cursor: not-allowed; }

.msg { font-size: .82rem; padding: .45rem .7rem; border-radius: 6px; }
.msg.ok { background: rgba(67,160,71,.12); color: #81c784; }
.msg.error { background: rgba(231,76,60,.12); color: #ef5350; }
</style>
