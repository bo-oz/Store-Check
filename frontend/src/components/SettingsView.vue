<template>
  <div class="settings-view">
    <h2>Settings</h2>

    <!-- Connection selector -->
    <section class="card">
      <div class="section-header">
        <h3>Qdrant connections</h3>
        <button class="btn-add" @click="startNew">+ New connection</button>
      </div>

      <div v-if="loadError" class="msg error">{{ loadError }}</div>

      <div class="conn-list">
        <div
          v-for="c in connections"
          :key="c.name"
          :class="['conn-row', { active: c.name === activeConnection }]"
          @click="selectConn(c.name)"
        >
          <div class="conn-info">
            <span class="conn-name">{{ c.name }}</span>
            <span class="conn-detail">{{ c.qdrant_collection }} · {{ c.embed_dim }}d</span>
          </div>
          <div class="conn-badges">
            <span v-if="c.name === activeConnection" class="badge-active">active</span>
            <button class="btn-icon" title="Edit" @click.stop="startEdit(c)">✏</button>
            <button class="btn-icon danger" title="Delete" @click.stop="confirmDel(c.name)" :disabled="connections.length <= 1">🗑</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Edit / New connection form -->
    <section class="card" v-if="editing">
      <h3>{{ isNew ? 'New connection' : `Edit "${editing.name}"` }}</h3>

      <label>Connection name <span class="req">*</span></label>
      <input v-model="editing.name" :disabled="!isNew" placeholder="e.g. prod-1024" />

      <label>Qdrant URL <span class="req">*</span></label>
      <input v-model="editing.qdrant_url" placeholder="https://…" />

      <label>Qdrant API key <span class="req">*</span></label>
      <input v-model="editing.qdrant_key" type="password" placeholder="eyJ…" />

      <label>Collection name <span class="req">*</span></label>
      <input v-model="editing.qdrant_collection" placeholder="retail_shelf_analytics_dinov2_1024" />

      <label>DINOv2 model</label>
      <select v-model="editing.dinov2_model" @change="syncDim">
        <option v-for="m in SUPPORTED_MODELS" :key="m.key" :value="m.key">{{ m.label }}</option>
      </select>

      <label>Embedding dimension</label>
      <input type="number" v-model.number="editing.embed_dim" />

      <div v-if="formError"   class="msg error">{{ formError }}</div>
      <div v-if="formSuccess" class="msg success">{{ formSuccess }}</div>

      <div class="form-actions">
        <button class="btn-cancel" @click="editing = null">Cancel</button>
        <button class="btn-save" :disabled="saving" @click="saveConn">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </section>

    <!-- Collection info for active connection -->
    <section class="card info">
      <h3>Active collection info</h3>
      <div v-if="info">
        <div class="info-row"><span>Name</span><span>{{ info.collection }}</span></div>
        <div class="info-row"><span>Vectors</span><span>{{ info.vector_count }}</span></div>
        <div class="info-row"><span>Dimensions</span><span>{{ info.vector_dim }}</span></div>
      </div>
      <div v-else-if="infoError" class="msg error">{{ infoError }}</div>
      <div v-else class="muted">—</div>
      <button class="btn-refresh" @click="loadInfo">Refresh</button>
    </section>

    <!-- Delete confirm -->
    <div v-if="deleteTarget" class="confirm-overlay" @mousedown.self="deleteTarget = null">
      <div class="confirm-box">
        <p>Delete connection <strong>{{ deleteTarget }}</strong>?</p>
        <div class="confirm-actions">
          <button class="btn-cancel" @click="deleteTarget = null">Cancel</button>
          <button class="btn-delete" :disabled="deleting" @click="doDelete">
            {{ deleting ? 'Deleting…' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchConfig, setActiveConnection, saveConnection, deleteConnection, collectionInfo } from '../api.js'

const SUPPORTED_MODELS = [
  { key: 'vit_small_patch14_dinov2.lvd142m',  label: 'DINOv2 small  (384-dim)',  dim: 384  },
  { key: 'vit_base_patch14_dinov2.lvd142m',   label: 'DINOv2 base   (768-dim)',  dim: 768  },
  { key: 'vit_large_patch14_dinov2.lvd142m',  label: 'DINOv2 large (1024-dim)', dim: 1024 },
]

const connections     = ref([])
const activeConnection = ref('')
const loadError       = ref('')
const info            = ref(null)
const infoError       = ref('')
const editing         = ref(null)
const isNew           = ref(false)
const saving          = ref(false)
const formError       = ref('')
const formSuccess     = ref('')
const deleteTarget    = ref(null)
const deleting        = ref(false)

async function load() {
  loadError.value = ''
  try {
    const cfg = await fetchConfig()
    connections.value = cfg.connections
    activeConnection.value = cfg.active_connection
  } catch {
    loadError.value = 'Could not load config — is the backend running?'
  }
}

async function loadInfo() {
  info.value = null; infoError.value = ''
  try { info.value = await collectionInfo() }
  catch (e) { infoError.value = e?.response?.data?.detail ?? 'Could not reach collection' }
}

async function selectConn(name) {
  if (name === activeConnection.value) return
  await setActiveConnection(name)
  activeConnection.value = name
  loadInfo()
}

function startEdit(c) {
  editing.value = { ...c }
  isNew.value = false
  formError.value = ''; formSuccess.value = ''
}

function startNew() {
  editing.value = { name: '', qdrant_url: '', qdrant_key: '', qdrant_collection: '', embed_dim: 1024, dinov2_model: 'vit_large_patch14_dinov2.lvd142m' }
  isNew.value = true
  formError.value = ''; formSuccess.value = ''
}

function syncDim() {
  const m = SUPPORTED_MODELS.find(m => m.key === editing.value.dinov2_model)
  if (m) editing.value.embed_dim = m.dim
}

async function saveConn() {
  formError.value = ''; formSuccess.value = ''
  const e = editing.value
  if (!e.name.trim() || !e.qdrant_url.trim() || !e.qdrant_collection.trim()) {
    formError.value = 'Name, URL and collection are required.'; return
  }
  // For edits, if key is blank we need to preserve existing — send the masked version back
  // The backend will upsert; if key is blank on edit we skip updating it
  saving.value = true
  try {
    await saveConnection(e)
    formSuccess.value = 'Saved.'
    await load()
    setTimeout(() => { editing.value = null }, 800)
  } catch (err) {
    formError.value = err?.response?.data?.detail ?? 'Save failed'
  } finally {
    saving.value = false
  }
}

function confirmDel(name) { deleteTarget.value = name }

async function doDelete() {
  deleting.value = true
  try {
    await deleteConnection(deleteTarget.value)
    deleteTarget.value = null
    await load()
  } catch (e) {
    deleteTarget.value = null
  } finally {
    deleting.value = false
  }
}

onMounted(() => { load(); loadInfo() })
</script>

<style scoped>
.settings-view { padding: 1.5rem; max-width: 680px; margin: 0 auto; }
h2 { font-size: 1.4rem; color: #fff; margin-bottom: 1.25rem; }
h3 { font-size: .95rem; color: #ccc; }

.card {
  background: #1a1d2e; border-radius: 10px; padding: 1.25rem;
  display: flex; flex-direction: column; gap: .65rem; margin-bottom: 1.25rem;
}
.section-header { display: flex; align-items: center; justify-content: space-between; }
.btn-add {
  padding: .3rem .8rem; background: #5c6bc0; color: #fff;
  border: none; border-radius: 6px; cursor: pointer; font-size: .82rem; font-weight: 600;
}
.btn-add:hover { opacity: .85; }

.conn-list { display: flex; flex-direction: column; gap: .4rem; }
.conn-row {
  display: flex; align-items: center; justify-content: space-between;
  background: #0f1117; border: 1px solid #2a2e3f; border-radius: 8px;
  padding: .6rem .85rem; cursor: pointer; transition: border-color .15s;
}
.conn-row:hover  { border-color: #3a3f52; }
.conn-row.active { border-color: #5c6bc0; }
.conn-info { display: flex; flex-direction: column; gap: .15rem; }
.conn-name   { font-size: .88rem; color: #e0e0e0; }
.conn-detail { font-size: .75rem; color: #666; }
.conn-badges { display: flex; align-items: center; gap: .4rem; }
.badge-active {
  font-size: .72rem; padding: .15rem .5rem; background: rgba(92,107,192,.2);
  color: #7986cb; border-radius: 10px;
}
.btn-icon {
  background: none; border: none; cursor: pointer; font-size: .85rem;
  color: #666; padding: .15rem .3rem; border-radius: 4px;
}
.btn-icon:hover { background: #2a2e3f; color: #ccc; }
.btn-icon.danger:hover { background: rgba(231,76,60,.15); color: #e74c3c; }
.btn-icon:disabled { opacity: .3; cursor: not-allowed; }

label { font-size: .82rem; color: #aaa; }
.req { color: #ef5350; }
input, select {
  width: 100%; background: #0f1117; border: 1px solid #2a2e3f;
  color: #e0e0e0; padding: .45rem .7rem; border-radius: 6px; font-size: .88rem;
  outline: none; transition: border-color .15s; box-sizing: border-box;
}
input:focus, select:focus { border-color: #5c6bc0; }
select option { background: #1a1d2e; }

.form-actions { display: flex; gap: .75rem; margin-top: .2rem; }
.btn-cancel {
  flex: 1; padding: .5rem; background: #2a2e3f; color: #ccc;
  border: none; border-radius: 7px; cursor: pointer;
}
.btn-save {
  flex: 2; padding: .5rem; background: #5c6bc0; color: #fff;
  border: none; border-radius: 7px; font-weight: 600; cursor: pointer;
}
.btn-save:hover:not(:disabled) { opacity: .85; }
.btn-save:disabled { opacity: .4; cursor: not-allowed; }
.btn-delete {
  flex: 1; padding: .5rem; background: rgba(231,76,60,.15); color: #e74c3c;
  border: none; border-radius: 7px; cursor: pointer; font-weight: 600;
}
.btn-delete:hover:not(:disabled) { background: rgba(231,76,60,.3); }

.msg { font-size: .82rem; }
.error   { color: #ef5350; }
.success { color: #2ecc71; }

.info { gap: .5rem; }
.info-row { display: flex; justify-content: space-between; font-size: .85rem; padding: .2rem 0; border-bottom: 1px solid #1f2338; }
.info-row span:first-child { color: #5c6bc0; }
.muted { color: #555; font-size: .85rem; }
.btn-refresh {
  margin-top: .2rem; padding: .35rem .9rem; background: #2a2e3f; color: #ccc;
  border: none; border-radius: 6px; cursor: pointer; font-size: .82rem; align-self: flex-start;
}
.btn-refresh:hover { background: #3a3f52; }

.confirm-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.65);
  display: flex; align-items: center; justify-content: center; z-index: 200;
}
.confirm-box {
  background: #1a1d2e; border-radius: 10px; padding: 1.5rem; min-width: 280px;
  display: flex; flex-direction: column; gap: 1rem;
}
.confirm-box p { font-size: .95rem; color: #e0e0e0; }
.confirm-actions { display: flex; gap: .75rem; }
</style>
