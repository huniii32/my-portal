const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const ROOT = __dirname + "/..";
const STATIC = ROOT + "/web/static";
const TEMPLATES = ROOT + "/web/templates";
function readFirst(paths) {
  for (const candidate of paths) {
    try {
      return fs.readFileSync(candidate, "utf8");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  throw new Error("missing file: " + paths.join(" / "));
}
const staticFile = (name) => readFirst([`${STATIC}/${name}`, `${ROOT}/${name}`]);
const templateFile = (name) => readFirst([`${TEMPLATES}/${name}`, `${ROOT}/${name}`]);
const assistantSource = staticFile("assistant.js");
const assistantCss = staticFile("assistant.css");
const portalSource = staticFile("portal.js");
assert.match(assistantSource, /능동 알림 설정/);
assert.match(assistantSource, /업무 알림 시간/);
assert.match(assistantSource, /조용한 시간/);
assert.match(assistantSource, /assistant-activity-list/);
assert.match(assistantSource, /create_task: "할 일 추가"/);
assert.match(assistantSource, /complete_task: "완료 처리"/);
assert.match(assistantSource, /reschedule_task: "날짜 변경"/);
assert.equal(assistantSource.includes("proactive 알림 사용"), false);
assert.match(assistantCss, /assistant-schedule-grid\{grid-template-columns:repeat\(3/);
assert.match(assistantCss, /assistant-quiet-grid\{grid-template-columns:repeat\(2/);
assert.match(assistantCss, /@media \(max-width:600px\)/);
assert.match(assistantCss, /assistant-preferences>summary::before/);
assert.match(assistantCss, /assistant-preferences\[open\]>summary::before/);
assert.match(portalSource, /function renderWorkDigest/);
assert.match(portalSource, /digestTextNode/);
const digestRenderBlock = portalSource.slice(portalSource.indexOf("function renderWorkDigest"), portalSource.indexOf("async function loadWorkDigest"));
assert.equal(digestRenderBlock.includes("innerHTML"), false, "digest bullet rendering must use textContent/DOM nodes");

class Element {
  constructor(id = "") {
    this.id = id;
    this.children = [];
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.textContent = "";
    this.className = "";
    this.innerHTML = "";
    this.style = {};
  }

  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatchEvent(event) { for (const listener of this.listeners[event.type] || []) listener.call(this, event); }
  click() { if (!this.disabled) this.dispatchEvent({ type: "click", currentTarget: this, target: this }); }
  append(...nodes) { this.children.push(...nodes); nodes.forEach(node => { node.parentNode = this; }); }
  replaceChildren(...nodes) { this.children = nodes; nodes.forEach(node => { node.parentNode = this; }); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this); }
  cloneNode() {
    const copy = new Element(this.id);
    copy.hidden = this.hidden; copy.disabled = this.disabled; copy.value = this.value;
    copy.textContent = this.textContent; copy.className = this.className; copy.innerHTML = this.innerHTML;
    copy.children = this.children.map(child => child.cloneNode(true));
    return copy;
  }
  focus() {}
}

const elements = Object.fromEntries(["today", "chat-empty", "chat-reset", "chat-form", "log", "chat-input", "confirm", "chat-status"].map(id => [id, new Element(id)]));
elements["chat-empty"].className = "chat-empty";
elements["chat-form"].onsubmit = null;
const send = new Element("send");
const document = {
  body: { style: {} },
  hidden: false,
  getElementById: id => elements[id] || null,
  querySelector: selector => selector === ".send" ? send : null,
  querySelectorAll: () => [],
  createElement: tag => new Element(tag),
  addEventListener() {},
  dispatchEvent() {},
};

const encoder = new TextEncoder();
const chatCalls = [];
const goalCalls = [];
const actionCalls = [];
let nextChatResponse;
let releaseChat;
let releaseSave;

function responseFor(answer) {
  let first = true;
  return {
    ok: true,
    body: { getReader: () => ({ read: async () => {
      if (first) {
        first = false;
        return { value: encoder.encode(`data: ${JSON.stringify({ choices: [{ delta: { content: answer } }] })}\n\n`), done: false };
      }
      return { value: encoder.encode("data: [DONE]\n\n"), done: true };
    } }) },
  };
}

const context = {
  console,
  document,
  location: { hostname: "127.0.0.1" },
  window: { open() {} },
  TextDecoder,
  TextEncoder,
  Uint8Array,
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
  fetch: async (url, options = {}) => {
    if (url === "/api/chat") {
      chatCalls.push(JSON.parse(options.body));
      if (nextChatResponse) return nextChatResponse();
      return responseFor("응답");
    }
    if (url === "/api/goals" && options.method === "PUT") {
      goalCalls.push(JSON.parse(options.body));
      return new Promise(resolve => { releaseSave = () => resolve({ ok: true, json: async () => ({}) }); });
    }
    if (url === "/api/assistant/actions" && options.method === "POST") {
      actionCalls.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({}) };
    }
    return { ok: true, json: async () => ({}) };
  },
  setInterval() {},
  setTimeout,
  clearTimeout,
  Intl,
  Date,
  Promise,
  Math,
  JSON,
};

vm.runInNewContext(staticFile("portal.js"), context, { filename: "portal.js" });

function makeSessionStorage(initial = null) {
  const values = new Map();
  if (initial !== null) values.set("suhun.portal.chat.v1", initial);
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    dump: key => values.get(key),
  };
}

function makeChatPage(storage, answer) {
  const pageElements = Object.fromEntries(["today", "chat-empty", "chat-reset", "chat-form", "log", "chat-input", "confirm", "chat-status"].map(id => [id, new Element(id)]));
  pageElements["chat-empty"].className = "chat-empty";
  pageElements["log"].append(pageElements["chat-empty"]);
  const pageSend = new Element("send");
  const pageDocument = {
    body: { style: {} }, hidden: false,
    getElementById: id => pageElements[id] || null,
    querySelector: selector => selector === ".send" ? pageSend : null,
    querySelectorAll: () => [], createElement: tag => new Element(tag),
    addEventListener() {}, dispatchEvent() {},
  };
  const calls = [];
  const pageContext = {
    console, document: pageDocument, location: { hostname: "127.0.0.1" }, window: { open() {} }, sessionStorage: storage,
    TextDecoder, TextEncoder, Uint8Array,
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    fetch: async (url, options = {}) => {
      if (url === "/api/chat") { calls.push(JSON.parse(options.body)); return typeof answer === "function" ? answer() : responseFor(answer); }
      return { ok: true, json: async () => ({}) };
    },
    setInterval() {}, setTimeout, clearTimeout, Intl, Date, Promise, Math, JSON,
  };
  vm.runInNewContext(portalSource, pageContext, { filename: "portal.js restored-page" });
  return { elements: pageElements, calls, submit: async text => {
    pageElements["chat-input"].value = text;
    return pageElements["chat-form"].onsubmit({ preventDefault() {} });
  } };
}

async function submit(text) {
  elements["chat-input"].value = text;
  const result = elements["chat-form"].onsubmit({ preventDefault() {} });
  await Promise.resolve();
  return result;
}

(async () => {
  nextChatResponse = () => new Promise(resolve => {
    releaseChat = () => resolve(responseFor("첫 답변"));
  });
  const inFlight = submit("첫 요청");
  await Promise.resolve();
  assert.equal(elements["chat-reset"].disabled, true, "stream 중 초기화를 막아야 한다");
  const beforeBlockedReset = elements["log"].children.length;
  elements["chat-reset"].dispatchEvent({ type: "click" });
  assert.equal(elements["log"].children.length, beforeBlockedReset, "stream 중 메시지를 지우면 안 된다");
  releaseChat();
  await inFlight;

  nextChatResponse = () => responseFor('```json\n{"week":{"items":[]},"day":{"items":[]}}\n```');
  await submit("초안 요청");
  assert.equal(elements["confirm"].hidden, false, "목표 초안 확인 버튼이 보여야 한다");
  elements["chat-reset"].click();
  assert.equal(elements["log"].children[0].id, "chat-empty", "초기 빈 상태를 복원해야 한다");
  assert.equal(elements["chat-input"].value, "");
  assert.equal(elements["confirm"].hidden, true, "초기화 시 목표 초안 확인 버튼을 숨겨야 한다");
  assert.equal(elements["chat-status"].textContent, "");
  elements["confirm"].click();
  assert.equal(goalCalls.length, 0, "초기화한 목표 초안을 저장하면 안 된다");

  nextChatResponse = () => responseFor("새 답변");
  await submit("초기화 후 요청");
  assert.deepEqual(chatCalls.at(-1).messages, [{ role: "user", content: "초기화 후 요청" }], "다음 요청은 초기화된 history를 사용해야 한다");

  nextChatResponse = () => responseFor('```json\n{"week":{"items":[]},"day":{"items":[]}}\n```');
  await submit("저장할 초안");
  const saveClick = elements["confirm"].onclick();
  await Promise.resolve();
  assert.equal(elements["chat-reset"].disabled, true, "목표 저장 중 초기화를 막아야 한다");
  const beforeSaveReset = elements["log"].children.length;
  elements["chat-reset"].dispatchEvent({ type: "click" });
  assert.equal(elements["log"].children.length, beforeSaveReset, "목표 저장 중 메시지를 지우면 안 된다");
  releaseSave();
  await saveClick;
  assert.equal(elements["chat-reset"].disabled, false, "목표 저장 후 초기화를 다시 허용해야 한다");

  nextChatResponse = () => responseFor('```assistant_action\n{"action":"create_task","title":"후속 업무","date":"2026-09-17"}\n```');
  await submit("후속 업무를 만들어줘");
  assert.equal(elements["confirm"].hidden, false, "허용된 assistant_action 제안 확인 버튼이 보여야 한다");
  assert.equal(elements["confirm"].textContent, "이 작업 실행", "액션 제안은 작업 실행 버튼을 사용해야 한다");
  await elements["confirm"].onclick();
  assert.deepEqual(actionCalls, [{ action: "create_task", title: "후속 업무", date: "2026-09-17" }], "확인한 액션만 백엔드로 보내야 한다");

  nextChatResponse = () => responseFor('```assistant_action\n{"action":"reschedule_task","task_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","date":"2026-09-19","expected":{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","title":"기존 업무","date":"2026-09-18","done":false}}\n```');
  await submit("기존 업무 일정을 바꿔줘");
  assert.match(elements["chat-status"].textContent, /기존 업무/);
  assert.match(elements["chat-status"].textContent, /2026-09-18.*2026-09-19/);
  await elements["confirm"].onclick();
  assert.deepEqual(actionCalls.at(-1), { action: "reschedule_task", task_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", date: "2026-09-19", expected: { id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", title: "기존 업무", date: "2026-09-18", done: false } }, "스냅샷을 포함한 일정 변경만 백엔드로 보내야 한다");

  const storage = makeSessionStorage();
  const leakedToken = "sk-proj-abcdefghijklmnopqrstuvwxyz123456";
  const authToken = "auth_secret_value_1234567890";
  const assignedToken = "assigned_secret_value_1234567890";
  const proposalAnswer = `제안입니다.\n\`\`\`assistant_action\n{"action":"create_task","title":"다음 업무","date":"2026-09-17"}\n\`\`\`\nAPI_KEY=${leakedToken}\nAuthorization: Bearer ${authToken}\ntoken=Bearer ${assignedToken}`;
  const firstPage = makeChatPage(storage, proposalAnswer);
  firstPage.elements["chat-input"].value = "임시 작성 내용";
  firstPage.elements["chat-input"].dispatchEvent({ type: "input" });
  assert.match(storage.dump("suhun.portal.chat.v1"), /임시 작성 내용/);
  await firstPage.submit("이전 페이지에서 보낸 요청");
  assert.equal(firstPage.elements["confirm"].hidden, false);
  const saved = JSON.parse(storage.dump("suhun.portal.chat.v1"));
  assert.deepEqual(saved.messages.map(item => item.role), ["user", "assistant"]);
  assert.equal(saved.draft, "");
  assert.equal(storage.dump("suhun.portal.chat.v1").includes(leakedToken), false, "assistant 응답의 비밀값은 저장 전에 가려야 한다");
  assert.equal(storage.dump("suhun.portal.chat.v1").includes(authToken), false, "Authorization Bearer 토큰 전체를 가려야 한다");
  assert.equal(storage.dump("suhun.portal.chat.v1").includes(assignedToken), false, "token=Bearer 토큰 전체를 가려야 한다");

  const nextPage = makeChatPage(storage, "새 페이지 응답");
  assert.match(nextPage.elements.log.children[1].textContent, /다음 업무/);
  assert.match(nextPage.elements.log.children[1].textContent, /\[비공개 정보\]/);
  assert.equal(nextPage.elements.confirm.hidden, true, "페이지 이동 후 stale proposal 확인은 복원하지 않아야 한다");
  nextPage.elements["chat-input"].value = "새 페이지 초안";
  nextPage.elements["chat-input"].dispatchEvent({ type: "input" });
  const finalPage = makeChatPage(storage, "세 번째 응답");
  assert.equal(finalPage.elements["chat-input"].value, "새 페이지 초안");
  await finalPage.submit("이어서 보내는 요청");
  assert.deepEqual(finalPage.calls[0].messages.map(item => item.content), ["이전 페이지에서 보낸 요청", saved.messages[1].content, "이어서 보내는 요청"]);
  finalPage.elements["chat-reset"].click();
  assert.equal(storage.dump("suhun.portal.chat.v1"), undefined, "초기화 시 sessionStorage도 비워야 한다");

  const malformedStorage = makeSessionStorage("{broken-json");
  const malformedPage = makeChatPage(malformedStorage, "응답");
  assert.equal(malformedPage.elements.log.children[0].id, "chat-empty");
  assert.equal(malformedStorage.dump("suhun.portal.chat.v1"), undefined, "손상된 상태는 안전하게 제거해야 한다");
  const oversizedStorage = makeSessionStorage("x".repeat(110001));
  const oversizedPage = makeChatPage(oversizedStorage, "응답");
  assert.equal(oversizedPage.elements.log.children[0].id, "chat-empty");
  assert.equal(oversizedStorage.dump("suhun.portal.chat.v1"), undefined, "상한 초과 상태는 제거해야 한다");

  const cappedState = {
    version: 1,
    messages: Array.from({ length: 45 }, (_, index) => ({ role: index % 2 ? "assistant" : "user", content: `message-${index}-` + "x".repeat(100) })),
    draft: "d".repeat(5000),
  };
  const cappedStorage = makeSessionStorage(JSON.stringify(cappedState));
  const cappedPage = makeChatPage(cappedStorage, "응답");
  assert.equal(cappedPage.elements.log.children.length, 40);
  assert.equal(cappedPage.elements["chat-input"].value.length, 4000);
  const longMessageState = makeSessionStorage(JSON.stringify({ version: 1, messages: [{ role: "assistant", content: "x".repeat(3000) }], draft: "" }));
  const longMessagePage = makeChatPage(longMessageState, "응답");
  assert.equal(longMessagePage.elements.log.children[0].textContent.length, 2400);

  const streamStorage = makeSessionStorage(JSON.stringify({ version: 1, messages: [{ role: "user", content: "이전 저장 메시지" }], draft: "보낼 초안" }));
  let releaseStreaming;
  const streamPage = makeChatPage(streamStorage, () => new Promise(resolve => { releaseStreaming = () => resolve(responseFor("스트림 응답")); }));
  const streaming = streamPage.submit("보낼 초안");
  await Promise.resolve();
  const inFlightState = JSON.parse(streamStorage.dump("suhun.portal.chat.v1"));
  assert.equal(inFlightState.draft, "", "전송한 초안은 스트림 중 저장 상태에서 비워야 한다");
  assert.deepEqual(inFlightState.messages.map(item => item.content), ["이전 저장 메시지"], "스트림 중 사용자 메시지와 부분 답변은 저장하면 안 된다");
  const navigatedDuringStream = makeChatPage(streamStorage, "다음 페이지 응답");
  assert.deepEqual(navigatedDuringStream.elements.log.children.map(item => item.textContent), ["이전 저장 메시지"]);
  assert.equal(navigatedDuringStream.elements["chat-input"].value, "");
  releaseStreaming();
  await streaming;

  for (const page of ["index", "apps", "tasks", "goals", "organize"]) {
    assert.match(templateFile(`${page}.html`), /portal\.js\?v=/, `${page} 페이지가 공통 chat persistence 스크립트를 불러야 한다`);
  }
  console.log("portal chat reset and assistant action checks passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
