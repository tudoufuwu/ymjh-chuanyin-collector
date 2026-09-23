"use strict";

const labels = {
  interconnect_world: "互联世界", world: "世界", transmit: "传音", system: "系统",
  recruit: "招募", season: "赛季", school: "门派", clan: "宗门", team: "队伍",
  guild: "帮派", sworn: "结义", street: "街坊", single_server: "单服", other: "其他",
};
const state = { page: 1, totalPages: 1 };
const el = {
  health: document.querySelector("#health"), summary: document.querySelector("#summary"),
  category: document.querySelector("#category"), date: document.querySelector("#date"),
  query: document.querySelector("#query"), roleName: document.querySelector("#role-name"),
  roleId: document.querySelector("#role-id"), messages: document.querySelector("#messages"),
  previous: document.querySelector("#previous"), next: document.querySelector("#next"),
  page: document.querySelector("#page"), template: document.querySelector("#message-template"),
};

function request(path) { return fetch(path, { cache: "no-store" }).then(async response => {
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}); }
function formatTime(value) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date); }
function option(select, value, text) { const item = document.createElement("option"); item.value = value; item.textContent = text; select.append(item); }

async function loadMetadata() {
  const [health, summary] = await Promise.all([request("/api/health"), request("/api/summary")]);
  el.health.textContent = health.latest ? `本地归档 · ${health.message_count.toLocaleString("zh-CN")} 条 · 最新 ${formatTime(health.latest)}` : "本地归档为空";
  for (const item of summary.categories) option(el.category, item.category, `${item.label}（${item.count.toLocaleString("zh-CN")}）`);
  await loadDates();
}
async function loadDates() {
  const current = el.date.value;
  el.date.replaceChildren(); option(el.date, "", "全部日期");
  const category = el.category.value ? `?category=${encodeURIComponent(el.category.value)}` : "";
  const body = await request(`/api/dates${category}`);
  for (const item of body.dates) option(el.date, item.day, `${item.day}（${item.count.toLocaleString("zh-CN")}）`);
  el.date.value = current;
}
function parameters() {
  const params = new URLSearchParams({ page: String(state.page), limit: "50" });
  if (el.category.value) params.set("category", el.category.value);
  if (el.date.value) params.set("date", el.date.value);
  if (el.query.value.trim()) params.set("q", el.query.value.trim());
  if (el.roleName.value.trim()) params.set("role_name", el.roleName.value.trim());
  if (el.roleId.value.trim()) params.set("role_id", el.roleId.value.trim());
  return params;
}
function render(messages) {
  el.messages.replaceChildren();
  if (!messages.length) { const empty = document.createElement("p"); empty.className = "empty"; empty.textContent = "没有符合条件的记录"; el.messages.append(empty); return; }
  const batch = document.createDocumentFragment();
  for (const message of messages) {
    const node = el.template.content.cloneNode(true);
    node.querySelector(".badge").textContent = labels[message.category] || message.channel_label || message.category;
    node.querySelector(".name").textContent = message.role_name || "系统";
    node.querySelector(".role-id").textContent = message.role_id ? `ID ${message.role_id}` : "";
    const time = node.querySelector("time"); time.dateTime = message.server_time; time.textContent = formatTime(message.server_time);
    node.querySelector(".text").textContent = message.text || "";
    batch.append(node);
  }
  el.messages.append(batch);
}
async function loadMessages() {
  el.summary.textContent = "正在读取…";
  try {
    const body = await request(`/api/messages?${parameters()}`);
    state.page = body.page; state.totalPages = body.total_pages;
    render(body.messages);
    el.summary.textContent = `共 ${body.total.toLocaleString("zh-CN")} 条 · 第 ${body.page.toLocaleString("zh-CN")} / ${body.total_pages.toLocaleString("zh-CN")} 页`;
    el.page.textContent = `第 ${body.page} / ${body.total_pages} 页`;
    el.previous.disabled = body.page <= 1; el.next.disabled = body.page >= body.total_pages;
  } catch (error) { el.messages.replaceChildren(); const empty = document.createElement("p"); empty.className = "empty"; empty.textContent = `读取失败：${error.message}`; el.messages.append(empty); el.summary.textContent = "本地服务不可用"; }
}
function search() { state.page = 1; loadMessages(); }
document.querySelector("#search").addEventListener("click", search);
document.querySelector("#reset").addEventListener("click", () => { el.category.value = ""; el.date.value = ""; el.query.value = ""; el.roleName.value = ""; el.roleId.value = ""; loadDates().then(search); });
el.category.addEventListener("change", () => loadDates().then(search));
el.date.addEventListener("change", search);
for (const input of [el.query, el.roleName, el.roleId]) input.addEventListener("keydown", event => { if (event.key === "Enter") search(); });
el.previous.addEventListener("click", () => { if (state.page > 1) { state.page -= 1; loadMessages(); } });
el.next.addEventListener("click", () => { if (state.page < state.totalPages) { state.page += 1; loadMessages(); } });
loadMetadata().then(loadMessages).catch(error => { el.health.textContent = `本地服务不可用：${error.message}`; });
