<template>
  <div class="browser">
    <div class="browser-header">
      <h2>Qdrant collection</h2>
      <div class="subtabs">
        <button :class="{ active: tab === 'entries' }" @click="tab = 'entries'">Entries</button>
        <button :class="{ active: tab === 'labels' }" @click="tab = 'labels'">🏷 Labels</button>
      </div>
      <div v-if="tab === 'entries'" class="toolbar">
        <input v-model="searchQuery" placeholder="Search by name…" @keyup.enter="doSearch" />
        <button class="btn-search" @click="doSearch">Search</button>
        <button class="btn-clear" v-if="searchQuery" @click="clearSearch">✕</button>
        <select v-model="companyFilter" @change="doSearch" class="filter-select">
          <option value="">All products</option>
          <option value="true">Own brand</option>
          <option value="false">Other brands</option>
        </select>
        <span class="total">{{ total }} entries</span>
      </div>
    </div>

    <LabelManager v-if="tab === 'labels'" @changed="load" />

    <template v-else>
    <div v-if="loading" class="loading">Loading…</div>
    <div v-else-if="!items.length" class="empty">No entries found.</div>

    <div v-else class="grid">
      <div v-for="item in items" :key="item.id" class="entry-card">
        <div class="img-wrap">
          <img v-if="item.image_b64" :src="'data:image/jpeg;base64,' + item.image_b64" />
          <div v-else class="no-img">No image</div>
        </div>
        <div class="entry-body">
          <div v-if="!item._editing" class="payload-view">
            <div v-for="(v, k) in item.payload" :key="k" class="prow">
              <span class="pk">{{ k }}</span>
              <span class="pv">{{ String(v) }}</span>
            </div>
            <div class="entry-actions">
              <button class="btn-edit" @click="startEdit(item)">Edit</button>
              <button class="btn-delete" @click="confirmDelete(item)">Delete</button>
            </div>
          </div>
          <div v-else class="payload-edit">
            <div v-for="(v, k) in item._draft" :key="k" class="prow edit">
              <span class="pk">{{ k }}</span>
              <input v-if="typeof v === 'boolean'" type="checkbox" v-model="item._draft[k]" />
              <input v-else v-model="item._draft[k]" />
            </div>
            <div v-if="item._error" class="msg error">{{ item._error }}</div>
            <div class="entry-actions">
              <button class="btn-save" :disabled="item._saving" @click="saveEdit(item)">
                {{ item._saving ? 'Saving…' : 'Save' }}
              </button>
              <button class="btn-cancel" @click="item._editing = false">Cancel</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="pagination" v-if="total > limit">
      <button :disabled="currentPage <= 1" @click="prev">‹ Prev</button>
      <span>Page {{ currentPage }} · {{ total }} total</span>
      <button :disabled="cursorStack.length <= currentPage" @click="next">Next ›</button>
    </div>

    <div v-if="deleteTarget" class="confirm-overlay" @mousedown.self="deleteTarget = null">
      <div class="confirm-box">
        <p>Delete <strong>{{ deleteTarget.payload.product_name ?? deleteTarget.id }}</strong>?</p>
        <div class="confirm-actions">
          <button class="btn-cancel" @click="deleteTarget = null">Cancel</button>
          <button class="btn-delete" :disabled="deleting" @click="doDelete">
            {{ deleting ? 'Deleting…' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { browseQdrant, updateQdrantPoint, deleteQdrantPoint } from '../api.js'
import LabelManager from './LabelManager.vue'

const tab = ref('entries')

const items  = ref([])
const total  = ref(0)
const limit  = 20
const loading = ref(false)
const searchQuery = ref('')
const activeSearch = ref('')
const companyFilter = ref('')
const deleteTarget = ref(null)
const deleting = ref(false)

// Cursor stack for prev/next — each entry is the cursor to fetch that page
// null = first page; subsequent pages use the next_cursor returned by the API
const cursorStack = ref([null])  // stack of cursors, current page = last element
const currentPage = ref(1)       // 1-based for display

async function load() {
  loading.value = true
  const cursor = cursorStack.value[cursorStack.value.length - 1]
  try {
    const res = await browseQdrant({
      cursor,
      limit,
      search: activeSearch.value,
      companyProduct: companyFilter.value || null,
    })
    total.value = res.total
    items.value = res.items.map(i => reactive({ ...i, _editing: false, _draft: null, _saving: false, _error: '' }))
    // Store next cursor at the end of the stack if not already there
    if (res.next_cursor && cursorStack.value.length === currentPage.value) {
      cursorStack.value.push(res.next_cursor)
    }
  } finally {
    loading.value = false
  }
}

function doSearch() {
  activeSearch.value = searchQuery.value
  cursorStack.value = [null]
  currentPage.value = 1
  load()
}
function clearSearch() {
  searchQuery.value = ''
  activeSearch.value = ''
  companyFilter.value = ''
  cursorStack.value = [null]
  currentPage.value = 1
  load()
}
function prev() {
  if (currentPage.value <= 1) return
  currentPage.value--
  // pop back to the previous cursor
  cursorStack.value = cursorStack.value.slice(0, currentPage.value)
  load()
}
function next() {
  currentPage.value++
  load()
}

function startEdit(item) {
  item._draft = { ...item.payload }
  item._error = ''
  item._editing = true
}

async function saveEdit(item) {
  item._saving = true; item._error = ''
  try {
    await updateQdrantPoint(item.id, item._draft)
    item.payload = { ...item._draft }
    item._editing = false
  } catch (e) {
    item._error = e?.response?.data?.detail ?? 'Save failed'
  } finally {
    item._saving = false
  }
}

function confirmDelete(item) { deleteTarget.value = item }

async function doDelete() {
  deleting.value = true
  try {
    await deleteQdrantPoint(deleteTarget.value.id)
    items.value = items.value.filter(i => i.id !== deleteTarget.value.id)
    total.value--
    deleteTarget.value = null
  } finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.browser { padding: 1.5rem; max-width: 1400px; margin: 0 auto; }
.browser-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; flex-wrap: wrap; gap: .75rem; }
h2 { font-size: 1.4rem; color: #fff; }

.subtabs { display: flex; gap: .35rem; }
.subtabs button {
  padding: .35rem .9rem; background: #1a1d2e; color: #888; border: 1px solid #2a2e3f;
  border-radius: 6px; cursor: pointer; font-size: .85rem; transition: all .15s;
}
.subtabs button.active { background: #2a2e3f; color: #fff; border-color: #5c6bc0; }
.subtabs button:hover:not(.active) { color: #ccc; }

.toolbar { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.toolbar input {
  background: #1a1d2e; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .4rem .7rem; border-radius: 6px; font-size: .88rem; outline: none; width: 220px;
}
.toolbar input:focus { border-color: #5c6bc0; }
.filter-select {
  background: #1a1d2e; border: 1px solid #2a2e3f; color: #ccc;
  padding: .4rem .7rem; border-radius: 6px; font-size: .85rem; outline: none; cursor: pointer;
}
.filter-select:focus { border-color: #5c6bc0; }
.filter-select option { background: #1a1d2e; }
.btn-search, .btn-clear {
  padding: .4rem .85rem; background: #2a2e3f; color: #ccc;
  border: none; border-radius: 6px; cursor: pointer; font-size: .85rem;
}
.btn-search:hover, .btn-clear:hover { background: #3a3f52; }
.total { font-size: .82rem; color: #666; }

.loading, .empty { color: #888; padding: 3rem 0; text-align: center; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 1rem; }

.entry-card { background: #1a1d2e; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }
.img-wrap { background: #0f1117; height: 160px; display: flex; align-items: center; justify-content: center; }
.img-wrap img { width: 100%; height: 100%; object-fit: contain; }
.no-img { color: #555; font-size: .8rem; }

.entry-body { padding: .75rem; flex: 1; display: flex; flex-direction: column; gap: .4rem; }
.payload-view, .payload-edit { flex: 1; display: flex; flex-direction: column; gap: .3rem; }
.prow { display: flex; gap: .4rem; font-size: .78rem; align-items: baseline; }
.prow.edit { align-items: center; }
.pk { color: #5c6bc0; min-width: 90px; flex-shrink: 0; }
.pv { color: #ccc; word-break: break-word; }
.prow input:not([type=checkbox]) {
  flex: 1; background: #0f1117; border: 1px solid #2a2e3f; color: #e0e0e0;
  padding: .25rem .5rem; border-radius: 4px; font-size: .78rem; outline: none;
}
.prow input:focus { border-color: #5c6bc0; }

.entry-actions { display: flex; gap: .4rem; margin-top: auto; padding-top: .5rem; }
.btn-edit, .btn-cancel {
  flex: 1; padding: .35rem; background: #2a2e3f; color: #ccc;
  border: none; border-radius: 6px; cursor: pointer; font-size: .78rem;
}
.btn-delete {
  flex: 1; padding: .35rem; background: rgba(231,76,60,.15); color: #e74c3c;
  border: none; border-radius: 6px; cursor: pointer; font-size: .78rem;
}
.btn-save {
  flex: 1; padding: .35rem; background: #5c6bc0; color: #fff;
  border: none; border-radius: 6px; cursor: pointer; font-size: .78rem; font-weight: 600;
}
.btn-edit:hover { background: #3a3f52; }
.btn-delete:hover { background: rgba(231,76,60,.3); }
.btn-save:hover:not(:disabled) { opacity: .85; }
.btn-save:disabled { opacity: .4; cursor: not-allowed; }

.msg.error { color: #ef5350; font-size: .78rem; }

.pagination { display: flex; align-items: center; gap: 1rem; justify-content: center; margin-top: 1.5rem; font-size: .85rem; color: #aaa; }
.pagination button {
  padding: .4rem .9rem; background: #2a2e3f; color: #ccc;
  border: none; border-radius: 6px; cursor: pointer;
}
.pagination button:disabled { opacity: .35; cursor: not-allowed; }

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
