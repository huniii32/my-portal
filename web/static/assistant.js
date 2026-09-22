import { PlushMascot } from "/assets/mascot.js";

const overlay = document.getElementById("secretary-overlay");
const roamer = document.getElementById("secretary-roamer");
const mascotButton = document.getElementById("secretary-mascot");
const bubble = document.getElementById("secretary-bubble");
const bubbleText = document.getElementById("secretary-bubble-text");
const dialog = document.getElementById("assistant-dialog");
const summary = document.getElementById("assistant-summary-text");
const summaryList = document.getElementById("assistant-summary-list");
const chat = document.getElementById("organize");
const chatHome = document.getElementById("assistant-chat-home");
const chatSlot = document.getElementById("assistant-chat-slot");
const opener = document.getElementById("assistant-opener");
const closeButton = document.getElementById("assistant-close");
const pauseButton = document.getElementById("assistant-pause");
const hideButton = document.getElementById("assistant-hide");
const dockChat = document.getElementById("secretary-chat");
const dockPause = document.getElementById("secretary-pause");
const dockHide = document.getElementById("secretary-hide");
const sideChat = document.body.classList.contains("overview-page") && window.matchMedia("(min-width: 901px)").matches;
const mascot = new PlushMascot(mascotButton);
function storageGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (_) {} }
function storageDel(key) { try { localStorage.removeItem(key); } catch (_) {} }
let returnFocus = null, panelOpen = false, hovering = false, paused = storageGet("secretary-paused") === "true";
let hidden = storageGet("secretary-hidden") === "true", lastNotice = "", noticeTimer = 0, briefing = null, briefingKey = "";
let briefingEvents = null, briefingFallbackTimer = 0;
let assistantPreferences = null;
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const walk = { x: 0, y: 0, targetX: 0, targetY: 0, heading: 0, phase: 0, last: 0, raf: 0, ready: false };

function setHidden(value) { hidden = value; storageSet("secretary-hidden", String(value)); overlay.hidden = value; opener.textContent = value ? "내 비서 다시 보기" : "내 비서"; syncMotion(); if (value && overlay.contains(document.activeElement)) opener.focus(); }
function freeze() { return dragging || hidden || paused || panelOpen || hovering || !bubble.hidden || document.hidden || reducedMotion.matches || Boolean(document.querySelector("dialog[open]")) || Boolean(document.activeElement?.matches("input, textarea, select, [contenteditable='true']")); }
function dimensions() {
  const mobile = innerWidth <= 600, width = mobile ? 190 : 220, height = mobile ? 250 : 290, bubbleWidth = Math.min(mobile ? 236 : 266, innerWidth - (mobile ? 128 : 164)), bubbleRight = mobile ? 83 : 104;
  const reserved = sideChat ? 380 : 0;
  const maxX = Math.max(10, innerWidth - width - 10 - reserved); return { width, height, minX: Math.max(10, Math.min(maxX, bubbleWidth + bubbleRight - width + 4)), maxX, minY: Math.max(70, innerHeight - height - 74), maxY: Math.max(70, innerHeight - height - 14) };
}
function point(x, y) { const size = dimensions(); return { x: Math.max(size.minX, Math.min(size.maxX, x)), y: Math.max(size.minY, Math.min(size.maxY, y)) }; }
function dragPoint(x, y) {
  const size = dimensions();
  return {
    x: Math.max(10, Math.min(Math.max(10, innerWidth - size.width - 10), x)),
    y: Math.max(10, Math.min(Math.max(10, innerHeight - size.height - 10), y)),
  };
 }
function writePosition() { roamer.style.transform = `translate3d(${Math.round(walk.x)}px,${Math.round(walk.y)}px,0)`; }
function controlRects() { return [...document.querySelectorAll("button, input, textarea, select, a[href], [contenteditable='true']")].filter(node => !roamer.contains(node) && !node.hidden && !node.closest("[hidden]")).map(node => node.getBoundingClientRect()).filter(rect => rect.width && rect.height); }
function mascotBox(x, y) {
  const { width, height } = dimensions();
  return { left: x + 28, right: x + width - 28, top: y + 60, bottom: y + height - 8 };
}
function overlapsControl(x, y, controls) {
  const box = mascotBox(x, y);
  return controls.some(rect => box.left < rect.right && box.right > rect.left && box.top < rect.bottom && box.bottom > rect.top);
}
function chooseTarget() {
  const size = dimensions();
  return point(size.maxX, size.maxY);
}
function stopWalk() { if (walk.raf) cancelAnimationFrame(walk.raf); walk.raf = 0; walk.last = 0; }
function frame(now) {
  walk.raf = 0; if (freeze()) return syncMotion();
  const elapsed = Math.min(.05, Math.max(.001, (now - walk.last) / 1000)); walk.last = now;
  const dx = walk.targetX - walk.x, dy = walk.targetY - walk.y, distance = Math.hypot(dx, dy), speed = 42, step = Math.min(distance, speed * elapsed);
  if (distance <= .5) { walk.phase = Math.round(walk.phase / Math.PI) * Math.PI; walk.heading = 0; mascot.setLocomotion({ heading: 0, gait: walk.phase }); return; }
  walk.x += dx / distance * step; walk.y += dy / distance * step; writePosition(); walk.phase += step * Math.PI * 2 / 52;
  mascot.setLocomotion({ walking: true, heading: walk.heading, gait: walk.phase, speed }); walk.raf = requestAnimationFrame(frame);
}
function move(force = false) {
  if (!walk.ready) { const size = dimensions(); walk.x = size.maxX; walk.y = size.maxY; const start = chooseTarget(); walk.x = start.x; walk.y = start.y; walk.ready = true; writePosition(); }
  if (hidden || freeze()) return; const target = chooseTarget(); walk.targetX = target.x; walk.targetY = target.y;
  if (!walk.raf) { walk.last = performance.now(); walk.raf = requestAnimationFrame(frame); }
}
function syncMotion(force = false) {
  const stopped = freeze(); mascot.setReduced(reducedMotion.matches); mascot.setPaused(stopped);
  if (stopped) { stopWalk(); return; }
  if (force || !walk.raf) move(true);
}
function setPause(value) { paused = value; storageSet("secretary-paused", String(value)); pauseButton.textContent = value ? "움직이기" : "잠시 멈춤"; dockPause.setAttribute("aria-pressed", String(value)); dockPause.title = value ? "이동 시작" : "이동 정지"; dockPause.innerHTML = `<span class="mascot-control-icon" aria-hidden="true">${value ? "▶" : "■"}</span><span>${value ? "이동 시작" : "이동 정지"}</span>`; syncMotion(); }
function say(text, priority = false) { if (hidden || (!priority && text === lastNotice)) return; lastNotice = text; bubbleText.textContent = text; bubble.hidden = false; syncMotion(); clearTimeout(noticeTimer); const holdMs = Math.min(30000, 9000 + text.length * 60); noticeTimer = setTimeout(() => { if (!panelOpen) { bubble.hidden = true; syncMotion(true); } }, holdMs); }
function briefingText(data) { const parts = []; if (data.overdue.count) parts.push(`미완료 지난 업무 ${data.overdue.count}개`); if (data.pending.count) parts.push(`오늘 할 일 ${data.pending.count}개`); const goals = data.goals.week.items.length + data.goals.day.items.length; if (goals) parts.push(`목표 ${goals}개`); const trading = data.trading?.alert; if (trading) parts.push(`주식 알림: ${trading.message || trading.title}`); if (!parts.length) return "오늘 미완료 할 일이 없어요."; const first = data.overdue.items[0] || data.pending.items[0]; const title = first?.title ? `${first.title.slice(0, 45)}${first.title.length > 45 ? "…" : ""}` : ""; return `${parts.join(", ")}예요.${title ? ` 먼저 확인할 일: ${title}` : ""}`; }
function panelSummary(data) { if (!data) return "저장된 업무를 불러오는 중이에요."; const goals = data.goals.week.items.length + data.goals.day.items.length; return `${briefingText(data)}${goals ? ` 현재 목표 ${goals}개를 확인했습니다.` : " 목표는 아직 정해지지 않았어요."}`; }
function renderItems(data) { summaryList.replaceChildren(); if (!data) return; const lines = [...data.overdue.items.map(item => `기한 지남 · ${item.title} (${item.date})`), ...data.pending.items.map(item => `오늘 · ${item.title}`), ...data.goals.week.items.map(item => `이번 주 ${item.goal}: ${item.current}/${item.target}${item.unit}`), ...data.goals.day.items.map(item => `오늘 목표 ${item.goal}: ${item.current}/${item.target}${item.unit}`)]; lines.slice(0, 8).forEach(line => { const node = document.createElement("div"); node.textContent = line; summaryList.append(node); }); }
function proactiveText(data) { const notice = data?.notifications?.proactive?.at(-1); return notice?.message || briefingText(data); }
function proactiveIds(data) { const values = data?.notifications?.proactive; return new Set((Array.isArray(values) ? values : []).map(item => item?.id).filter(Boolean)); }
function applyBriefing(next, announce = false, silenceChange = false) {
  const previous = briefing;
  const previousProactive = proactiveIds(previous);
  briefing = next;
  summary.textContent = panelSummary(briefing);
  renderItems(briefing);
  const nextProactive = proactiveIds(briefing);
  const nextKey = JSON.stringify([briefing.source_date, briefing.pending, briefing.overdue, briefing.goals, briefing.trading?.alert]);
  const changed = Boolean(briefingKey) && briefingKey !== nextKey;
  const newProactive = Boolean(briefingKey) && [...nextProactive].some(id => !previousProactive.has(id));
  briefingKey = nextKey;
  if (announce || (!silenceChange && (changed || newProactive))) {
    const message = announce || newProactive ? proactiveText(briefing) : briefingText(briefing);
    say(`${announce ? "곰비예요. " : "알림: "}${message}`, true);
  }
  return changed || newProactive;
}
async function refreshBriefing(announce = false, silenceChange = false) { if (document.hidden) return; try { const response = await fetch("/api/assistant/briefing"); if (!response.ok) throw new Error("업무 저장소를 읽지 못했습니다."); applyBriefing(await response.json(), announce, silenceChange); return briefing; } catch (_) { summary.textContent = "업무 비서가 저장소를 읽지 못했습니다. 원본 데이터는 바꾸지 않았어요."; renderItems(null); if (announce) say("업무 저장소를 읽지 못했어요. 잠시 후 다시 확인할게요.", true); return null; } }
function stopBriefingFallback() { if (briefingFallbackTimer) { clearInterval(briefingFallbackTimer); briefingFallbackTimer = 0; } }
function startBriefingFallback() { if (briefingFallbackTimer) return; if (!document.hidden) refreshBriefing(); briefingFallbackTimer = setInterval(() => { if (!document.hidden && !panelOpen) refreshBriefing(); }, 60000); }
function connectBriefingEvents() { if (!("EventSource" in window)) { startBriefingFallback(); return; } briefingEvents = new EventSource("/api/assistant/events"); briefingEvents.onopen = () => stopBriefingFallback(); briefingEvents.addEventListener("briefing", event => { try { applyBriefing(JSON.parse(event.data)); } catch (_) {} }); briefingEvents.onerror = () => startBriefingFallback(); }
function ensureAssistantExtras() {
  const summarySection = document.querySelector(".assistant-summary");
  if (!summarySection) return;
  if (!document.getElementById("assistant-preferences")) {
    const details = document.createElement("details");
    details.id = "assistant-preferences";
    details.className = "assistant-preferences";
    details.innerHTML = `<summary><span class="assistant-preferences-title">능동 알림 설정</span><span class="assistant-preferences-help">업무 시간에 곰비가 먼저 알려드려요.</span></summary><form class="assistant-preferences-form"><label class="assistant-preferences-enabled"><input id="assistant-proactive-enabled" type="checkbox"><span><strong>능동 알림 받기</strong><small>업무 요약과 알림을 정해진 시간에 확인해요.</small></span></label><fieldset class="assistant-preferences-group"><legend>업무 알림 시간</legend><div class="assistant-schedule-grid"><label class="assistant-time-field" for="assistant-morning"><span>아침 계획</span><input id="assistant-morning" type="time" required></label><label class="assistant-time-field" for="assistant-midday"><span>점심 점검</span><input id="assistant-midday" type="time" required></label><label class="assistant-time-field" for="assistant-wrap-up"><span>업무 마무리</span><input id="assistant-wrap-up" type="time" required></label></div></fieldset><fieldset class="assistant-preferences-group assistant-quiet-group"><legend>조용한 시간</legend><div class="assistant-quiet-grid"><label class="assistant-time-field" for="assistant-quiet-start"><span>시작</span><input id="assistant-quiet-start" type="time" required></label><label class="assistant-time-field" for="assistant-quiet-end"><span>종료</span><input id="assistant-quiet-end" type="time" required></label></div></fieldset><div class="assistant-preferences-footer"><span id="assistant-preferences-status" class="chat-status" aria-live="polite"></span><button class="assistant-preferences-save" type="submit">설정 저장</button></div></form>`;
    summarySection.append(details);
    details.querySelector("form").onsubmit = saveAssistantPreferences;
  }
  if (!document.getElementById("assistant-activity")) {
    const activity = document.createElement("section");
    activity.id = "assistant-activity";
    activity.innerHTML = '<div class="assistant-activity-heading"><div><h3>최근 업무 제안 실행</h3><p>곰비의 제안 중 직접 확인한 기록이에요.</p></div></div><div id="assistant-activity-list" class="assistant-activity-list" aria-live="polite">불러오는 중…</div>';
    summarySection.append(activity);
  }
  loadAssistantPreferences();
  loadAssistantActivity();
}
async function loadAssistantPreferences() {
  try {
    const response = await fetch("/api/assistant/preferences");
    if (!response.ok) throw new Error("설정을 불러오지 못했습니다.");
    assistantPreferences = await response.json();
    for (const key of ["morning", "midday", "wrap_up", "quiet_start", "quiet_end"]) document.getElementById(`assistant-${key.replaceAll("_", "-")}`).value = assistantPreferences[key];
    document.getElementById("assistant-proactive-enabled").checked = assistantPreferences.proactive_enabled !== false;
  } catch (_) { const status = document.getElementById("assistant-preferences-status"); if (status) status.textContent = "설정을 불러오지 못했습니다."; }
}
async function saveAssistantPreferences(event) {
  event.preventDefault();
  const payload = { proactive_enabled: document.getElementById("assistant-proactive-enabled").checked, morning: document.getElementById("assistant-morning").value, midday: document.getElementById("assistant-midday").value, wrap_up: document.getElementById("assistant-wrap-up").value, quiet_start: document.getElementById("assistant-quiet-start").value, quiet_end: document.getElementById("assistant-quiet-end").value };
  const status = document.getElementById("assistant-preferences-status");
  try { const response = await fetch("/api/assistant/preferences", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); if (!response.ok) throw new Error("설정을 저장하지 못했습니다."); assistantPreferences = await response.json(); if (status) { status.textContent = "알림 설정을 저장했습니다."; status.className = "chat-status success"; } } catch (_) { if (status) { status.textContent = "알림 설정을 저장하지 못했습니다."; status.className = "chat-status error"; } }
}
async function loadAssistantActivity() {
  const list = document.getElementById("assistant-activity-list");
  if (!list) return;
  try { const response = await fetch("/api/assistant/activity"); if (!response.ok) throw new Error(); const entries = await response.json(); const actionLabels = { create_task: "할 일 추가", complete_task: "완료 처리", reschedule_task: "날짜 변경" }; list.replaceChildren(); (Array.isArray(entries) ? entries : []).slice(-5).reverse().forEach(entry => { const row = document.createElement("div"); row.className = "assistant-activity-row"; row.textContent = `${entry.status === "success" ? "완료" : "실패"} · ${actionLabels[entry.action] || "업무 처리"}${entry.title ? ` · ${entry.title}` : ""}${entry.date ? ` (${entry.date})` : ""}`; list.append(row); }); if (!list.children.length) list.textContent = "최근 실행 기록이 없습니다."; } catch (_) { list.textContent = "실행 기록을 불러오지 못했습니다."; }
}
function openPanel(trigger = opener) { if (sideChat) { setHidden(false); bubble.hidden = true; document.getElementById("chat-input")?.focus(); return; } if (document.querySelector("dialog[open]") && !dialog.open) return; returnFocus = trigger; setHidden(false); panelOpen = true; bubble.hidden = true; syncMotion(); if (chat && chatHome) { chat.hidden = false; chatHome.before(chat); chatSlot.append(chat); chat.querySelector("#organize-title").textContent = "대화하기"; } else { chatSlot.innerHTML = '<p class="empty-state">업무 정리는 <a href="/organize">TODO-LIST 페이지</a>에서 이어가세요.</p>'; } dialog.showModal(); refreshBriefing(); requestAnimationFrame(() => { if (dialog.open) document.getElementById("chat-input")?.focus(); }); }
function closePanel() { if (!dialog.open) return; dialog.close(); }
function restorePanel() { if (sideChat) return; panelOpen = false; if (chat && chatHome) { chatHome.after(chat); chat.hidden = true; chat.querySelector("#organize-title").textContent = "TODO-LIST"; } else { chatSlot.innerHTML = ""; } syncMotion(); (returnFocus && !overlay.hidden ? returnFocus : opener).focus(); returnFocus = null; }
function eventNotice(event) { const detail = event.detail || {}; const messages = { taskAdded: "할 일을 추가했어요. 잊지 않게 챙길게요.", taskDone: "완료 표시를 확인했어요. 수고했어요!", taskReopened: "할 일을 다시 진행 중으로 바꿨어요.", taskDeleted: "할 일을 목록에서 뺐어요.", goalsSaved: "목표를 저장했어요. 진행을 같이 볼게요.", assistantAction: "제안한 작업을 실행했어요.", organizing: "업무를 정리하는 중이에요.", waiting: "곰비가 답변을 기다리고 있어요.", finished: "업무 정리 답변을 받았어요.", error: "업무 정리를 마치지 못했어요. 다시 시도해 주세요." }; if (messages[detail.type]) say(messages[detail.type], true); refreshBriefing(false, true); if (detail.type === "assistantAction") loadAssistantActivity(); }

let dragging = false, pointerDown = false, suppressClick = false, dragStartX = 0, dragStartY = 0, dragOrigX = 0, dragOrigY = 0;
mascotButton.addEventListener("click", event => { if (suppressClick) { suppressClick = false; event.stopImmediatePropagation(); event.preventDefault(); } }, true);
mascotButton.addEventListener("pointerdown", event => {
  if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
  pointerDown = true; dragging = false;
  dragStartX = event.clientX; dragStartY = event.clientY; dragOrigX = walk.x; dragOrigY = walk.y;
  try { mascotButton.setPointerCapture(event.pointerId); } catch (_) {}
});
mascotButton.addEventListener("pointermove", event => {
  if (!pointerDown || !event.isPrimary) return;
  const dx = event.clientX - dragStartX, dy = event.clientY - dragStartY;
  if (!dragging && Math.hypot(dx, dy) < 5) return;
  if (!dragging) { dragging = true; stopWalk(); mascot.setLocomotion({}); mascotButton.classList.add("dragging"); }
  const next = dragPoint(dragOrigX + dx, dragOrigY + dy);
  walk.x = next.x; walk.y = next.y; walk.targetX = next.x; walk.targetY = next.y; walk.heading = 0;
  writePosition();
});
function endDrag(moved) {
  if (!pointerDown && !dragging) return;
  pointerDown = false; mascotButton.classList.remove("dragging");
  if (dragging) { dragging = false; if (moved) suppressClick = true; syncMotion(); }
}
mascotButton.addEventListener("pointerup", () => endDrag(true));
mascotButton.addEventListener("pointercancel", () => endDrag(false));
mascotButton.addEventListener("dragstart", event => event.preventDefault());
if (new URLSearchParams(location.search).get("secretary") === "show") { storageDel("secretary-hidden"); hidden = false; }
mascot.start(); setPause(paused); setHidden(hidden); syncMotion(); move(true);
opener.addEventListener("click", () => openPanel(opener)); mascotButton.addEventListener("click", () => openPanel(mascotButton));
dockChat.addEventListener("click", () => openPanel(dockChat)); dockPause.addEventListener("click", () => setPause(!paused)); dockHide.addEventListener("click", () => setHidden(true));
document.getElementById("secretary-bubble-dismiss").addEventListener("click", () => { bubble.hidden = true; syncMotion(true); });
closeButton.addEventListener("click", closePanel); dialog.addEventListener("close", restorePanel); pauseButton.addEventListener("click", () => setPause(!paused));
hideButton.addEventListener("click", () => { closePanel(); setHidden(true); });
document.getElementById("assistant-today").addEventListener("click", () => refreshBriefing(true));
document.getElementById("assistant-organize").addEventListener("click", () => { const input = document.getElementById("chat-input"); const form = document.getElementById("chat-form"); if (input && form) { input.value = "오늘 업무를 정리해줘."; form.requestSubmit(); } else { closePanel(); location.href = "/organize"; } });
document.getElementById("assistant-goals").addEventListener("click", () => { closePanel(); document.getElementById("goals")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); });
roamer.addEventListener("mouseenter", () => { hovering = true; syncMotion(); }); roamer.addEventListener("mouseleave", () => { hovering = false; syncMotion(); });
roamer.addEventListener("focusin", () => { hovering = true; syncMotion(); }); roamer.addEventListener("focusout", () => { hovering = false; syncMotion(); });
document.addEventListener("focusin", () => syncMotion()); document.addEventListener("visibilitychange", () => syncMotion());
reducedMotion.addEventListener("change", () => { if (reducedMotion.matches) mascot.setLocomotion(); syncMotion(true); });
window.addEventListener("resize", () => { if (!walk.ready) return; const current = point(walk.x, walk.y), target = point(walk.targetX, walk.targetY); walk.x = current.x; walk.y = current.y; walk.targetX = target.x; walk.targetY = target.y; writePosition(); if (!freeze() && !walk.raf) move(true); }); document.addEventListener("assistant:notice", eventNotice);
setInterval(() => { if (!freeze() && !walk.raf) move(); }, 5200);
connectBriefingEvents();
ensureAssistantExtras();
