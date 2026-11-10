// Thin client. Errors surface the backend message; nothing is retried or swapped silently.
async function request(path, init) {
  const res = await fetch(`/api${path}`, init);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail ?? `HTTP ${res.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

function call(method, path, body) {
  return request(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

export const api = {
  listProjects: () => call('GET', '/projects'),
  createProject: (body) => call('POST', '/projects', body),
  getProject: (id) => call('GET', `/projects/${id}`),
  updateProject: (id, patch) => call('PATCH', `/projects/${id}`, patch),
  draftAboutScope: (id, model) => call('POST', `/projects/${id}/about-scope/draft`, { model }),
  listModels: () => call('GET', '/models'),
  readConsole: (after) => call('GET', `/console?after=${after}`),
  readConsoleLine: (seq) => call('GET', `/console/lines/${seq}`),
  expand: (body) => call('POST', '/expand', body),
};

// Every other resource lives inside a project; there is no unscoped call.
export function projectApi(projectId) {
  const base = `/projects/${projectId}`;
  return {
    listSources: () => call('GET', `${base}/sources`),
    uploadSourceFile(file) {
      const form = new FormData();
      form.append('file', file, file.name);
      return request(`${base}/sources/upload`, { method: 'POST', body: form });
    },
    generate: (sourceId, model, options) => call('POST', `${base}/sources/${sourceId}/generate`, { model, ...options }),
    readingEstimate: (model, amount, care, mix) => call('GET', `${base}/reading-estimate?${new URLSearchParams({ model, amount, care, false_pct: String(mix?.false ?? 15), doubt_pct: String(mix?.doubts ?? 15) })}`),
    readFigures: (sourceId, model) => call('POST', `${base}/sources/${sourceId}/figures/read`, { model }),
    listThemes: () => call('GET', `${base}/themes`),
    createTheme: (body) => call('POST', `${base}/themes`, body),
    editTheme: (id, body) => call('PATCH', `${base}/themes/${id}`, body),
    mergeTheme: (id, into) => call('POST', `${base}/themes/${id}/merge`, { into }),
    splitTheme: (id, model) => call('POST', `${base}/themes/${id}/split`, { model }),
    confirmSplitTheme: (id, proposal) => call('POST', `${base}/themes/${id}/split/confirm`, { proposal }),
    undoThemeOperation: (snapshot) => call('POST', `${base}/themes/undo`, { snapshot }),
    listSamples(filters = {}) {
      const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value)).toString();
      return call('GET', `${base}/samples${query ? `?${query}` : ''}`);
    },
    repeatedAnswers: () => call('GET', `${base}/samples/repeated-answers`),
    reword: (ids, model) => call('POST', `${base}/samples/reword`, { sample_ids: ids, model }),
    undoReword: (batch) => call('POST', `${base}/samples/reword/${encodeURIComponent(batch)}/undo`),
    decideMany: (ids, decision) => call('POST', `${base}/samples/decide`, { sample_ids: ids, decision }),
    approve: (id) => call('POST', `${base}/samples/${id}/approve`),
    reject: (id) => call('POST', `${base}/samples/${id}/reject`),
    resetSample: (id) => call('POST', `${base}/samples/${id}/reset`),
    editSample: (id, body) => call('PUT', `${base}/samples/${id}`, body),
    changeKind: (id, body) => call('POST', `${base}/samples/${id}/kind`, body),
    confirmChecks: (id, body) => call('POST', `${base}/samples/${id}/checks`, body),
    draftRationale: (id, model) => call('POST', `${base}/samples/${id}/rationale/draft`, { model }),
    saveRationale: (id, body) => call('POST', `${base}/samples/${id}/rationale`, body),
    resetRationale: (id, rid) => call('POST', `${base}/samples/${id}/rationale/${rid}/reset`),
    pillars: () => call('GET', `${base}/pillars`),
    listRuns: () => call('GET', `${base}/runs`),
    stopRun: (kind, subject) => call('POST', `${base}/runs/${kind}/${subject}/stop`),
    continueRun: (kind, subject) => call('POST', `${base}/runs/${kind}/${subject}/continue`),
    runChallenge: (model) => call('POST', `${base}/challenge`, { model }),
    challenge: () => call('GET', `${base}/challenge`),
    listConflicts: (status = 'open') => call('GET', `${base}/conflicts?status=${status}`),
    resolveConflict: (id, body) => call('POST', `${base}/conflicts/${id}/resolve`, body),
    reopenConflict: (id) => call('POST', `${base}/conflicts/${id}/reopen`),
    listSimilar: () => call('GET', `${base}/similar`),
    keepOne: (keepId, sampleIds) => call('POST', `${base}/similar/keep-one`, { keep_id: keepId, sample_ids: sampleIds }),
    keepApart: (sampleIds, undo = false) => call('POST', `${base}/similar/keep-apart`, { sample_ids: sampleIds, undo }),
    listPatterns: () => call('GET', `${base}/patterns`),
    createPattern: (body) => call('POST', `${base}/patterns`, body),
    setPatternStatus: (id, status) => call('POST', `${base}/patterns/${id}/status`, { status }),
    createBatch: (patternId, body) => call('POST', `${base}/patterns/${patternId}/batches`, body),
    kbGraph: () => call('GET', `${base}/kb/graph`),
    connectTheme: (id, model) => call('POST', `${base}/themes/${id}/connect`, { model }),
    writeRefusals: (model) => call('POST', `${base}/refusals`, { model }),
    writeNeighbours: (model) => call('POST', `${base}/neighbours`, { model }),
    writeFalsePremises: (model) => call('POST', `${base}/false-premises`, { model }),
    writeKinds: (id, model, { unanswered_pct, false_premise_pct, neighbour_pct }) => call('POST', `${base}/sources/${id}/kinds`, { model, unanswered_pct, false_premise_pct, neighbour_pct }),
    setLicense: (id, license_basis) => call('PATCH', `${base}/sources/${id}`, { license_basis }),
    listDatasets: () => call('GET', `${base}/datasets`),
    exportDataset: (body) => call('POST', `${base}/datasets`, body),
    trainingVariants: () => call('GET', `${base}/training-variants`),
    prepareTraining: (model, train_model, prepare_count) => call('POST', `${base}/training-variants/prepare`, { model, train_model, prepare_count }),
    dropTrainingVariant: (id) => call('POST', `${base}/training-variants/${encodeURIComponent(id)}/drop`, {}),
    undoTrainingVariant: (id) => call('POST', `${base}/training-variants/${encodeURIComponent(id)}/undo`, {}),
    downloadUrl: (id) => `/api${base}/datasets/${id}/download`,
    trainModels: () => call('GET', `${base}/train/models`),
    trainPreflight: (body) => call('POST', `${base}/train/preflight`, body),
    startTraining: (body) => call('POST', `${base}/train/runs`, body),
    listTrainRuns: () => call('GET', `${base}/train/runs`),
    trainChanges: () => call('GET', `${base}/train/changes`),
    updateTrainRun: (id, body) => call('PATCH', `${base}/train/runs/${encodeURIComponent(id)}`, body),
    deleteTrainRun: (id) => call('DELETE', `${base}/train/runs/${encodeURIComponent(id)}`),
    undoDeleteTrainRun: (id) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/undo-delete`, {}),
    deleteOtherTrainRuns: () => call('DELETE', `${base}/train/runs?keep=in_use`),
    trainRun: (id) => call('GET', `${base}/train/runs/${encodeURIComponent(id)}`),
    trainEvents: (id, after = 0) => call('GET', `${base}/train/runs/${encodeURIComponent(id)}/events?after=${after}`),
    stopTraining: (id) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/stop`),
    continueTraining: (id) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/continue`),
    downloadTrainUrl: (id) => `/api${base}/train/runs/${encodeURIComponent(id)}/download`,
    compareTraining: (id, body = {}) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/compare`, body),
    trainComparison: (id) => call('GET', `${base}/train/runs/${encodeURIComponent(id)}/comparison`),
    chooseComparison: (id, item, choice) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/comparison/${encodeURIComponent(item)}/choice`, { choice }),
    tryTraining: (id, body) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/try`, body),
    draftRecallQuestions: (id) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/recall/draft`, {}),
    reviewRecallQuestion: (id, item, body) => call('POST', `${base}/train/runs/${encodeURIComponent(id)}/recall/${encodeURIComponent(item)}/review`, body),
  };
}
