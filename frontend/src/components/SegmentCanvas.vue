<template>
  <div class="canvas-wrap">
    <canvas
      ref="canvas"
      :width="displayW"
      :height="displayH"
      @click="onClick"
      @mousemove="onHover"
      @mouseleave="hoverIdx = -1"
      style="cursor:pointer; display:block; width:100%;"
    />
    <div class="nav">
      <button @click="prev" :disabled="current <= 0">‹ Prev</button>
      <span>{{ current + 1 }} / {{ boxes.length }}</span>
      <button @click="next" :disabled="current >= boxes.length - 1">Next ›</button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'

const props = defineProps({
  imageUrl: String,
  imageW: Number,
  imageH: Number,
  boxes: Array,       // [[x1,y1,x2,y2],...]
  results: Array,     // parallel array of match results (may be null while loading)
  current: Number,
})
const emit = defineEmits(['update:current'])

const canvas = ref(null)
const hoverIdx = ref(-1)
const img = ref(null)

const MAX_W = 900
const scale = Math.min(1, MAX_W / (props.imageW || 1))
const displayW = Math.round((props.imageW || 800) * scale)
const displayH = Math.round((props.imageH || 600) * scale)

function loadImage() {
  return new Promise(resolve => {
    const i = new Image()
    i.crossOrigin = 'anonymous'
    i.src = props.imageUrl
    i.onload = () => { img.value = i; resolve() }
  })
}

function draw() {
  if (!canvas.value || !img.value) return
  const ctx = canvas.value.getContext('2d')
  ctx.clearRect(0, 0, displayW, displayH)
  ctx.drawImage(img.value, 0, 0, displayW, displayH)

  props.boxes.forEach((box, i) => {
    const [x1, y1, x2, y2] = box.map(v => v * scale)
    const isCurrent = i === props.current
    const isHover = i === hoverIdx.value
    const result = props.results?.[i]
    const matched = result?.matched
    const color = isCurrent
      ? '#f1c40f'
      : isHover
        ? '#ffffff'
        : matched === true
          ? '#2ecc71'
          : matched === false
            ? '#e74c3c'
            : '#5c6bc0'

    ctx.strokeStyle = color
    ctx.lineWidth = isCurrent ? 2.5 : 1.5
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)

    if (isCurrent) {
      ctx.fillStyle = 'rgba(241,196,15,0.12)'
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
    }

    // small index label
    ctx.fillStyle = color
    ctx.font = `${isCurrent ? 'bold ' : ''}11px sans-serif`
    ctx.fillText(i + 1, x1 + 3, y1 + 13)
  })
}

function onClick(e) {
  if (!props.boxes.length) return
  const rect = canvas.value.getBoundingClientRect()
  const mx = (e.clientX - rect.left) * (displayW / rect.width)
  const my = (e.clientY - rect.top) * (displayH / rect.height)

  // find topmost (smallest area) box containing the click
  let best = -1, bestArea = Infinity
  props.boxes.forEach((box, i) => {
    const [x1, y1, x2, y2] = box.map(v => v * scale)
    if (mx >= x1 && mx <= x2 && my >= y1 && my <= y2) {
      const area = (x2 - x1) * (y2 - y1)
      if (area < bestArea) { best = i; bestArea = area }
    }
  })
  if (best >= 0) emit('update:current', best)
}

function onHover(e) {
  if (!props.boxes.length) return
  const rect = canvas.value.getBoundingClientRect()
  const mx = (e.clientX - rect.left) * (displayW / rect.width)
  const my = (e.clientY - rect.top) * (displayH / rect.height)
  let best = -1, bestArea = Infinity
  props.boxes.forEach((box, i) => {
    const [x1, y1, x2, y2] = box.map(v => v * scale)
    if (mx >= x1 && mx <= x2 && my >= y1 && my <= y2) {
      const area = (x2 - x1) * (y2 - y1)
      if (area < bestArea) { best = i; bestArea = area }
    }
  })
  hoverIdx.value = best
  draw()
}

function prev() { if (props.current > 0) emit('update:current', props.current - 1) }
function next() { if (props.current < props.boxes.length - 1) emit('update:current', props.current + 1) }

onMounted(async () => {
  await loadImage()
  draw()
})

watch(() => [props.current, props.results], draw, { deep: true })
</script>

<style scoped>
.canvas-wrap { position: relative; }
canvas { border-radius: 8px; }
.nav {
  display: flex; align-items: center; justify-content: center; gap: 1rem;
  margin-top: .75rem;
}
.nav button {
  background: #2a2e3f; border: none; color: #ccc;
  padding: .4rem .9rem; border-radius: 6px; cursor: pointer; font-size: 1rem;
  transition: background .15s;
}
.nav button:hover:not(:disabled) { background: #3a3f52; }
.nav button:disabled { opacity: .3; cursor: not-allowed; }
.nav span { color: #aaa; font-size: .9rem; min-width: 80px; text-align: center; }
</style>
