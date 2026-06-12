const state = {
  documents: [],
  selectedDocId: null,
  debugVisible: false,
  chatMessages: [],
  chatCorpusMode: "auto",
  chatRetrievalMode: "agentic",
  selectedCorpusDocIds: [],
  config: {},
  ingestionMode: "hybrid_blob_skillset",
};

async function fetchJson(url, options = {}) {
  const timeoutMs = options.timeoutMs || 30000;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Request failed");
  }
  return response.json();
}

function $(selector) {
  return document.querySelector(selector);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function extractReferencedCitationIds(text) {
  const ids = new Set();
  const matches = String(text || "").matchAll(/\[(\d+)\]/g);
  for (const match of matches) {
    ids.add(Number(match[1]));
  }
  return ids;
}

function hasVisualIntent(text) {
  return /\b(diagram|figure|image|photo|picture|map|blueprint|chart|graph|illustration|visual|workflow|architecture)\b/i.test(
    String(text || "")
  );
}

function renderMarkdown(text) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let listMode = null;
  let listItems = [];
  let paragraph = [];
  let inCodeBlock = false;
  let codeLines = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  }

  function flushList() {
    if (!listMode || !listItems.length) return;
    const items = listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("");
    blocks.push(listMode === "ol" ? `<ol>${items}</ol>` : `<ul>${items}</ul>`);
    listMode = null;
    listItems = [];
  }

  function flushCodeBlock() {
    if (!codeLines.length) return;
    blocks.push(`<pre class="message-code"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    const unorderedMatch = line.match(/^[-*]\s+(.*)$/);
    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    const fenceMatch = line.match(/^```/);

    if (fenceMatch) {
      flushParagraph();
      flushList();
      if (inCodeBlock) {
        flushCodeBlock();
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(rawLine);
      continue;
    }

    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = Math.min(6, headingMatch[1].length);
      blocks.push(`<h${level} class="message-heading">${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    if (unorderedMatch) {
      flushParagraph();
      if (listMode !== "ul") {
        flushList();
        listMode = "ul";
      }
      listItems.push(unorderedMatch[1]);
      continue;
    }

    if (orderedMatch) {
      flushParagraph();
      if (listMode !== "ol") {
        flushList();
        listMode = "ol";
      }
      listItems.push(orderedMatch[1]);
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  flushCodeBlock();
  return blocks.join("") || `<p>${renderInlineMarkdown(text)}</p>`;
}

function buildCitationById(citations = []) {
  const map = new Map();
  citations.forEach((citation) => {
    if (citation && Number.isInteger(citation.reference_id)) {
      map.set(citation.reference_id, citation);
    }
  });
  return map;
}

function renderAnswerWithReferences(text, citations = []) {
  const html = renderMarkdown(text);
  const citationById = buildCitationById(citations);
  return html.replace(/\[(\d+)\]/g, (match, rawId) => {
    const refId = Number(rawId);
    if (!citationById.has(refId)) {
      return match;
    }
    return `<a href="#citation-ref-${refId}" class="inline-citation-link" data-citation-ref-link="${refId}">[${refId}]</a>`;
  });
}

function bindCitationReferenceLinks() {
  document.querySelectorAll("[data-citation-ref-link]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      const refId = node.dataset.citationRefLink;
      const target = document.getElementById(`citation-ref-${refId}`);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("citation-card-active");
      window.setTimeout(() => target.classList.remove("citation-card-active"), 1600);
    });
  });
}

function groupCitationsBySource(citations = []) {
  const groups = [];
  const byKey = new Map();
  citations.forEach((citation) => {
    const sourceName = citation.knowledge_source || "unknown-source";
    const indexName = citation.index_name || "unknown-index";
    const key = `${sourceName}::${indexName}`;
    if (!byKey.has(key)) {
      const group = { key, sourceName, indexName, citations: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    byKey.get(key).citations.push(citation);
  });
  return groups;
}

function setActiveScreen(screen) {
  document.querySelectorAll(".screen").forEach((node) => node.classList.remove("active"));
  document.querySelectorAll(".nav-link").forEach((node) => node.classList.remove("active"));
  $(`#screen-${screen}`).classList.add("active");
  document.querySelector(`.nav-link[data-screen="${screen}"]`).classList.add("active");
}

function stageLabel(value) {
  return value.replaceAll("_", " ");
}

function titleCaseWords(value) {
  return String(value || "")
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function shortDocId(docOrId) {
  const raw = typeof docOrId === "string" ? docOrId : docOrId?.doc_id;
  return raw ? String(raw).slice(0, 8) : "unknown";
}

function workshopProfileIdForDoc(doc) {
  const blobSkillset = doc?.enrichment_status?.blob_skillset || {};
  const searchObjects = blobSkillset.search_objects || {};
  const diagnostics = blobSkillset.diagnostics || {};
  return searchObjects.workshop_profile_id || diagnostics.workshop_profile?.id || doc?.workshop_skill_profile || "untracked";
}

function workshopProfileTitleForDoc(doc) {
  const blobSkillset = doc?.enrichment_status?.blob_skillset || {};
  const searchObjects = blobSkillset.search_objects || {};
  return searchObjects.workshop_profile_title || doc?.workshop_profile_title || titleCaseWords(workshopProfileIdForDoc(doc));
}

function formatTimestamp(value) {
  if (!value) return "N/A";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

function corpusDisplayLabel(doc) {
  return doc?.corpus_label || `${doc.file_name} · ${workshopProfileTitleForDoc(doc)} · ${shortDocId(doc)}`;
}

function corpusMetaLine(doc) {
  const parts = [`Profile ${workshopProfileTitleForDoc(doc)}`, `Doc ${shortDocId(doc)}`];
  if (doc?.source_kind) {
    parts.push(`Source ${doc.source_kind}`);
  }
  if (doc?.last_sync_time || doc?.created_at) {
    parts.push(`Time ${formatTimestamp(doc.last_sync_time || doc.created_at)}`);
  }
  return parts.join(" · ");
}

function statusClass(status) {
  if (status === "failed") return "failed";
  if (status === "processing") return "processing";
  return "";
}

function setGenerationStatus(kind, message) {
  const banner = $("#generation-status");
  if (!banner) return;
  const labels = {
    running: "Generation Running",
    success: "Generation Queued",
    error: "Generation Failed",
  };
  banner.className = "operation-status";
  banner.classList.add(kind);
  banner.classList.remove("hidden");
  banner.innerHTML = `<strong>${labels[kind] || "Generation Status"}</strong><div>${escapeHtml(message)}</div>`;
}

function clearGenerationStatus() {
  const banner = $("#generation-status");
  if (!banner) return;
  banner.className = "operation-status hidden";
  banner.innerHTML = "";
}

function getSelectedIngestionMode() {
  return $("#ingestion-mode-select")?.value || state.ingestionMode || state.config.default_ingestion_mode || "hybrid_blob_skillset";
}

function syncIngestionModeControl() {
  const select = $("#ingestion-mode-select");
  const caption = $("#ingestion-mode-caption");
  if (!select) return;
  const nextMode = state.ingestionMode || state.config.default_ingestion_mode || "hybrid_blob_skillset";
  select.value = nextMode;
  if (caption) {
    caption.textContent =
      nextMode === "hybrid_blob_skillset"
        ? "Hybrid mode uploads the file to Azure Blob, runs Azure AI Search skillset enrichment, and then merges those outputs back into the app-managed retrieval corpus."
        : "App-managed mode keeps parsing, normalization, chunking, and publishing inside the app without the Blob + skillset enrichment lane.";
  }
}

function syncRetrievalModeControl() {
  const select = $("#retrieval-mode-select");
  const caption = $("#retrieval-mode-caption");
  const activityTitle = $("#chat-activity-title");
  if (!select) return;
  select.value = state.chatRetrievalMode || "agentic";
  if (activityTitle) {
    activityTitle.textContent = state.chatRetrievalMode === "agentic" ? "Agentic Retrieval Activity" : "Retrieval Activity";
  }
  if (!caption) return;
  if (state.chatRetrievalMode === "full_text") {
    caption.textContent =
      "Full text search uses keyword and lexical matching over the canonical chunk index.";
    return;
  }
  if (state.chatRetrievalMode === "vector") {
    caption.textContent =
      "Vector search uses embedding similarity over chunk vectors in the canonical index.";
    return;
  }
  if (state.chatRetrievalMode === "hybrid") {
    caption.textContent =
      "Hybrid search combines keyword search and vector similarity over the same chunk corpus.";
    return;
  }
  caption.textContent =
    "Agentic retrieval uses the official Azure AI Search knowledge-base path with query planning, subqueries, and grounded synthesis.";
}

function getReadyDocuments() {
  return state.documents.filter((doc) => doc.status === "ready");
}

function syncSelectedCorpusDocIds() {
  const readyIds = new Set(getReadyDocuments().map((doc) => doc.doc_id));
  state.selectedCorpusDocIds = state.selectedCorpusDocIds.filter((docId) => readyIds.has(docId));
  if (state.chatCorpusMode === "custom" && state.selectedCorpusDocIds.length === 0) {
    if (state.selectedDocId && readyIds.has(state.selectedDocId)) {
      state.selectedCorpusDocIds = [state.selectedDocId];
    } else {
      const firstReady = getReadyDocuments()[0];
      if (firstReady) {
        state.selectedCorpusDocIds = [firstReady.doc_id];
      }
    }
  }
}

function renderMetrics(payload) {
  const metrics = [
    ["Total Documents", payload.total_documents],
    ["Processing Queue", payload.processing_queue],
    ["Ready for Chat", payload.ready_for_chat],
    ["Failed Jobs", payload.failed_jobs],
  ];
  $("#metrics-grid").innerHTML = metrics
    .map(
      ([label, value]) => `
      <article class="metric">
        <p class="eyebrow">${label}</p>
        <p class="metric-value">${value}</p>
      </article>
    `
    )
    .join("");
  $("#recent-activity").innerHTML =
    payload.recent_activity.length === 0
      ? `<div class="muted">No activity yet.</div>`
      : payload.recent_activity
          .map(
            (item) => `
      <div class="table-row">
        <div>${item.file_name}</div>
        <div>${stageLabel(item.stage)}</div>
        <div>${new Date(item.updated_at).toLocaleString()}</div>
        <div>${item.doc_id.slice(0, 8)}</div>
      </div>
    `
          )
          .join("");
}

function renderDocuments() {
  $("#documents-list").innerHTML =
    state.documents.length === 0
      ? `<div class="muted">No submitted documents yet.</div>`
      : state.documents
          .map(
            (doc) => `
      <article class="doc-card">
        <div class="panel-head">
          <h4>${escapeHtml(corpusDisplayLabel(doc))}</h4>
          <span class="status-pill ${statusClass(doc.status)}">${doc.status}</span>
        </div>
        <p class="muted small">${escapeHtml(corpusMetaLine(doc))}</p>
        <p class="muted small">Format: ${doc.format} · Parser: ${doc.parser_path}</p>
        <p class="muted small">Stage: ${stageLabel(doc.stage)}</p>
        <div class="progress-track"><div class="progress-fill" style="width:${doc.progress}%"></div></div>
        <p class="muted small">Chunks: ${doc.chunk_count || 0} · Sections: ${doc.section_count || 0}</p>
        <div class="upload-form">
          <button class="ghost" data-doc-detail="${doc.doc_id}">Inspect</button>
          <button class="ghost" data-doc-retry="${doc.doc_id}">Retry</button>
          <button class="ghost danger-ghost" data-doc-delete="${doc.doc_id}">Delete</button>
        </div>
      </article>
    `
          )
          .join("");

  document.querySelectorAll("[data-doc-detail]").forEach((button) =>
    button.addEventListener("click", () => loadDocumentDetail(button.dataset.docDetail))
  );
  document.querySelectorAll("[data-doc-retry]").forEach((button) =>
    button.addEventListener("click", async () => {
      await fetchJson(`/api/documents/${button.dataset.docRetry}/retry`, { method: "POST" });
      await refreshDocuments();
    })
  );
  document.querySelectorAll("[data-doc-delete]").forEach((button) =>
    button.addEventListener("click", async () => {
      await handleDeleteDocument(button.dataset.docDelete);
    })
  );
}

function renderDetail(doc) {
  const warnings = (doc.warnings || []).map((item) => `<li>${item}</li>`).join("");
  const errors = (doc.errors || []).map((item) => `<li>${item}</li>`).join("");
  const metadata = doc.intermediate?.metadata || {};
  const segmentSummary = metadata.segment_count
    ? `${metadata.segment_count} segment(s) via ${metadata.segmentation_strategy || "segmentation"}`
    : "N/A";
  const figureSummary = metadata.figure_count ? `${metadata.figure_count} extracted figure artifact(s)` : "N/A";
  const blobSkillset = doc.enrichment_status?.blob_skillset || metadata.search_skillset_blob || null;
  const blobStatus = blobSkillset?.status || "not_run";
  const blobMessage = blobSkillset?.message || "No Blob + skillset enrichment status recorded.";
  const blobObjects = blobSkillset?.search_objects || {};
  const nativeStatus = doc.enrichment_status?.native_multimodal || {};
  const workshopProfileTitle = workshopProfileTitleForDoc(doc);
  const workshopProfileId = workshopProfileIdForDoc(doc);
  const activity = (doc.activity || [])
    .slice()
    .reverse()
    .slice(0, 8)
    .map((item) => `<div><strong>${item.level}</strong> ${item.message}</div>`)
    .join("");

  $("#document-detail").innerHTML = `
    <h4>${escapeHtml(corpusDisplayLabel(doc))}</h4>
    <div class="detail-grid">
      <div><strong>Doc ID</strong>${escapeHtml(doc.doc_id)}</div>
      <div><strong>Workshop Profile</strong>${escapeHtml(workshopProfileTitle)} (${escapeHtml(workshopProfileId)})</div>
      <div><strong>Source Kind</strong>${escapeHtml(doc.source_kind || "upload")}</div>
      <div><strong>Created</strong>${escapeHtml(formatTimestamp(doc.created_at))}</div>
      <div><strong>Detected Format</strong>${doc.format}</div>
      <div><strong>Complexity</strong>${doc.complexity}</div>
      <div><strong>Parser Path</strong>${doc.parser_path}</div>
      <div><strong>Ingestion Mode</strong>${doc.ingestion_mode || "app_managed"}</div>
      <div><strong>Page Count</strong>${doc.page_count || "N/A"}</div>
      <div><strong>Chunk Count</strong>${doc.chunk_count}</div>
      <div><strong>Segmentation</strong>${segmentSummary}</div>
      <div><strong>Figure Artifacts</strong>${figureSummary}</div>
      <div><strong>Publish Status</strong>${doc.publish_status.message}</div>
      <div><strong>Last Sync</strong>${doc.publish_status.last_sync_time || "N/A"}</div>
      <div><strong>Stored Path</strong>${doc.stored_path}</div>
      <div><strong>External Source URI</strong>${doc.external_source_uri || "N/A"}</div>
    </div>
    <div>
      <strong>Blob + Skillset Enrichment</strong>
      <div class="detail-grid">
        <div><strong>Status</strong>${escapeHtml(blobStatus)}</div>
        <div><strong>Message</strong>${escapeHtml(blobMessage)}</div>
        <div><strong>Blob Source</strong>${doc.external_source_path || "N/A"}</div>
        <div><strong>Enrichment Index</strong>${blobObjects.index_name || "N/A"}</div>
        <div><strong>Skillset</strong>${blobObjects.skillset_name || "N/A"}</div>
        <div><strong>Indexer</strong>${blobObjects.indexer_name || "N/A"}</div>
        <div><strong>Workshop Profile</strong>${escapeHtml(blobObjects.workshop_profile_title || workshopProfileTitle)}</div>
      </div>
    </div>
    <div>
      <strong>Native Blob Multimodal Retrieval</strong>
      <div class="detail-grid">
        <div><strong>Status</strong>${escapeHtml(nativeStatus.status || "not_run")}</div>
        <div><strong>Message</strong>${escapeHtml(nativeStatus.message || "No native multimodal status recorded.")}</div>
        <div><strong>Knowledge Source</strong>${escapeHtml(nativeStatus.knowledge_source_name || "N/A")}</div>
        <div><strong>Knowledge Base</strong>${escapeHtml(nativeStatus.knowledge_base_name || "N/A")}</div>
      </div>
    </div>
    <div>
      <strong>Warnings</strong>
      ${warnings ? `<ul>${warnings}</ul>` : `<div class="muted">None</div>`}
    </div>
    <div>
      <strong>Errors</strong>
      ${errors ? `<ul>${errors}</ul>` : `<div class="muted">None</div>`}
    </div>
    <div>
      <strong>Recent Activity</strong>
      <div class="table-like">${activity || `<div class="muted">No activity.</div>`}</div>
    </div>
  `;
}

async function loadDocumentDetail(docId) {
  state.selectedDocId = docId;
  const doc = await fetchJson(`/api/documents/${docId}`);
  renderDetail(doc);
}

async function refreshDocuments() {
  state.documents = await fetchJson("/api/documents");
  syncSelectedCorpusDocIds();
  renderDocuments();
  renderChatScopeControls();
  if (state.selectedDocId) {
    const exists = state.documents.some((item) => item.doc_id === state.selectedDocId);
    if (exists) {
      await loadDocumentDetail(state.selectedDocId);
    } else {
      state.selectedDocId = null;
      $("#document-detail").innerHTML = `<div class="detail-card muted">Select a document card to inspect the full pipeline state.</div>`;
    }
  }
}

async function refreshDashboard() {
  const payload = await fetchJson("/api/dashboard");
  renderMetrics(payload);
}

async function refreshKnowledge() {
  const payload = await fetchJson("/api/knowledge/status");
  $("#knowledge-status").innerHTML = `
    <div class="detail-grid">
      <div><strong>Knowledge Base</strong>${payload.selected_knowledge_base}</div>
      <div><strong>Mode</strong>${payload.status.mode}</div>
      <div><strong>Ready</strong>${payload.status.ready}</div>
      <div><strong>Resource</strong>${payload.status.resource}</div>
      <div><strong>Last Sync</strong>${payload.status.last_sync_time || "N/A"}</div>
      <div><strong>Message</strong>${payload.status.message}</div>
    </div>
  `;
  $("#knowledge-documents").innerHTML =
    payload.documents.length === 0
      ? `<div class="muted">No ready documents have been published yet.</div>`
      : payload.documents
          .map(
            (item) => `
        <div class="table-row corpus-row">
          <div>
            <strong>${escapeHtml(corpusDisplayLabel(item))}</strong>
            <div class="muted small">${escapeHtml(corpusMetaLine(item))}</div>
            <div class="muted small">${escapeHtml(item.index_name || "No index name")} · ${escapeHtml(item.knowledge_source_name || "No knowledge source")}</div>
          </div>
          <div>${item.chunk_count}</div>
          <div>${item.section_count}</div>
          <div>${escapeHtml(formatTimestamp(item.last_sync_time))}</div>
          <div><button class="ghost danger-ghost" data-knowledge-delete="${item.doc_id}">Delete</button></div>
        </div>
      `
          )
          .join("");
  document.querySelectorAll("[data-knowledge-delete]").forEach((button) =>
    button.addEventListener("click", async () => {
      await handleDeleteDocument(button.dataset.knowledgeDelete);
    })
  );
  renderChatScopeControls();
}

async function refreshConfig() {
  const payload = await fetchJson("/api/config");
  state.config = payload;
  state.ingestionMode = payload.default_ingestion_mode || state.ingestionMode;
  syncIngestionModeControl();
  syncRetrievalModeControl();
  $("#config-summary").innerHTML = `
    <div>Default ingestion: ${escapeHtml(payload.default_ingestion_mode || "app_managed")}</div>
    <div>Pipeline lane: ${escapeHtml(payload.search_pipeline_mode || "app_managed")}</div>
    <div>Search: ${payload.azure_search_enabled ? "configured" : "local preview"}</div>
    <div>Core lab modes: ${escapeHtml((payload.available_retrieval_modes || []).join(", ") || "agentic")}</div>
    <div>Agentic retrieval: ${payload.azure_agentic_retrieval_enabled ? "enabled" : "off"}</div>
    <div>Planning model: ${
      payload.azure_agentic_planning_model_enabled
        ? escapeHtml(payload.azure_agentic_planning_model || "configured")
        : "off"
    }</div>
    <div>Multi-index routing: ${payload.azure_search_multi_index_enabled ? "configured" : "primary index only"}</div>
    <div>Blob skillset lane: ${payload.azure_search_blob_ingestion_enabled ? "configured" : "off"}</div>
    <div>Optional multimodal extension: ${payload.azure_search_native_multimodal_enabled ? "configured" : "off"}</div>
    <div>Workshop profile: ${escapeHtml(payload.workshop_skill_profile || "untracked")}</div>
    <div>Skill extractor: ${escapeHtml(payload.azure_search_skillset_preferred_extractor || "layout")}</div>
    <div>Answer synthesis: ${payload.azure_search_enable_answer_synthesis ? "enabled" : "off"}</div>
    <div>Enrichment cache: ${payload.azure_search_enable_enrichment_cache ? "enabled" : "off"}</div>
    <div>Prompt skill: ${payload.azure_search_enable_genai_prompt_skill ? "enabled" : "off"}</div>
    <div>Integrated vectorization: ${payload.azure_search_enable_integrated_vectorization ? "enabled" : "off"}</div>
    <div>Image serving: ${payload.azure_search_enable_image_serving ? "enabled" : "off"}</div>
    <div>Doc Intelligence: ${payload.azure_document_intelligence_enabled ? "configured" : "off"}</div>
    <div>Content Understanding: ${payload.azure_content_understanding_enabled ? "configured" : "off"}</div>
    <div>Blob image store: ${payload.azure_blob_storage_enabled ? "configured" : "off"}</div>
  `;
}

function chatTimeoutMs() {
  const configuredSeconds = Number(state.config?.request_timeout_seconds || 60);
  return Math.max(120000, (configuredSeconds + 30) * 1000);
}

function renderChatScopeControls() {
  const readyDocs = getReadyDocuments();
  const autoButton = $("#chat-scope-auto");
  const customButton = $("#chat-scope-custom");
  const picker = $("#chat-corpus-picker");
  const summary = $("#chat-scope-summary");

  autoButton.classList.toggle("active", state.chatCorpusMode === "auto");
  customButton.classList.toggle("active", state.chatCorpusMode === "custom");

  if (!readyDocs.length) {
    picker.classList.add("hidden");
    picker.innerHTML = "";
    summary.textContent = "No ready corpora are available yet.";
    return;
  }

  if (state.chatCorpusMode === "auto") {
    picker.classList.add("hidden");
    picker.innerHTML = "";
    summary.textContent = `Auto mode uses all ${readyDocs.length} ready corpora.`;
    return;
  }

  picker.classList.remove("hidden");
  summary.textContent =
    state.selectedCorpusDocIds.length > 0
      ? `Custom selection targets ${state.selectedCorpusDocIds.length} corpus${state.selectedCorpusDocIds.length === 1 ? "" : "a"}.`
      : "Select at least one ready corpus.";
  picker.innerHTML = readyDocs
    .map(
      (doc) => `
      <label class="corpus-option">
        <input type="checkbox" data-corpus-checkbox="${doc.doc_id}" ${state.selectedCorpusDocIds.includes(doc.doc_id) ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(corpusDisplayLabel(doc))}</strong>
          <span class="muted small">${escapeHtml(corpusMetaLine(doc))}</span>
          <span class="muted small">Chunks ${doc.chunk_count || 0} · Sections ${doc.section_count || 0}</span>
        </span>
      </label>
    `
    )
    .join("");
  document.querySelectorAll("[data-corpus-checkbox]").forEach((checkbox) =>
    checkbox.addEventListener("change", () => {
      const selected = Array.from(document.querySelectorAll("[data-corpus-checkbox]:checked")).map(
        (node) => node.dataset.corpusCheckbox
      );
      state.selectedCorpusDocIds = selected;
      renderChatScopeControls();
    })
  );
}

async function handleDeleteDocument(docId) {
  const documentRecord = state.documents.find((doc) => doc.doc_id === docId);
  const label = documentRecord ? corpusDisplayLabel(documentRecord) : docId;
  const confirmed = window.confirm(`Delete corpus "${label}" and remove its indexed chunks?`);
  if (!confirmed) return;

  await fetchJson(`/api/documents/${docId}`, { method: "DELETE", timeoutMs: 60000 });
  if (state.selectedDocId === docId) {
    state.selectedDocId = null;
  }
  state.selectedCorpusDocIds = state.selectedCorpusDocIds.filter((value) => value !== docId);
  await Promise.all([refreshDashboard(), refreshDocuments(), refreshKnowledge()]);
}

function collectImageEvidence(citations, answerText = "") {
  const referencedIds = extractReferencedCitationIds(answerText);
  const eligibleCitations =
    referencedIds.size > 0
      ? (citations || []).filter((citation) => referencedIds.has(Number(citation.reference_id)))
      : citations || [];
  const seen = new Set();
  const images = [];
  for (const citation of eligibleCitations) {
    const renderVisualAssets = hasVisualIntent(
      [answerText, citation.supporting_query, citation.snippet, citation.title].filter(Boolean).join(" ")
    );
    if (!renderVisualAssets) {
      continue;
    }
    for (const image of citation.image_evidence || []) {
      if (!image.artifact_id || !citation.doc_id) continue;
      const key = `${citation.doc_id}:${image.artifact_id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      images.push({
        ...image,
        kind: "artifact",
        doc_id: citation.doc_id,
      });
    }
    for (const assetPath of citation.asset_image_paths || []) {
      const key = `native:${assetPath}`;
      if (!assetPath || seen.has(key)) continue;
      seen.add(key);
      images.push({
        kind: "native_asset",
        asset_path: assetPath,
        description: citation.title || "Native image evidence",
      });
    }
  }
  return images;
}

function buildEvidenceImageSrc(image) {
  if (image.kind === "native_asset") {
    return `/api/native-images?path=${encodeURIComponent(image.asset_path)}`;
  }
  return `/api/documents/${image.doc_id}/figures/${image.artifact_id}`;
}

function buildEvidenceImageAlt(image) {
  return image.description || image.image_name || "Figure evidence";
}

function renderEvidenceImageCards(images, limit = 4) {
  const cards = (images || [])
    .slice(0, limit)
    .map(
      (image) => `
      <figure class="image-evidence-card">
        <img src="${buildEvidenceImageSrc(image)}" alt="${escapeHtml(buildEvidenceImageAlt(image))}" loading="lazy" />
        <figcaption>${escapeHtml(buildEvidenceImageAlt(image))}</figcaption>
      </figure>
    `
    )
    .join("");
  return cards ? `<div class="image-evidence-grid">${cards}</div>` : "";
}

function renderChatThread() {
  const thread = $("#chat-thread");
  if (!state.chatMessages.length) {
    thread.innerHTML = `<div class="chat-empty">The corpus must be ready before chat returns grounded results.</div>`;
    return;
  }

  thread.innerHTML = state.chatMessages
    .map((message) => {
      const images =
        message.role === "assistant"
          ? collectImageEvidence(message.citations || [], message.answerText || "")
          : [];
      return `
        <div class="message-row ${message.role}">
          <article class="message-bubble ${message.pending ? "pending" : ""}">
            <div class="message-role">${message.role === "user" ? "You" : "Agent"}</div>
            <div class="message-body">${message.html}</div>
            ${
              images.length
                ? `<div class="message-images">${renderEvidenceImageCards(images, 4)}</div>`
                : ""
            }
          </article>
        </div>
      `;
    })
    .join("");

  thread.scrollTop = thread.scrollHeight;
  bindCitationReferenceLinks();
}

function renderCitations(citations, diagnostics = {}, answerText = "") {
  if (!citations || citations.length === 0) {
    $("#chat-citations").innerHTML = `<div class="muted">No citations returned.</div>`;
    return;
  }

  const referencedIds = extractReferencedCitationIds(answerText);
  const sourceCounts = diagnostics.evidence_source_counts || {};
  const missingSources = diagnostics.missing_positive_sources || [];
  const summary = `
    <article class="citation-summary">
      <strong>Evidence Summary</strong>
      <div class="muted small">Rendered knowledge sources: ${escapeHtml(
        Object.entries(sourceCounts)
          .map(([source, count]) => `${source} (${count})`)
          .join(", ") || "none"
      )}</div>
      ${
        missingSources.length
          ? `<div class="muted small">Positive retrieval sources still missing evidence cards: ${escapeHtml(missingSources.join(", "))}</div>`
          : `<div class="muted small">All positive retrieval sources are represented in the evidence panel.</div>`
      }
    </article>
  `;

  const groups = groupCitationsBySource(citations);
  const html = groups
    .map(
      (group) => `
      <section class="citation-group">
        <div class="citation-group-head">
          <strong>${escapeHtml(group.sourceName)}</strong>
          <span class="muted small">${escapeHtml(group.indexName)} · ${group.citations.length} chunk${
            group.citations.length === 1 ? "" : "s"
          }</span>
        </div>
        ${[...group.citations]
          .sort((left, right) => {
            const leftUsed = referencedIds.has(Number(left.reference_id)) ? 0 : 1;
            const rightUsed = referencedIds.has(Number(right.reference_id)) ? 0 : 1;
            if (leftUsed !== rightUsed) {
              return leftUsed - rightUsed;
            }
            return Number(left.reference_id || 999) - Number(right.reference_id || 999);
          })
          .map(
            (item) => {
              const isReferenced = referencedIds.has(Number(item.reference_id));
              const renderVisualAssets =
                referencedIds.size === 0
                  ? hasVisualIntent([item.supporting_query, item.snippet, item.title].filter(Boolean).join(" "))
                  : isReferenced &&
                    hasVisualIntent([answerText, item.supporting_query, item.snippet, item.title].filter(Boolean).join(" "));
              return `
          <article class="citation-card ${isReferenced ? "citation-card-used" : ""}" id="citation-ref-${item.reference_id}" data-citation-card="${item.reference_id}">
            <div class="citation-card-head">
              <span class="citation-ref-badge">[${item.reference_id ?? "?"}]</span>
              <div>
                <strong>${escapeHtml(item.title)}</strong>
                <div class="muted small">${escapeHtml(item.uri || item.chunk_id || "No URI available")}</div>
              </div>
            </div>
            <div class="citation-meta muted small">
              ${
                item.page_numbers?.length
                  ? `Pages ${item.page_numbers.join(", ")}`
                  : "No page number available"
              }
              ${isReferenced ? " · cited in answer" : ""}
              ${item.evidence_kind === "activity_support" ? " · source-balanced support" : ""}
              ${item.retrieval_step ? ` · from step ${item.retrieval_step}` : ""}
            </div>
            ${
              item.supporting_query
                ? `<div class="citation-query muted small">Support query: ${escapeHtml(item.supporting_query)}</div>`
                : ""
            }
            <div>${escapeHtml(item.snippet)}</div>
            ${
              renderVisualAssets && (item.image_evidence?.length || item.asset_image_paths?.length)
                ? renderEvidenceImageCards(
                    [
                      ...(item.image_evidence || [])
                        .filter((image) => image.artifact_id && item.doc_id)
                        .map((image) => ({ ...image, kind: "artifact", doc_id: item.doc_id })),
                      ...(item.asset_image_paths || []).map((assetPath) => ({
                        kind: "native_asset",
                        asset_path: assetPath,
                        description: item.title || "Native image evidence",
                      })),
                    ],
                    3
                  )
                : ""
            }
          </article>
        `;
            }
          )
          .join("")}
      </section>
    `
    )
    .join("");

  $("#chat-citations").innerHTML = summary + html;
}

function renderSubqueries(diagnostics = {}) {
  const subqueries = diagnostics.subqueries || [];
  const activity = diagnostics.activity || [];
  const hasReasoning = activity.some((item) => item.type === "agenticReasoning");
  const selectedIndexes = diagnostics.selected_search_indexes || [];
  const selectedSources = diagnostics.selected_knowledge_sources || [];
  const selectedNativeSources = diagnostics.selected_native_knowledge_sources || [];
  const routingMode = diagnostics.routing_mode;
  const routingReason = diagnostics.routing_reason;
  const searchMethod = diagnostics.search_method || diagnostics.retrieval_mode;
  const displayMethod = searchMethod ? titleCaseWords(String(searchMethod).replaceAll("_", " ")) : "";
  const routeSummary = selectedIndexes.length
    ? `<article class="subquery-note"><strong>Routing</strong><div>${
        diagnostics.multi_index_routing ? "Multi-index" : "Single-index"
      } request over ${escapeHtml(selectedIndexes.join(", "))}</div>${
        selectedSources.length ? `<div class="muted small">Knowledge sources: ${escapeHtml(selectedSources.join(", "))}</div>` : ""
      }${displayMethod ? `<div class="muted small">Retrieval: ${escapeHtml(displayMethod)}</div>` : ""}${
        routingMode ? `<div class="muted small">Routing: ${escapeHtml(routingMode)}</div>` : ""
      }${
        routingReason ? `<div class="muted small">${escapeHtml(routingReason)}</div>` : ""
      }</article>`
    : selectedNativeSources.length
      ? `<article class="subquery-note"><strong>Routing</strong><div>Native Blob multimodal request</div><div class="muted small">Knowledge sources: ${escapeHtml(
          selectedNativeSources.join(", ")
        )}</div></article>`
    : "";

  if (!subqueries.length) {
    $("#chat-subqueries").innerHTML = hasReasoning
      ? routeSummary +
        `<article class="subquery-note">Agentic reasoning ran, but Azure Search did not expose decomposed search steps in the response payload for this request.</article>`
      : routeSummary || `<div class="muted">No retrieval trace yet.</div>`;
    return;
  }

  const note =
    subqueries.length === 1 && hasReasoning
      ? `<article class="subquery-note">This request used Azure Search agentic reasoning, but the service exposed only one concrete search step in the current payload. That is not just a UI collapse.</article>`
      : "";

  $("#chat-subqueries").innerHTML =
    routeSummary +
    note +
    subqueries
      .map(
        (item) => `
      <article class="subquery-card">
        <strong>Step ${item.step}</strong>
        <div class="muted small">Search intent</div>
        <div class="subquery-intent">${escapeHtml(item.display_search || item.search || "No search text returned")}</div>
        ${
          item.raw_search && (item.display_search || "").trim() !== item.raw_search.trim()
            ? `<details class="subquery-raw"><summary>Raw search</summary><div class="muted small">${escapeHtml(item.raw_search)}</div></details>`
            : ""
        }
        <div class="muted small">${escapeHtml(item.knowledge_source || "Knowledge source unavailable")} · ${escapeHtml(item.activity_type || "searchIndex")} · ${item.result_count ?? "?"} hits · ${item.elapsed_ms ?? "?"} ms</div>
      </article>
    `
      )
      .join("");
}

async function handleUpload(event) {
  event.preventDefault();
  const file = $("#upload-input").files[0];
  if (!file) return;
  const ingestionMode = getSelectedIngestionMode();
  const formData = new FormData();
  formData.append("file", file);
  formData.append("ingestion_mode", ingestionMode);
  setGenerationStatus("running", `Uploading ${file.name} and queuing it for ingestion in ${ingestionMode} mode...`);
  try {
    await fetchJson("/api/documents/upload", { method: "POST", body: formData });
    $("#upload-form").reset();
    await refreshDashboard();
    await refreshDocuments();
    await refreshKnowledge();
    setGenerationStatus("success", `${file.name} was uploaded and queued for ingestion in ${ingestionMode} mode.`);
  } catch (error) {
    setGenerationStatus("error", error.message || "Document upload failed.");
  }
}

async function handleGenerateRandomResearch() {
  const button = $("#generate-random-research");
  const ingestionMode = getSelectedIngestionMode();
  button.disabled = true;
  button.textContent = "Generating…";
  setGenerationStatus(
    "running",
    `Generating a large research corpus for ${ingestionMode} mode. This can take a minute or two because the PDF is created before the ingestion job is queued.`
  );
  try {
    const payload = await fetchJson(
      `/api/samples/random-research-corpus?ingestion_mode=${encodeURIComponent(ingestionMode)}`,
      { method: "POST", timeoutMs: 120000 }
    );
    state.selectedDocId = payload.job.doc_id;
    await Promise.all([refreshDashboard(), refreshDocuments(), refreshKnowledge()]);
    await loadDocumentDetail(payload.job.doc_id);
    const sampleLabel = payload.sample.report_title || payload.sample.topic_key || "Research corpus";
    setGenerationStatus(
      "success",
      `${sampleLabel} was generated (${payload.sample.page_count} pages) and queued for ingestion as ${payload.sample.file_name}.`
    );
  } catch (error) {
    setGenerationStatus("error", error.message || "Random research corpus generation failed.");
    $("#document-detail").innerHTML = `<div class="muted">${error.message}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Generate Random Research Corpus";
  }
}

async function handleGenerateFuturesReport() {
  const button = $("#generate-futures-report");
  const ingestionMode = getSelectedIngestionMode();
  button.disabled = true;
  button.textContent = "Generating…";
  setGenerationStatus(
    "running",
    `Generating the AI futures report for ${ingestionMode} mode. This can take a minute or two before the ingestion job appears.`
  );
  try {
    const payload = await fetchJson(
      `/api/samples/generative-ai-futures-report?ingestion_mode=${encodeURIComponent(ingestionMode)}`,
      { method: "POST", timeoutMs: 120000 }
    );
    state.selectedDocId = payload.job.doc_id;
    await Promise.all([refreshDashboard(), refreshDocuments(), refreshKnowledge()]);
    await loadDocumentDetail(payload.job.doc_id);
    setGenerationStatus(
      "success",
      `${payload.sample.file_name} was generated (${payload.sample.page_count} pages) and queued for ingestion.`
    );
  } catch (error) {
    setGenerationStatus("error", error.message || "AI futures report generation failed.");
    $("#document-detail").innerHTML = `<div class="muted">${error.message}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Generate AI Futures Report";
  }
}

async function handleGenerateConstructionReport() {
  const button = $("#generate-construction-report");
  const ingestionMode = getSelectedIngestionMode();
  button.disabled = true;
  button.textContent = "Generating…";
  setGenerationStatus(
    "running",
    `Generating the construction report with blueprint-style diagrams for ${ingestionMode} mode. This can take a minute or two before the job is queued.`
  );
  try {
    const payload = await fetchJson(
      `/api/samples/construction-industry-report?ingestion_mode=${encodeURIComponent(ingestionMode)}`,
      {
        method: "POST",
        timeoutMs: 120000,
      }
    );
    state.selectedDocId = payload.job.doc_id;
    await Promise.all([refreshDashboard(), refreshDocuments(), refreshKnowledge()]);
    await loadDocumentDetail(payload.job.doc_id);
    setGenerationStatus(
      "success",
      `${payload.sample.file_name} was generated (${payload.sample.page_count} pages) and queued for ingestion.`
    );
  } catch (error) {
    setGenerationStatus("error", error.message || "Construction report generation failed.");
    $("#document-detail").innerHTML = `<div class="muted">${error.message}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Generate Construction Report";
  }
}

async function handleChat(event) {
  event.preventDefault();
  const input = $("#chat-input");
  const question = input.value.trim();
  if (!question) return;
  const selectedDocIds = state.chatCorpusMode === "custom" ? state.selectedCorpusDocIds.slice() : [];
  if (state.chatCorpusMode === "custom" && selectedDocIds.length === 0) {
    $("#chat-subqueries").innerHTML = `<div class="muted">Select at least one ready corpus before sending a custom-scoped question.</div>`;
    return;
  }
  input.value = "";
  input.focus();
  const submitButton = $('#chat-form button[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = "Running…";
  $("#chat-citations").innerHTML = `<div class="muted">Waiting for grounded response…</div>`;
  $("#chat-subqueries").innerHTML = `<div class="muted">Waiting for query plan…</div>`;
  state.chatMessages.push({
    role: "user",
    html: renderMarkdown(question),
    pending: false,
    citations: [],
  });
  state.chatMessages.push({
    role: "assistant",
    html: (() => {
      const scopeMessage =
        state.chatCorpusMode === "custom"
          ? `over ${selectedDocIds.length} selected corpus${selectedDocIds.length === 1 ? "" : "a"}`
          : "over all ready corpora";
      const modeMessage =
        state.chatRetrievalMode === "full_text"
          ? "using full text search"
          : state.chatRetrievalMode === "vector"
            ? "using vector search"
            : state.chatRetrievalMode === "hybrid"
              ? "using hybrid search"
              : "using agentic retrieval";
      return `<p>Running grounded retrieval ${scopeMessage} ${modeMessage}…</p>`;
    })(),
    pending: true,
    citations: [],
  });
  renderChatThread();
  try {
    const timeoutMs = chatTimeoutMs();
    const payload = await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        include_debug: true,
        corpus_mode: state.chatCorpusMode,
        corpus_doc_ids: selectedDocIds,
        retrieval_mode: state.chatRetrievalMode,
      }),
      timeoutMs,
    });
    state.chatMessages[state.chatMessages.length - 1] = {
      role: "assistant",
      html: renderAnswerWithReferences(payload.answer, payload.citations || []),
      answerText: payload.answer || "",
      pending: false,
      citations: payload.citations || [],
      diagnostics: payload.diagnostics || {},
    };
    renderChatThread();
    renderCitations(payload.citations || [], payload.diagnostics || {}, payload.answer || "");
    renderSubqueries(payload.diagnostics || {});
    $("#chat-debug").textContent = JSON.stringify(payload.diagnostics, null, 2);
  } catch (error) {
    const timeoutSeconds = Math.round(chatTimeoutMs() / 1000);
    const message =
      error.name === "AbortError"
        ? `Grounded retrieval timed out after ${timeoutSeconds} seconds.`
        : error.message || "Grounded retrieval failed.";
    state.chatMessages[state.chatMessages.length - 1] = {
      role: "assistant",
      html: renderMarkdown(message),
      answerText: message,
      pending: false,
      citations: [],
      diagnostics: { error: message },
    };
    renderChatThread();
    $("#chat-citations").innerHTML = `<div class="muted">${escapeHtml(message)}</div>`;
    $("#chat-subqueries").innerHTML = `<div class="muted">${escapeHtml(message)}</div>`;
    $("#chat-debug").textContent = JSON.stringify({ error: message }, null, 2);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Send";
  }
}

async function bootstrap() {
  document.querySelectorAll(".nav-link").forEach((button) =>
    button.addEventListener("click", () => setActiveScreen(button.dataset.screen))
  );
  $("#refresh-dashboard").addEventListener("click", refreshDashboard);
  $("#refresh-documents").addEventListener("click", refreshDocuments);
  $("#sync-knowledge").addEventListener("click", async () => {
    await fetchJson("/api/knowledge/sync", { method: "POST" });
    await refreshKnowledge();
  });
  $("#toggle-debug").addEventListener("click", () => {
    state.debugVisible = !state.debugVisible;
    $("#chat-debug").classList.toggle("hidden", !state.debugVisible);
  });
  $("#chat-scope-auto").addEventListener("click", () => {
    state.chatCorpusMode = "auto";
    renderChatScopeControls();
  });
  $("#chat-scope-custom").addEventListener("click", () => {
    state.chatCorpusMode = "custom";
    syncSelectedCorpusDocIds();
    renderChatScopeControls();
  });
  $("#retrieval-mode-select").addEventListener("change", (event) => {
    state.chatRetrievalMode = event.target.value;
    syncRetrievalModeControl();
  });
  $("#generate-random-research").addEventListener("click", handleGenerateRandomResearch);
  $("#generate-futures-report").addEventListener("click", handleGenerateFuturesReport);
  $("#generate-construction-report").addEventListener("click", handleGenerateConstructionReport);
  $("#ingestion-mode-select").addEventListener("change", (event) => {
    state.ingestionMode = event.target.value;
    syncIngestionModeControl();
  });
  $("#upload-form").addEventListener("submit", handleUpload);
  $("#chat-form").addEventListener("submit", handleChat);

  await Promise.all([refreshConfig(), refreshDashboard(), refreshDocuments(), refreshKnowledge()]);
  renderChatScopeControls();
  syncRetrievalModeControl();
}

bootstrap().catch((error) => {
  console.error(error);
  $("#config-summary").textContent = error.message;
});
