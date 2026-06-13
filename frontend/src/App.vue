<template>
  <div id="app">
    <header>
      <div class="logo">🏪 Store Check</div>

      <div class="header-actions">
        <button class="nav-btn" :class="{ active: view === 'annotate' }" @click="view = 'annotate'">✏ Annotate</button>
        <button class="nav-btn" :class="{ active: view === 'browser' }"  @click="view = 'browser'">Collection</button>
        <button class="nav-btn" :class="{ active: view === 'train' }"    @click="view = 'train'">🎓 Training</button>
        <button class="nav-btn" :class="{ active: view === 'settings' }" @click="view = 'settings'">⚙ Settings</button>
      </div>
    </header>

    <main>
      <AnnotateView  v-if="view === 'annotate'" />
      <QdrantBrowser v-else-if="view === 'browser'" />
      <TrainView     v-else-if="view === 'train'" />
      <SettingsView  v-else-if="view === 'settings'" />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import QdrantBrowser from './components/QdrantBrowser.vue'
import SettingsView  from './components/SettingsView.vue'
import AnnotateView  from './components/AnnotateView.vue'
import TrainView     from './components/TrainView.vue'

const view = ref('annotate')
</script>

<style>
#app { min-height: 100vh; display: flex; flex-direction: column; }

header {
  display: flex; align-items: center;
  padding: .9rem 2rem; background: #13162a;
  border-bottom: 1px solid #1f2338;
  flex-wrap: wrap; gap: 1rem;
}
.logo { font-size: 1.1rem; font-weight: 700; color: #fff; white-space: nowrap; }

.header-actions { display: flex; gap: .4rem; margin-left: auto; }
.nav-btn {
  padding: .35rem .85rem; background: transparent; color: #888;
  border: 1px solid #2a2e3f; border-radius: 6px; cursor: pointer; font-size: .83rem;
  transition: all .15s;
}
.nav-btn:hover { background: #1f2338; color: #ccc; }
.nav-btn.active { background: #1f2338; color: #7986cb; border-color: #5c6bc0; }

main { flex: 1; padding: 2rem 1rem; }
</style>
