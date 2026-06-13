import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

export async function addCrop(payload) {
  const { data } = await http.post('/qdrant/add', payload)
  return data // { point_id, product_name }
}

export async function collectionInfo() {
  const { data } = await http.get('/qdrant/collection/info')
  return data
}

export async function fetchConfig() {
  const { data } = await http.get('/config')
  return data
}

export async function setActiveConnection(name) {
  const { data } = await http.post('/config/active', { active_connection: name })
  return data
}

export async function saveConnection(conn) {
  const { data } = await http.put('/config/connections', conn)
  return data
}

export async function deleteConnection(name) {
  const { data } = await http.delete(`/config/connections/${encodeURIComponent(name)}`)
  return data
}

export async function browseQdrant({ cursor = null, limit = 20, search = '', companyProduct = null } = {}) {
  const params = { limit, search }
  if (cursor != null) params.offset = cursor
  if (companyProduct != null) params.company_product = companyProduct
  const { data } = await http.get('/qdrant/browse', { params })
  return data
}

export async function updateQdrantPoint(id, payload) {
  const { data } = await http.patch(`/qdrant/points/${id}`, { payload })
  return data
}

export async function deleteQdrantPoint(id) {
  const { data } = await http.delete(`/qdrant/points/${id}`)
  return data
}

export async function startTraining(params = {}) {
  const { data } = await http.post('/training/start', params)
  return data
}

export async function getTrainingStatus() {
  const { data } = await http.get('/training/status')
  return data
}

export async function getModelInfo() {
  const { data } = await http.get('/training/model-info')
  return data
}

export async function listArchivedModels() {
  const { data } = await http.get('/training/models')
  return data // { models: [...], active: stem }
}

export async function activateModel(stem) {
  const { data } = await http.post(`/training/models/${encodeURIComponent(stem)}/activate`)
  return data
}

export async function deleteArchivedModel(stem) {
  const { data } = await http.delete(`/training/models/${encodeURIComponent(stem)}`)
  return data
}

// ── Label management ──────────────────────────────────────────────────────────
export async function getLabels(fuzzyThreshold = 0.85) {
  const { data } = await http.get('/qdrant/labels', { params: { fuzzy_threshold: fuzzyThreshold } })
  return data
}

export async function renameLabels(fromLabels, toLabel) {
  const { data } = await http.post('/qdrant/labels/rename', { from_labels: fromLabels, to_label: toLabel })
  return data
}

export async function clusterLabel(label, mode = 'hybrid') {
  const { data } = await http.get('/qdrant/labels/clusters', { params: { label, mode } })
  return data
}

export async function getLabelPoints(label) {
  const { data } = await http.get('/qdrant/labels/points', { params: { label } })
  return data
}

export async function seededSplit({ label, groups, mode = 'hybrid', useShape = true }) {
  const { data } = await http.post('/qdrant/labels/seeded-split', {
    label, groups, mode, use_shape: useShape,
  })
  return data
}

export async function batchUpdatePoints(pointIds, payload) {
  const { data } = await http.post('/qdrant/points/batch-update', { point_ids: pointIds, payload })
  return data
}

export async function batchDeletePoints(pointIds) {
  const { data } = await http.post('/qdrant/points/batch-delete', { point_ids: pointIds })
  return data
}

export async function assignPoints(pointIds, toLabel) {
  const { data } = await http.post('/qdrant/labels/assign', { point_ids: pointIds, to_label: toLabel })
  return data
}

export async function getClassCoverage(minTiles = 5) {
  const { data } = await http.get('/training/class-coverage', { params: { min_tiles: minTiles } })
  return data
}

// ── Annotation Studio ─────────────────────────────────────────────────────────
export async function uploadShelf(file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/shelves/upload', form)
  return data // { shelf_id, width, height, already_exists, box_count }
}

export function shelfImageUrl(shelfId) {
  return `/api/shelves/${shelfId}/image`
}

export function shelfThumbnailUrl(shelfId) {
  return `/api/shelves/${shelfId}/thumbnail`
}

export async function listShelves() {
  const { data } = await http.get('/shelves')
  return data // { shelves: [...] }
}

export async function getShelfAnnotations(shelfId) {
  const { data } = await http.get(`/shelves/${shelfId}/annotations`)
  return data // { annotations: [...] }
}

export async function getAllLabels() {
  const { data } = await http.get('/shelves/labels/all')
  return data // { labels: [...] }
}

export async function listDetectionModels() {
  const { data } = await http.get('/shelves/models')
  return data // { models: [{id, name, available}] }
}

export async function matchCrop(shelfId, box, scoreThreshold = 0.55) {
  const { data } = await http.post(`/shelves/${shelfId}/match-crop`, {
    box, score_threshold: scoreThreshold,
  })
  return data // { winner, vote_score, confidence_tier, payload, match_image_b64 }
}

export async function detectShelf(shelfId, { model = 'fastsam-s', confThreshold = 0.25, textPrompts,
                                             iou, imgsz, minArea, maxAreaRatio, minAspect, dedupeIou } = {}) {
  const params = { model, conf_threshold: confThreshold }
  if (textPrompts) params.text_prompts = textPrompts
  if (iou != null) params.iou = iou
  if (imgsz != null) params.imgsz = imgsz
  if (minArea != null) params.min_area = minArea
  if (maxAreaRatio != null) params.max_area_ratio = maxAreaRatio
  if (minAspect != null) params.min_aspect = minAspect
  if (dedupeIou != null) params.dedupe_iou = dedupeIou
  const { data } = await http.post(`/shelves/${shelfId}/detect`, null, { params })
  return data // { candidates: [{x1,y1,x2,y2,label,confidence}], total_detected, skipped }
}
