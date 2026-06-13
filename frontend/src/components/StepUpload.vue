<template>
  <div class="upload-step">
    <h2>Upload a shelf picture</h2>
    <div
      class="drop-zone"
      :class="{ dragging }"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
      @click="fileInput.click()"
    >
      <template v-if="preview">
        <img :src="preview" class="preview-img" />
        <p class="hint">Click or drop to replace</p>
      </template>
      <template v-else>
        <div class="icon">🖼️</div>
        <p>Drop a shelf photo here or <span class="link">click to browse</span></p>
        <p class="hint">JPG, PNG, WEBP · max 50 MB</p>
      </template>
    </div>
    <input ref="fileInput" type="file" accept="image/*" style="display:none" @change="onPick" />

    <label class="new-image-toggle">
      <input type="checkbox" v-model="newImage" />
      <span class="toggle-label">
        <span class="toggle-title">New products / first scan of this shelf</span>
        <span class="toggle-hint">Auto-saves matched crops to Qdrant to grow your collection</span>
      </span>
    </label>

    <div v-if="error" class="error">{{ error }}</div>

    <button class="btn-primary" :disabled="!file || loading" @click="upload">
      <span v-if="loading">Uploading…</span>
      <span v-else>Continue →</span>
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { uploadImage } from '../api.js'

const emit = defineEmits(['uploaded'])

const fileInput = ref(null)
const file = ref(null)
const preview = ref(null)
const dragging = ref(false)
const loading = ref(false)
const error = ref('')
const newImage = ref(false)

function setFile(f) {
  if (!f || !f.type.startsWith('image/')) { error.value = 'Please select an image file.'; return }
  file.value = f
  error.value = ''
  const reader = new FileReader()
  reader.onload = e => { preview.value = e.target.result }
  reader.readAsDataURL(f)
}

function onDrop(e) {
  dragging.value = false
  setFile(e.dataTransfer.files[0])
}
function onPick(e) {
  setFile(e.target.files[0])
}

async function upload() {
  if (!file.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await uploadImage(file.value)
    emit('uploaded', { ...result, newImage: newImage.value })
  } catch (e) {
    error.value = e?.response?.data?.detail ?? 'Upload failed'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.upload-step { max-width: 640px; margin: 0 auto; padding: 2rem; }
h2 { font-size: 1.4rem; margin-bottom: 1.5rem; color: #fff; }
.drop-zone {
  border: 2px dashed #3a3f52;
  border-radius: 12px;
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  transition: border-color .2s, background .2s;
  min-height: 200px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .5rem;
}
.drop-zone:hover, .drop-zone.dragging {
  border-color: #5c6bc0;
  background: rgba(92, 107, 192, .07);
}
.icon { font-size: 3rem; }
.link { color: #7986cb; text-decoration: underline; }
.hint { font-size: .8rem; color: #666; }
.preview-img { max-height: 300px; max-width: 100%; border-radius: 8px; object-fit: contain; }
.new-image-toggle {
  display: flex; align-items: flex-start; gap: .75rem;
  margin-top: 1.25rem; cursor: pointer;
  background: #1a1d2e; border-radius: 10px; padding: .9rem 1rem;
}
.new-image-toggle input[type="checkbox"] { accent-color: #5c6bc0; margin-top: .15rem; flex-shrink: 0; width: 16px; height: 16px; cursor: pointer; }
.toggle-label { display: flex; flex-direction: column; gap: .2rem; }
.toggle-title { font-size: .9rem; color: #e0e0e0; }
.toggle-hint { font-size: .78rem; color: #666; }
.error { color: #ef5350; margin-top: .75rem; font-size: .9rem; }
.btn-primary {
  margin-top: 1.5rem; width: 100%; padding: .75rem;
  background: #5c6bc0; color: #fff; border: none; border-radius: 8px;
  font-size: 1rem; cursor: pointer; transition: background .2s;
}
.btn-primary:hover:not(:disabled) { background: #7986cb; }
.btn-primary:disabled { opacity: .4; cursor: not-allowed; }
</style>
