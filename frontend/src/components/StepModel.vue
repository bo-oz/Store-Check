<template>
  <div class="model-step">
    <h2>Configure detection</h2>

    <section class="card">
      <h3>Model</h3>
      <div class="model-groups">
        <div v-for="group in modelGroups" :key="group.type" class="model-group">
          <p class="group-label">{{ group.label }}</p>
          <div class="model-list">
            <label
              v-for="m in group.models"
              :key="m.key"
              class="model-card"
              :class="{ active: selected === m.key }"
            >
              <input type="radio" :value="m.key" v-model="selected" @change="applyDefaults(m)" />
              <span class="model-name">{{ m.key }}</span>
            </label>
          </div>
        </div>
      </div>
    </section>

    <!-- YOLOv8-SKU: training panel -->
    <section v-if="selectedType === 'yolov8sku'" class="card training-panel">
      <h3>SKU Model Training</h3>

      <!-- Training progress -->
      <div class="train-status" :class="training.status">
        <div class="status-row">
          <span v-if="['exporting','training'].includes(training.status)" class="spin-icon" />
          <span class="status-badge">{{ training.status }}</span>
          <span class="status-msg">{{ training.message }}</span>
          <span v-if="training.progress > 1 && ['exporting','training'].includes(training.status)" class="pct-label">
            {{ training.progress }}%
          </span>
        </div>
        <div v-if="['exporting','training'].includes(training.status)" class="progress-bar">
          <div class="progress-fill" :style="{ width: training.progress + '%' }"></div>
        </div>
        <div v-if="etaStr" class="eta-row"><span class="eta-label">{{ etaStr }}</span></div>
        <div v-if="training.status === 'error'" class="train-error">{{ training.message }}</div>
      </div>

      <!-- Model archive -->
      <div v-if="archivedModels.length" class="archive-section">
        <p class="archive-title">Trained models</p>
        <div class="archive-list">
          <div v-for="m in archivedModels" :key="m.stem"
               class="archive-row" :class="{ 'archive-active': m.active }">
            <div class="archive-info">
              <span class="archive-stem">{{ m.stem }}</span>
              <span v-if="m.active" class="active-badge">active</span>
              <span class="archive-meta">
                {{ m.n_classes }} classes
                <template v-if="m.best_map50"> · mAP50 {{ (m.best_map50 * 100).toFixed(1) }}%</template>
                <template v-if="m.best_map50_95"> · mAP50-95 {{ (m.best_map50_95 * 100).toFixed(1) }}%</template>
                <template v-if="m.trained_at"> · {{ new Date(m.trained_at).toLocaleDateString() }}</template>
                · {{ m.size_mb }} MB
              </span>
            </div>
            <div class="archive-actions">
              <button v-if="!m.active" class="btn-activate" :disabled="activating"
                      @click="activateArchived(m.stem)" title="Use this model for detection">
                {{ activating === m.stem ? '…' : '▶ Use' }}
              </button>
              <button v-if="!m.active" class="btn-delete-model" :disabled="activating"
                      @click="deleteArchived(m.stem)" title="Remove from archive">✕</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Train config -->
      <div v-if="!['exporting','training'].includes(training.status)" class="train-config">
        <div class="train-row">
          <label>Epochs</label>
          <input type="number" v-model.number="trainEpochs" min="5" max="300" />
        </div>
        <div class="train-row">
          <label>Base model</label>
          <select v-model="trainModel">
            <optgroup label="YOLOv8 (stable)">
              <option value="yolov8n.pt">YOLOv8n — nano, fastest</option>
              <option value="yolov8s.pt">YOLOv8s — small</option>
              <option value="yolov8m.pt">YOLOv8m — medium</option>
            </optgroup>
            <optgroup label="YOLO11 (recommended)">
              <option value="yolo11n.pt">YOLO11n — nano, fastest ★</option>
              <option value="yolo11s.pt">YOLO11s — small, good balance ★</option>
              <option value="yolo11m.pt">YOLO11m — medium, more accurate</option>
            </optgroup>
            <optgroup label="YOLO12 (latest, attention-based)">
              <option value="yolo12n.pt">YOLO12n — nano</option>
              <option value="yolo12s.pt">YOLO12s — small</option>
            </optgroup>
          </select>
          <span v-if="archivedModels.find(m => m.stem === trainModelStem)"
                class="already-trained-badge">already trained</span>
        </div>
        <div class="train-row">
          <label>Image size</label>
          <input type="number" v-model.number="trainImgsz" min="320" max="1280" step="32"
                 title="640 matches the tile size — keep at 640" />
        </div>
        <div class="train-row">
          <label>Batch size</label>
          <input type="number" v-model.number="trainBatch" min="1" max="64" />
        </div>
        <div class="train-row single-class-row">
          <label class="toggle-label">
            <input type="checkbox" v-model="trainSingleClass" />
            Single class mode
          </label>
          <span v-if="trainSingleClass" class="single-class-hint">
            All labels → "custom medicine package" — tests box detection only
          </span>
        </div>
        <div v-if="!trainSingleClass" class="train-row">
          <label>Min tiles / class</label>
          <input type="number" v-model.number="trainMinTiles" min="0" max="50" title="Classes appearing in fewer tiles than this are collapsed to 'medicine package'. 0 = disabled." />
          <span class="field-hint">{{ trainMinTiles === 0 ? 'disabled' : `< ${trainMinTiles} tiles → "medicine package"` }}</span>
        </div>
        <div v-if="!trainSingleClass" class="coverage-row">
          <button class="btn-coverage" @click="loadCoverage" :disabled="coverageLoading">
            {{ coverageLoading ? '…' : '📊 Class coverage report' }}
          </button>
          <span v-if="coverageError" class="coverage-error">{{ coverageError }}</span>
        </div>
        <div v-if="coverageData" class="coverage-panel">
          <div class="coverage-summary">
            <span class="cov-named">{{ coverageData.n_named }} named</span>
            <span class="cov-sep">·</span>
            <span class="cov-collapsed">{{ coverageData.n_collapsed }} → "medicine package"</span>
            <span class="cov-sep">·</span>
            <span class="cov-threshold">threshold: {{ coverageData.threshold }} tiles</span>
          </div>
          <div class="coverage-table-wrap">
            <table class="coverage-table">
              <thead><tr><th>Product name</th><th>Tiles</th><th>YOLO class</th></tr></thead>
              <tbody>
                <tr v-for="c in coverageData.coverage" :key="c.name" :class="c.named ? 'cov-row-named' : 'cov-row-fallback'">
                  <td class="cov-name">{{ c.name }}</td>
                  <td class="cov-count">{{ c.tile_count }}</td>
                  <td class="cov-class">
                    <span v-if="c.named" class="cov-badge-named">{{ c.name }}</span>
                    <span v-else class="cov-badge-fallback">medicine package</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-if="trainError" class="train-error">{{ trainError }}</div>
        <button class="btn-train" @click="triggerTraining">
          {{ archivedModels.find(m => m.stem === (trainModelStem + (trainSingleClass ? '-single' : ''))) ? '↺ Retrain' : 'Train' }}
          {{ trainModelStem }}{{ trainSingleClass ? ' (single class)' : '' }}
        </button>
      </div>

      <div v-if="!training.weights_exist && !archivedModels.length" class="no-weights">
        No trained weights found. Train a model to get started.
      </div>
    </section>

    <!-- YOLO-World: text prompts -->
    <section v-if="selectedType === 'yoloworld'" class="card">
      <h3>Detection prompts</h3>
      <p class="hint">Comma-separated list of what to look for in the image.</p>
      <textarea
        v-model="params.text_prompts"
        rows="3"
        placeholder="box, package, bottle, container"
      />
    </section>

    <section class="card">
      <h3>Model parameters</h3>
      <div class="param-grid">
        <Slider label="Confidence" v-model="params.conf" :min="0.05" :max="0.95" :step="0.05" />
        <Slider label="IOU (NMS)" v-model="params.iou" :min="0.1" :max="0.95" :step="0.05" />
        <Slider label="Image size" v-model="params.imgsz" :min="320" :max="2048" :step="32" :integer="true" />
      </div>
    </section>

    <section class="card">
      <h3>Geometry filter</h3>
      <div class="param-grid">
        <Slider label="Min box area (px²)" v-model="params.min_area" :min="100" :max="10000" :step="100" :integer="true" />
        <Slider label="Max area ratio" v-model="params.max_area_ratio" :min="0.01" :max="0.5" :step="0.01" />
        <Slider label="Min aspect ratio" v-model="params.min_aspect" :min="0.05" :max="0.9" :step="0.05" />
      </div>
    </section>

    <section class="card">
      <h3>Search threshold</h3>
      <div class="param-grid">
        <Slider label="Vote floor (min score)" v-model="params.score_threshold" :min="0.40" :max="0.85" :step="0.01" />
        <Slider label="Top-K results" v-model="params.top_k" :min="1" :max="10" :step="1" :integer="true" />
      </div>
    </section>

    <div v-if="error" class="error">{{ error }}</div>

    <button class="btn-primary" :disabled="loading" @click="run">
      <span v-if="loading">Running detection…</span>
      <span v-else>Run detection →</span>
    </button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchModels, runSegmentation, startTraining, getTrainingStatus, getModelInfo,
         listArchivedModels, activateModel, deleteArchivedModel, getClassCoverage } from '../api.js'
import Slider from './Slider.vue'

const props = defineProps({ sessionId: String })
const emit = defineEmits(['done'])

const models = ref([])
const selected = ref('fastsam-s')
const loading = ref(false)
const error = ref('')

// Training state
const training = ref({ status: 'idle', message: '', progress: 0, weights_exist: false, n_classes: 0, last_trained: null })
const trainEpochs = ref(60)
const trainModel = ref('yolo11s.pt')
const trainImgsz = ref(640)
const trainBatch = ref(8)
const trainSingleClass = ref(false)
const trainMinTiles = ref(5)
const trainError = ref('')

// Coverage report
const coverageData = ref(null)
const coverageLoading = ref(false)
const coverageError = ref('')

async function loadCoverage() {
  coverageLoading.value = true
  coverageError.value = ''
  coverageData.value = null
  try {
    coverageData.value = await getClassCoverage(trainMinTiles.value)
  } catch (e) {
    coverageError.value = e?.response?.data?.detail ?? 'Failed to load coverage'
  } finally {
    coverageLoading.value = false
  }
}

// Model archive
const archivedModels = ref([])
const activating = ref(null)  // stem currently being activated

const trainModelStem = computed(() => trainModel.value.replace(/\.pt$/, ''))

async function refreshArchive() {
  try {
    const d = await listArchivedModels()
    archivedModels.value = d.models
  } catch { }
}

async function activateArchived(stem) {
  activating.value = stem
  try {
    await activateModel(stem)
    await refreshArchive()
  } catch (e) {
    alert(e?.response?.data?.detail ?? 'Failed to activate model')
  } finally {
    activating.value = null
  }
}

async function deleteArchived(stem) {
  if (!confirm(`Delete model "${stem}" from archive?`)) return
  try {
    await deleteArchivedModel(stem)
    await refreshArchive()
  } catch (e) {
    alert(e?.response?.data?.detail ?? 'Failed to delete model')
  }
}
let _pollInterval = null
let _trainStartedAt = null   // local timestamp when training kicked off

// ETA tracking
const etaStr = ref('')

function _updateEta(progress) {
  if (!_trainStartedAt || progress <= 1) { etaStr.value = ''; return }
  const elapsed = (Date.now() - _trainStartedAt) / 1000   // seconds
  const fraction = progress / 100
  if (fraction <= 0) { etaStr.value = ''; return }
  const total = elapsed / fraction
  const remaining = Math.max(0, total - elapsed)
  etaStr.value = _fmtSecs(remaining)
}

function _fmtSecs(s) {
  if (s < 60) return `~${Math.round(s)}s remaining`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  if (m < 60) return `~${m}m ${sec}s remaining`
  const h = Math.floor(m / 60)
  return `~${h}h ${m % 60}m remaining`
}

async function refreshTrainingStatus() {
  try {
    training.value = await getTrainingStatus()
    if (['exporting', 'training'].includes(training.value.status)) {
      _updateEta(training.value.progress)
    } else {
      etaStr.value = ''
    }
  } catch { /* backend not ready */ }
}

async function loadModelInfo() {
  try {
    const info = await getModelInfo()
    if (info.n_classes) training.value.n_classes = info.n_classes
  } catch { }
}

function startPoll() {
  if (_pollInterval) return
  _pollInterval = setInterval(async () => {
    await refreshTrainingStatus()
    if (!['exporting', 'training'].includes(training.value.status)) {
      clearInterval(_pollInterval)
      _pollInterval = null
      _trainStartedAt = null
      await refreshArchive()   // refresh archive once training finishes
    }
  }, 2000)
}

async function triggerTraining() {
  trainError.value = ''
  training.value = { ...training.value, status: 'exporting', message: 'Starting…', progress: 1 }
  try {
    await startTraining({
      epochs: trainEpochs.value,
      base_model: trainModel.value,
      imgsz: trainImgsz.value,
      batch: trainBatch.value,
      single_class: trainSingleClass.value ? 'custom medicine package' : '',
      min_tiles_for_class: trainSingleClass.value ? 0 : trainMinTiles.value,
    })
    _trainStartedAt = Date.now()
    etaStr.value = ''
    await refreshTrainingStatus()
    startPoll()
  } catch (e) {
    trainError.value = e?.response?.data?.detail ?? 'Failed to start training'
  }
}

onUnmounted(() => { if (_pollInterval) clearInterval(_pollInterval) })

const params = ref({
  conf: 0.55,
  iou: 0.80,
  imgsz: 1024,
  min_area: 1500,
  max_area_ratio: 0.12,
  min_aspect: 0.20,
  score_threshold: 0.55,
  top_k: 3,
  text_prompts: 'medicine box, pharmaceutical package, drug box, supplement bottle',
})

const selectedModel = computed(() => models.value.find(m => m.key === selected.value))
const selectedType  = computed(() => selectedModel.value?.type ?? 'fastsam')

const modelGroups = computed(() => {
  const groups = {}
  for (const m of models.value) {
    if (!groups[m.type]) groups[m.type] = []
    groups[m.type].push(m)
  }
  return [
    { type: 'fastsam',       label: 'FastSAM — segment everything',                      models: groups['fastsam']       ?? [] },
    { type: 'yoloworld',    label: 'YOLO-World — text-prompted detection',               models: groups['yoloworld']     ?? [] },
    { type: 'groundingdino', label: 'Grounding DINO — pharma-optimised open-vocabulary', models: groups['groundingdino'] ?? [] },
    { type: 'yolov8sku',     label: 'YOLOv8-SKU — trained on your Qdrant collection',   models: groups['yolov8sku']     ?? [] },
  ].filter(g => g.models.length)
})

onMounted(async () => {
  try {
    const data = await fetchModels()
    models.value = data.models
    if (data.models.length) applyDefaults(data.models[0])
    const gd = data.geometry_defaults
    params.value.min_area = gd.min_area
    params.value.max_area_ratio = gd.max_area_ratio
    params.value.min_aspect = gd.min_aspect
  } catch {
    // backend might not be running in preview
  }
  await refreshTrainingStatus()
  await loadModelInfo()
  await refreshArchive()
  if (['exporting', 'training'].includes(training.value.status)) startPoll()
})

function applyDefaults(model) {
  selected.value = model.key
  params.value.conf  = model.defaults.conf
  params.value.iou   = model.defaults.iou
  params.value.imgsz = model.defaults.imgsz
  if (model.defaults.text_prompts) {
    params.value.text_prompts = model.defaults.text_prompts
  }
}

async function run() {
  loading.value = true
  error.value = ''
  try {
    const payload = {
      session_id: props.sessionId,
      model: selected.value,
      conf: params.value.conf,
      iou: params.value.iou,
      imgsz: params.value.imgsz,
      min_area: params.value.min_area,
      max_area_ratio: params.value.max_area_ratio,
      min_aspect: params.value.min_aspect,
    }
    if (selectedType.value === 'yoloworld') {
      payload.text_prompts = params.value.text_prompts
    }
    const result = await runSegmentation(payload)
    emit('done', {
      boxes: result.boxes,
      labels: result.labels || null,
      confidences: result.confidences || null,
      searchParams: { top_k: params.value.top_k, score_threshold: params.value.score_threshold },
    })
  } catch (e) {
    error.value = e?.response?.data?.detail ?? 'Detection failed'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.model-step { max-width: 720px; margin: 0 auto; padding: 2rem; }
h2 { font-size: 1.4rem; margin-bottom: 1.5rem; color: #fff; }
h3 { font-size: 1rem; color: #aaa; margin-bottom: .75rem; }
.card { background: #1a1d2e; border-radius: 10px; padding: 1.25rem; margin-bottom: 1rem; }

.model-groups { display: flex; flex-direction: column; gap: 1rem; }
.group-label { font-size: .78rem; color: #5c6bc0; text-transform: uppercase; letter-spacing: .05em; margin-bottom: .4rem; }
.model-list { display: flex; gap: .6rem; flex-wrap: wrap; }
.model-card {
  display: flex; align-items: center; gap: .5rem;
  background: #0f1117; border: 2px solid #2a2e3f;
  border-radius: 8px; padding: .5rem .9rem; cursor: pointer;
  transition: border-color .2s;
}
.model-card.active { border-color: #5c6bc0; }
.model-card input { accent-color: #5c6bc0; }
.model-name { font-size: .9rem; font-family: monospace; }

.hint { font-size: .78rem; color: #666; margin-bottom: .5rem; }
textarea {
  width: 100%; background: #0f1117; border: 1px solid #2a2e3f;
  color: #e0e0e0; padding: .5rem .7rem; border-radius: 6px; font-size: .88rem;
  outline: none; resize: vertical; font-family: inherit; box-sizing: border-box;
  transition: border-color .15s;
}
textarea:focus { border-color: #5c6bc0; }

.param-grid { display: grid; gap: .75rem; }
.error { color: #ef5350; margin-bottom: .75rem; font-size: .9rem; }
.btn-primary {
  width: 100%; padding: .75rem;
  background: #5c6bc0; color: #fff; border: none; border-radius: 8px;
  font-size: 1rem; cursor: pointer; transition: background .2s;
}
.btn-primary:hover:not(:disabled) { background: #7986cb; }
.btn-primary:disabled { opacity: .4; cursor: not-allowed; }

/* Training panel */
.training-panel { border-left: 3px solid #5c6bc0; }
.train-status { margin-bottom: 1rem; }
.status-row { display: flex; align-items: center; gap: .6rem; margin-bottom: .4rem; }
.status-badge {
  font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
  padding: .15rem .45rem; border-radius: 4px; background: #2a2e3f; color: #aaa;
}
.train-status.training .status-badge,
.train-status.exporting .status-badge { background: #5c6bc0; color: #fff; }
.train-status.done .status-badge { background: #43a047; color: #fff; }
.train-status.error .status-badge { background: #ef5350; color: #fff; }
.status-msg { font-size: .85rem; color: #ccc; flex: 1; min-width: 0; }
.pct-label { font-size: .82rem; color: #7986cb; font-variant-numeric: tabular-nums; white-space: nowrap; margin-left: auto; }
.progress-bar { height: 8px; background: #2a2e3f; border-radius: 4px; overflow: hidden; margin-bottom: .35rem; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #3949ab, #7986cb); transition: width .6s ease; }
.eta-row { margin-bottom: .4rem; }
.eta-label { font-size: .78rem; color: #888; font-style: italic; }
.train-meta { font-size: .78rem; color: #666; }
.train-error { color: #ef5350; font-size: .82rem; margin-top: .4rem; }

.spin-icon {
  width: 14px; height: 14px; flex-shrink: 0;
  border: 2px solid rgba(92,107,192,.35);
  border-top-color: #7986cb;
  border-radius: 50%;
  animation: spin .8s linear infinite;
  display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }
.no-weights { font-size: .82rem; color: #ef9a9a; margin-top: .75rem; }
.train-config { display: flex; flex-direction: column; gap: .6rem; }
.train-row { display: flex; align-items: center; gap: .75rem; }
.train-row label { width: 90px; font-size: .82rem; color: #aaa; flex-shrink: 0; }
.train-row input, .train-row select {
  flex: 1; background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .35rem .6rem; border-radius: 6px; font-size: .88rem; outline: none;
}
.train-row input:focus, .train-row select:focus { border-color: #5c6bc0; }
.btn-train {
  margin-top: .25rem; padding: .55rem 1rem;
  background: #3949ab; color: #fff; border: none; border-radius: 8px;
  font-size: .9rem; cursor: pointer; transition: background .2s; align-self: flex-start;
}
.btn-train:hover { background: #5c6bc0; }

/* Model archive */
.archive-section { margin-bottom: 1.25rem; }
.archive-title { font-size: .75rem; color: #666; text-transform: uppercase; letter-spacing: .06em; margin-bottom: .5rem; }
.archive-list { display: flex; flex-direction: column; gap: .4rem; }
.archive-row {
  display: flex; align-items: center; justify-content: space-between;
  background: #12151f; border: 1px solid #1f2338; border-radius: 7px;
  padding: .5rem .75rem; gap: .75rem;
}
.archive-row.archive-active { border-color: #3d5a80; background: #0d1a2a; }
.archive-info { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; min-width: 0; }
.archive-stem { font-size: .88rem; font-weight: 600; color: #c5cae9; white-space: nowrap; }
.active-badge { font-size: .7rem; background: #1a3a5c; color: #64b5f6; border: 1px solid #2a5a8c; border-radius: 10px; padding: .05rem .45rem; }
.archive-meta { font-size: .75rem; color: #555; white-space: nowrap; }
.archive-actions { display: flex; gap: .35rem; flex-shrink: 0; }
.btn-activate {
  font-size: .75rem; padding: .2rem .55rem; border-radius: 5px; border: none; cursor: pointer;
  background: rgba(92,107,192,.15); color: #7986cb; transition: background .15s;
}
.btn-activate:hover:not(:disabled) { background: rgba(92,107,192,.3); }
.btn-delete-model {
  font-size: .75rem; padding: .2rem .5rem; border-radius: 5px; border: none; cursor: pointer;
  background: rgba(231,76,60,.1); color: #e57373; transition: background .15s;
}
.btn-delete-model:hover:not(:disabled) { background: rgba(231,76,60,.25); }

/* Single class mode */
.single-class-row { flex-wrap: wrap; padding: .25rem 0; }
.toggle-label { display: flex; align-items: center; gap: .4rem; cursor: pointer; font-size: .82rem; color: #aaa; white-space: nowrap; }
.toggle-label input[type=checkbox] { accent-color: #5c6bc0; width: 14px; height: 14px; }
.single-class-hint { font-size: .75rem; color: #f39c12; background: rgba(243,156,18,.08); border: 1px solid rgba(243,156,18,.2); border-radius: 5px; padding: .2rem .5rem; }

/* field inline hint */
.field-hint { font-size: .75rem; color: #666; white-space: nowrap; }

/* Coverage report */
.coverage-row { display: flex; align-items: center; gap: .6rem; }
.btn-coverage {
  font-size: .78rem; padding: .25rem .7rem; border-radius: 6px; border: 1px solid #2a2e3f;
  background: #12151f; color: #7986cb; cursor: pointer; transition: background .15s;
}
.btn-coverage:hover:not(:disabled) { background: #1a1d2e; }
.btn-coverage:disabled { opacity: .5; cursor: not-allowed; }
.coverage-error { font-size: .75rem; color: #ef5350; }
.coverage-panel { background: #0d1018; border: 1px solid #1f2338; border-radius: 8px; padding: .75rem; margin-top: .25rem; }
.coverage-summary { display: flex; gap: .5rem; align-items: center; margin-bottom: .6rem; flex-wrap: wrap; }
.cov-named { font-size: .78rem; color: #81c784; font-weight: 600; }
.cov-collapsed { font-size: .78rem; color: #f39c12; font-weight: 600; }
.cov-threshold { font-size: .75rem; color: #555; }
.cov-sep { color: #333; }
.coverage-table-wrap { max-height: 260px; overflow-y: auto; border-radius: 5px; }
.coverage-table { width: 100%; border-collapse: collapse; font-size: .78rem; }
.coverage-table th { position: sticky; top: 0; background: #0d1018; color: #555; font-weight: 500; text-align: left; padding: .3rem .5rem; border-bottom: 1px solid #1f2338; }
.coverage-table td { padding: .28rem .5rem; border-bottom: 1px solid #111318; }
.cov-row-named td { color: #c5cae9; }
.cov-row-fallback td { color: #555; }
.cov-name { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cov-count { text-align: right; font-variant-numeric: tabular-nums; }
.cov-badge-named { font-size: .7rem; background: #1a2e1a; color: #81c784; border: 1px solid #2a5a2a; border-radius: 8px; padding: .08rem .45rem; }
.cov-badge-fallback { font-size: .7rem; background: #2a1e0a; color: #f39c12; border: 1px solid #5a3c10; border-radius: 8px; padding: .08rem .45rem; }

/* "already trained" hint next to model selector */
.already-trained-badge {
  font-size: .72rem; background: #1a2a0a; color: #8bc34a; border: 1px solid #4a7a1a;
  border-radius: 10px; padding: .1rem .45rem; white-space: nowrap;
}
</style>
