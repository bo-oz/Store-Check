<template>
  <div class="slider-row">
    <label>{{ label }}</label>
    <input
      type="range"
      :min="min" :max="max" :step="step"
      :value="modelValue"
      @input="emit('update:modelValue', integer ? parseInt($event.target.value) : parseFloat($event.target.value))"
    />
    <span class="val">{{ integer ? modelValue : modelValue.toFixed(2) }}</span>
  </div>
</template>

<script setup>
defineProps({ label: String, modelValue: Number, min: Number, max: Number, step: Number, integer: Boolean })
const emit = defineEmits(['update:modelValue'])
</script>

<style scoped>
.slider-row { display: grid; grid-template-columns: 180px 1fr 52px; align-items: center; gap: .75rem; }
label { font-size: .85rem; color: #ccc; }
input[type=range] { accent-color: #5c6bc0; cursor: pointer; }
.val { font-size: .85rem; color: #7986cb; text-align: right; font-variant-numeric: tabular-nums; }
</style>
