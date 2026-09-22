const host = location.hostname === "company-com.tail52eb07.ts.net" ? "100.97.194.62" : (location.hostname || "127.0.0.1");
let pending = null;
let pendingType = "goal";
let chatBusy = false;
let chatSaveBusy = false;
const history = [];
const initialChatEmpty = document.getElementById("chat-empty")?.cloneNode(true);
const CHAT_STATE_KEY = "suhun.portal.chat.v1";
const CHAT_STATE_MAX_MESSAGES = 40;
const CHAT_STATE_MAX_MESSAGE_CHARS = 2400;
const CHAT_STATE_MAX_DRAFT_CHARS = 4000;
const CHAT_STATE_MAX_SERIALIZED_CHARS = 110000;
const launching = new Set();
let appsInFlight = null;
let loadedGoals = null;
let editingGoal = null;
let taskRequest = 0;
let tasksBusy = false;

const manualDialog = document.getElementById("manual-dialog");
const manualClose = document.getElementById("manual-close");
let manualReturnFocus = null;
let manualBodyOverflow = "";

function openManual(event) {
  if (manualDialog.open) return;
  manualReturnFocus = event.currentTarget;
  manualBodyOverflow = document.body.style.overflow;
  manualDialog.showModal();
  document.body.style.overflow = "hidden";
  manualClose.focus();
}

function closeManual() {
  if (manualDialog.open) manualDialog.close();
}

if (manualDialog && manualClose) {
document.querySelectorAll("[data-open-manual]").forEach(button => button.addEventListener("click", openManual));
manualClose.addEventListener("click", closeManual);
manualDialog.addEventListener("close", () => {
  document.body.style.overflow = manualBodyOverflow;
  const trigger = manualReturnFocus;
  manualReturnFocus = null;
  if (trigger?.isConnected) trigger.focus();
});
manualDialog.addEventListener("click", event => {
  if (event.target !== manualDialog) return;
  const rect = manualDialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeManual();
});
}

const APP_DETAILS = {
  clink: { name: "CLINK", purpose: "보험금 청구서 자동 작성", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M7 3.5h7l3 3V20H7z" stroke-linejoin="round"/><path d="M14 3.5V7h3M9.5 11h5M9.5 14.5h5" stroke-linecap="round"/></svg>' },
  ipis: { name: "IPIS", purpose: "보험 CMT 매칭", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="8" cy="8" r="3"/><circle cx="16" cy="16" r="3"/><path d="m10.2 10.2 3.6 3.6M5 17.5h6M13 6.5h6" stroke-linecap="round"/></svg>' },
  trading: { name: "Trading", purpose: "트레이딩 대시보드", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M4 18.5h16M6 15l3-4 3 2 5-6" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 7h3v3" stroke-linecap="round" stroke-linejoin="round"/></svg>' },
  rivals: { name: "Rivals Deck", purpose: "9이닝스 라이벌즈 덱관리", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M7 4.5c2.5 3 2.5 12 0 15M17 4.5c-2.5 3-2.5 12 0 15" stroke-linecap="round" stroke-dasharray="2.5 1.8"/></svg>' },
};

const APP_GROUP_FALLBACK = [
  { id: "work", title: "회사" },
  { id: "personal", title: "개인" },
];

function linkHostname(url) {
  try { return new URL(url).hostname; } catch (error) { return url; }
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(number) : "—";
}

function setToday() {
  const node = document.getElementById("today");
  if (!node) return;
  const date = new Date();
  node.textContent = new Intl.DateTimeFormat("ko-KR", { dateStyle: "full" }).format(date);
  node.dateTime = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function setGoalsStatus(message, kind = "") {
  const node = document.getElementById("goals-status");
  if (!node) return;
  node.textContent = message;
  node.className = `chat-status${kind ? ` ${kind}` : ""}`;
}

const projectNames = { ipis: "IPIS", clink: "CLINK" };
const priorityNames = { high: "높음", mid: "보통", low: "낮음" };
const kindNames = { numeric: "수치형", checklist: "체크형" };
let goalTasks = [];

function goalById(id) {
  for (const period of ["week", "day"]) {
    const items = loadedGoals?.[period]?.items || [];
    const index = items.findIndex(item => item && item.id === id);
    if (index >= 0) return { period, index, item: items[index] };
  }
  return null;
}

function linkedTasks(goalId) {
  return goalTasks.filter(task => task.goal_id === goalId);
}

function checklistProgress(goalId) {
  const tasks = linkedTasks(goalId);
  const done = tasks.filter(task => task.done).length;
  return { total: tasks.length, done, percent: tasks.length ? Math.round(done / tasks.length * 100) : 0 };
}

function goalProgressLabel(item) {
  if (item.kind === "checklist") {
    const progress = checklistProgress(item.id);
    return `${projectNames[item.project] || "업무"} ${item.goal || "목표"}: ${progress.done}/${progress.total} 완료`;
  }
  const current = Number(item.current);
  const targetValue = Number(item.target);
  const percent = Number.isFinite(current) && targetValue > 0 ? Math.max(0, Math.min(100, Math.round(current / targetValue * 100))) : 0;
  return `${projectNames[item.project] || "업무"} ${item.goal || "목표"}: ${percent}% 진행`;
}

function drawGoals(goals) {
  loadedGoals = goals;
  if (!document.getElementById("week") || !document.getElementById("day")) return;
  const safeGoals = goals || {};
  const week = safeGoals.week || { start: "", items: [] };
  const day = safeGoals.day || { date: "", items: [] };
  document.getElementById("week-when").textContent = week.start || "기간 미정";
  document.getElementById("day-when").textContent = day.date || "날짜 미정";
  for (const [key, period] of [["week", week], ["day", day]]) {
    const target = document.getElementById(key);
    const items = Array.isArray(period.items) ? period.items : [];
    if (!items.length) {
      target.innerHTML = '<div class="empty-state"><p>아직 정한 목표가 없습니다. 아래에서 직접 추가하거나 업무 정리에서 정하세요.</p><a href="/organize">업무 정리에서 목표 정하기</a></div>';
      continue;
    }
    target.innerHTML = items.map((item, index) => {
      const project = projectNames[item.project] || String(item.project || "업무");
      const kind = kindNames[item.kind] || "수치형";
      const label = escapeHtml(goalProgressLabel(item));
      let progressHtml = "";
      if (item.kind === "checklist") {
        const progress = checklistProgress(item.id);
        progressHtml = `<div class="goal-row-top"><span class="goal-number">${progress.done} / ${progress.total} 완료</span></div>
        <div class="goal-bar" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress.percent}"><i style="width:${progress.percent}%"></i></div>`;
      } else {
        const current = Number(item.current);
        const targetValue = Number(item.target);
        const percent = Number.isFinite(current) && targetValue > 0 ? Math.max(0, Math.min(100, Math.round(current / targetValue * 100))) : 0;
        progressHtml = `<div class="goal-row-top"><span class="goal-number">${formatNumber(item.current)} / ${formatNumber(item.target)} ${escapeHtml(item.unit || "")}</span></div>
        <div class="goal-bar" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><i style="width:${percent}%"></i></div>`;
      }
      const memoHtml = item.memo ? `<p class="goal-memo">${escapeHtml(item.memo)}</p>` : "";
      return `<article class="goal-row" data-period="${key}" data-index="${index}">
        <div class="goal-row-top">
          <div class="goal-copy"><span class="goal-project">${escapeHtml(project)}</span><span class="goal-kind">${escapeHtml(kind)}</span><span class="goal-text">${escapeHtml(item.goal || "목표")}</span></div>
          <span class="goal-row-buttons"><button type="button" class="goal-edit">수정</button><button type="button" class="goal-delete">삭제</button></span>
        </div>
        ${progressHtml}
        ${memoHtml}
        <div class="goal-links" data-goal-id="${escapeHtml(item.id || "")}"></div>
      </article>`;
    }).join("");
    target.querySelectorAll(".goal-edit").forEach(button => {
      button.onclick = () => showGoalEditor(key, Number(button.closest(".goal-row").dataset.index));
    });
    target.querySelectorAll(".goal-delete").forEach(button => {
      button.onclick = () => deleteGoal(key, Number(button.closest(".goal-row").dataset.index));
    });
  }
  renderGoalLinks();
}

function goalRange() {
  const weekStart = loadedGoals?.week?.start || localDate();
  const dayDate = loadedGoals?.day?.date || localDate();
  const start = weekStart < dayDate ? weekStart : dayDate;
  let end = weekStart;
  const weekEnd = new Date(`${weekStart}T00:00:00`);
  if (!Number.isNaN(weekEnd.getTime())) {
    weekEnd.setDate(weekEnd.getDate() + 6);
    const endText = `${weekEnd.getFullYear()}-${String(weekEnd.getMonth() + 1).padStart(2, "0")}-${String(weekEnd.getDate()).padStart(2, "0")}`;
    end = endText > start ? endText : start;
  }
  if (dayDate > end) end = dayDate;
  return { start, end };
}

async function loadGoalTasks() {
  if (!document.getElementById("week")) return;
  const { start, end } = goalRange();
  try {
    const response = await fetch(`/api/tasks?from=${encodeURIComponent(start)}&to=${encodeURIComponent(end)}`);
    if (!response.ok) throw new Error("연결된 할 일을 불러오지 못했습니다.");
    goalTasks = await response.json();
  } catch (error) {
    goalTasks = [];
  }
  refreshGoalView();
}

async function loadGoalsPage() {
  const ok = await loadGoals();
  if (ok) await loadGoalTasks();
  else renderGoalLinks();
}

function renderGoalLinks() {
  document.querySelectorAll(".goal-links").forEach(box => {
    const found = goalById(box.dataset.goalId);
    if (!found) { box.innerHTML = ""; return; }
    const { period, item } = found;
    const tasks = linkedTasks(item.id);
    const candidates = goalTasks.filter(task => !task.goal_id);
    const rows = tasks.length ? tasks.map(task => `
      <li class="goal-link-row${task.done ? " done" : ""}">
        <input type="checkbox" data-task-toggle="${task.id}"${task.done ? " checked" : ""} aria-label="${escapeHtml(task.title)} 완료">
        <span class="goal-link-title">${escapeHtml(task.title)}</span>
        <span class="goal-link-date">${escapeHtml(task.date)}</span>
        <button type="button" class="goal-link-unlink" data-task-unlink="${task.id}" aria-label="${escapeHtml(task.title)} 연결 해제">해제</button>
      </li>`).join("") : '<li class="goal-link-empty">연결된 할 일이 없습니다. 아래에서 연결하거나 새로 만드세요.</li>';
    const options = candidates.map(task => `<option value="${task.id}">${escapeHtml(task.date)} · ${escapeHtml(task.title)}</option>`).join("");
    box.innerHTML = `
      <p class="goal-links-title">연결된 할 일 ${tasks.length ? `(${tasks.filter(task => task.done).length}/${tasks.length})` : ""}</p>
      <ul class="goal-link-list">${rows}</ul>
      <div class="goal-link-add">
        <select data-link-pick aria-label="연결할 할 일 선택"><option value="">할 일 선택…</option>${options}</select>
        <button type="button" data-link-do>연결</button>
      </div>
      <form class="goal-link-create" data-period-hint="${period}">
        <input type="text" data-link-title maxlength="200" placeholder="새 할 일 제목" aria-label="새 할 일 제목">
        <input type="date" data-link-date value="${escapeHtml(loadedGoals?.day?.date || localDate())}" aria-label="새 할 일 날짜">
        <button type="submit">할 일 만들기</button>
      </form>
      <p class="inline-status" aria-live="polite"></p>`;
    box.querySelectorAll("[data-task-toggle]").forEach(check => {
      check.onchange = () => toggleLinkedTask(check.dataset.taskToggle, check.checked, box);
    });
    box.querySelectorAll("[data-task-unlink]").forEach(button => {
      button.onclick = () => linkTask(button.dataset.taskUnlink, null);
    });
    box.querySelector("[data-link-do]").onclick = () => {
      const pick = box.querySelector("[data-link-pick]");
      if (!pick.value) { box.querySelector(".inline-status").textContent = "연결할 할 일을 선택하세요."; return; }
      linkTask(pick.value, item.id);
    };
    box.querySelector(".goal-link-create").onsubmit = event => createLinkedTask(event, item.id, box);
  });
}

async function toggleLinkedTask(id, done, box) {
  const status = box.querySelector(".inline-status");
  try {
    const response = await fetch(`/api/tasks/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done }) });
    if (!response.ok) throw new Error("할 일을 저장하지 못했습니다.");
    const updated = await response.json();
    goalTasks = goalTasks.map(task => task.id === id ? updated : task);
    refreshGoalView();
    document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: done ? "taskDone" : "taskReopened" } }));
  } catch (error) {
    if (status) status.textContent = error instanceof Error ? error.message : "할 일을 저장하지 못했습니다.";
    renderGoalLinks();
  }
}

function refreshGoalView() {
  if (!document.getElementById("week") || !loadedGoals) return;
  if (editingGoal) { renderGoalLinks(); return; }
  drawGoals(loadedGoals);
}

async function linkTask(id, goalId) {
  try {
    const response = await fetch(`/api/tasks/${id}/link`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal_id: goalId }) });
    if (!response.ok) throw new Error("연결하지 못했습니다.");
    const updated = await response.json();
    goalTasks = goalTasks.map(task => task.id === id ? updated : task);
    refreshGoalView();
    if (document.getElementById("task-date")) await loadTasks();
    setGoalsStatus(goalId ? "할 일을 목표에 연결했습니다." : "목표 연결을 해제했습니다.", "success");
  } catch (error) {
    setGoalsStatus(error instanceof Error ? error.message : "연결하지 못했습니다.", "error");
    setTasksStatus(error instanceof Error ? error.message : "연결하지 못했습니다.", "error");
  }
}

async function createLinkedTask(event, goalId, box) {
  event.preventDefault();
  const status = box.querySelector(".inline-status");
  const titleInput = box.querySelector("[data-link-title]");
  const dateInput = box.querySelector("[data-link-date]");
  const title = titleInput.value.trim();
  if (!title) { status.textContent = "할 일 제목을 입력하세요."; return; }
  if (!dateInput.value) { status.textContent = "날짜를 선택하세요."; return; }
  try {
    const response = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, date: dateInput.value, goal_id: goalId }) });
    if (!response.ok) throw new Error("할 일을 만들지 못했습니다.");
    const created = await response.json();
    const { start, end } = goalRange();
    if (created.date >= start && created.date <= end) goalTasks.push(created);
    titleInput.value = "";
    refreshGoalView();
    setGoalsStatus("목표에 연결된 할 일을 만들었습니다.", "success");
    document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "taskAdded" } }));
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "할 일을 만들지 못했습니다.";
  }
}

async function deleteGoal(period, index) {
  const goalPeriod = loadedGoals?.[period];
  const item = goalPeriod?.items?.[index];
  if (!item) return;
  if (!confirm(`'${item.goal}' 목표를 삭제할까요? 연결된 할 일은 유지되고 연결만 해제됩니다.`)) return;
  try {
    const response = await fetch(`/api/goals/${period}/${index}`, { method: "DELETE" });
    if (response.status === 404) throw new Error("목표를 찾을 수 없습니다.");
    if (!response.ok) throw new Error("목표를 삭제하지 못했습니다.");
    drawGoals(await response.json());
    await loadGoalTasks();
    setGoalsStatus("목표를 삭제했습니다.", "success");
    document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "goalsSaved" } }));
  } catch (error) {
    setGoalsStatus(error instanceof Error ? error.message : "목표를 삭제하지 못했습니다.", "error");
  }
}

function wireGoalAddForms() {
  document.querySelectorAll(".goal-add-form").forEach(form => {
    const kindSelect = form.querySelector('select[name="kind"]');
    const numericWrap = form.querySelector(".goal-add-numeric");
    const syncKind = () => { if (numericWrap) numericWrap.hidden = kindSelect.value !== "numeric"; };
    kindSelect.onchange = syncKind;
    syncKind();
    form.onsubmit = async event => {
      event.preventDefault();
      const status = form.querySelector(".inline-status");
      const data = new FormData(form);
      const kind = data.get("kind");
      const payload = {
        project: data.get("project"),
        goal: String(data.get("goal") || "").trim(),
        kind,
        memo: String(data.get("memo") || "").trim(),
      };
      if (kind === "numeric") {
        payload.target = Number(data.get("target"));
        payload.unit = String(data.get("unit") || "").trim();
      } else {
        payload.target = 0;
        payload.unit = "";
      }
      if (!payload.goal) { status.textContent = "목표 내용을 입력하세요."; return; }
      const submit = form.querySelector('button[type="submit"]');
      submit.disabled = true;
      try {
        const response = await fetch(`/api/goals/${form.dataset.period}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        if (!response.ok) throw new Error("목표를 추가하지 못했습니다. 수치를 확인하세요.");
        drawGoals(await response.json());
        await loadGoalTasks();
        form.reset();
        syncKind();
        form.closest("details").open = false;
        setGoalsStatus("목표를 추가했습니다.", "success");
        document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "goalsSaved" } }));
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : "목표를 추가하지 못했습니다.";
      } finally {
        submit.disabled = false;
      }
    };
  });
}

function showGoalEditor(period, index) {
  if (editingGoal) return;
  const row = document.querySelector(`.goal-row[data-period="${period}"][data-index="${index}"]`);
  const goalPeriod = loadedGoals?.[period];
  const item = goalPeriod?.items?.[index];
  if (!row || !item) return;
  editingGoal = { period, index };
  const form = document.createElement("form");
  form.className = "goal-edit-form goal-edit-full";
  form.innerHTML = `
    <label>프로젝트 <select name="project"><option value="ipis">IPIS</option><option value="clink">CLINK</option></select></label>
    <label>목표 내용 <input name="goal" type="text" maxlength="200" required value="${escapeHtml(item.goal || "")}"></label>
    <label>종류 <select name="kind"><option value="numeric">수치형</option><option value="checklist">체크형</option></select></label>
    <span class="goal-edit-numeric">
      <label>완료 수치 <input name="current" type="number" min="0" step="any" required value="${escapeHtml(item.current ?? 0)}"></label>
      <label>목표 수치 <input name="target" type="number" min="0" step="any" required value="${escapeHtml(item.target ?? 0)}"></label>
      <label>단위 <input name="unit" type="text" maxlength="20" value="${escapeHtml(item.unit || "")}"></label>
    </span>
    <label>메모 <input name="memo" type="text" maxlength="500" value="${escapeHtml(item.memo || "")}"></label>
    <span class="goal-edit-buttons"><button class="task-add" type="submit">저장</button><button class="quiet-button" type="button">취소</button></span>
    <p class="inline-status" aria-live="polite"></p>`;
  form.project.value = item.project || "ipis";
  form.kind.value = item.kind || "numeric";
  const numericWrap = form.querySelector(".goal-edit-numeric");
  const syncKind = () => { numericWrap.hidden = form.kind.value !== "numeric"; };
  form.kind.onchange = syncKind;
  syncKind();
  const [save, cancel] = form.querySelectorAll(".goal-edit-buttons button");
  cancel.onclick = () => { form.remove(); editingGoal = null; };
  form.onsubmit = async event => {
    event.preventDefault();
    const status = form.querySelector(".inline-status");
    const kind = form.kind.value;
    const payload = {
      project: form.project.value,
      goal: form.goal.value.trim(),
      kind,
      memo: form.memo.value.trim(),
      expected: item,
      expected_date: period === "week" ? goalPeriod.start : goalPeriod.date,
    };
    if (kind === "numeric") {
      payload.current = Number(form.current.value);
      payload.target = Number(form.target.value);
      payload.unit = form.unit.value.trim();
      if (!form.current.value.trim() || !Number.isFinite(payload.current) || payload.current < 0) { status.textContent = "완료 수치는 0 이상의 수치여야 합니다."; return; }
    }
    if (!payload.goal) { status.textContent = "목표 내용을 입력하세요."; return; }
    save.disabled = cancel.disabled = true;
    try {
      const expectedDate = period === "week" ? goalPeriod.start : goalPeriod.date;
      const response = await fetch(`/api/goals/${period}/${index}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, expected_date: expectedDate }) });
      if (response.status === 409) { form.remove(); editingGoal = null; const reloaded = await loadGoals(true); setGoalsStatus(reloaded ? "다른 곳에서 목표가 변경되었습니다. 최신 내용을 불러왔습니다." : "다른 곳에서 목표가 변경되었습니다. 페이지를 새로고침한 뒤 다시 시도하세요.", "error"); if (reloaded) await loadGoalTasks(); return; }
      if (!response.ok) throw new Error("목표를 저장하지 못했습니다. 수치를 확인하세요.");
      editingGoal = null;
      drawGoals(await response.json());
      await loadGoalTasks();
      setGoalsStatus("목표를 저장했습니다.", "success");
      document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "goalsSaved" } }));
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "목표를 저장하지 못했습니다.";
      save.disabled = cancel.disabled = false;
    }
  };
  row.append(form);
  form.goal.focus();
}

async function loadGoals(force = false) {
  if (editingGoal && !force) return;
  try {
    const response = await fetch("/api/goals");
    if (!response.ok) throw new Error("목표를 불러오지 못했습니다.");
    drawGoals(await response.json());
    setGoalsStatus("");
    return true;
  } catch (error) {
    setGoalsStatus(error instanceof Error ? error.message : "목표를 불러오지 못했습니다.", "error");
    return false;
  }
}

function localDate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function setTasksStatus(message, kind = "") {
  const node = document.getElementById("tasks-status");
  if (!node) return;
  node.textContent = message;
  node.className = `chat-status${kind ? ` ${kind}` : ""}`;
}

function taskGoalLabel(task) {
  if (!task.goal_id) return null;
  const found = goalById(task.goal_id);
  if (!found) return "연결된 목표";
  const project = projectNames[found.item.project] || "업무";
  return `${project} · ${found.item.goal || "목표"}`;
}

function goalOptionsHtml(selectedId) {
  const options = [];
  for (const [key, label] of [["week", "주간"], ["day", "일간"]]) {
    for (const item of loadedGoals?.[key]?.items || []) {
      const project = projectNames[item.project] || "업무";
      const selected = item.id === selectedId ? " selected" : "";
      options.push(`<option value="${escapeHtml(item.id)}"${selected}>${label} · ${escapeHtml(project)} · ${escapeHtml(item.goal || "목표")}</option>`);
    }
  }
  return options.join("");
}

function fillTaskGoalPicker() {
  const picker = document.getElementById("task-goal");
  if (!picker) return;
  const keep = picker.value;
  picker.innerHTML = `<option value="">연결 없음</option>${goalOptionsHtml("")}`;
  if (keep && goalById(keep)) picker.value = keep;
}

function renderTasks(tasks) {
  const list = document.getElementById("task-list");
  const count = document.getElementById("task-count");
  if (!list) return;
  const done = tasks.filter(task => task.done).length;
  if (count) count.textContent = `${done}개 완료 / ${tasks.length}개`;
  list.innerHTML = tasks.length ? "" : '<p class="empty-state">이 날짜에 저장된 할 일이 없습니다.</p>';
  const hasGoals = ((loadedGoals?.week?.items || []).length + (loadedGoals?.day?.items || []).length) > 0;
  tasks.forEach(task => {
    const row = document.createElement("div");
    row.className = `task-row${task.done ? " done" : ""}`;
    const check = document.createElement("input");
    check.type = "checkbox"; check.checked = task.done; check.disabled = tasksBusy; check.setAttribute("aria-label", `${task.title} 완료`);
    check.onchange = () => mutateTask(task.id, { done: check.checked });
    check.id = `task-${task.id}`;
    const main = document.createElement("div");
    main.className = "task-main";
    const label = document.createElement("label"); label.textContent = task.title; label.htmlFor = check.id;
    main.append(label);
    if (task.memo) {
      const memo = document.createElement("p");
      memo.className = "task-memo"; memo.textContent = task.memo;
      main.append(memo);
    }
    const meta = document.createElement("div");
    meta.className = "task-meta";
    const pri = document.createElement("span");
    pri.className = `task-pri pri-${task.priority || "mid"}`;
    pri.textContent = priorityNames[task.priority] || "보통";
    meta.append(pri);
    const goalLabel = taskGoalLabel(task);
    if (goalLabel) {
      const badge = document.createElement("span");
      badge.className = "task-goal-badge"; badge.textContent = goalLabel;
      badge.title = "연결된 목표 (목표 관리에서 확인)";
      meta.append(badge);
      if (!tasksBusy) {
        const unlink = document.createElement("button");
        unlink.type = "button"; unlink.className = "task-goal-unlink"; unlink.textContent = "연결 해제";
        unlink.setAttribute("aria-label", `${task.title} 목표 연결 해제`);
        unlink.onclick = () => linkTask(task.id, null);
        meta.append(unlink);
      }
    } else if (hasGoals && !tasksBusy) {
      const pick = document.createElement("select");
      pick.className = "task-link";
      pick.setAttribute("aria-label", `${task.title} 목표 연결`);
      pick.innerHTML = `<option value="">목표 연결…</option>${goalOptionsHtml("")}`;
      pick.onchange = () => { if (pick.value) linkTask(task.id, pick.value); };
      meta.append(pick);
    }
    main.append(meta);
    if (!tasksBusy) {
      const edit = document.createElement("button");
      edit.type = "button"; edit.className = "task-edit"; edit.textContent = "수정";
      edit.setAttribute("aria-label", `${task.title} 수정`);
      edit.onclick = () => showTaskEditor(row, task);
      row.append(check, main, edit);
    } else {
      row.append(check, main);
    }
    const remove = document.createElement("button");
    remove.type = "button"; remove.className = "task-delete"; remove.disabled = tasksBusy; remove.textContent = "삭제"; remove.setAttribute("aria-label", `${task.title} 삭제`);
    remove.onclick = () => { if (confirm(`'${task.title}' 할 일을 삭제할까요?`)) mutateTask(task.id); };
    row.append(remove); list.append(row);
  });
}

function showTaskEditor(row, task) {
  if (row.querySelector(".task-edit-form")) return;
  const form = document.createElement("form");
  form.className = "task-edit-form";
  form.innerHTML = `
    <input name="title" type="text" maxlength="200" required value="${escapeHtml(task.title)}" aria-label="할 일 제목">
    <select name="priority" aria-label="우선순위">
      <option value="high">높음</option><option value="mid">보통</option><option value="low">낮음</option>
    </select>
    <input name="memo" type="text" maxlength="500" value="${escapeHtml(task.memo || "")}" placeholder="메모 (선택 사항)" aria-label="메모">
    <button class="task-add" type="submit">저장</button><button class="quiet-button" type="button">취소</button>
    <p class="inline-status" aria-live="polite"></p>`;
  form.priority.value = task.priority || "mid";
  const [save, cancel] = form.querySelectorAll("button");
  cancel.onclick = () => form.remove();
  form.onsubmit = async event => {
    event.preventDefault();
    const status = form.querySelector(".inline-status");
    const title = form.title.value.trim();
    if (!title) { status.textContent = "할 일을 입력하세요."; return; }
    save.disabled = cancel.disabled = true;
    try {
      const response = await fetch(`/api/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, priority: form.priority.value, memo: form.memo.value.trim() }),
      });
      if (response.status === 404) throw new Error("할 일을 찾을 수 없습니다.");
      if (!response.ok) throw new Error("할 일을 저장하지 못했습니다.");
      await loadTasks();
      setTasksStatus("할 일을 수정했습니다.", "success");
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "할 일을 저장하지 못했습니다.";
      save.disabled = cancel.disabled = false;
    }
  };
  row.append(form);
  form.title.focus();
}

async function loadTasks() {
  const dateInput = document.getElementById("task-date");
  if (!dateInput) return;
  const selected = dateInput.value;
  const request = ++taskRequest;
  if (!selected) {
    document.getElementById("task-list").innerHTML = '<p class="empty-state">날짜를 선택하세요.</p>';
    document.getElementById("task-count").textContent = "—";
    setTasksStatus("날짜를 선택한 뒤 다시 시도하세요.", "error");
    return;
  }
  document.getElementById("task-list").innerHTML = '<p class="empty-state">할 일을 불러오는 중…</p>';
  document.getElementById("task-count").textContent = "—";
  try {
    const response = await fetch(`/api/tasks?date=${encodeURIComponent(selected)}`);
    if (!response.ok) throw new Error("할 일을 불러오지 못했습니다.");
    const tasks = await response.json();
    if (request === taskRequest && selected === document.getElementById("task-date").value) { renderTasks(tasks); setTasksStatus(""); }
  } catch (error) {
    if (request === taskRequest) {
      const message = error instanceof Error ? error.message : "할 일을 불러오지 못했습니다.";
      document.getElementById("task-list").innerHTML = '<p class="empty-state">할 일을 불러오지 못했습니다. <button id="tasks-retry" class="quiet-button" type="button">다시 시도</button></p>';
      document.getElementById("tasks-retry").onclick = loadTasks;
      setTasksStatus(message, "error");
    }
  }
}

async function mutateTask(id, update) {
  if (tasksBusy) return;
  tasksBusy = true; setTaskControls(true);
  try {
    const response = await fetch(`/api/tasks/${id}`, update ? { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(update) } : { method: "DELETE" });
    if (!response.ok) throw new Error("할 일을 저장하지 못했습니다.");
    await loadTasks();
    document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: update ? (update.done ? "taskDone" : "taskReopened") : "taskDeleted" } }));
  } catch (error) { await loadTasks(); setTasksStatus(error instanceof Error ? error.message : "할 일을 저장하지 못했습니다.", "error"); }
  finally { tasksBusy = false; setTaskControls(false); }
}

function setTaskControls(disabled) {
  const dateInput = document.getElementById("task-date");
  if (!dateInput) return;
  dateInput.disabled = disabled;
  for (const id of ["task-title", "task-memo", "task-priority", "task-goal"]) {
    const node = document.getElementById(id);
    if (node) node.disabled = disabled;
  }
  const submit = document.querySelector("#task-form button[type='submit'], #task-form button:not([type])");
  if (submit) submit.disabled = disabled;
  document.querySelectorAll("#task-list input, #task-list button, #task-list select").forEach(control => { control.disabled = disabled; });
}

const taskForm = document.getElementById("task-form");
if (taskForm) {
taskForm.onsubmit = async event => {
  event.preventDefault();
  if (tasksBusy) return;
  const input = document.getElementById("task-title");
  const title = input.value.trim();
  if (!title) { setTasksStatus("할 일을 입력하세요.", "error"); return; }
  if (!document.getElementById("task-date").value) { setTasksStatus("날짜를 선택한 뒤 추가하세요.", "error"); return; }
  const memoNode = document.getElementById("task-memo");
  const priorityNode = document.getElementById("task-priority");
  const goalNode = document.getElementById("task-goal");
  const payload = { title, date: document.getElementById("task-date").value };
  if (memoNode && memoNode.value.trim()) payload.memo = memoNode.value.trim();
  if (priorityNode && priorityNode.value) payload.priority = priorityNode.value;
  if (goalNode && goalNode.value) payload.goal_id = goalNode.value;
  tasksBusy = true; setTaskControls(true);
  try {
    const response = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!response.ok) throw new Error("할 일을 추가하지 못했습니다.");
    input.value = "";
    if (memoNode) memoNode.value = "";
    if (goalNode) goalNode.value = "";
    await loadTasks(); setTasksStatus("할 일을 추가했습니다.", "success");
    document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "taskAdded" } }));
  } catch (error) { setTasksStatus(error instanceof Error ? error.message : "할 일을 추가하지 못했습니다.", "error"); }
  finally { tasksBusy = false; setTaskControls(false); }
};
}

const taskDateInput = document.getElementById("task-date");
if (taskDateInput) {
  taskDateInput.value = localDate();
  taskDateInput.onchange = () => { syncCalendar(); loadTasks(); };
}
const tasksRefresh = document.getElementById("tasks-refresh");
if (tasksRefresh) tasksRefresh.onclick = loadTasks;

const holidayCache = new Map();
let calYear = 0;
let calMonth = 0;

async function ensureHolidays(year) {
  if (holidayCache.has(year)) return holidayCache.get(year);
  const empty = { days: new Set(), names: {} };
  try {
    const response = await fetch(`/api/holidays?year=${year}`);
    if (!response.ok) throw new Error("holidays failed");
    const body = await response.json();
    const entry = { days: new Set(body.days || []), names: body.names || {} };
    holidayCache.set(year, entry);
    return entry;
  } catch {
    holidayCache.set(year, empty);
    return empty;
  }
}

function parseSelectedDate() {
  const value = document.getElementById("task-date")?.value || "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
  if (match) return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
  const now = new Date();
  return { y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() };
}

function syncCalendar() {
  const selected = parseSelectedDate();
  if (calYear !== selected.y || calMonth !== selected.m) {
    calYear = selected.y;
    calMonth = selected.m;
  }
  renderCalendar();
}

function shiftCalendar(delta) {
  let y = calYear;
  let m = calMonth + delta;
  if (m === 0) { y -= 1; m = 12; }
  if (m === 13) { y += 1; m = 1; }
  if (y < 1900 || y > 2100) return;
  calYear = y;
  calMonth = m;
  renderCalendar();
}

async function renderCalendar() {
  const grid = document.getElementById("cal-grid");
  const title = document.getElementById("cal-title");
  const dateInput = document.getElementById("task-date");
  if (!grid || !title || !dateInput) return;
  const viewY = calYear;
  const viewM = calMonth;
  title.textContent = `${viewY}년 ${viewM}월`;
  const { days, names } = await ensureHolidays(viewY);
  if (calYear !== viewY || calMonth !== viewM) return;
  const selectedValue = document.getElementById("task-date").value;
  const today = localDate();
  const firstDow = new Date(viewY, viewM - 1, 1).getDay();
  const daysInMonth = new Date(viewY, viewM, 0).getDate();
  grid.innerHTML = "";
  for (let i = 0; i < firstDow; i++) {
    const blank = document.createElement("span");
    blank.className = "cal-cell blank";
    blank.setAttribute("aria-hidden", "true");
    grid.append(blank);
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${viewY}-${String(viewM).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const dow = new Date(viewY, viewM - 1, d).getDay();
    const isHoliday = days.has(key);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cal-cell"
      + (dow === 0 ? " sun" : "")
      + (dow === 6 ? " sat" : "")
      + (isHoliday ? " holiday" : "")
      + (key === today ? " today" : "")
      + (key === selectedValue ? " selected" : "");
    const name = names[key];
    button.setAttribute("aria-label", `${viewM}월 ${d}일${isHoliday ? ` 공휴일${name ? ` ${name}` : ""}` : ""}${key === today ? " 오늘" : ""}`);
    if (key === selectedValue) button.setAttribute("aria-current", "date");
    button.innerHTML = `<span class="cal-day">${d}</span>${isHoliday && name ? `<span class="cal-holiday">${escapeHtml(name)}</span>` : ""}`;
    button.onclick = () => {
      document.getElementById("task-date").value = key;
      renderCalendar();
      loadTasks();
    };
    grid.append(button);
  }
}

const calPrev = document.getElementById("cal-prev");
const calNext = document.getElementById("cal-next");
const calToday = document.getElementById("cal-today");
if (calPrev && calNext && calToday) {
  calPrev.onclick = () => shiftCalendar(-1);
  calNext.onclick = () => shiftCalendar(1);
  calToday.onclick = () => {
    document.getElementById("task-date").value = localDate();
    syncCalendar();
    loadTasks();
  };
  syncCalendar();
}

function appMarkup(key, entry) {
  const details = APP_DETAILS[key];
  const up = Boolean(entry && entry.up);
  const statusClass = up ? "up" : "";
  const statusText = up ? "운영 중" : "연결 대기";
  const action = up ? "열기" : "시작하기";
  return `<div class="app-top"><span class="app-icon">${details.icon}</span><span class="status-badge ${statusClass}">${statusText}</span></div>
    <div class="app-copy"><p class="app-name">${details.name}</p><p class="app-purpose">${details.purpose}</p></div>
    <div class="app-bottom"><span class="app-note">${up ? "백엔드 응답 확인됨" : "서비스를 시작할 수 있습니다"}</span><span class="app-action">${action}</span></div>`;
}

function showAppsError(message) {
  const box = document.getElementById("apps");
  if (!box) return;
  box.innerHTML = `<p class="empty-state"><span class="err">${escapeHtml(message)}</span></p>`;
  document.getElementById("apps-status").textContent = message;
}

function managedAppCard(key, entry) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "app app-card";
  button.innerHTML = appMarkup(key, entry);
  button.setAttribute("aria-label", `${APP_DETAILS[key].name} ${entry.up ? "열기" : "시작하기"}`);
  button.onclick = () => openApp(key, entry, button);
  return button;
}

function linkAppCard(app) {
  const details = APP_DETAILS[app.key] || { name: app.name, purpose: "", icon: "" };
  const anchor = document.createElement("a");
  anchor.className = "app app-card";
  anchor.href = app.url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.innerHTML = `<div class="app-top"><span class="app-icon">${details.icon}</span><span class="status-badge">외부 링크</span></div>
    <div class="app-copy"><p class="app-name">${escapeHtml(details.name)}</p><p class="app-purpose">${escapeHtml(details.purpose)}</p></div>
    <div class="app-bottom"><span class="app-note">${escapeHtml(linkHostname(app.url))}</span><span class="app-action">열기 ↗</span></div>`;
  anchor.setAttribute("aria-label", `${details.name} 새 탭으로 열기`);
  return anchor;
}

async function loadApps() {
  if (appsInFlight || launching.size) return appsInFlight;
  const box = document.getElementById("apps");
  if (!box) return null;
  box.setAttribute("aria-busy", "true");
  document.getElementById("apps-refresh").disabled = true;
  appsInFlight = (async () => { try {
    const [statusResponse, catalogResponse] = await Promise.all([fetch("/api/status"), fetch("/api/apps")]);
    if (!statusResponse.ok) throw new Error("업무 앱 상태를 불러오지 못했습니다.");
    const status = await statusResponse.json();
    if (launching.size) return;
    const catalog = catalogResponse.ok ? await catalogResponse.json() : null;
    const groups = Array.isArray(catalog?.groups) && catalog.groups.length ? catalog.groups : APP_GROUP_FALLBACK;
    const items = Array.isArray(catalog?.apps) && catalog.apps.length ? catalog.apps : [
      { key: "clink", kind: "managed", group: "work" },
      { key: "ipis", kind: "managed", group: "work" },
      { key: "trading", kind: "managed", group: "personal" },
    ];
    box.innerHTML = "";
    for (const group of groups) {
      const cards = items.filter(app => app.group === group.id);
      if (!cards.length) continue;
      const section = document.createElement("section");
      section.className = "app-group";
      section.setAttribute("aria-label", group.title);
      section.innerHTML = `<h3 class="app-group-title">${escapeHtml(group.title)}</h3>`;
      const grid = document.createElement("div");
      grid.className = "app-grid";
      for (const app of cards) {
        if (app.kind === "link" && app.url) grid.append(linkAppCard(app));
        else if (app.kind !== "link" && status[app.key]) grid.append(managedAppCard(app.key, status[app.key]));
      }
      section.append(grid);
      box.append(section);
    }
    document.getElementById("apps-status").textContent = "업무 앱 상태를 업데이트했습니다.";
    document.getElementById("apps-last-check").textContent = `마지막 성공 확인: ${new Intl.DateTimeFormat("ko-KR", { timeStyle: "medium" }).format(new Date())}`;
  } catch (error) {
    showAppsError(error instanceof Error ? error.message : "업무 앱 상태를 불러오지 못했습니다.");
  } finally {
    box.setAttribute("aria-busy", "false");
    document.getElementById("apps-refresh").disabled = launching.size > 0;
    appsInFlight = null;
  } })();
  return appsInFlight;
}

function showAppError(button, message) {
  const badge = button.querySelector(".status-badge");
  const note = button.querySelector(".app-note");
  if (badge) { badge.className = "status-badge error"; badge.textContent = "실행 오류"; }
  if (note) note.innerHTML = `<span class="app-error">${escapeHtml(message)}</span>`;
}

async function openApp(key, entry, button) {
  const url = `http://${host}:${entry.port}`;
  if (entry.up) { window.open(url, "_blank"); return; }
  if (launching.has(key)) return;
  const popup = window.open("about:blank", "_blank");
  if (!popup) { showAppError(button, "팝업이 차단되었습니다. 브라우저에서 팝업을 허용하세요."); return; }
  launching.add(key);
  button.disabled = true;
  const badge = button.querySelector(".status-badge");
  const action = button.querySelector(".app-action");
  const note = button.querySelector(".app-note");
  if (badge) { badge.className = "status-badge pending"; badge.textContent = "연결 확인 중"; }
  if (action) action.textContent = "시작 중…";
  if (note) note.textContent = "서비스를 시작하는 중입니다";
  let opened = false;
  try {
    const launchResponse = await fetch(`/api/launch/${key}`, { method: "POST" });
    if (!launchResponse.ok) throw new Error("서비스를 시작하지 못했습니다. 사용 안내의 로그를 확인하세요.");
    const started = await launchResponse.json();
    for (let waited = 0; waited < 60; waited += 2) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      if (note) note.textContent = `연결 확인 중… ${waited + 2}초`;
      const statusResponse = await fetch("/api/status");
      if (!statusResponse.ok) throw new Error("상태 확인에 실패했습니다. 포털 연결을 확인하세요.");
      const status = await statusResponse.json();
      if (status[key]?.up) {
        popup.location.href = url;
        opened = true;
        return;
      }
    }
    throw new Error(`실행 시간이 초과되었습니다. 로그: ${started.log || "journalctl --user -u 서비스이름.service -n 100 -f"}`);
  } catch (error) {
    if (!popup.closed) popup.close();
    showAppError(button, error instanceof Error ? error.message : "앱 실행에 실패했습니다.");
  } finally {
    button.disabled = false;
    launching.delete(key);
    if (!opened && action) action.textContent = "다시 시도";
    if (opened) loadApps();
  }
}

function setChatStatus(message, kind = "") {
  const node = document.getElementById("chat-status");
  if (!node) return;
  node.textContent = message;
  node.className = `chat-status${kind ? ` ${kind}` : ""}`;
}

function syncChatReset() {
  const button = document.getElementById("chat-reset");
  if (button) button.disabled = chatBusy || chatSaveBusy;
}

function safeStoredChatText(value, maxLength = CHAT_STATE_MAX_MESSAGE_CHARS) {
  return String(value || "")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]{12,}/gi, "[비공개 토큰]")
    .replace(/\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|authorization)\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+/gi, "[비공개 정보]")
    .replace(/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, "[비공개 토큰]")
    .replace(/\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{16,}|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b/g, "[비공개 정보]")
    .replace(/-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----/gi, "[비공개 키]")
    .slice(0, maxLength);
}

function saveChatState() {
  try {
    const input = document.getElementById("chat-input");
    const messages = history.slice(-CHAT_STATE_MAX_MESSAGES).map(item => ({
      role: item.role,
      content: safeStoredChatText(item.content),
    }));
    const state = {
      version: 1,
      messages,
      draft: safeStoredChatText(input?.value || "", CHAT_STATE_MAX_DRAFT_CHARS),
    };
    const serialized = JSON.stringify(state);
    if (serialized.length <= CHAT_STATE_MAX_SERIALIZED_CHARS) sessionStorage.setItem(CHAT_STATE_KEY, serialized);
  } catch (_) {
    // Storage can be disabled or full; chat remains usable for this page.
  }
}

function restoreChatState() {
  try {
    const serialized = sessionStorage.getItem(CHAT_STATE_KEY);
    if (!serialized || serialized.length > CHAT_STATE_MAX_SERIALIZED_CHARS) {
      if (serialized) sessionStorage.removeItem(CHAT_STATE_KEY);
      return;
    }
    const state = JSON.parse(serialized);
    if (!state || state.version !== 1 || !Array.isArray(state.messages)) {
      sessionStorage.removeItem(CHAT_STATE_KEY);
      return;
    }
    for (const item of state.messages.slice(-CHAT_STATE_MAX_MESSAGES)) {
      if (!item || !["user", "assistant"].includes(item.role) || typeof item.content !== "string") continue;
      const content = safeStoredChatText(item.content);
      if (!content) continue;
      history.push({ role: item.role, content });
      addMessage(item.role, content);
    }
    const input = document.getElementById("chat-input");
    if (input && typeof state.draft === "string") input.value = safeStoredChatText(state.draft, CHAT_STATE_MAX_DRAFT_CHARS);
    // Proposal text may remain in the transcript, but its confirmation is deliberately never restored.
    pending = null;
    pendingType = "goal";
    const confirmButton = document.getElementById("confirm");
    if (confirmButton) confirmButton.hidden = true;
  } catch (_) {
    try { sessionStorage.removeItem(CHAT_STATE_KEY); } catch (_) {}
  }
}

function resetChat() {
  if (chatBusy || chatSaveBusy) return false;
  history.length = 0;
  try { sessionStorage.removeItem(CHAT_STATE_KEY); } catch (_) {}
  pending = null;
  pendingType = "goal";
  const log = document.getElementById("log");
  if (log && initialChatEmpty) log.replaceChildren(initialChatEmpty.cloneNode(true));
  const input = document.getElementById("chat-input");
  if (input) { input.value = ""; input.style.height = "auto"; input.disabled = false; }
  const send = document.querySelector(".send");
  if (send) send.disabled = false;
  const confirmButton = document.getElementById("confirm");
  if (confirmButton) { confirmButton.hidden = true; confirmButton.disabled = false; confirmButton.textContent = "이 목표로 확정"; }
  setChatStatus("");
  syncChatReset();
  return true;
}

function addMessage(role, text) {
  document.getElementById("chat-empty")?.remove();
  const node = document.createElement("div");
  node.className = `msg ${role === "user" ? "me" : "ai"}`;
  node.textContent = text;
  const log = document.getElementById("log");
  if (!log) return null;
  log.append(node);
  log.scrollTop = log.scrollHeight;
  return node;
}

function parseProposal(answer) {
  const matches = [...answer.matchAll(/```(json|assistant_action)\s*([\s\S]*?)```/gi)];
  for (const match of matches) {
    try {
      const value = JSON.parse(match[2]);
      if (match[1].toLowerCase() === "assistant_action") {
        if (["create_task", "complete_task", "reschedule_task"].includes(value?.action)) return { kind: "action", value };
      } else if (value && typeof value === "object" && !value.action) return { kind: "goal", value };
    } catch (_) {}
  }
  return null;
}

function actionPreview(action) {
  const expected = action?.expected || {};
  const title = expected.title || action?.title || "(제목 없음)";
  const currentDate = expected.date || "현재 날짜 미정";
  if (action?.action === "create_task") return `할 일 추가: ${title} (${action.date || "날짜 미정"})`;
  if (action?.action === "complete_task") return `할 일 완료 표시: ${title} (현재 ${currentDate})`;
  if (action?.action === "reschedule_task") return `할 일 날짜 변경: ${title} (${currentDate} → ${action.date || "날짜 미정"})`;
  return "확인할 제안이 없습니다.";
}

function offerConfirm(answer) {
  const button = document.getElementById("confirm");
  if (!button) { pending = null; return null; }
  const proposal = parseProposal(answer);
  if (!proposal) { button.hidden = true; pending = null; pendingType = "goal"; return null; }
  pending = proposal.value;
  pendingType = proposal.kind;
  button.textContent = pendingType === "action" ? "이 작업 실행" : "이 목표로 확정";
  button.hidden = false;
  if (pendingType === "action") setChatStatus(`실행 제안: ${actionPreview(pending)}`);
  return proposal;
}

const chatInput = document.getElementById("chat-input");
if (chatInput) {
  restoreChatState();
  chatInput.addEventListener("input", saveChatState);
  // Enter: 보내기 / Ctrl·Shift+Enter: 줄바꿈. 한글 조합 중(isComposing)에는 건드리지 않는다.
  chatInput.addEventListener("keydown", event => {
    if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    document.getElementById("chat-form")?.requestSubmit();
  });
  // 한 줄일 땐 예전 입력칸과 같은 높이, 줄이 늘면 최대 160px까지만 커진다.
  if (chatInput.tagName === "TEXTAREA") {
    const autogrow = () => {
      chatInput.style.height = "auto";
      chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
    };
    chatInput.addEventListener("input", autogrow);
    autogrow();
  }
}

const chatForm = document.getElementById("chat-form");
if (chatForm) {
document.getElementById("chat-reset")?.addEventListener("click", resetChat);
chatForm.onsubmit = async event => {
  event.preventDefault();
  if (chatBusy) return;
  const input = document.getElementById("chat-input");
  const send = document.querySelector(".send");
  const text = input.value.trim();
  const assistantChat = document.getElementById("assistant-dialog")?.open;
  if (!text) return;
  chatBusy = true;
  syncChatReset();
  if (send) send.disabled = true;
  input.disabled = true;
  document.getElementById("confirm").hidden = true;
  pending = null;
  setChatStatus("답변을 기다리는 중…");
  document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "organizing" } }));
  input.value = "";
  input.style.height = "auto";
  saveChatState();
  addMessage("user", text);
  const requestHistory = [...history, { role: "user", content: text }];
  const node = addMessage("assistant", "응답을 작성하는 중…");
  let answer = "";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: requestHistory }),
    });
    if (!response.ok || !response.body) throw new Error("응답을 받지 못했습니다. 잠시 후 다시 시도하세요.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const consume = raw => {
      const data = raw.split(/\r?\n/).filter(line => line.startsWith("data:")).map(line => line.slice(5).trim()).join("\n");
      if (!data || data === "[DONE]") return;
      let parsed;
      try { parsed = JSON.parse(data); } catch { return; }
      if (parsed.error) throw new Error(parsed.error);
      answer += parsed.choices?.[0]?.delta?.content || "";
      node.textContent = answer || "응답을 작성하는 중…";
      document.getElementById("log").scrollTop = 1e9;
    };
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() || "";
      for (const eventText of events) consume(eventText);
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!answer) throw new Error("응답 내용이 비어 있습니다. 다시 시도하세요.");
    history.push({ role: "user", content: text }, { role: "assistant", content: answer });
    if (history.length > CHAT_STATE_MAX_MESSAGES) history.splice(0, history.length - CHAT_STATE_MAX_MESSAGES);
    saveChatState();
    node.textContent = answer;
    const proposal = offerConfirm(answer);
    if (!proposal || proposal.kind !== "action") setChatStatus("답변을 받았습니다.", "success");
    document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "finished" } }));
  } catch (error) {
    node.className = "msg ai err";
    node.textContent = error instanceof Error ? error.message : "업무 정리 중 오류가 발생했습니다.";
    setChatStatus("업무 정리를 완료하지 못했습니다.", "error");
    document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "error" } }));
  } finally {
    chatBusy = false;
    syncChatReset();
    if (send) send.disabled = false;
    input.disabled = false;
    if (!assistantChat || document.getElementById("assistant-dialog")?.open) input.focus();
  }
};
}

const confirmButton = document.getElementById("confirm");
if (confirmButton) {
confirmButton.onclick = async () => {
  if (!pending) return;
  chatSaveBusy = true;
  syncChatReset();
  const button = document.getElementById("confirm");
  button.disabled = true;
  const actionMode = pendingType === "action";
  button.textContent = actionMode ? "실행 중…" : "저장 중…";
  setChatStatus(actionMode ? "제안한 작업을 확인하는 중…" : "목표를 저장하는 중…");
  try {
    const response = await fetch(actionMode ? "/api/assistant/actions" : "/api/goals", {
      method: actionMode ? "POST" : "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pending),
    });
    if (!response.ok) throw new Error(actionMode ? "작업을 실행하지 못했습니다. 대상이 바뀌었을 수 있습니다." : "저장 실패 — 목표 형식을 확인하세요.");
    button.hidden = true;
    pending = null;
    pendingType = "goal";
    button.textContent = "이 목표로 확정";
    setChatStatus(actionMode ? "제안한 작업을 실행했습니다." : "목표를 저장했습니다.", "success");
    if (actionMode) document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "assistantAction" } }));
    else { await loadGoals(); document.dispatchEvent(new CustomEvent("assistant:notice", { detail: { type: "goalsSaved" } })); }
  } catch (error) {
    setChatStatus(error instanceof Error ? error.message : "목표를 저장하지 못했습니다.", "error");
  } finally {
    chatSaveBusy = false;
    syncChatReset();
    button.disabled = false;
    button.textContent = actionMode ? "이 작업 실행" : "이 목표로 확정";
  }
};
}

setToday();
if (document.getElementById("week")) {
  wireGoalAddForms();
  loadGoalsPage();
}
if (document.getElementById("task-date")) {
  loadGoals().then(() => { fillTaskGoalPicker(); loadTasks(); });
} else if (document.getElementById("task-list")) {
  loadGoals();
}
const appsRefresh = document.getElementById("apps-refresh");
if (document.getElementById("apps")) {
  loadApps();
  if (appsRefresh) appsRefresh.onclick = loadApps;
  setInterval(loadApps, 15000);
}

async function loadOverview() {
  const box = document.getElementById("overview-status");
  if (!box) return;
  try {
    const [statusResponse, briefingResponse] = await Promise.all([fetch("/api/status"), fetch("/api/assistant/briefing")]);
    if (!statusResponse.ok) throw new Error("상태를 불러오지 못했습니다.");
    const status = await statusResponse.json();
    const upCount = Object.values(status).filter(entry => entry && entry.up).length;
    let taskLine = "오늘 할 일을 불러오지 못했습니다.";
    let goalLine = "";
    if (briefingResponse.ok) {
      const briefing = await briefingResponse.json();
      const today = briefing.pending.count;
      const overdue = briefing.overdue.count;
      taskLine = overdue ? `오늘 ${today}개 · 기한 지남 ${overdue}개` : `오늘 ${today}개`;
      const goals = briefing.goals.week.items.length + briefing.goals.day.items.length;
      goalLine = goals ? `진행 중 목표 ${goals}개` : "정해진 목표가 없습니다";
    }
    box.innerHTML = `
      <a class="overview-card" href="/apps"><span class="overview-num">${upCount} / 3</span><span class="overview-label">실행 중 앱</span></a>
      <a class="overview-card" href="/tasks"><span class="overview-num">${escapeHtml(taskLine)}</span><span class="overview-label">할 일 현황</span></a>
      <a class="overview-card" href="/goals"><span class="overview-num">${escapeHtml(goalLine)}</span><span class="overview-label">목표 현황</span></a>
      <a class="overview-card" href="/organize"><span class="overview-num">→</span><span class="overview-label">TODO-LIST로 가기</span></a>`;
  } catch (error) {
    box.innerHTML = `<p class="empty-state">현황을 불러오지 못했습니다. <button id="overview-retry" class="quiet-button" type="button">다시 시도</button></p>`;
    document.getElementById("overview-retry").onclick = loadOverview;
  }
}
loadOverview();

const DIGEST_GROUPS = [
  ["completed", "완료한 일"],
  ["in_progress", "진행 중"],
  ["cautions", "확인할 점"],
  ["tomorrow", "내일 이어갈 일"],
];

function digestTextNode(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

function renderWorkDigest(digest) {
  const content = document.getElementById("work-digest-content");
  const status = document.getElementById("work-digest-status");
  const generated = document.getElementById("work-digest-generated");
  if (!content || !status || !generated) return;
  content.replaceChildren();
  if (!digest) {
    content.hidden = true;
    generated.textContent = "아직 정리하지 않았습니다.";
    status.className = "digest-status";
    status.textContent = "오늘의 회고가 아직 없습니다. 지금 정리해 보세요.";
    return;
  }
  content.hidden = false;
  const generatedAt = digest.generated_at ? new Date(digest.generated_at) : null;
  generated.textContent = generatedAt && !Number.isNaN(generatedAt.valueOf())
    ? `${digest.mode === "fallback" ? "로컬 백업 요약 · " : "생성됨 · "}${generatedAt.toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" })}`
    : digest.mode === "fallback" ? "로컬 백업 요약" : "생성됨";
  status.className = `digest-status${digest.mode === "fallback" ? " fallback" : ""}`;
  status.textContent = digest.mode === "fallback" ? "모델 연결 없이 확인 가능한 기록만 간단히 정리했습니다." : "오늘의 로컬 업무 기록을 정리했습니다.";
  const counts = document.createElement("div");
  counts.className = "digest-source-counts";
  Object.entries(digest.source_counts || {}).forEach(([source, count]) => counts.append(digestTextNode("span", "digest-source-badge", `${source} ${count}`)));
  if (counts.children.length) content.append(counts);
  const groups = document.createElement("div");
  groups.className = "digest-groups";
  DIGEST_GROUPS.forEach(([key, label]) => {
    const group = document.createElement("section");
    group.className = "digest-group";
    group.append(digestTextNode("h3", "digest-group-title", label));
    const values = Array.isArray(digest[key]) ? digest[key] : [];
    const list = document.createElement("ul");
    list.className = "digest-list";
    values.forEach(value => {
      if (typeof value === "string" && value.trim()) list.append(digestTextNode("li", "digest-item", value));
    });
    if (!list.children.length) list.append(digestTextNode("li", "digest-empty", "기록이 없습니다."));
    group.append(list);
    groups.append(group);
  });
  content.append(groups);
}

async function loadWorkDigest(refresh = false) {
  const button = document.getElementById("work-digest-refresh");
  const status = document.getElementById("work-digest-status");
  if (!status) return;
  if (button) button.disabled = true;
  status.className = "digest-status";
  status.textContent = refresh ? "오늘의 기록을 정리하는 중…" : "오늘의 회고를 불러오는 중…";
  try {
    const response = await fetch(refresh ? "/api/work-digest/refresh" : "/api/work-digest", refresh ? { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" } : undefined);
    if (response.status === 404) { renderWorkDigest(null); return; }
    if (!response.ok) throw new Error("업무 회고를 불러오지 못했습니다.");
    renderWorkDigest(await response.json());
  } catch (_) {
    const content = document.getElementById("work-digest-content");
    if (content) { content.replaceChildren(); content.hidden = true; }
    status.className = "digest-status error";
    status.textContent = "업무 회고를 불러오지 못했습니다. 잠시 후 다시 시도하세요.";
  } finally {
    if (button) button.disabled = false;
  }
}

const digestRefresh = document.getElementById("work-digest-refresh");
if (digestRefresh) digestRefresh.addEventListener("click", () => loadWorkDigest(true));
if (document.getElementById("work-digest-content")) loadWorkDigest();
