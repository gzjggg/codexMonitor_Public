const POLL_INTERVAL = 2000;

const elements = {
  rows: document.querySelector("#eventRows"),
  empty: document.querySelector("#emptyState"),
  emptyTitle: document.querySelector("#emptyTitle"),
  emptyDetail: document.querySelector("#emptyDetail"),
  textFilter: document.querySelector("#textFilter"),
  statusFilter: document.querySelector("#statusFilter"),
  purposeFilter: document.querySelector("#purposeFilter"),
  liveState: document.querySelector("#liveState"),
  liveText: document.querySelector("#liveText"),
  updatedAt: document.querySelector("#updatedAt"),
  totalCount: document.querySelector("#totalCount"),
  matchCount: document.querySelector("#matchCount"),
  mismatchCount: document.querySelector("#mismatchCount"),
  unknownCount: document.querySelector("#unknownCount"),
  healthStatus: document.querySelector("#healthStatus"),
  healthSource: document.querySelector("#healthSource"),
  healthScan: document.querySelector("#healthScan"),
  healthProbe: document.querySelector("#healthProbe"),
  healthError: document.querySelector("#healthError"),
  languageToggle: document.querySelector("#languageToggle"),
};

const translations = {
  zh: {
    title: "Codex 模型监视器", heading: "模型调用监视器", intro: "对比每次调用所请求的模型与服务端声明的模型。",
    noticeLabel: "判读说明", notice: "名称不同只表示请求值与服务端声明值不一致，并不能单独证明模型被降级。 服务端声明来自响应体 <code>response.model</code> 或响应头 <code>openai-model</code>。 请求模型是客户端实际发送的值；后台标题 / 摘要调用与主任务独立，用途无法确认时标为未知。",
    summaryLabel: "事件概览", total: "全部记录", equal: "一致", different: "不一致", unknown: "未知",
    healthTitle: "采集状态", waitingData: "等待数据", source: "来源", lastScan: "最后扫描", probe: "探针", error: "错误", none: "无",
    eventsTitle: "调用记录", filterPurpose: "按调用用途筛选", allPurposes: "全部用途", filterRecords: "筛选记录",
    searchPlaceholder: "筛选模型、线程、传输方式…", filterStatus: "按状态筛选", allStatuses: "全部状态",
    time: "时间", purpose: "调用用途", requestedModel: "请求模型", serverModel: "服务端声明", status: "状态", threadTurn: "线程 / 回合", transport: "传输",
    emptyTitle: "暂无调用记录", emptyDetail: "捕获到模型调用后会显示在这里。", noMatches: "没有匹配的记录", adjustFilters: "请调整筛选条件。",
    cannotRead: "无法读取调用记录", notUpdated: "尚未更新", connecting: "正在连接", disconnected: "连接中断", retrying: "将在 2 秒后重试", live: "实时更新中", updated: "更新于 {time}",
    healthOk: "已读取探针记录", healthWaiting: "等待探针数据", healthError: "采集异常", internalProbe: "Codex 内部探针", noneReturned: "未返回",
    responseHeader: "响应头：{model}", warmup: "预热", invalidData: "接口返回的数据格式无效", readFailed: "读取数据失败", httpError: "请求失败（HTTP {status}）",
    switchLanguage: "Switch to English", purposeMain: "主任务", purposeFork: "分支对话", purposeTitleSummary: "后台：标题 / 摘要", purposeMemory: "系统：记忆整理", purposeSuggestions: "系统：任务建议", purposeSuggestionReview: "系统：任务建议安全审核", purposeSubagent: "子代理", purposeBackground: "后台辅助", purposeWarmup: "预热", purposeUnknown: "用途未知",
  },
  en: {
    title: "Codex Model Monitor", heading: "Model Call Monitor", intro: "Compare the model requested for each call with the model declared by the server.",
    noticeLabel: "Interpretation note", notice: "Different names only mean that the requested value and server-declared value do not match; this alone does not prove a model downgrade. The server declaration comes from <code>response.model</code> in the response body or the <code>openai-model</code> response header. The requested model is the value actually sent by the client. Background title and summary calls are separate from the main task; calls whose purpose cannot be determined are marked unknown.",
    summaryLabel: "Event summary", total: "All records", equal: "Match", different: "Mismatch", unknown: "Unknown",
    healthTitle: "Collector status", waitingData: "Waiting for data", source: "Source", lastScan: "Last scan", probe: "Probe", error: "Error", none: "None",
    eventsTitle: "Call records", filterPurpose: "Filter by call purpose", allPurposes: "All purposes", filterRecords: "Filter records",
    searchPlaceholder: "Filter models, threads, transport…", filterStatus: "Filter by status", allStatuses: "All statuses",
    time: "Time", purpose: "Call purpose", requestedModel: "Requested model", serverModel: "Server declaration", status: "Status", threadTurn: "Thread / turn", transport: "Transport",
    emptyTitle: "No call records", emptyDetail: "Model calls will appear here after they are captured.", noMatches: "No matching records", adjustFilters: "Adjust the filters and try again.",
    cannotRead: "Unable to read call records", notUpdated: "Not updated yet", connecting: "Connecting", disconnected: "Connection interrupted", retrying: "Retrying in 2 seconds", live: "Updating live", updated: "Updated at {time}",
    healthOk: "Probe records loaded", healthWaiting: "Waiting for probe data", healthError: "Collector error", internalProbe: "Codex internal probe", noneReturned: "Not returned",
    responseHeader: "Response header: {model}", warmup: "Warmup", invalidData: "The API returned invalid data", readFailed: "Unable to read data", httpError: "Request failed (HTTP {status})",
    switchLanguage: "切换到中文", purposeMain: "Main task", purposeFork: "Forked conversation", purposeTitleSummary: "Background: title / summary", purposeMemory: "System: memory", purposeSuggestions: "System: task suggestions", purposeSuggestionReview: "System: suggestion safety review", purposeSubagent: "Subagent", purposeBackground: "Background helper", purposeWarmup: "Warmup", purposeUnknown: "Unknown purpose",
  },
};

const purposeKeys = {
  main: "purposeMain", fork: "purposeFork", title_summary: "purposeTitleSummary", memory: "purposeMemory",
  suggestions: "purposeSuggestions", suggestion_review: "purposeSuggestionReview", subagent: "purposeSubagent",
  background: "purposeBackground", warmup: "purposeWarmup", unknown: "purposeUnknown",
};

const savedLanguage = localStorage.getItem("codex-monitor-language");
let language = savedLanguage === "zh" || savedLanguage === "en"
  ? savedLanguage
  : navigator.language.toLocaleLowerCase().startsWith("zh") ? "zh" : "en";

function t(key, values = {}) {
  return Object.entries(values).reduce((text, [name, value]) => text.replace(`{${name}}`, value), translations[language][key]);
}

function purposeLabel(purpose) {
  return t(purposeKeys[purpose] || "purposeUnknown");
}

function applyLanguage() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  document.title = t("title");
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach((node) => { node.innerHTML = t(node.dataset.i18nHtml); });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => { node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel)); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => { node.placeholder = t(node.dataset.i18nPlaceholder); });
  elements.languageToggle.textContent = language === "zh" ? "English" : "中文";
  elements.languageToggle.setAttribute("aria-label", t("switchLanguage"));
}

function normalizeStatus(status) {
  if (status === "equal" || status === "match") return "equal";
  if (status === "different" || status === "mismatch") return "different";
  return "unknown";
}

let events = [];
let loadingError = null;
let currentHealth = {};
let connectionState = "connecting";
let lastUpdated = null;

function valueOrDash(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(language === "zh" ? "zh-CN" : "en-US", { hour12: false });
}

function appendCell(row, label, value, className = "") {
  const cell = document.createElement("td");
  cell.dataset.label = label;
  cell.textContent = valueOrDash(value);
  if (className) cell.className = className;
  row.append(cell);
  return cell;
}

function renderEvents() {
  const errorText = loadingError?.key ? t(loadingError.key, loadingError.values) : loadingError?.text || "";
  const query = elements.textFilter.value.trim().toLocaleLowerCase();
  const selectedStatus = elements.statusFilter.value;
  const selectedPurpose = elements.purposeFilter.value;
  const filtered = events.filter((event) => {
    const status = normalizeStatus(event.status);
    const text = [
      event.id,
      event.thread_id,
      event.turn_id,
      event.requested_model,
      event.server_model,
      event.response_model,
      event.source,
      event.transport,
      purposeLabel(event.purpose),
    ].filter(Boolean).join(" ").toLocaleLowerCase();
    return (selectedStatus === "all" || status === selectedStatus)
      && (selectedPurpose === "all" || (event.purpose || "unknown") === selectedPurpose)
      && (!query || text.includes(query));
  });

  elements.rows.replaceChildren();
  for (const event of filtered) {
    const row = document.createElement("tr");
    const status = normalizeStatus(event.status);
    appendCell(row, t("time"), formatTime(event.time), "time-cell");
    appendCell(row, t("purpose"), purposeLabel(event.purpose));
    appendCell(row, t("requestedModel"), event.requested_model, "model-cell");
    const modelCell = appendCell(row, t("serverModel"), event.response_model || event.server_model, "model-cell");
    if (event.response_model && event.server_model) {
      const headerModel = document.createElement("small");
      headerModel.textContent = t("responseHeader", { model: event.server_model });
      modelCell.append(document.createElement("br"), headerModel);
    }

    const statusCell = document.createElement("td");
    statusCell.dataset.label = t("status");
    const badge = document.createElement("span");
    badge.className = `status status-${status}`;
    badge.textContent = t(status);
    statusCell.append(badge);
    row.append(statusCell);

    appendCell(row, t("source"), event.source === "none" ? t("noneReturned") : event.source);
    appendCell(row, t("threadTurn"), [event.thread_id, event.turn_id].filter(Boolean).join(" / "), "identity-cell");
    appendCell(row, t("transport"), [event.transport, event.warmup ? t("warmup") : ""].filter(Boolean).join(" · "));
    elements.rows.append(row);
  }

  elements.empty.hidden = filtered.length > 0;
  if (!filtered.length) {
    elements.emptyTitle.textContent = errorText ? t("cannotRead") : events.length ? t("noMatches") : t("emptyTitle");
    elements.emptyDetail.textContent = errorText || (events.length ? t("adjustFilters") : t("emptyDetail"));
  }
}

function renderSummary() {
  const counts = { equal: 0, different: 0, unknown: 0 };
  for (const event of events) counts[normalizeStatus(event.status)] += 1;
  elements.totalCount.textContent = String(events.length);
  elements.matchCount.textContent = String(counts.equal);
  elements.mismatchCount.textContent = String(counts.different);
  elements.unknownCount.textContent = String(counts.unknown);
}

function renderHealth(health = {}) {
  currentHealth = health;
  const status = valueOrDash(health.status);
  elements.healthStatus.textContent = ({ok: t("healthOk"), waiting: t("healthWaiting"), error: t("healthError")})[status] || status;
  elements.healthStatus.dataset.state = String(health.status || "unknown").toLocaleLowerCase();
  elements.healthSource.textContent = health.source === "probe" ? t("internalProbe") : valueOrDash(health.source);
  elements.healthScan.textContent = formatTime(health.last_scan);
  elements.healthProbe.textContent = valueOrDash(health.probe);
  elements.healthError.textContent = health.error ? String(health.error) : t("none");
  elements.healthError.classList.toggle("has-error", Boolean(health.error));
}

function renderConnection() {
  elements.liveText.textContent = connectionState === "offline"
    ? t("disconnected")
    : connectionState === "connecting"
      ? t("connecting")
      : ({waiting: t("healthWaiting"), error: t("healthError")})[currentHealth.status] || t("live");
  elements.updatedAt.textContent = connectionState === "offline"
    ? t("retrying")
    : lastUpdated
      ? t("updated", { time: lastUpdated.toLocaleTimeString(language === "zh" ? "zh-CN" : "en-US", { hour12: false }) })
      : t("notUpdated");
}

async function refresh() {
  try {
    const response = await fetch("/api/events", { cache: "no-store" });
    if (!response.ok) throw { key: "httpError", values: { status: response.status } };
    const data = await response.json();
    if (!Array.isArray(data.events)) throw { key: "invalidData" };

    events = data.events;
    loadingError = null;
    renderHealth(data.health);
    renderSummary();
    renderEvents();
    elements.liveState.dataset.state = "online";
    connectionState = "online";
    lastUpdated = new Date();
    renderConnection();
  } catch (error) {
    loadingError = error?.key ? error : { text: error instanceof Error ? error.message : t("readFailed") };
    connectionState = "offline";
    elements.liveState.dataset.state = "offline";
    renderConnection();
    renderEvents();
  } finally {
    setTimeout(refresh, POLL_INTERVAL);
  }
}

elements.textFilter.addEventListener("input", renderEvents);
elements.statusFilter.addEventListener("change", renderEvents);
elements.purposeFilter.addEventListener("change", renderEvents);
elements.languageToggle.addEventListener("click", () => {
  language = language === "zh" ? "en" : "zh";
  localStorage.setItem("codex-monitor-language", language);
  applyLanguage();
  renderHealth(currentHealth);
  renderSummary();
  renderEvents();
  renderConnection();
});

applyLanguage();
refresh();
