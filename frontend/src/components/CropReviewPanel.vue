<template>
  <div class="panel">
    <div v-if="!result" class="loading">
      <span class="spinner" />
      Searching Qdrant…
    </div>
    <template v-else>
      <div class="header">
        <span v-if="result.pre_labeled" class="badge pre-labeled">🎯 SKU detected</span>
        <template v-else>
          <span class="badge" :class="tierClass">{{ tierLabel }}</span>
          <span v-if="result.vote_count" class="vote-chip">
            {{ result.vote_count }}/10 votes · {{ (result.vote_score * 100).toFixed(0) }}%
          </span>
        </template>
        <span v-if="result.pre_labeled" class="score">conf {{ (result.confidence * 100).toFixed(1) }}%</span>
        <span class="box-label">
          box {{ result.box[0] }},{{ result.box[1] }} → {{ result.box[2] }},{{ result.box[3] }}
        </span>
      </div>

      <!-- Winner name for non-pre-labeled results -->
      <div v-if="!result.pre_labeled && result.winner" class="winner-card" :class="tierClass">
        <p class="winner-name">{{ result.winner }}</p>
        <p class="winner-hint" v-if="result.confidence_tier === 'strong'">Auto-approved — mark as noise or override if wrong.</p>
        <p class="winner-hint" v-else>Best guess — verify before approving.</p>
      </div>

      <!-- Pre-labeled (YOLOv8-SKU) -->
      <div v-if="result.pre_labeled" class="pre-label-card">
        <p class="pre-label-name">{{ result.label }}</p>
        <p class="pre-label-hint">Identified by trained SKU model. Mark correct or add/override below.</p>
      </div>

      <div class="images">
        <div class="img-card">
          <p class="img-label">Shelf crop</p>
          <img v-if="result.crop_b64" :src="'data:image/jpeg;base64,' + result.crop_b64" />
          <div v-else class="no-img">— loading —</div>
        </div>
        <div v-if="!result.pre_labeled" class="img-card">
          <p class="img-label">Best Qdrant match</p>
          <img v-if="result.hits[0]?.image_b64" :src="'data:image/jpeg;base64,' + result.hits[0].image_b64" />
          <div v-else-if="!result.hits.length" class="no-img">— no match —</div>
          <div v-else class="no-img">— no image stored —</div>
        </div>
      </div>

      <div v-if="!result.pre_labeled && result.hits.length" class="hits">
        <p class="hits-title">Top matches</p>
        <div v-for="(h, i) in result.hits" :key="h.id" class="hit-row">
          <span class="hit-rank">#{{ i + 1 }}</span>
          <span class="hit-score" :class="scoreClass(h.score)">{{ h.score.toFixed(4) }}</span>
          <span class="hit-name">{{ h.payload.product_name ?? h.id }}</span>
          <span class="hit-pack">{{ h.payload.pack_type ?? '' }}</span>
        </div>
        <div class="payload">
          <div v-for="(v, k) in result.hits[0].payload" :key="k" class="payload-row">
            <span class="pk">{{ k }}</span>
            <span class="pv">{{ v }}</span>
          </div>
        </div>
      </div>

      <div class="actions">
        <button class="btn-action correct" @click="emit('decide', 'correct')">{{ correctLabel }}</button>
        <button class="btn-action noise"   @click="emit('decide', 'noise')">🚫 Noise</button>
        <button class="btn-action add"     @click="emit('decide', 'add')">➕ Add to Qdrant</button>
        <button class="btn-action skip"    @click="emit('decide', 'skip')">⏭ Skip</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  result: Object,
  newImage: { type: Boolean, default: false },
})
const emit = defineEmits(['decide'])

const correctLabel = computed(() => {
  if (props.newImage && props.result?.winner) return '✅ Save to Qdrant'
  return '✅ Correct'
})

const tierClass = computed(() => {
  const t = props.result?.confidence_tier
  if (t === 'strong') return 'strong'
  if (t === 'uncertain') return 'uncertain'
  return 'nomatch'
})

const tierLabel = computed(() => {
  const t = props.result?.confidence_tier
  if (t === 'strong') return '✓ Strong match'
  if (t === 'uncertain') return '? Uncertain'
  return '⚠ No match'
})

function scoreClass(s) {
  if (s >= 0.9) return 'high'
  if (s >= 0.75) return 'mid'
  return 'low'
}
</script>

<style scoped>
.panel { background: #1a1d2e; border-radius: 10px; padding: 1.25rem; }
.loading { display: flex; align-items: center; gap: .75rem; color: #aaa; padding: 2rem 0; justify-content: center; }
.spinner {
  width: 20px; height: 20px; border: 2px solid #3a3f52;
  border-top-color: #5c6bc0; border-radius: 50%; animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg) } }

.header { display: flex; align-items: center; gap: .75rem; margin-bottom: 1rem; flex-wrap: wrap; }
.badge { padding: .25rem .65rem; border-radius: 20px; font-size: .8rem; font-weight: 600; }
.badge.match    { background: rgba(46,204,113,.15); color: #2ecc71; }
.badge.strong   { background: rgba(46,204,113,.15); color: #2ecc71; }
.badge.uncertain{ background: rgba(243,156,18,.15); color: #f39c12; }
.badge.nomatch  { background: rgba(150,150,150,.12); color: #888; }
.badge.pre-labeled { background: rgba(92,107,192,.2); color: #9fa8da; }

.vote-chip { font-size: .78rem; color: #7986cb; background: rgba(92,107,192,.12); padding: .15rem .5rem; border-radius: 20px; }

.winner-card { border-radius: 8px; padding: .65rem 1rem; margin-bottom: 1rem; }
.winner-card.strong   { background: rgba(46,204,113,.07); border-left: 3px solid #2ecc71; }
.winner-card.uncertain{ background: rgba(243,156,18,.07); border-left: 3px solid #f39c12; }
.winner-name { font-size: 1.05rem; font-weight: 600; color: #e0e0e0; margin-bottom: .2rem; }
.winner-hint { font-size: .75rem; color: #666; }

.pre-label-card { background: #0f1117; border-radius: 8px; padding: .75rem 1rem; margin-bottom: 1rem; }
.pre-label-name { font-size: 1.05rem; font-weight: 600; color: #e0e0e0; margin-bottom: .25rem; }
.pre-label-hint { font-size: .75rem; color: #666; }
.score { font-size: .85rem; color: #7986cb; font-variant-numeric: tabular-nums; }
.box-label { font-size: .75rem; color: #666; margin-left: auto; }

.images { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
.img-card { background: #0f1117; border-radius: 8px; padding: .75rem; }
.img-label { font-size: .75rem; color: #666; margin-bottom: .5rem; }
.img-card img { width: 100%; height: 160px; object-fit: contain; border-radius: 4px; }
.no-img { height: 160px; display: flex; align-items: center; justify-content: center; color: #555; }

.hits { margin-bottom: 1rem; }
.hits-title { font-size: .8rem; color: #888; margin-bottom: .5rem; }
.hit-row { display: grid; grid-template-columns: 24px 64px 1fr auto; gap: .4rem; align-items: center; padding: .25rem 0; border-bottom: 1px solid #1f2338; }
.hit-rank { font-size: .75rem; color: #666; }
.hit-score { font-size: .8rem; font-variant-numeric: tabular-nums; }
.hit-score.high { color: #2ecc71; }
.hit-score.mid { color: #f39c12; }
.hit-score.low { color: #e74c3c; }
.hit-name { font-size: .85rem; }
.hit-pack { font-size: .75rem; color: #888; }

.payload { margin-top: .75rem; background: #0f1117; border-radius: 6px; padding: .5rem .75rem; max-height: 120px; overflow-y: auto; }
.payload-row { display: flex; gap: .5rem; font-size: .78rem; padding: .15rem 0; }
.pk { color: #5c6bc0; min-width: 120px; }
.pv { color: #ccc; word-break: break-word; }

.actions { display: flex; gap: .5rem; flex-wrap: wrap; }
.btn-action {
  flex: 1; min-width: 110px; padding: .55rem;
  border: none; border-radius: 7px; cursor: pointer;
  font-size: .85rem; font-weight: 600; transition: opacity .15s;
}
.btn-action:hover { opacity: .85; }
.correct { background: rgba(46,204,113,.15); color: #2ecc71; }
.noise   { background: rgba(231,76,60,.15);  color: #e74c3c; }
.add     { background: rgba(241,196,15,.15); color: #f1c40f; }
.skip    { background: rgba(92,107,192,.15); color: #7986cb; }
</style>
