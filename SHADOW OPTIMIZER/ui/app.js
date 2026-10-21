const welcome = document.querySelector("#welcome");
const dashboard = document.querySelector("#dashboard");
const loading = document.querySelector("#loading-overlay");
const analyzeButton = document.querySelector("#analyze-button");
const refreshButton = document.querySelector("#refresh-button");
const closeAppButton = document.querySelector("#close-app-button");
const liveToggleButton = document.querySelector("#live-toggle");
const chart = document.querySelector("#resource-chart");
const chartContext = chart.getContext("2d");
const dashboardNavButtons = [...document.querySelectorAll(".dashboard-nav button[data-view]")];
const navPinButton = document.querySelector("#nav-pin-button");

// A preferência é opcional: o painel continua funcionando sem armazenamento local.
function setNavigationPinned(pinned) {
  dashboard.classList.toggle("nav-pinned", pinned);
  navPinButton.setAttribute("aria-pressed", String(pinned));
  const label = pinned ? "Recolher menu" : "Fixar menu aberto";
  navPinButton.title = label;
  navPinButton.setAttribute("aria-label", label);
  navPinButton.querySelector(".nav-label").textContent = label;
}
try {
  setNavigationPinned(localStorage.getItem("shadow.navigationPinned") === "true");
} catch { setNavigationPinned(false); }
navPinButton.addEventListener("click", () => {
  const pinned = navPinButton.getAttribute("aria-pressed") !== "true";
  setNavigationPinned(pinned);
  try { localStorage.setItem("shadow.navigationPinned", String(pinned)); } catch { /* Preferência apenas nesta sessão. */ }
  window.requestAnimationFrame(() => {
    if (isOverviewVisible()) drawChart();
    const performancePage = document.querySelector('[data-page="performance"]');
    if (!performancePage.classList.contains("hidden")) drawPerformanceChart();
  });
});

let latestReport = null;
let liveTimer = null;
let liveRequestBusy = false;
let liveSampleCount = 0;
let livePausedByVisibility = false;
let currentOptimizerOverview = null;
let performanceRecords = [];
let performanceSessionSamples = [];
let performanceCapture = null;
let performanceTimer = null;
let performanceSessionStartedAt = null;
let appClosing = false;
let uiPreferences = { lightweight: false, interval_seconds: 1, effects: "full", show_intro: true };
let telemetryTimer = null;
let telemetryBusy = false;
let sensorsEnabled = false;
let performanceRequestBusy = false;
let preparationBusy = false;
function effectiveIntervalMs() { return 1000 * Math.max(uiPreferences.interval_seconds, uiPreferences.lightweight ? 3 : 1); }
function effectsEnabled() { return !uiPreferences.lightweight && uiPreferences.effects === "full" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches; }


analyzeButton.addEventListener("click", analyze);
document.querySelector("#intro-skip-button").addEventListener("click", enterDashboard);
document.querySelector("#intro-replay-button").addEventListener("click", startPresentation);

let presentationTimer = null;
let presentationLeaving = false;

function startPresentation() {
  if (presentationLeaving) return;
  window.clearTimeout(presentationTimer);
  dashboard.setAttribute("inert", "");
  dashboard.classList.add("hidden");
  welcome.classList.remove("hidden", "intro-playing", "welcome-leaving");
  // Reinicia a sequência apenas ao abrir ou ao clicar em Rever apresentação.
  void welcome.offsetWidth;
  welcome.classList.add("intro-playing");
  document.querySelector("#intro-skip-button").focus({ preventScroll: true });
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  presentationTimer = window.setTimeout(enterDashboard, reducedMotion ? 0 : 1900);
}

async function enterDashboard() {
  if (presentationLeaving || welcome.classList.contains("hidden")) return;
  presentationLeaving = true;
  window.clearTimeout(presentationTimer);
  dashboard.classList.remove("hidden");
  dashboard.classList.add("dashboard-arriving");
  welcome.classList.add("welcome-leaving");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reducedMotion) await new Promise(resolve => window.setTimeout(resolve, 450));
  welcome.classList.add("hidden");
  welcome.classList.remove("intro-playing", "welcome-leaving");
  dashboard.classList.remove("dashboard-arriving");
  dashboard.removeAttribute("inert");
  analyzeButton.focus({ preventScroll: true });
  drawChart();
  presentationLeaving = false;
}

refreshButton.addEventListener("click", analyze);
closeAppButton.addEventListener("click", () => {
  if (window.pywebview && window.pywebview.api) {
    stopUiTimers();
    window.pywebview.api.close_app();
  }
});
function stopUiTimers() {
  appClosing = true;
  window.clearInterval(liveTimer);
  window.clearInterval(performanceTimer);
  window.clearInterval(telemetryTimer);
  window.clearTimeout(presentationTimer);
  liveTimer = null;
  performanceTimer = null;
  livePausedByVisibility = false;
}
window.addEventListener("pagehide", stopUiTimers);
document.querySelector("#process-list").addEventListener("click", handleProcessAction);
document.querySelector("#cleanup-button").addEventListener("click", cleanupTempFiles);
document.querySelector("#cleanup-files").addEventListener("change", updateCleanupSelection);
document.querySelector("#startup-list").addEventListener("click", handleStartupAction);
document.querySelector("#power-plan-button").addEventListener("click", activateSelectedPowerPlan);
document.querySelector("#power-plan-select").addEventListener("change", updatePowerDescription);
document.querySelector("#games-refresh-button").addEventListener("click", loadGamingOverview);
document.querySelector("#game-select").addEventListener("change", selectGame);
document.querySelector("#save-game-profile-button").addEventListener("click", saveSelectedGameProfile);
document.querySelector("#performance-start-button").addEventListener("click", startPerformanceSession);
document.querySelector("#performance-stop-button").addEventListener("click", stopPerformanceSession);
document.querySelector("#performance-discard-button").addEventListener("click", discardPerformanceSession);
document.querySelector("#performance-import-button").addEventListener("click", choosePerformanceCapture);
document.querySelector("#performance-save-button").addEventListener("click", savePerformanceResult);
document.querySelector("#performance-game-select").addEventListener("change", updatePerformanceControls);
document.querySelector("#performance-phase-select").addEventListener("change", updatePerformanceControls);
document.querySelector("#performance-config-label").addEventListener("input", updatePerformanceControls);
document.querySelector("#performance-compare-select").addEventListener("change", renderPerformanceComparison);
document.querySelector("#performance-left-select").addEventListener("change", renderPerformanceComparison);
document.querySelector("#performance-right-select").addEventListener("change", renderPerformanceComparison);
document.querySelector("#network-refresh-button").addEventListener("click", loadNetworkOverview);
document.querySelector("#network-test-button").addEventListener("click", runNetworkTest);
document.querySelector("#history-refresh-button").addEventListener("click", loadHistoryOverview);
document.querySelector("#action-history-list").addEventListener("click", handleHistoryUndo);
document.querySelector("#settings-refresh-button").addEventListener("click", loadSettingsOverview);
document.querySelector("#launch-at-login-button").addEventListener("click", toggleLaunchAtLogin);
document.querySelector("#error-log-refresh-button").addEventListener("click", loadErrorLog);
document.querySelector("#error-log-clear-button").addEventListener("click", clearErrorLog);
document.querySelector("#game-live-button").addEventListener("click", () => {
  if (!liveTimer) toggleLiveMonitoring();
  showDashboardPage("overview");
});
liveToggleButton.addEventListener("click", toggleLiveMonitoring);
document.querySelector("#score-explain-button").addEventListener("click", () => {
  document.querySelector("#score-method-dialog").showModal();
});
document.querySelector("#score-dialog-close").addEventListener("click", () => {
  document.querySelector("#score-method-dialog").close();
});
let chartResizeTimer = 0;
window.addEventListener("resize", () => {
  window.clearTimeout(chartResizeTimer);
  chartResizeTimer = window.setTimeout(drawChart, 150);
});
dashboardNavButtons.forEach(button => {
  button.addEventListener("click", () => showDashboardPage(button.dataset.view));
});
document.querySelectorAll("[data-open-page]").forEach(button => {
  button.addEventListener("click", () => showDashboardPage(button.dataset.openPage));
});
window.addEventListener("pywebviewready", () => {
  document.body.classList.add("desktop-ready");
  window.pywebview.api.ui_preferences().then(value => {
    applyUiPreferences(value);
    if (!value.show_intro) enterDashboard();
  }).catch(error => showNotice(`Preferências indisponíveis: ${error.message || error}`, "warning"));
});
window.addEventListener("error", event => {
  if (window.pywebview?.api) window.pywebview.api.log_frontend_error(event.message || "Erro JavaScript", event.filename || "");
});
window.addEventListener("unhandledrejection", event => {
  if (window.pywebview?.api) window.pywebview.api.log_frontend_error(event.reason?.message || String(event.reason || "Promise rejeitada"), "Promise não tratada");
});

function showDashboardPage(pageName) {
  document.querySelectorAll(".dashboard-page").forEach(page => {
    page.classList.toggle("hidden", page.dataset.page !== pageName);
  });
  dashboardNavButtons.forEach(button => {
    if (button.dataset.view === pageName) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (pageName === "overview") drawChart();
  if (pageName === "games" && latestReport) loadGameRecommendations();
  if (pageName === "performance") {
    drawPerformanceChart();
    const performanceChart = document.querySelector("#performance-chart");
    performanceChart.classList.remove("chart-animate");
    void performanceChart.offsetWidth;
    performanceChart.classList.add("chart-animate");
  }
  if (pageName === "history") loadHistoryOverview();
  if (pageName === "settings") loadSettingsOverview();
  if (pageName === "games") loadGamePreparation();
  syncTelemetryTimer();
}

async function loadSettingsOverview() {
  const refresh = document.querySelector("#settings-refresh-button");
  refresh.disabled = true;
  try {
    const settings = await window.pywebview.api.settings_overview();
    renderSettings(settings);
    await refreshTelemetry();
  } catch (error) {
    showNotice(`Não foi possível carregar as configurações: ${error.message || error}`, "warning");
  } finally {
    refresh.disabled = false;
  }
}

function renderSettings(settings) {
  const compatibility = settings.compatibility || {};
  setText("compatibility-name", compatibility.system_name || "Sistema desconhecido");
  setText("compatibility-target", compatibility.target || "Windows 10 e Windows 11");
  setText("compatibility-mode", compatibility.mode || "não validado");
  setText("compatibility-build", compatibility.build ? String(compatibility.build) : compatibility.release || "não disponível");
  const badge = document.querySelector("#compatibility-badge");
  badge.className = `level-badge ${compatibility.supported ? "" : compatibility.mode === "desenvolvimento" ? "medium" : "high"}`;
  badge.textContent = compatibility.supported ? "COMPATÍVEL" : compatibility.mode === "desenvolvimento" ? "DESENVOLVIMENTO" : "NÃO VALIDADO";
  setText("compatibility-summary", compatibility.supported
    ? `${compatibility.system_name} · suporte-alvo confirmado. Algumas medições ainda dependem de hardware e drivers.`
    : `${compatibility.system_name || "Este sistema"} está em modo de desenvolvimento. A versão distribuída tem como alvo Windows 10/11.`);

  const capabilityList = document.querySelector("#capability-list");
  capabilityList.replaceChildren();
  for (const capability of compatibility.capabilities || []) {
    const row = document.createElement("li");
    row.className = `capability-row capability-${capability.status}`;
    const heading = document.createElement("div");
    heading.className = "capability-heading";
    const name = document.createElement("strong");
    name.textContent = capability.name;
    const status = document.createElement("span");
    status.textContent = ({ available: "DISPONÍVEL", limited: "LIMITADO", unavailable: "INDISPONÍVEL" })[capability.status] || "VERIFICAR";
    heading.append(name, status);
    const details = document.createElement("p");
    details.textContent = capability.details;
    row.append(heading, details);
    capabilityList.append(row);
  }

  const startup = settings.launch_at_login || {};
  const launchButton = document.querySelector("#launch-at-login-button");
  launchButton.disabled = !startup.supported;
  launchButton.dataset.enabled = String(Boolean(startup.enabled));
  launchButton.textContent = startup.enabled ? "Desativar inicialização" : "Ativar inicialização";
  setText("launch-at-login-state", startup.enabled ? "Ativo para esta conta" : startup.supported ? "Desativado" : "Indisponível neste modo");
  setText("launch-at-login-help", startup.message || "Disponível no Shadow.exe para Windows.");

  const log = settings.error_log || {};
  setText("error-log-path", `Arquivo local: ${log.path || "não disponível"}`);
  setText("error-log-size", `${log.size_bytes ? formatBytes(log.size_bytes) : "0 bytes"} registrados`);
  document.querySelector("#error-log-clear-button").disabled = !log.size_bytes;
}

async function toggleLaunchAtLogin() {
  const button = document.querySelector("#launch-at-login-button");
  const enabled = button.dataset.enabled !== "true";
  const message = enabled
    ? "O Shadow será iniciado quando você entrar na sua conta do Windows. Deseja ativar?"
    : "O Shadow deixará de iniciar quando você entrar na sua conta do Windows. Deseja desativar?";
  if (!window.confirm(message)) return;
  button.disabled = true;
  try {
    const result = await window.pywebview.api.set_launch_at_login(enabled);
    showNotice(result.message, result.success ? "success" : "warning");
    if (result.success) await loadSettingsOverview();
    else button.disabled = false;
  } catch (error) {
    logClientError("Falha ao alterar inicialização do Shadow", error);
    showNotice(`Não foi possível alterar a inicialização: ${error.message || error}`, "warning");
    button.disabled = false;
  }
}

async function loadErrorLog() {
  const button = document.querySelector("#error-log-refresh-button");
  button.disabled = true;
  try {
    const result = await window.pywebview.api.read_error_log();
    if (!result.success) throw new Error(result.message);
    const content = result.contents || "Nenhum erro registrado.";
    document.querySelector("#error-log-content").textContent = result.truncated
      ? `[Exibindo o trecho mais recente do log]\n${content}` : content;
    setText("error-log-path", `Arquivo local: ${result.path || "não disponível"}`);
    const logBytes = new Blob([result.contents || ""]).size;
    setText("error-log-size", `${logBytes ? formatBytes(logBytes) : "0 bytes"} registrados`);
    document.querySelector("#error-log-clear-button").disabled = !result.contents;
  } catch (error) {
    logClientError("Falha ao ler log de erros", error);
    showNotice(`Não foi possível ler o log: ${error.message || error}`, "warning");
  } finally {
    button.disabled = false;
  }
}

async function clearErrorLog() {
  if (!window.confirm("Apagar o log de erros local do Shadow?")) return;
  const button = document.querySelector("#error-log-clear-button");
  button.disabled = true;
  try {
    const result = await window.pywebview.api.clear_error_log();
    showNotice(result.message, result.success ? "success" : "warning");
    if (result.success) {
      document.querySelector("#error-log-content").textContent = "Nenhum erro registrado.";
      setText("error-log-size", "0 bytes registrados");
    } else button.disabled = false;
  } catch (error) {
    logClientError("Falha ao limpar log de erros", error);
    showNotice(`Não foi possível limpar o log: ${error.message || error}`, "warning");
    button.disabled = false;
  }
}

function logClientError(context, error) {
  if (!window.pywebview?.api) return;
  window.pywebview.api.log_frontend_error(`${context}: ${error?.message || error}`, "Shadow UI");
}

async function analyze() {
  if (analyzeButton.disabled) return;
  if (liveTimer) toggleLiveMonitoring();
  loading.classList.remove("hidden");
  loading.setAttribute("aria-busy", "true");
  dashboard.setAttribute("aria-busy", "true");
  refreshButton.disabled = true;
  analyzeButton.disabled = true;
  liveToggleButton.disabled = true;
  showError("");
  renderScanProgress({ stage: null, stages: [] }, "pending");
  try {
    const started = await window.pywebview.api.start_scan();
    if (!started.success) throw new Error(started.message || "A análise não pôde ser iniciada.");

    let progress;
    do {
      if (appClosing) return;
      progress = await window.pywebview.api.scan_progress();
      renderScanProgress(progress, "pending");
      if (progress.running) await new Promise(resolve => window.setTimeout(resolve, 260));
    } while (progress.running);

    if (!progress.success || !progress.report) {
      throw new Error(progress.error || "A análise terminou sem gerar um relatório.");
    }
    latestReport = progress.report;
    renderReport(latestReport);
    renderScanProgress(progress, "active");
    await loadHistoryOverview();
    await loadOptimizerOverview();
    renderScanProgress(progress, "complete");
    loading.classList.add("hidden");
  } catch (error) {
    logClientError("Falha durante a análise", error);
    loading.classList.add("hidden");
    showError(`Não foi possível analisar o computador: ${error.message || error}`);
  } finally {
    loading.setAttribute("aria-busy", "false");
    dashboard.setAttribute("aria-busy", "false");
    refreshButton.disabled = false;
    analyzeButton.disabled = false;
    liveToggleButton.disabled = !latestReport;
  }
}

function renderScanProgress(progress, panelStatus = "pending") {
  const states = new Map((progress.stages || []).map(stage => [stage.name, stage.status]));
  states.set("Carregando recursos do painel", panelStatus);
  const steps = document.querySelectorAll("[data-scan-stage]");
  for (const step of steps) {
    const status = states.get(step.dataset.scanStage) || "pending";
    step.className = `scan-stage scan-stage-${status}`;
    step.setAttribute("aria-current", status === "active" ? "step" : "false");
  }
  const active = (progress.stages || []).find(stage => stage.status === "active");
  const current = panelStatus === "active" ? "Carregando recursos do painel"
    : panelStatus === "complete" ? "Análise concluída"
      : active?.name || (progress.success ? "Análise concluída" : "Preparando as leituras do sistema");
  setText("scan-current-step", current);
}

async function loadHistoryOverview() {
  try {
    const history = await window.pywebview.api.history_overview();
    renderHistory(history);
  } catch (error) {
    showNotice(`Não foi possível carregar o histórico: ${error.message || error}`, "warning");
  }
}

function renderHistory(history) {
  const diagnostics = history.diagnostics || [];
  const actions = history.actions || [];
  const diagnosticList = document.querySelector("#diagnostic-history-list");
  const actionList = document.querySelector("#action-history-list");
  diagnosticList.replaceChildren();
  actionList.replaceChildren();
  setText("history-diagnostics-caption", `${diagnostics.length} registro(s) · ${history.storage || "armazenados localmente"}`);

  if (!diagnostics.length) appendEmpty(diagnosticList, "Nenhuma análise salva ainda.");
  for (const record of diagnostics) {
    const item = document.createElement("li");
    item.className = "history-entry";
    const heading = document.createElement("div");
    heading.className = "history-entry-heading";
    const title = document.createElement("strong");
    title.textContent = record.diagnosis?.level ? `Nível ${record.diagnosis.level}` : "Análise do sistema";
    const date = document.createElement("time");
    date.textContent = formatHistoryDate(record.timestamp);
    heading.append(title, date);
    const description = document.createElement("p");
    description.textContent = record.diagnosis?.message || `${record.system?.name || "Sistema"} · ${record.system?.release || "versão não identificada"}`;
    const metrics = document.createElement("small");
    metrics.textContent = `CPU média ${Number(record.cpu_percent || 0).toFixed(1)}% · RAM ${Number(record.ram_percent || 0).toFixed(1)}% · ${Number(record.ram_total_gb || 0).toFixed(1)} GB`;
    item.append(heading, description, metrics);
    diagnosticList.append(item);
  }

  if (!actions.length) appendEmpty(actionList, "Nenhuma ação salva ainda.");
  for (const action of actions) {
    const item = document.createElement("li");
    item.className = "history-entry action-history-entry";
    const heading = document.createElement("div");
    heading.className = "history-entry-heading";
    const title = document.createElement("strong");
    title.textContent = action.title || "Ação do Shadow";
    const date = document.createElement("time");
    date.textContent = formatHistoryDate(action.timestamp);
    heading.append(title, date);
    const details = document.createElement("p");
    details.textContent = action.details || "";
    const status = document.createElement("small");
    status.className = action.undone ? "history-status undone" : action.reversible ? "history-status reversible" : "history-status irreversible";
    status.textContent = action.undone ? "Desfeita" : action.reversible ? "Pode ser desfeita" : "Não pode ser desfeita";
    item.append(heading, details, status);
    if (action.reversible && !action.undone) {
      const undo = document.createElement("button");
      undo.type = "button";
      undo.className = "history-undo-button";
      undo.dataset.actionId = action.id;
      undo.textContent = "Desfazer";
      item.append(undo);
    }
    actionList.append(item);
  }

  renderHistoryComparison(diagnostics);
}

function renderHistoryComparison(diagnostics) {
  const target = document.querySelector("#history-comparison");
  target.replaceChildren();
  if (diagnostics.length < 2) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Faça pelo menos duas análises para comparar.";
    target.append(empty);
    return;
  }
  const [current, previous] = diagnostics;
  const grid = document.createElement("div");
  grid.className = "history-compare-grid";
  const currentCard = createHistoryCompareCard("Mais recente", current);
  const previousCard = createHistoryCompareCard("Anterior", previous);
  grid.append(currentCard, previousCard);
  const delta = document.createElement("p");
  delta.className = "history-delta-note";
  const cpuDelta = Number(current.cpu_percent || 0) - Number(previous.cpu_percent || 0);
  const ramDelta = Number(current.ram_percent || 0) - Number(previous.ram_percent || 0);
  delta.textContent = `Variação observada: CPU ${formatSigned(cpuDelta)} pontos · RAM ${formatSigned(ramDelta)} pontos.`;
  target.append(grid, delta);
}

function createHistoryCompareCard(label, record) {
  const card = document.createElement("div");
  card.className = "history-compare-card";
  const heading = document.createElement("strong");
  heading.textContent = label;
  const date = document.createElement("time");
  date.textContent = formatHistoryDate(record.timestamp);
  const metrics = document.createElement("p");
  metrics.textContent = `CPU ${Number(record.cpu_percent || 0).toFixed(1)}% · RAM ${Number(record.ram_percent || 0).toFixed(1)}%`;
  const system = document.createElement("small");
  system.textContent = `${record.system?.name || "Sistema"} ${record.system?.release || ""} · ${Number(record.ram_total_gb || 0).toFixed(1)} GB RAM`;
  card.append(heading, date, metrics, system);
  return card;
}

function formatHistoryDate(timestamp) {
  if (!Number.isFinite(Number(timestamp))) return "Data indisponível";
  return new Date(Number(timestamp) * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function formatSigned(value) {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

async function handleHistoryUndo(event) {
  const button = event.target.closest(".history-undo-button");
  if (!button) return;
  if (!window.confirm("Desfazer esta alteração e voltar ao estado anterior registrado?")) return;
  button.disabled = true;
  try {
    const result = await window.pywebview.api.undo_history_action(button.dataset.actionId);
    showNotice(result.message, result.success ? "success" : "warning");
    if (result.success) {
      await loadHistoryOverview();
      await loadOptimizerOverview();
    } else {
      button.disabled = false;
    }
  } catch (error) {
    showNotice(`Não foi possível desfazer a ação: ${error.message || error}`, "warning");
    button.disabled = false;
  }
}

function renderReport(report) {
  const memory = report.memory;
  setText("cpu-value", `${report.cpu_percent.toFixed(1)}%`);
  setText("ram-value", `${memory.used_percent.toFixed(1)}%`);
  setText("available-value", `${memory.available_gb.toFixed(1)} GB`);
  setText("ram-total", `Memória total: ${memory.total_gb.toFixed(2)} GB`);
  setWidth("cpu-meter", report.cpu_percent);
  setWidth("ram-meter", memory.used_percent);
  const status = document.querySelector("#system-status");
  status.classList.add("ready");
  status.innerHTML = `<span class="status-dot"></span>${escapeHtml(report.system.display_name || report.system.name)} · análise concluída`;

  const level = report.diagnosis.level;
  const badge = document.querySelector("#level-badge");
  badge.textContent = `NÍVEL ${level}`;
  badge.className = `level-badge ${level === "ALTO" ? "high" : level === "MÉDIO" ? "medium" : ""}`;
  setText("hero-diagnosis-title", `Nível ${level.toLowerCase()}`);
  setText("hero-diagnosis-summary", `${report.diagnosis.message} O diagnóstico é preliminar e não mede desempenho em jogos.`);
  renderHeadroomScore(report);

  const processList = document.querySelector("#process-list");
  processList.replaceChildren();
  for (const process of report.top_ram_processes.slice(0, 5)) {
    const row = document.createElement("li");
    row.className = "process-row";
    const name = document.createElement("span");
    name.className = "process-name";
    const usage = document.createElement("span");
    usage.className = "process-usage";
    name.textContent = `${process.name} · PID ${process.pid}`;
    usage.textContent = `${process.ram_mb.toFixed(0)} MB`;
    const closeButton = document.createElement("button");
    closeButton.className = "process-close-button";
    closeButton.type = "button";
    closeButton.textContent = "Encerrar";
    closeButton.setAttribute("aria-label", `Encerrar ${process.name}`);
    closeButton.dataset.pid = process.pid;
    closeButton.dataset.name = process.name;
    closeButton.dataset.createTime = process.create_time;
    row.append(name, usage, closeButton);
    processList.append(row);
  }

  const overviewProcessList = document.querySelector("#overview-process-list");
  overviewProcessList.replaceChildren();
  if (!report.top_ram_processes.length) appendEmpty(overviewProcessList, "Nenhum processo disponível nesta leitura.");
  for (const process of report.top_ram_processes.slice(0, 3)) {
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.className = "overview-process-name";
    name.textContent = process.name;
    const usage = document.createElement("strong");
    usage.textContent = `${process.ram_mb.toFixed(0)} MB`;
    row.append(name, usage);
    overviewProcessList.append(row);
  }

  const recommendationList = document.querySelector("#recommendation-list");
  recommendationList.replaceChildren();
  for (const recommendation of report.recommendations) {
    const item = document.createElement("li");
    item.textContent = recommendation;
    recommendationList.append(item);
  }

  setText("platform-note", report.system.is_windows
    ? "Análise informativa; não mede FPS de jogos."
    : "Modo de desenvolvimento no Linux; sistema-alvo: Windows 10/11.");
  drawChart();
  animateChart();
}

function renderHeadroomScore(report) {
  const cpuSamples = report.monitoring.cpu_samples || [];
  const ramSamples = report.monitoring.ram_samples || [];
  const cpuAverage = Number.isFinite(report.monitoring.average_cpu)
    ? report.monitoring.average_cpu
    : cpuSamples.reduce((sum, value) => sum + value, 0) / Math.max(cpuSamples.length, 1);
  const ramAverage = Number.isFinite(report.monitoring.average_ram)
    ? report.monitoring.average_ram
    : ramSamples.reduce((sum, value) => sum + value, 0) / Math.max(ramSamples.length, 1);
  const score = Math.round(Math.max(0, Math.min(100, 100 - (cpuAverage * 0.4 + ramAverage * 0.6))));
  document.querySelector("#score-gauge").style.setProperty("--score", score);
  setText("availability-score", String(score));
  setText("score-caption", `CPU média ${cpuAverage.toFixed(0)}% · RAM média ${ramAverage.toFixed(0)}%`);
}

async function loadOptimizerOverview() {
  try {
    currentOptimizerOverview = await window.pywebview.api.optimizer_overview();
    renderDisks(currentOptimizerOverview.disks || []);
    renderTempPreview(currentOptimizerOverview.temp_cleanup || {});
    renderStartup(currentOptimizerOverview.startup || {});
    renderPowerPlans(currentOptimizerOverview.power_plans || {});
    latestReport.findings = await window.pywebview.api.diagnostic_findings(latestReport, currentOptimizerOverview);
    renderDiagnosticReport(latestReport, currentOptimizerOverview);
    await loadGamingOverview();
    await loadPerformanceOverview();
    await loadNetworkOverview();
  } catch (error) {
    showNotice(`Não foi possível carregar as ferramentas: ${error.message || error}`, "warning");
    if (latestReport) {
      latestReport.findings = await window.pywebview.api.diagnostic_findings(latestReport, {});
      renderDiagnosticReport(latestReport, {});
      await loadGamingOverview();
      await loadPerformanceOverview();
      await loadNetworkOverview();
    }
  }
}

let gamingOverview = { games: [], profiles: {}, history: [] };

async function loadGamingOverview() {
  const refresh = document.querySelector("#games-refresh-button");
  refresh.disabled = true;
  try {
    gamingOverview = await window.pywebview.api.gaming_overview();
    renderGamingOverview(gamingOverview);
  } catch (error) {
    setText("games-library-message", `Não foi possível consultar a biblioteca: ${error.message || error}`);
    showNotice("O Gaming Hub não conseguiu ler os manifestos dos jogos.", "warning");
  } finally {
    refresh.disabled = false;
  }
}

async function loadPerformanceOverview() {
  try {
    const data = await window.pywebview.api.performance_overview();
    performanceRecords = data.records || [];
    setText("performance-gpu-note", data.gpu_message || "Uso de GPU pode ficar indisponível.");
    renderPerformanceHistory();
  } catch (error) {
    setText("performance-gpu-note", `Não foi possível carregar o histórico: ${error.message || error}`);
  }
}

async function loadNetworkOverview() {
  const button = document.querySelector("#network-refresh-button");
  button.disabled = true;
  try {
    const overview = await window.pywebview.api.network_overview();
    renderNetworkOverview(overview);
  } catch (error) {
    setText("network-adapter-summary", `Não foi possível listar adaptadores: ${error.message || error}`);
  } finally {
    button.disabled = false;
  }
}

function renderNetworkOverview(overview) {
  const adapters = overview.adapters || [];
  const list = document.querySelector("#network-adapter-list");
  list.replaceChildren();
  setText("network-adapter-summary", `${overview.active_adapters || 0} interface(s) ativa(s) · Gateway IPv4: ${overview.gateway || "não identificado"}`);
  if (!adapters.length) {
    appendEmpty(list, overview.message || "Nenhum adaptador foi listado pelo sistema.");
    return;
  }
  for (const adapter of adapters) {
    const row = document.createElement("li");
    row.className = "network-adapter-row";
    const heading = document.createElement("div");
    heading.className = "network-adapter-heading";
    const name = document.createElement("strong");
    name.textContent = adapter.name;
    const state = document.createElement("span");
    state.className = adapter.is_up ? "network-state up" : "network-state";
    state.textContent = adapter.is_up ? "ATIVO" : "INATIVO";
    heading.append(name, state);
    const details = document.createElement("small");
    const addressText = adapter.addresses?.length ? adapter.addresses.join(" · ") : "Sem endereço IP listado";
    const speedText = adapter.speed_mbps ? ` · ${adapter.speed_mbps} Mbps` : "";
    const mtuText = adapter.mtu ? ` · MTU ${adapter.mtu}` : "";
    details.textContent = `${addressText}${speedText}${mtuText}`;
    row.append(heading, details);
    list.append(row);
  }
}

async function runNetworkTest() {
  const button = document.querySelector("#network-test-button");
  const target = document.querySelector("#network-target-input").value.trim();
  button.disabled = true;
  button.textContent = "Testando…";
  setText("network-test-status", "Enviando sondas ICMP ao gateway e ao destino…");
  try {
    const result = await window.pywebview.api.run_network_test(target);
    if (!result.success) {
      setText("network-test-status", result.message || "Não foi possível executar o teste.");
      return;
    }
    document.querySelector("#network-results").classList.remove("hidden");
    renderNetworkResultCard("network-target-result", "DESTINO ESCOLHIDO", result.target);
    if (result.gateway_result) renderNetworkResultCard("network-gateway-result", "GATEWAY LOCAL", result.gateway_result);
    else renderNetworkResultCard("network-gateway-result", "GATEWAY LOCAL", null, result.gateway || "Gateway não identificado; não testado.");
    renderNetworkFindings(result.diagnosis || []);
    setText("network-test-status", `Teste concluído · ${result.target.sent} sondas para ${result.target.host}. A rota e as condições podem variar.`);
  } catch (error) {
    setText("network-test-status", `O teste falhou: ${error.message || error}`);
  } finally {
    button.disabled = false;
    button.textContent = "Testar conexão";
  }
}

function renderNetworkResultCard(id, headingText, result, fallback = "") {
  const card = document.querySelector(`#${id}`);
  card.replaceChildren();
  const label = document.createElement("span"); label.className = "section-kicker"; label.textContent = headingText;
  const title = document.createElement("h2"); title.textContent = result?.host || fallback;
  card.append(label, title);
  if (!result) return;
  const metrics = document.createElement("div"); metrics.className = "network-metrics";
  const items = [
    ["LATÊNCIA MÉDIA", formatNetworkLatency(result.average_ms, result)],
    ["PERDA", `${result.packet_loss_percent.toFixed(0)}%`],
    ["PACOTES", `${result.received}/${result.sent}`],
  ];
  for (const [name, value] of items) {
    const metric = document.createElement("div");
    const metricName = document.createElement("small"); metricName.textContent = name;
    const metricValue = document.createElement("strong"); metricValue.textContent = value;
    metric.append(metricName, metricValue); metrics.append(metric);
  }
  card.append(metrics);
  const detail = document.createElement("p");
  detail.className = "network-result-detail";
  detail.textContent = result.latency_samples
    ? `Mín. ${result.min_ms.toFixed(2)} ms · Máx. ${result.max_ms.toFixed(2)} ms`
    : result.error || (result.below_resolution_count ? "Respostas abaixo da resolução de 1 ms." : "Sem leitura de latência confirmada.");
  card.append(detail);
}

function formatNetworkLatency(value, result) {
  if (value !== null && value !== undefined) return `${value.toFixed(2)} ms`;
  if (result.below_resolution_count && result.below_resolution_count === result.received) return "< 1 ms";
  return "n/d";
}

function renderNetworkFindings(findings) {
  const list = document.querySelector("#network-diagnosis-list");
  list.replaceChildren();
  if (!findings.length) {
    appendEmpty(list, "Nenhuma orientação disponível.");
    return;
  }
  for (const finding of findings) {
    const item = document.createElement("li");
    item.className = `finding-row severity-${finding.severity || "info"}`;
    const heading = document.createElement("div"); heading.className = "finding-heading";
    const title = document.createElement("strong"); title.textContent = finding.title;
    const severity = document.createElement("span"); severity.className = "finding-severity";
    severity.textContent = ({ high: "ALTA", medium: "MÉDIA", info: "INFO" })[finding.severity] || "INFO";
    heading.append(title, severity);
    const detail = document.createElement("p"); detail.textContent = finding.detail;
    const suggestion = document.createElement("small"); suggestion.textContent = `Sugestão: ${finding.suggestion}`;
    item.append(heading, detail, suggestion);
    list.append(item);
  }
}

function renderGamingOverview(data) {
  const games = data.games || [];
  populatePerformanceGames(games);
  const select = document.querySelector("#game-select");
  const previousId = select.value;
  select.replaceChildren();
  if (!games.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Nenhum jogo encontrado";
    select.append(option);
    select.disabled = true;
    document.querySelector("#game-profile-select").disabled = true;
    document.querySelector("#save-game-profile-button").disabled = true;
    setText("games-library-message", data.message || "Nenhum jogo foi encontrado.");
    setText("games-count", "0 jogos");
    setSelectedGame(null);
  } else {
    for (const game of games) {
      const option = document.createElement("option");
      option.value = game.id;
      option.textContent = `${game.name} · ${game.launcher}`;
      select.append(option);
    }
    select.disabled = false;
    select.value = games.some(game => game.id === previousId) ? previousId : games[0].id;
    setText("games-library-message", data.message || "Manifestos do Steam/Epic consultados.");
    setText("games-count", `${games.length} ${games.length === 1 ? "jogo" : "jogos"}`);
    selectGame();
  }
  renderGameHistory(data.history || []);
}

function populatePerformanceGames(games) {
  const select = document.querySelector("#performance-game-select");
  const previous = select.value;
  select.replaceChildren();
  if (!games.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Nenhum jogo detectado";
    select.append(option);
    select.disabled = true;
  } else {
    for (const game of games) {
      const option = document.createElement("option");
      option.value = game.id;
      option.textContent = `${game.name} · ${game.launcher}`;
      select.append(option);
    }
    select.disabled = false;
    if (games.some(game => game.id === previous)) select.value = previous;
  }
  updatePerformanceControls();
}

function currentSelectedGame() {
  const id = document.querySelector("#game-select").value;
  return gamingOverview.games?.find(game => game.id === id) || null;
}

function setSelectedGame(game) {
  const card = document.querySelector("#selected-game-card");
  card.replaceChildren();
  const icon = document.createElement("span");
  icon.className = "game-icon";
  icon.textContent = "▣";
  const details = document.createElement("div");
  const name = document.createElement("strong");
  const launcher = document.createElement("small");
  if (game) {
    name.textContent = game.name;
    launcher.textContent = `Instalado · ${game.launcher}`;
    setText("selected-game-path", game.path || "");
    const saved = gamingOverview.profiles?.[game.id];
    document.querySelector("#game-profile-select").disabled = false;
    document.querySelector("#save-game-profile-button").disabled = false;
    document.querySelector("#game-profile-select").value = saved?.profile || "balanced";
    setText("game-profile-status", saved ? `Preferência atual: ${profileLabel(saved.profile)} · salva ${formatSavedDate(saved.saved_at)}.` : "Nenhuma preferência salva para este jogo.");
  } else {
    name.textContent = "Nenhum jogo selecionado";
    launcher.textContent = "Os jogos encontrados aparecerão aqui.";
    setText("selected-game-path", "");
    document.querySelector("#game-profile-select").disabled = true;
    document.querySelector("#save-game-profile-button").disabled = true;
    setText("game-profile-status", "Nenhuma preferência salva para este jogo.");
  }
  details.append(name, launcher);
  card.append(icon, details);
  loadGamePreparation();
}

function selectGame() {
  const game = currentSelectedGame();
  setSelectedGame(game);
  loadGameRecommendations();
}

async function loadGameRecommendations() {
  const game = currentSelectedGame();
  const list = document.querySelector("#game-guidance-list");
  list.replaceChildren();
  if (!game || !latestReport) {
    appendEmpty(list, game ? "Faça a análise do computador para ver sugestões baseadas no hardware." : "Selecione um jogo após a análise do PC.");
    return;
  }
  try {
    const recommendations = await window.pywebview.api.game_recommendations(
      game.id, game.name, latestReport.hardware || {}, latestReport.memory || {}
    );
    for (const recommendation of recommendations) {
      const item = document.createElement("li");
      item.className = "finding-row severity-info";
      const text = document.createElement("p");
      text.textContent = recommendation;
      item.append(text);
      list.append(item);
    }
  } catch (error) {
    appendEmpty(list, `Sugestões indisponíveis: ${error.message || error}`);
  }
}

async function saveSelectedGameProfile() {
  const game = currentSelectedGame();
  if (!game) return;
  const button = document.querySelector("#save-game-profile-button");
  button.disabled = true;
  try {
    const profile = document.querySelector("#game-profile-select").value;
    const result = await window.pywebview.api.save_game_profile(game.id, game.name, profile);
    if (!result.success) {
      showNotice(result.message, "warning");
      return;
    }
    gamingOverview.profiles = result.data.profiles;
    gamingOverview.history = result.data.history;
    setSelectedGame(game);
    renderGameHistory(gamingOverview.history);
    showNotice("Preferência salva localmente no Shadow. Nenhuma configuração do jogo foi alterada.", "success");
  } catch (error) {
    showNotice(`Não foi possível salvar a preferência: ${error.message || error}`, "warning");
  } finally {
    button.disabled = !currentSelectedGame();
  }
}

function renderGameHistory(history) {
  const list = document.querySelector("#game-profile-history");
  list.replaceChildren();
  if (!history.length) {
    appendEmpty(list, "Nenhum perfil salvo ainda.");
    return;
  }
  for (const entry of history.slice(0, 12)) {
    const item = document.createElement("li");
    item.className = "game-history-row";
    const gameName = document.createElement("strong");
    gameName.textContent = entry.game_name;
    const profile = document.createElement("span");
    profile.textContent = profileLabel(entry.profile);
    const savedAt = document.createElement("small");
    savedAt.textContent = formatSavedDate(entry.saved_at);
    item.append(gameName, profile, savedAt);
    list.append(item);
  }
}

function profileLabel(profile) {
  return ({ balanced: "Equilibrado", performance: "Priorizar desempenho", quality: "Priorizar qualidade visual" })[profile] || "Equilibrado";
}

function formatSavedDate(value) {
  if (!value) return "agora";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "data não disponível" : date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

async function startPerformanceSession() {
  try {
    const result = await window.pywebview.api.start_performance_monitoring();
    if (!result.success) {
      showNotice(result.message, "warning");
      return;
    }
    performanceSessionSamples = [];
    performanceCapture = null;
    performanceSessionStartedAt = Date.now();
    setText("performance-capture-preview", "Finalize a sessão para importar a captura de FPS.");
    setText("performance-session-status", "MEDINDO");
    document.querySelector("#performance-session-status").classList.remove("paused");
    document.querySelector("#performance-start-button").disabled = true;
    document.querySelector("#performance-stop-button").disabled = false;
    document.querySelector("#performance-import-button").disabled = true;
    document.querySelector("#performance-discard-button").disabled = true;
    document.querySelector("#performance-save-button").disabled = true;
    setText("performance-import-note", "A sessão está ativa. Jogue e use sua ferramenta de captura de FPS em paralelo.");
    performanceTimer = window.setInterval(samplePerformanceSession, effectiveIntervalMs());
    await samplePerformanceSession();
  } catch (error) {
    showNotice(`Não foi possível iniciar a sessão: ${error.message || error}`, "warning");
  }
}

async function samplePerformanceSession() {
  if (!performanceSessionStartedAt || performanceRequestBusy || appClosing) return;
  performanceRequestBusy = true;
  const session = performanceSessionStartedAt;
  try {
    const result = await window.pywebview.api.sample_performance_monitoring();
    if (appClosing || session !== performanceSessionStartedAt) return;
    if (result.limit_reached) await stopPerformanceSession();
    if (!result.success) {
      showNotice(result.message, "warning");
      return;
    }
    performanceSessionSamples.push(result.sample);
    setText("performance-duration", formatDuration(result.sample.elapsed));
    drawPerformanceChart();
  } catch (error) {
    showNotice(`A leitura da sessão falhou: ${error.message || error}`, "warning");
  } finally { performanceRequestBusy = false; }
}

async function stopPerformanceSession() {
  if (!performanceSessionStartedAt) return;
  window.clearInterval(performanceTimer);
  performanceTimer = null;
  try {
    const result = await window.pywebview.api.stop_performance_monitoring();
    if (!result.success) {
      showNotice(result.message, "warning");
      return;
    }
    performanceSessionSamples = result.samples || performanceSessionSamples;
    performanceSessionStartedAt = null;
    document.querySelector("#performance-session-status").classList.add("paused");
    setText("performance-session-status", "FINALIZADO");
    document.querySelector("#performance-start-button").disabled = performanceSessionSamples.length > 0;
    document.querySelector("#performance-stop-button").disabled = true;
    document.querySelector("#performance-discard-button").disabled = !performanceSessionSamples.length;
    document.querySelector("#performance-import-button").disabled = !performanceSessionSamples.length;
    setText("performance-import-note", performanceSessionSamples.length
      ? `${performanceSessionSamples.length} amostra(s) medidas. Agora escolha o CSV de FPS.`
      : "Nenhuma amostra foi coletada; inicie outra sessão antes de salvar.");
    updatePerformanceControls();
  } catch (error) {
    showNotice(`Não foi possível finalizar a sessão: ${error.message || error}`, "warning");
    performanceSessionStartedAt = null;
    document.querySelector("#performance-start-button").disabled = false;
    document.querySelector("#performance-stop-button").disabled = true;
  }
}

async function discardPerformanceSession() {
  if (!performanceSessionSamples.length || !window.confirm("Descartar as amostras ainda não salvas desta sessão?")) return;
  try {
    const result = await window.pywebview.api.discard_performance_session();
    if (!result.success) {
      showNotice(result.message, "warning");
      return;
    }
    performanceSessionSamples = [];
    performanceCapture = null;
    document.querySelector("#performance-start-button").disabled = false;
    document.querySelector("#performance-discard-button").disabled = true;
    setText("performance-capture-preview", "Nenhum CSV selecionado.");
    setText("performance-duration", "00:00");
    setText("performance-session-status", "DESCARTADO");
    setText("performance-import-note", "A sessão foi descartada. Você pode iniciar outra medição.");
    updatePerformanceControls();
    drawPerformanceChart();
  } catch (error) {
    showNotice(`Não foi possível descartar a sessão: ${error.message || error}`, "warning");
  }
}

async function choosePerformanceCapture() {
  if (!performanceSessionSamples.length) return;
  const button = document.querySelector("#performance-import-button");
  button.disabled = true;
  try {
    const capture = await window.pywebview.api.choose_performance_capture();
    if (capture.cancelled) return;
    if (!capture.success) {
      showNotice(capture.message || "CSV inválido.", "warning");
      return;
    }
    performanceCapture = capture;
    const values = [
      capture.average_fps === null ? "FPS médio: indisponível" : `FPS médio: ${capture.average_fps.toFixed(1)}`,
      capture.one_percent_low === null ? "1% low: indisponível" : `1% low: ${capture.one_percent_low.toFixed(1)}`,
      capture.average_frametime_ms === null ? "frametime médio: indisponível" : `frametime médio: ${capture.average_frametime_ms.toFixed(2)} ms`,
      capture.frame_count ? `${capture.frame_count.toLocaleString("pt-BR")} frames` : "resumo do CSV",
    ];
    setText("performance-capture-preview", `${capture.source_file} · ${values.join(" · ")}`);
    setText("performance-import-note", "Confira se a captura corresponde ao jogo e à mesma sessão medida.");
    updatePerformanceControls();
  } catch (error) {
    showNotice(`Não foi possível importar o CSV: ${error.message || error}`, "warning");
  } finally {
    button.disabled = !performanceSessionSamples.length;
  }
}

async function savePerformanceResult() {
  const gameSelect = document.querySelector("#performance-game-select");
  const game = gamingOverview.games?.find(item => item.id === gameSelect.value);
  if (!game || !performanceCapture || !performanceSessionSamples.length) return;
  const button = document.querySelector("#performance-save-button");
  button.disabled = true;
  try {
    const result = await window.pywebview.api.save_performance_result(
      performanceCapture,
      game.id,
      game.name,
      document.querySelector("#performance-config-label").value,
      document.querySelector("#performance-phase-select").value
    );
    if (!result.success) {
      showNotice(result.message, "warning");
      return;
    }
    performanceRecords = result.records || [];
    performanceSessionSamples = [];
    performanceCapture = null;
    document.querySelector("#performance-start-button").disabled = false;
    document.querySelector("#performance-discard-button").disabled = true;
    setText("performance-capture-preview", "Nenhum CSV selecionado.");
    setText("performance-import-note", "Medição salva localmente. Repita o mesmo cenário para comparar.");
    renderPerformanceHistory();
    showNotice("Medição real salva no histórico local.", "success");
  } catch (error) {
    showNotice(`Não foi possível salvar a medição: ${error.message || error}`, "warning");
  } finally {
    updatePerformanceControls();
  }
}

function updatePerformanceControls() {
  const gameSelected = Boolean(document.querySelector("#performance-game-select").value);
  const labelPresent = Boolean(document.querySelector("#performance-config-label").value.trim());
  const canImport = performanceSessionSamples.length > 0 && !performanceSessionStartedAt;
  document.querySelector("#performance-import-button").disabled = !canImport;
  document.querySelector("#performance-save-button").disabled = !gameSelected || !labelPresent || !performanceCapture || !canImport;
  if (!performanceSessionStartedAt && performanceSessionSamples.length) {
    document.querySelector("#performance-start-button").disabled = true;
    document.querySelector("#performance-discard-button").disabled = false;
  }
}

function renderPerformanceHistory() {
  const list = document.querySelector("#performance-history-list");
  list.replaceChildren();
  const games = [...new Map(performanceRecords.map(record => [record.game_id, record.game_name])).entries()];
  const compare = document.querySelector("#performance-compare-select");
  const previous = compare.value;
  compare.replaceChildren();
  if (!performanceRecords.length) {
    appendEmpty(list, "Nenhuma medição salva ainda.");
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Sem medições salvas";
    compare.append(option);
    compare.disabled = true;
    document.querySelector("#performance-left-select").disabled = true;
    document.querySelector("#performance-right-select").disabled = true;
    document.querySelector("#performance-comparison").innerHTML = '<p class="empty-state">Salve uma medição antes e outra depois para comparar.</p>';
    return;
  }
  for (const [id, name] of games) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = name;
    compare.append(option);
  }
  compare.disabled = false;
  if (games.some(([id]) => id === previous)) compare.value = previous;

  for (const record of performanceRecords.slice(0, 20)) {
    const row = document.createElement("li");
    row.className = "performance-history-row";
    const title = document.createElement("strong");
    title.textContent = `${record.game_name} · ${record.config_label}`;
    const phase = document.createElement("span");
    phase.textContent = phaseLabel(record.phase);
    const metrics = document.createElement("small");
    const fps = record.capture?.average_fps;
    const low = record.capture?.one_percent_low;
    const system = record.system || {};
    const resourceSummary = [
      system.cpu_average == null ? null : `CPU ${system.cpu_average.toFixed(0)}%`,
      system.gpu_average == null ? null : `GPU ${system.gpu_average.toFixed(0)}%`,
      system.ram_average == null ? null : `RAM ${system.ram_average.toFixed(0)}%`,
    ].filter(Boolean).join(" / ");
    metrics.textContent = `${fps == null ? "FPS n/d" : `${fps.toFixed(1)} FPS`} · ${low == null ? "1% low n/d" : `${low.toFixed(1)} 1% low`}${resourceSummary ? ` · ${resourceSummary}` : ""} · ${formatSavedDate(record.saved_at)}`;
    row.append(title, phase, metrics);
    list.append(row);
  }
  renderPerformanceComparison();
}

function renderPerformanceComparison() {
  const gameId = document.querySelector("#performance-compare-select").value;
  const records = performanceRecords.filter(record => record.game_id === gameId);
  const leftSelect = document.querySelector("#performance-left-select");
  const rightSelect = document.querySelector("#performance-right-select");
  const previousLeft = leftSelect.value;
  const previousRight = rightSelect.value;
  leftSelect.replaceChildren();
  rightSelect.replaceChildren();
  for (const record of records) {
    const label = `${phaseLabel(record.phase)} · ${record.config_label} · ${record.capture?.average_fps == null ? "FPS n/d" : `${record.capture.average_fps.toFixed(1)} FPS`} · ${formatSavedDate(record.saved_at)}`;
    for (const select of [leftSelect, rightSelect]) {
      const option = document.createElement("option");
      option.value = record.id;
      option.textContent = label;
      select.append(option);
    }
  }
  leftSelect.disabled = records.length === 0;
  rightSelect.disabled = records.length < 2;
  const beforeRecord = records.find(record => record.phase === "before");
  const afterRecord = records.find(record => record.phase === "after");
  const firstDefault = beforeRecord || records[0];
  const secondDefault = afterRecord || records.find(record => record.id !== firstDefault?.id);
  if (records.some(record => record.id === previousLeft)) leftSelect.value = previousLeft;
  else if (firstDefault) leftSelect.value = firstDefault.id;
  if (records.some(record => record.id === previousRight) && previousRight !== leftSelect.value) rightSelect.value = previousRight;
  else if (secondDefault) rightSelect.value = secondDefault.id;
  const left = records.find(record => record.id === leftSelect.value);
  const right = records.find(record => record.id === rightSelect.value);
  const panel = document.querySelector("#performance-comparison");
  panel.replaceChildren();
  if (!left || !right || left.id === right.id) {
    const message = document.createElement("p");
    message.className = "empty-state";
    message.textContent = "Salve duas medições deste jogo para comparar configurações.";
    panel.append(message);
    return;
  }
  const table = document.createElement("div");
  table.className = "performance-compare-table";
  for (const [label, key, unit] of [
    ["FPS médio", "average_fps", " FPS"],
    ["1% low", "one_percent_low", " FPS"],
    ["Frametime médio", "average_frametime_ms", " ms"],
    ["Frametime p99", "p99_frametime_ms", " ms"],
  ]) {
    const oldValue = left.capture?.[key];
    const newValue = right.capture?.[key];
    const row = document.createElement("div");
    row.className = "performance-compare-row";
    const name = document.createElement("span"); name.textContent = label;
    const beforeText = document.createElement("span"); beforeText.textContent = oldValue == null ? "—" : `${oldValue.toFixed(2)}${unit}`;
    const afterText = document.createElement("span"); afterText.textContent = newValue == null ? "—" : `${newValue.toFixed(2)}${unit}`;
    const delta = document.createElement("strong");
    delta.textContent = oldValue == null || newValue == null ? "sem dados" : `${newValue - oldValue >= 0 ? "+" : ""}${(newValue - oldValue).toFixed(2)}${unit}`;
    row.append(name, beforeText, afterText, delta);
    table.append(row);
  }
  const headings = document.createElement("div");
  headings.className = "performance-compare-headings";
  headings.innerHTML = "<span>Métrica</span><span>A</span><span>B</span><span>Diferença</span>";
  panel.append(headings, table);
  const note = document.createElement("p");
  note.className = "gaming-note";
  note.textContent = `A: ${left.config_label} (${phaseLabel(left.phase).toLowerCase()}) · B: ${right.config_label} (${phaseLabel(right.phase).toLowerCase()}). Variações também podem vir de cenas, drivers, temperatura e tarefas de fundo.`;
  panel.append(note);
}

function phaseLabel(phase) {
  return ({ before: "ANTES", after: "DEPOIS", custom: "OUTRA CONFIG." })[phase] || "MEDIÇÃO";
}

function formatDuration(seconds) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function drawPerformanceChart(transition = false) {
  const canvas = document.querySelector("#performance-chart");
  if (!canvas) return;
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const previousFrame = transition ? captureCanvasFrame(canvas) : null;
  const context = canvas.getContext("2d");
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * scale);
  canvas.height = Math.round(bounds.height * scale);
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);
  const left = 35, right = bounds.width - 8, top = 12, bottom = bounds.height - 18;
  context.font = "9px Cascadia Mono, Consolas, monospace";
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (const value of [0, 25, 50, 75, 100]) {
    const y = bottom - (bottom - top) * value / 100;
    context.strokeStyle = "rgba(191, 153, 222, .12)";
    context.beginPath(); context.moveTo(left, y); context.lineTo(right, y); context.stroke();
    context.fillStyle = "#8a76a1"; context.fillText(String(value), left - 7, y);
  }
  if (performanceSessionSamples.length < 2) {
    context.textAlign = "center";
    context.fillStyle = "#806b95";
    context.fillText("As amostras do teste aparecerão aqui", (left + right) / 2, (top + bottom) / 2);
    finishCanvasDraw(canvas, previousFrame);
    return;
  }
  for (const [key, color] of [["cpu_percent", "#c08cff"], ["gpu_percent", "#7ce7ff"], ["ram_percent", "#ff7ad9"]]) {
    const values = performanceSessionSamples.map(item => item[key]);
    if (!values.some(value => value !== null && value !== undefined)) continue;
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    let drawing = false;
    values.forEach((value, index) => {
      if (value === null || value === undefined) { drawing = false; return; }
      const firstTime = performanceSessionSamples[0].elapsed;
      const duration = performanceSessionSamples.at(-1).elapsed - firstTime;
      const fraction = duration > 0 ? (performanceSessionSamples[index].elapsed - firstTime) / duration : index / (values.length - 1);
      const x = left + (right - left) * fraction;
      const y = bottom - (bottom - top) * Math.max(0, Math.min(100, value)) / 100;
      if (!drawing) { context.moveTo(x, y); drawing = true; }
      else context.lineTo(x, y);
    });
    context.stroke();
  }
  finishCanvasDraw(canvas, previousFrame);
}

window.addEventListener("resize", drawPerformanceChart);

function renderDiagnosticReport(report, overview) {
  const hardware = report.hardware || {};
  const system = report.system || {};
  const disks = overview.disks || [];
  const startup = overview.startup || {};
  const systemInfo = document.querySelector("#system-info-list");
  systemInfo.replaceChildren();

  addSystemInfo(systemInfo, "Sistema", `${system.display_name || system.name || "Não identificado"} · build ${system.version || "não disponível"}`);
  addSystemInfo(systemInfo, "Arquitetura", hardware.architecture || "Não identificada");
  addSystemInfo(systemInfo, "Processador", `${hardware.cpu_name || "Não identificado"} · ${hardware.physical_cores ?? "?"} núcleos / ${hardware.logical_cores ?? "?"} threads`);
  addSystemInfo(systemInfo, "Memória RAM", `${report.memory.total_gb.toFixed(2)} GB total · ${report.memory.available_gb.toFixed(2)} GB disponíveis`);
  addSystemInfo(systemInfo, "Placa(s) de vídeo", hardware.gpu_available
    ? hardware.gpu_names.join(" · ")
    : "Não identificada nesta leitura; confira o Gerenciador de Dispositivos.");
  if (disks.length) {
    addSystemInfo(systemInfo, "Armazenamento", disks.map(disk => `${disk.name}: ${disk.total_gb.toFixed(1)} GB`).join(" · "));
  }

  const startupInfo = startup.supported
    ? `${startup.items.filter(item => item.enabled).length} item(ns) ativos · ${startup.scope}`
    : startup.message || "Lista disponível na versão Windows.";
  addSystemInfo(systemInfo, "Inicialização", startupInfo);

  const findings = report.findings || [];
  const findingList = document.querySelector("#finding-list");
  findingList.replaceChildren();
  if (!findings.length) appendEmpty(findingList, "Nenhum achado disponível.");
  for (const finding of findings) {
    const item = document.createElement("li");
    item.className = `finding-row severity-${severityClass(finding.severity)}`;
    const heading = document.createElement("div");
    heading.className = "finding-heading";
    const title = document.createElement("strong");
    title.textContent = finding.title;
    const badge = document.createElement("span");
    badge.className = "finding-severity";
    badge.textContent = finding.severity;
    heading.append(title, badge);
    const evidence = document.createElement("p");
    evidence.textContent = finding.evidence;
    const suggestion = document.createElement("small");
    suggestion.textContent = `Sugestão: ${finding.suggestion}`;
    item.append(heading, evidence, suggestion);
    findingList.append(item);
  }

  const mostSevere = findings.some(item => item.severity === "ALTA") ? "ALTO"
    : findings.some(item => item.severity === "MÉDIA") ? "MÉDIO" : "BAIXO";
  const badge = document.querySelector("#level-badge");
  badge.textContent = `NÍVEL ${mostSevere}`;
  badge.className = `level-badge ${mostSevere === "ALTO" ? "high" : mostSevere === "MÉDIO" ? "medium" : ""}`;
  setText("diagnostic-count", `${findings.length} achado(s) · ${mostSevere.toLowerCase()} gravidade máxima`);

  const recommendationList = document.querySelector("#recommendation-list");
  recommendationList.replaceChildren();
  for (const finding of findings.slice(0, 3)) {
    const item = document.createElement("li");
    item.textContent = `${finding.title}: ${finding.suggestion}`;
    recommendationList.append(item);
  }
}

function addSystemInfo(list, label, value) {
  const item = document.createElement("li");
  const name = document.createElement("span");
  name.textContent = label;
  const detail = document.createElement("strong");
  detail.textContent = value;
  item.append(name, detail);
  list.append(item);
}

function severityClass(severity) {
  return ({ ALTA: "high", "MÉDIA": "medium", BAIXA: "low", INFO: "info" })[severity] || "info";
}

function renderDisks(disks) {
  const list = document.querySelector("#disk-list");
  list.replaceChildren();
  if (!disks.length) {
    setText("disk-value", "—");
    setText("disk-total", "Nenhuma unidade disponível");
    setWidth("disk-meter", 0);
    appendEmpty(list, "Nenhuma unidade acessível foi encontrada.");
    return;
  }
  const primaryDisk = disks[0];
  setText("disk-value", `${primaryDisk.used_percent.toFixed(0)}%`);
  setText("disk-total", `${primaryDisk.name} · ${primaryDisk.free_gb.toFixed(1)} GB livres`);
  setWidth("disk-meter", primaryDisk.used_percent);
  for (const disk of disks) {
    const row = document.createElement("li");
    row.className = "disk-row";
    const name = document.createElement("span");
    name.className = "disk-row-name";
    name.textContent = `${disk.name} · ${disk.used_percent.toFixed(0)}% usado`;
    const free = document.createElement("span");
    free.className = "disk-row-free";
    free.textContent = `${disk.free_gb.toFixed(1)} GB livres`;
    const meter = document.createElement("div");
    meter.className = "disk-meter";
    const fill = document.createElement("span");
    fill.style.width = `${Math.min(100, disk.used_percent)}%`;
    meter.append(fill);
    row.append(name, free, meter);
    list.append(row);
  }
}

function renderTempPreview(preview) {
  const summary = document.querySelector("#cleanup-summary");
  const button = document.querySelector("#cleanup-button");
  const list = document.querySelector("#cleanup-files");
  list.replaceChildren();
  button.textContent = "Limpar temporários selecionados";
  if (!preview.supported) {
    summary.textContent = preview.message || "Disponível na versão Windows.";
    button.disabled = true;
    appendEmpty(list, "Nenhuma alteração foi feita.");
    return;
  }
  summary.textContent = `${preview.file_count} arquivo(s) com mais de ${preview.minimum_age_days} dias · até ${formatBytes(preview.bytes)}. Revise a lista e desmarque o que quiser manter.`;
  button.disabled = preview.file_count === 0;
  if (!preview.files.length) {
    button.textContent = "Nenhum temporário antigo";
    appendEmpty(list, preview.file_count ? "Arquivos antigos encontrados." : "Nenhum temporário antigo encontrado.");
    return;
  }
  for (const file of preview.files) {
    const item = document.createElement("li");
    item.className = "cleanup-file-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.dataset.path = file.path;
    checkbox.setAttribute("aria-label", `Selecionar ${file.path} para limpeza`);
    const filename = document.createElement("span");
    filename.className = "cleanup-file";
    filename.textContent = file.path;
    filename.title = file.path;
    const size = document.createElement("span");
    size.className = "cleanup-file-size";
    size.textContent = formatBytes(file.bytes);
    item.append(checkbox, filename, size);
    list.append(item);
  }
  updateCleanupSelection();
}

function renderStartup(data) {
  const scope = document.querySelector("#startup-scope");
  const list = document.querySelector("#startup-list");
  list.replaceChildren();
  if (!data.supported) {
    scope.textContent = data.message || "Disponível na versão Windows.";
    appendEmpty(list, "Nenhuma configuração foi alterada.");
    return;
  }
  scope.textContent = data.scope;
  if (!data.items.length) {
    appendEmpty(list, "Nenhum item nesta lista da sua conta.");
    return;
  }
  for (const startup of data.items) {
    const row = document.createElement("li");
    row.className = "startup-row";
    const text = document.createElement("span");
    text.className = "startup-text";
    const name = document.createElement("span");
    name.className = "startup-name";
    name.textContent = startup.name;
    const command = document.createElement("span");
    command.className = "startup-command";
    command.textContent = startup.command;
    command.title = startup.command;
    text.append(name, command);
    const action = document.createElement("button");
    action.className = "startup-action";
    action.type = "button";
    action.textContent = startup.enabled ? "Desativar" : "Reativar";
    action.dataset.name = startup.name;
    action.dataset.enabled = String(startup.enabled);
    row.append(text, action);
    list.append(row);
  }
}

function renderPowerPlans(data) {
  const select = document.querySelector("#power-plan-select");
  const button = document.querySelector("#power-plan-button");
  select.replaceChildren();
  if (!data.supported || !data.plans.length) {
    select.disabled = true;
    button.disabled = true;
    document.querySelector("#power-description").textContent = data.message || "Nenhum plano disponível.";
    const option = document.createElement("option");
    option.textContent = "Disponível na versão Windows";
    select.append(option);
    return;
  }
  for (const plan of data.plans) {
    const option = document.createElement("option");
    option.value = plan.guid;
    option.textContent = `${plan.name}${plan.active ? " (atual)" : ""}`;
    option.dataset.description = plan.description;
    option.dataset.active = String(plan.active);
    select.append(option);
  }
  select.disabled = false;
  button.disabled = true;
  updatePowerDescription();
}

function updatePowerDescription() {
  const select = document.querySelector("#power-plan-select");
  const option = select.selectedOptions[0];
  if (!option || !currentOptimizerOverview?.power_plans?.supported) return;
  document.querySelector("#power-description").textContent = option.dataset.description;
  document.querySelector("#power-plan-button").disabled = option.dataset.active === "true";
}

async function cleanupTempFiles() {
  const preview = currentOptimizerOverview?.temp_cleanup;
  const selectedPaths = [...document.querySelectorAll("#cleanup-files input:checked")]
    .map(checkbox => checkbox.dataset.path);
  if (!preview?.supported || !selectedPaths.length) return;
  const selectedFiles = preview.files.filter(file => selectedPaths.includes(file.path));
  const selectedBytes = selectedFiles.reduce((total, file) => total + file.bytes, 0);
  const confirmed = window.confirm(
    `Você selecionou ${selectedFiles.length} arquivo(s) temporário(s) com mais de 7 dias.\n` +
    `Tamanho estimado: ${formatBytes(selectedBytes)}.\n\n` +
    "Arquivos em uso serão ignorados. Deseja continuar?"
  );
  if (!confirmed) return;
  const button = document.querySelector("#cleanup-button");
  button.disabled = true;
  try {
    const result = await window.pywebview.api.clean_temp(selectedPaths);
    showNotice(result.message, result.success ? "success" : "warning");
    await loadOptimizerOverview();
  } catch (error) {
    showNotice(`A limpeza não foi concluída: ${error.message || error}`, "warning");
    button.disabled = false;
  }
}

function updateCleanupSelection() {
  const selectedCount = document.querySelectorAll("#cleanup-files input:checked").length;
  const button = document.querySelector("#cleanup-button");
  button.disabled = selectedCount === 0;
  button.textContent = selectedCount
    ? `Limpar ${selectedCount} arquivo(s) selecionado(s)`
    : "Nenhum arquivo selecionado";
}

async function handleStartupAction(event) {
  const button = event.target.closest(".startup-action");
  if (!button) return;
  const enabled = button.dataset.enabled === "true";
  const itemName = button.dataset.name;
  const question = enabled
    ? `Desativar ${itemName} da inicialização da sua conta?\n\nO Shadow guarda uma cópia local para permitir reativar depois.`
    : `Reativar ${itemName} para iniciar quando você entrar no Windows?`;
  if (!window.confirm(question)) return;
  button.disabled = true;
  try {
    const result = await window.pywebview.api.set_startup(itemName, !enabled);
    showNotice(result.message, result.success ? "success" : "warning");
    if (result.success) await loadOptimizerOverview();
    else button.disabled = false;
  } catch (error) {
    showNotice(`Não foi possível alterar a inicialização: ${error.message || error}`, "warning");
    button.disabled = false;
  }
}

async function activateSelectedPowerPlan() {
  const select = document.querySelector("#power-plan-select");
  const option = select.selectedOptions[0];
  if (!option) return;
  if (!window.confirm(`Ativar o plano “${option.textContent}”?\n\nIsso muda o perfil de energia do Windows. Você pode escolher outro plano depois; não há garantia de aumento de FPS.`)) return;
  const button = document.querySelector("#power-plan-button");
  button.disabled = true;
  try {
    const result = await window.pywebview.api.set_power_plan(option.value);
    showNotice(result.message, result.success ? "success" : "warning");
    if (result.success) await loadOptimizerOverview();
    else button.disabled = false;
  } catch (error) {
    showNotice(`Não foi possível alterar o plano: ${error.message || error}`, "warning");
    button.disabled = false;
  }
}

function toggleLiveMonitoring() {
  if (!latestReport) return;
  if (liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
    liveToggleButton.textContent = "Iniciar ao vivo";
    document.querySelector("#live-status").classList.add("paused");
    document.querySelector("#live-status").innerHTML = "<i></i> PAUSADO";
    return;
  }
  liveToggleButton.textContent = "Pausar monitoramento";
  document.querySelector("#live-status").classList.remove("paused");
  document.querySelector("#live-status").innerHTML = "<i></i> AO VIVO";
  liveSampleCount = 0;
  updateLiveSample();
  liveTimer = setInterval(updateLiveSample, effectiveIntervalMs());
}

function isOverviewVisible() {
  const page = document.querySelector('.dashboard-page[data-page="overview"]');
  return Boolean(page && !page.classList.contains("hidden"));
}

async function updateLiveSample() {
  if (appClosing || liveRequestBusy || !window.pywebview?.api) return;
  liveRequestBusy = true;
  try {
    const sample = await window.pywebview.api.live_sample();
    setText("cpu-value", `${sample.cpu_percent.toFixed(1)}%`);
    setText("ram-value", `${sample.ram_percent.toFixed(1)}%`);
    setText("available-value", `${sample.available_gb.toFixed(1)} GB`);
    setWidth("cpu-meter", sample.cpu_percent);
    setWidth("ram-meter", sample.ram_percent);
    setText("disk-read-rate", `${sample.disk_read_mb_s.toFixed(1)} MB/s`);
    setText("disk-write-rate", `${sample.disk_write_mb_s.toFixed(1)} MB/s`);
    latestReport.monitoring.cpu_samples.push(sample.cpu_percent);
    latestReport.monitoring.ram_samples.push(sample.ram_percent);
    latestReport.monitoring.cpu_samples = latestReport.monitoring.cpu_samples.slice(-60);
    latestReport.monitoring.ram_samples = latestReport.monitoring.ram_samples.slice(-60);
    liveSampleCount += 1;
    if (liveSampleCount % 2 === 1) {
      renderLiveProcesses("live-cpu-list", sample.top_cpu_processes, item => `${item.cpu_percent.toFixed(1)}%`);
      renderLiveProcesses("live-ram-list", sample.top_ram_processes, item => `${item.ram_mb.toFixed(0)} MB`);
    }
    if (isOverviewVisible()) drawChart();
  } catch (error) {
    showNotice(`O monitoramento ao vivo parou: ${error.message || error}`, "warning");
    toggleLiveMonitoring();
  } finally {
    liveRequestBusy = false;
  }
}

function renderLiveProcesses(id, processes, valueText) {
  const list = document.getElementById(id);
  list.replaceChildren();
  if (!processes.length) {
    appendEmpty(list, "Sem dados de processos nesta amostra.");
    return;
  }
  for (const process of processes) {
    const row = document.createElement("li");
    row.className = "live-process-row";
    const name = document.createElement("span");
    name.textContent = `${process.name} · PID ${process.pid}`;
    const value = document.createElement("span");
    value.textContent = valueText(process);
    row.append(name, value);
    list.append(row);
  }
}

function appendEmpty(list, message) {
  const item = document.createElement("li");
  item.className = "empty-state";
  item.textContent = message;
  list.append(item);
}

function formatBytes(bytes) {
  if (!bytes) return "0 MB";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return `${value.toFixed(index >= 2 ? 1 : 0)} ${units[index]}`;
}

async function handleProcessAction(event) {
  const button = event.target.closest(".process-close-button");
  if (!button) return;

  const processName = button.dataset.name;
  const confirmed = window.confirm(
    `Deseja pedir ao sistema para encerrar ${processName} (PID ${button.dataset.pid})?\n\n` +
    "Isso pode fechar o aplicativo e causar perda de trabalho não salvo. O Shadow não força o encerramento."
  );
  if (!confirmed) return;

  button.disabled = true;
  showNotice("Solicitando o encerramento do aplicativo…", "info");
  try {
    const result = await window.pywebview.api.terminate_process(
      Number(button.dataset.pid),
      processName,
      Number(button.dataset.createTime)
    );
    if (!result.success) {
      showNotice(result.message, "warning");
      button.disabled = false;
      return;
    }

    await analyze();
    showNotice(`${result.message} Os recursos podem levar um tempo para atualizar.`, "success");
  } catch (error) {
    showNotice(`Não foi possível encerrar o processo: ${error.message || error}`, "warning");
    button.disabled = false;
  }
}

function drawChart(transition = false) {
  const rect = chart.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const previousFrame = transition ? captureCanvasFrame(chart) : null;
  const scale = window.devicePixelRatio || 1;
  chart.width = Math.round(rect.width * scale);
  chart.height = Math.round(rect.height * scale);
  chartContext.setTransform(scale, 0, 0, scale, 0, 0);
  chartContext.clearRect(0, 0, rect.width, rect.height);

  const left = 38;
  const right = rect.width - 12;
  const top = 14;
  const bottom = rect.height - 18;
  chartContext.font = "9px Cascadia Mono, Consolas, monospace";
  chartContext.textAlign = "right";
  chartContext.textBaseline = "middle";
  for (const value of [0, 25, 50, 75, 100]) {
    const y = bottom - (bottom - top) * value / 100;
    chartContext.strokeStyle = "rgba(191, 153, 222, .12)";
    chartContext.lineWidth = 1;
    chartContext.beginPath();
    chartContext.moveTo(left, y);
    chartContext.lineTo(right, y);
    chartContext.stroke();
    chartContext.fillStyle = "#8a76a1";
    chartContext.fillText(`${value}%`, left - 9, y);
  }
  if (!latestReport) {
    finishCanvasDraw(chart, previousFrame);
    return;
  }
  drawSeries(latestReport.monitoring.cpu_samples, "#c08cff", left, right, top, bottom);
  drawSeries(latestReport.monitoring.ram_samples, "#ff7ad9", left, right, top, bottom);
  finishCanvasDraw(chart, previousFrame);
}

function captureCanvasFrame(canvas) {
  if (!effectsEnabled()) return null;
  if (canvas.dataset.drawn !== "true" || !canvas.width || !canvas.height) return null;
  const previous = document.createElement("canvas");
  previous.width = canvas.width;
  previous.height = canvas.height;
  previous.setAttribute("aria-hidden", "true");
  previous.className = "chart-fade-frame";
  previous.getContext("2d").drawImage(canvas, 0, 0);
  return previous;
}

function finishCanvasDraw(canvas, previousFrame) {
  canvas.dataset.drawn = "true";
  if (!previousFrame || !canvas.parentElement) return;
  canvas.parentElement.append(previousFrame);
  const removeFrame = () => previousFrame.remove();
  previousFrame.addEventListener("animationend", removeFrame, { once: true });
  window.setTimeout(removeFrame, 450);
}

function drawSeries(values, color, left, right, top, bottom) {
  if (!values || values.length === 0) return;
  const span = Math.max(1, right - left);
  const points = values.map((value, index) => ({
    x: left + span * index / Math.max(values.length - 1, 1),
    y: bottom - (bottom - top) * Math.max(0, Math.min(value, 100)) / 100,
  }));

  const last = points[points.length - 1];
  const area = chartContext.createLinearGradient(0, top, 0, bottom);
  area.addColorStop(0, `${color}36`);
  area.addColorStop(.72, `${color}0c`);
  area.addColorStop(1, `${color}00`);
  chartContext.beginPath();
  chartContext.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length; index++) {
    const previous = points[index - 1];
    const current = points[index];
    const middle = (previous.x + current.x) / 2;
    chartContext.quadraticCurveTo(previous.x, previous.y, middle, (previous.y + current.y) / 2);
  }
  chartContext.lineTo(last.x, last.y);
  chartContext.lineTo(last.x, bottom);
  chartContext.lineTo(points[0].x, bottom);
  chartContext.closePath();
  chartContext.fillStyle = area;
  chartContext.fill();

  chartContext.beginPath();
  chartContext.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length; index++) {
    const previous = points[index - 1];
    const current = points[index];
    const middle = (previous.x + current.x) / 2;
    chartContext.quadraticCurveTo(previous.x, previous.y, middle, (previous.y + current.y) / 2);
  }
  chartContext.lineTo(last.x, last.y);
  chartContext.strokeStyle = color;
  chartContext.lineWidth = 2.2;
  chartContext.lineCap = "round";
  chartContext.lineJoin = "round";
  chartContext.shadowColor = color;
  chartContext.shadowBlur = 12;
  chartContext.stroke();
  chartContext.shadowBlur = 0;

  for (const point of points) {
    chartContext.beginPath();
    chartContext.arc(point.x, point.y, 2.2, 0, Math.PI * 2);
    chartContext.fillStyle = color;
    chartContext.fill();
  }
}

function animateChart() {
  chart.classList.remove("chart-animate");
  void chart.offsetWidth;
  chart.classList.add("chart-animate");
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element.textContent === String(value)) return;
  element.textContent = value;
  if (effectsEnabled() && element.matches(".live-stat b, .available-memory strong")) {
    element.classList.remove("value-updated");
    window.requestAnimationFrame(() => element.classList.add("value-updated"));
  }
}

function setWidth(id, value) {
  document.getElementById(id).style.width = `${Math.max(0, Math.min(value, 100))}%`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function showError(message) {
  const toast = document.querySelector("#error-toast");
  toast.textContent = message;
  toast.className = `notice-toast ${message ? "warning" : "hidden"}`;
  if (message && window.pywebview?.api) window.pywebview.api.log_frontend_error(message, "Falha exibida pela interface");
}

function showNotice(message, kind) {
  const toast = document.querySelector("#error-toast");
  toast.textContent = message;
  toast.className = `notice-toast ${kind}`;
  if (kind === "warning" && window.pywebview?.api) window.pywebview.api.log_frontend_error(message, "Aviso de operação");
}

/* ============================================================================
   CAMADA DE AMBIÊNCIA DA INTERFACE
   Efeitos puramente visuais; não alteram nenhuma leitura ou ação do sistema.
   ========================================================================== */

const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

document.addEventListener("pointerdown", event => {
  if (!effectsEnabled()) return;
  const button = event.target.closest(".primary-button, .secondary-button, .tool-action-button, .quick-action, .process-close-button, .startup-action, .history-undo-button");
  if (!button || button.disabled) return;
  const bounds = button.getBoundingClientRect();
  const size = Math.max(bounds.width, bounds.height);
  const ripple = document.createElement("span");
  ripple.className = "ui-ripple";
  ripple.style.width = `${size}px`;
  ripple.style.height = `${size}px`;
  ripple.style.left = `${event.clientX - bounds.left - size / 2}px`;
  ripple.style.top = `${event.clientY - bounds.top - size / 2}px`;
  button.append(ripple);
  ripple.addEventListener("animationend", () => ripple.remove(), { once: true });
});

document.addEventListener("visibilitychange", () => {
  if (appClosing) return;
  document.body.classList.toggle("window-hidden", document.hidden);
  syncTelemetryTimer();
  if (document.hidden) {
    if (liveTimer) {
      window.clearInterval(liveTimer);
      liveTimer = null;
      livePausedByVisibility = true;
    }
  } else if (livePausedByVisibility) {
    livePausedByVisibility = false;
    liveTimer = window.setInterval(updateLiveSample, effectiveIntervalMs());
  }
});


document.querySelector("#preferences-form").addEventListener("submit", saveUiPreferences);
document.querySelector("#sensor-refresh").addEventListener("click", () => { sensorsEnabled = true; refreshTelemetry(); syncTelemetryTimer(); });
document.querySelector("#game-prep-save").addEventListener("click", () => runPreparation(false));
document.querySelector("#game-prep-apply").addEventListener("click", () => runPreparation(true));
document.querySelector("#game-prep-restore").addEventListener("click", restorePreparation);

function applyUiPreferences(value) {
  uiPreferences = value;
  document.body.dataset.effects = value.lightweight && value.effects === "full" ? "reduced" : value.effects;
  document.body.classList.toggle("shadow-lite", value.lightweight);
  document.querySelector("#pref-lightweight").checked = value.lightweight;
  document.querySelector("#pref-interval").value = String(value.interval_seconds);
  document.querySelector("#pref-effects").value = value.effects;
  document.querySelector("#pref-intro").checked = value.show_intro;
  setText("preferences-status", `Leituras a cada ${effectiveIntervalMs() / 1000}s. Sensores a cada ${value.lightweight ? 10 : 5}s enquanto esta página ou os sensores estiverem visíveis.`);
  if (liveTimer) { clearInterval(liveTimer); liveTimer = setInterval(updateLiveSample, effectiveIntervalMs()); }
  if (performanceTimer) { clearInterval(performanceTimer); performanceTimer = setInterval(samplePerformanceSession, effectiveIntervalMs()); }
  syncTelemetryTimer();
}
async function saveUiPreferences(event) {
  event.preventDefault();
  const button = event.target.querySelector("button"); button.disabled = true;
  try {
    const result = await window.pywebview.api.save_ui_preferences({
      lightweight: document.querySelector("#pref-lightweight").checked,
      interval_seconds: Number(document.querySelector("#pref-interval").value),
      effects: document.querySelector("#pref-effects").value,
      show_intro: document.querySelector("#pref-intro").checked,
    });
    if (result.success) applyUiPreferences(result.settings);
    showNotice(result.message, result.success ? "success" : "warning");
  } catch (error) { showNotice(String(error), "warning"); }
  finally { button.disabled = false; }
}
function syncTelemetryTimer() {
  clearInterval(telemetryTimer); telemetryTimer = null;
  if (appClosing || document.hidden || !window.pywebview?.api) return;
  const settingsVisible = !document.querySelector('[data-page="settings"]').classList.contains("hidden");
  if (settingsVisible || (sensorsEnabled && isOverviewVisible())) {
    telemetryTimer = setInterval(refreshTelemetry, uiPreferences.lightweight ? 10000 : 5000);
  }
}
function sensorValue(value, unit) { return Number.isFinite(value) ? `${value.toFixed(1)}${unit}` : "indisponível"; }
async function refreshTelemetry() {
  if (telemetryBusy || appClosing || !window.pywebview?.api) return;
  telemetryBusy = true;
  try {
    const data = await window.pywebview.api.telemetry_snapshot();
    if (appClosing) return;
    const list = document.querySelector("#sensor-readings"); list.replaceChildren();
    const lines = (data.gpus || []).map(g => `${g.name} · GPU ${sensorValue(g.usage_percent, "%")} · ${sensorValue(g.temperature_c, " °C")} · VRAM ${sensorValue(g.memory_used_mb, " MiB")} / ${sensorValue(g.memory_total_mb, " MiB")} · ${g.source}`);
    lines.push(...(data.temperatures || []).map(t => `${t.name}: ${sensorValue(t.temperature_c, " °C")} · ${t.source}`));
    if (!lines.length) lines.push("Nenhum sensor compatível respondeu. Indisponível neste computador.");
    for (const text of lines) { const row = document.createElement("li"); row.className = "sensor-row"; row.textContent = text; list.append(row); }
    setText("sensor-status", `Última leitura: ${new Date(data.measured_at * 1000).toLocaleTimeString("pt-BR")}`);
    setText("sensor-help", [data.help, ...(data.notes || [])].join(" "));
    setText("shadow-consumption", `Shadow: CPU ${sensorValue(data.shadow.cpu_percent, "%")} · RAM ${sensorValue(data.shadow.ram_mb, " MiB")} · ${data.shadow.process_count} processos. ${data.shadow.note}`);
  } catch (error) { setText("sensor-status", `Leitura indisponível: ${error.message || error}`); }
  finally { telemetryBusy = false; }
}
async function loadGamePreparation() {
  if (!window.pywebview?.api || preparationBusy) return;
  const gameId = currentSelectedGame()?.id || "";
  try {
    const data = await window.pywebview.api.game_preparation_overview(gameId);
    if (gameId !== (currentSelectedGame()?.id || "") || preparationBusy) return;
    if (!data.success) { setText("game-prep-status", data.message); return; }
    const select = document.querySelector("#game-prep-power"); select.replaceChildren(new Option("Manter plano atual", "keep"));
    for (const plan of data.power.plans || []) select.add(new Option(plan.name + (plan.active ? " (atual)" : ""), plan.guid));
    select.value = data.preference.power_guid || "keep";
    if (!select.value) select.value = "keep";
    document.querySelectorAll(".game-checklist input").forEach((input, i) => { input.checked = data.preference.checklist?.[i] === true; });
    document.querySelector("#game-prep-save").disabled = !gameId;
    document.querySelector("#game-prep-apply").disabled = !gameId || !!data.session.active;
    document.querySelector("#game-prep-restore").disabled = !data.session.active;
    setText("game-prep-status", data.session.active ? `Preparação pendente: ${data.session.game_name}. Plano anterior: ${data.session.previous_name}. Restaure ao terminar de jogar.` : "Salve seu checklist e plano. Aplicar exige revisão e confirmação; marcar o checklist não altera o sistema.");
  } catch (error) { setText("game-prep-status", String(error)); }
}
async function runPreparation(apply) {
  const game = currentSelectedGame(); if (!game || preparationBusy) return;
  preparationBusy = true;
  try {
    let result = await window.pywebview.api.save_game_preparation(game.id, document.querySelector("#game-prep-power").value, [...document.querySelectorAll(".game-checklist input")].map(input => input.checked));
    if (apply && result.success) {
      result = await window.pywebview.api.review_game_preparation(game.id);
      if (result.success && result.changed && window.confirm(result.message)) result = await window.pywebview.api.apply_game_preparation(result.token);
      else if (result.changed) return;
    }
    showNotice(result.message, result.success ? "success" : "warning");
  } catch (error) { showNotice(String(error), "warning"); }
  finally { preparationBusy = false; await loadGamePreparation(); }
}
async function restorePreparation() {
  if (preparationBusy || !window.confirm("Restaurar o plano de energia anterior à preparação? Se ele foi alterado por fora, o Shadow preservará essa escolha.")) return;
  preparationBusy = true;
  try {
    const result = await window.pywebview.api.restore_game_preparation();
    showNotice(result.message, result.success ? "success" : "warning");
  } catch (error) { showNotice(String(error), "warning"); }
  finally { preparationBusy = false; await loadGamePreparation(); }
}
// A apresentação não chama a API: o usuário inicia a análise no painel.
startPresentation();
