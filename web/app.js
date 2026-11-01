const $ = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString();
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
}[char]));
let skills = [];
let selectedSkill = null;

function renderSkills(rows) {
  const max = Math.max(...rows.map((row) => Math.max(row.learners, row.teachers)), 1);
  $("skill-list").innerHTML = rows.map((row, index) => `
    <button class="skill-row skill-button" data-skill-id="${row.skill_id}" type="button">
      <span class="rank">${String(index + 1).padStart(2, "0")}</span>
      <span class="skill-name">${escapeHtml(row.skill_name)}</span>
      <span class="meta">T ${row.teachers}</span>
      <span class="meta">L ${row.learners}</span>
      <span class="bar"><i style="width:${Math.max(3, row.learners / max * 100)}%"></i></span>
      <span class="gap ${row.demand_gap <= 0 ? "neutral" : ""}">gap ${row.demand_gap > 0 ? "+" : ""}${row.demand_gap}</span>
    </button>`).join("");
  document.querySelectorAll(".skill-button").forEach((button) => {
    button.addEventListener("click", () => openMatches(Number(button.dataset.skillId)));
  });
  $("open-demand").textContent = number(rows.reduce((sum, row) => sum + Number(row.learners), 0));
  $("teaching-supply").textContent = number(rows.reduce((sum, row) => sum + Number(row.teachers), 0));
  $("exchanges").textContent = number(rows.reduce((sum, row) => sum + Number(row.completed_sessions), 0));
  $("skill-count").textContent = number(rows.length);
}

function renderLeaderboard(rows) {
  $("leaderboard").innerHTML = `<table><thead><tr><th>#</th><th>NAME</th><th>TAUGHT</th><th>LEARNED</th><th>TOTAL</th></tr></thead><tbody>${
    rows.map((row) => `<tr><td>${row.rank}</td><td>${escapeHtml(row.name)}</td><td>${row.sessions_taught}</td><td>${row.sessions_learned}</td><td>${row.total_sessions}</td></tr>`).join("")
  }</tbody></table>`;
}

function renderActivity(rows) {
  const max = Math.max(...rows.map((row) => Number(row.completed_sessions)), 1);
  $("activity").innerHTML = rows.map((row) => `
    <div class="activity-row"><span>${escapeHtml(row.skill_name)}<b>${row.completed_sessions}</b></span><span class="bar"><i style="width:${row.completed_sessions / max * 100}%"></i></span></div>`).join("");
}

function renderLearners(rows) {
  $("learner-select").innerHTML = rows.map((row) =>
    `<option value="${row.user_id}">${escapeHtml(row.name)} — ${escapeHtml(row.role)}</option>`).join("");
}

function renderRequests(rows) {
  if (!rows.length) {
    $("requests").innerHTML = '<div class="loading">No requests yet. Search for a skill to start an exchange.</div>';
    return;
  }
  const learnerId = Number($("learner-select").value);
  $("requests").innerHTML = rows.map((row) => `
    <div class="request-row">
      <strong>${escapeHtml(row.skill_name)}</strong>
      <span>${row.requester_id === learnerId ? "to " + escapeHtml(row.provider_name) : "from " + escapeHtml(row.requester_name)}</span>
      <span>${escapeHtml(row.status)}</span><span>${new Date(row.created_at).toLocaleDateString()}</span>
    </div>`).join("");
}

async function loadRequests() {
  const userId = $("learner-select").value;
  if (!userId) return;
  const rows = await fetch(`/api/requests?user_id=${userId}`).then((response) => response.json());
  renderRequests(rows);
}

async function openMatches(skillId) {
  const learnerId = $("learner-select").value;
  selectedSkill = skills.find((skill) => skill.skill_id === skillId);
  if (!learnerId) return;
  $("match-drawer").hidden = false;
  $("match-title").textContent = `Teachers for ${selectedSkill.skill_name}`;
  $("match-list").innerHTML = '<div class="loading">finding semantic matches...</div>';
  $("match-drawer").scrollIntoView({ behavior: "smooth" });
  const rows = await fetch(`/api/matches?learner_id=${learnerId}&skill_id=${skillId}`).then((response) => response.json());
  $("match-list").innerHTML = rows.length ? rows.map((row) => `
    <article class="match-card">
      <h3>${escapeHtml(row.provider_name)}</h3>
      <p>Similarity ${(Number(row.similarity) * 100).toFixed(1)}%<br>Average rating ${row.rating}/5</p>
      <button class="request-button" data-provider="${row.provider_id}" data-similarity="${row.similarity}" type="button">send request</button>
    </article>`).join("") : '<div class="loading">No teacher matches found for this skill.</div>';
  document.querySelectorAll(".request-button").forEach((button) => {
    button.addEventListener("click", () => createRequest(button));
  });
}

async function createRequest(button) {
  button.disabled = true;
  const response = await fetch("/api/requests", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      requester_id: Number($("learner-select").value),
      provider_id: Number(button.dataset.provider),
      skill_id: selectedSkill.skill_id,
      similarity_score: Number(button.dataset.similarity)
    })
  });
  const result = await response.json();
  button.textContent = response.ok ? `request #${result.request_id} sent` : result.error;
  if (response.ok) loadRequests();
}

async function load() {
  try {
    const [health, skillRows, leaderboard, activity, users] = await Promise.all([
      fetch("/api/health").then((response) => response.json()),
      fetch("/api/skills").then((response) => response.json()),
      fetch("/api/leaderboard").then((response) => response.json()),
      fetch("/api/activity").then((response) => response.json()),
      fetch("/api/users").then((response) => response.json())
    ]);
    if (health.error || skillRows.error) throw new Error(health.error || skillRows.error);
    skills = skillRows; renderLearners(users); renderSkills(skills); renderLeaderboard(leaderboard); renderActivity(activity);
    loadRequests();
    $("status-dot").classList.add("live"); $("status-text").textContent = "postgres live";
    $("server-time").textContent = health.server_time || "connected";
  } catch (error) {
    $("status-text").textContent = "database offline";
    $("server-time").textContent = error.message;
  }
}

$("refresh").addEventListener("click", load);
$("close-matches").addEventListener("click", () => $("match-drawer").hidden = true);
$("load-requests").addEventListener("click", loadRequests);
$("learner-select").addEventListener("change", loadRequests);
$("skill-search").addEventListener("input", (event) => {
  const term = event.target.value.toLowerCase();
  renderSkills(skills.filter((skill) => `${skill.skill_name} ${skill.category_name}`.toLowerCase().includes(term)));
});
load();
