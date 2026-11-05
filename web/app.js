const $ = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString();
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
}[char]));
let skills = [];
let selectedSkill = null;
let currentUser = null;
let csrfToken = null;

// --- Fetch wrapper that attaches CSRF token to mutating requests ---------

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (method !== "GET" && csrfToken) {
    options.headers = { ...options.headers, "X-CSRF-Token": csrfToken };
  }
  return fetch(path, options);
}

// --- Rendering -----------------------------------------------------------

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

function renderLearners(user) {
  currentUser = user;
  csrfToken = user?.csrf_token || null;
  renderProfile();
  $("login-panel").hidden = Boolean(currentUser);
  $("dashboard").hidden = !currentUser;
  $("logout-button").hidden = !currentUser;
  $("login-button").hidden = Boolean(currentUser);
  $("moderator-link").hidden = !currentUser || currentUser.role !== "admin";
  $("moderator-panel").hidden = !currentUser || currentUser.role !== "admin";
  if (currentUser) {
    loadMySkills();
    loadCommunity();
  }
  if (currentUser?.role === "admin") loadModerator();
}

function renderProfile() {
  const name = currentUser?.name || "Sign in / sign up";
  $("profile-avatar").textContent = name.charAt(0).toUpperCase() || "?";
  $("profile-name").textContent = name;
  $("profile-label").textContent = currentUser ? "Signed in as" : "Account";
  $("profile-email").textContent = currentUser?.email || "Choose a profile to continue";
  $("current-profile").textContent = currentUser ? `Searching as ${name}` : "Choose a profile above";
  $("current-profile").classList.toggle("ready", Boolean(currentUser));
}

function populateSkillChoices() {
  $("skill-choice").innerHTML = '<option value="">Choose a skill</option>' +
    skills.map((skill) => `<option value="${skill.skill_id}">${escapeHtml(skill.skill_name)}</option>`).join("");
}

async function loadMySkills() {
  const response = await api("/api/my-skills");
  if (!response.ok) return;
  const rows = await response.json();
  $("my-skills-list").innerHTML = rows.length ? rows.map((row) => `
    <article class="skill-card">
      <div><strong>${escapeHtml(row.skill_name)}</strong><small>${escapeHtml(row.proficiency_level || "level not specified")}</small></div>
      <span class="skill-type">${row.skill_type === "TEACH" ? "TEACHING" : "LEARNING"}</span>
    </article>`).join("") : '<div class="loading">Add a skill to start teaching or learning.</div>';
}

function moderatorButton(action, id, label, status) {
  const statusAttr = status ? ` data-status="${status}"` : "";
  return `<button class="moderator-action" data-mod-action="${action}" data-id="${id}"${statusAttr}>${label}</button>`;
}

function renderModerator(data) {
  $("moderator-users").innerHTML = `<table><thead><tr><th>ID</th><th>NAME</th><th>ROLE</th><th>ACTION</th></tr></thead><tbody>${
    data.users.map((row) => `<tr><td>${row.user_id}</td><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.role)}</td><td>${moderatorButton("delete-user", row.user_id, "delete")}</td></tr>`).join("")
  }</tbody></table>`;
  $("moderator-requests").innerHTML = `<table><thead><tr><th>ID</th><th>SKILL</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>${
    data.requests.map((row) => `<tr><td>${row.request_id}</td><td>${escapeHtml(row.skill_name)}</td><td>${row.status}</td><td>${moderatorButton("request-status", row.request_id, "accept", "accepted")}${moderatorButton("request-status", row.request_id, "reject", "rejected")}</td></tr>`).join("")
  }</tbody></table>`;
  $("moderator-slots").innerHTML = `<table><thead><tr><th>ID</th><th>PROVIDER</th><th>WHEN</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>${
    data.slots.map((row) => `<tr><td>${row.slot_id}</td><td>${escapeHtml(row.provider_name)}</td><td>${new Date(row.start_time).toLocaleString()}</td><td>${row.status}</td><td>${row.status === "open" ? moderatorButton("slot-status", row.slot_id, "cancel", "cancelled") : ""}</td></tr>`).join("")
  }</tbody></table>`;
  $("moderator-sessions").innerHTML = `<table><thead><tr><th>ID</th><th>SKILL</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>${
    data.sessions.map((row) => `<tr><td>${row.session_id}</td><td>${escapeHtml(row.skill_name)}</td><td>${row.status}</td><td>${row.status === "scheduled" ? moderatorButton("session-status", row.session_id, "complete", "completed") : ""}${row.status !== "cancelled" ? moderatorButton("session-status", row.session_id, "cancel", "cancelled") : ""}</td></tr>`).join("")
  }</tbody></table>`;
  $("moderator-feedback").innerHTML = `<table><thead><tr><th>ID</th><th>SESSION</th><th>RATING</th><th>ACTION</th></tr></thead><tbody>${
    data.feedback.map((row) => `<tr><td>${row.feedback_id}</td><td>${row.session_id}</td><td>${row.rating}/5</td><td>${moderatorButton("delete-feedback", row.feedback_id, "delete")}</td></tr>`).join("")
  }</tbody></table>`;
  $("moderator-reports").innerHTML = `<table><thead><tr><th>REPORT</th><th>REPORTED</th><th>REASON</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>${
    data.reports.map((row) => `<tr><td>${row.report_id}</td><td>${escapeHtml(row.reported_name)}</td><td>${escapeHtml(row.reason)}</td><td>${row.status}${row.banned_at ? " / BANNED" : ""}</td><td>${
      row.banned_at ? moderatorButton("unban-user", row.reported_user_id, "unban") : moderatorButton("ban-user", row.reported_user_id, "ban")
    }${row.status === "open" ? moderatorButton("report-status", row.report_id, "review", "reviewed") : ""}</td></tr>`).join("")
  }</tbody></table>`;
  $("moderator-slot-skill").innerHTML = '<option value="">Skill</option>' +
    data.skills.map((row) => `<option value="${row.skill_id}">${escapeHtml(row.name)}</option>`).join("");
}

async function loadModerator() {
  const response = await api("/api/moderation");
  if (response.ok) renderModerator(await response.json());
}

async function loadCommunity() {
  const response = await api("/api/users");
  if (!response.ok) return;
  const rows = await response.json();
  $("community-list").innerHTML = rows.length ? rows.map((row) => `
    <article class="user-card">
      <div><h3>${escapeHtml(row.name)}</h3><p>${escapeHtml(row.role)}${row.department ? ` · ${escapeHtml(row.department)}` : ""}</p></div>
      <button class="report-button" data-report-user="${row.user_id}" type="button">Report abuse</button>
    </article>`).join("") : '<div class="loading">No other users to show.</div>';
}

async function reportUser(userId) {
  const reason = window.prompt("Why are you reporting this user?");
  if (reason === null) return;
  const response = await api("/api/reports", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({reported_user_id: Number(userId), reason})
  });
  const result = await response.json();
  window.alert(response.ok ? "Report submitted to Arjun." : result.error);
}

async function moderatorAction(action, id, status) {
  if (action === "delete-user" || action === "delete-feedback") {
    if (!window.confirm("Apply this destructive action?")) return;
  }
  const response = await api("/api/moderation", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      action,
      [`${action === "delete-user" || action === "ban-user" || action === "unban-user"
        ? "user" : action === "delete-feedback" ? "feedback"
        : action === "request-status" ? "request" : action === "slot-status"
        ? "slot" : action === "report-status" ? "report" : "session"}_id`]: Number(id),
      status
    })
  });
  const result = await response.json();
  $("moderator-message").textContent = response.ok ? "Moderation change saved." : result.error;
  if (response.ok) loadModerator();
}

// --- Auth ----------------------------------------------------------------

function showPasswordRules() {
  return "At least 8 characters, with uppercase, lowercase, and a digit";
}

async function authenticate(path) {
  $("auth-error").textContent = "";
  const emailVal = $("auth-email").value.trim();
  const passwordVal = $("auth-password").value;

  if (!emailVal || !emailVal.includes("@")) {
    $("auth-error").textContent = "Enter a valid email address";
    return;
  }
  if (passwordVal.length < 8) {
    $("auth-error").textContent = showPasswordRules();
    return;
  }

  const body = { email: emailVal, password: passwordVal };
  if (path === "/api/register") {
    const nameVal = $("auth-name").value.trim();
    if (!nameVal) { $("auth-error").textContent = "Enter your name"; return; }
    body.name = nameVal;
  }

  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    $("auth-error").textContent = result.error;
    return;
  }
  $("auth-error").textContent = "";
  $("auth-password").value = "";
  renderLearners(result);
  loadRequests();
}

$("auth-form").addEventListener("submit", (event) => { event.preventDefault(); authenticate("/api/login"); });
$("register-button").addEventListener("click", () => authenticate("/api/register"));

// --- Requests & matches --------------------------------------------------

function renderRequests(rows) {
  if (!rows.length) {
    $("requests").innerHTML = '<div class="loading">No requests yet. Search for a skill to start an exchange.</div>';
    return;
  }
  const learnerId = currentUser?.user_id;
  if (!learnerId) {
    $("requests").innerHTML = '<div class="loading">Choose a profile above to see your requests.</div>';
    return;
  }
  $("requests").innerHTML = rows.map((row) => `
    <div class="request-row">
      <strong>${escapeHtml(row.skill_name)}</strong>
      <span>${row.requester_id === learnerId ? "to " + escapeHtml(row.provider_name) : "from " + escapeHtml(row.requester_name)}</span>
      <span>${escapeHtml(row.status)}</span><span>${new Date(row.created_at).toLocaleDateString()}</span>
    </div>`).join("");
}

async function loadRequests() {
  const userId = currentUser?.user_id;
  if (!userId) return;
  const rows = await fetch(`/api/requests?user_id=${userId}`).then((r) => r.json());
  renderRequests(rows);
}

async function openMatches(skillId) {
  const learnerId = currentUser?.user_id;
  selectedSkill = skills.find((skill) => skill.skill_id === skillId);
  if (!learnerId) return;
  $("match-drawer").hidden = false;
  $("match-title").textContent = `Teachers for ${selectedSkill.skill_name}`;
  $("match-list").innerHTML = '<div class="loading">finding semantic matches...</div>';
  $("match-drawer").scrollIntoView({ behavior: "smooth" });
  const rows = await fetch(`/api/matches?learner_id=${learnerId}&skill_id=${skillId}`).then((r) => r.json());
  $("match-list").innerHTML = rows.length ? rows.map((row) => `
    <article class="match-card">
      <h3>${escapeHtml(row.provider_name)}</h3>
      <p>Similarity ${(Number(row.similarity) * 100).toFixed(1)}%<br>Average rating ${row.rating}/5</p>
      <button class="report-button report-match-button" data-report-user="${row.provider_id}" type="button">report user</button>
      <button class="request-button" data-provider="${row.provider_id}" data-similarity="${row.similarity}" type="button">send request</button>
    </article>`).join("") : '<div class="loading">No teacher matches found for this skill.</div>';
  document.querySelectorAll(".request-button").forEach((button) => {
    button.addEventListener("click", () => createRequest(button));
  });
  document.querySelectorAll(".report-match-button").forEach((button) => {
    button.addEventListener("click", () => reportUser(button.dataset.reportUser));
  });
}

async function createRequest(button) {
  button.disabled = true;
  const response = await api("/api/requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      requester_id: currentUser.user_id,
      provider_id: Number(button.dataset.provider),
      skill_id: selectedSkill.skill_id,
      similarity_score: Number(button.dataset.similarity)
    })
  });
  const result = await response.json();
  button.textContent = response.ok ? `request #${result.request_id} sent` : result.error;
  if (response.ok) loadRequests();
}

// --- Initial load --------------------------------------------------------

async function load() {
  try {
    const [health, skillRows, leaderboard, activity, userRows] = await Promise.all([
      fetch("/api/health").then((r) => r.json()),
      fetch("/api/skills").then((r) => r.json()),
      fetch("/api/leaderboard").then((r) => r.json()),
      fetch("/api/activity").then((r) => r.json()),
      fetch("/api/me").then((r) => r.json())
    ]);
    if (health.error || skillRows.error) throw new Error(health.error || skillRows.error);
    skills = skillRows;
    populateSkillChoices();
    renderLearners(userRows);
    renderSkills(skills);
    renderLeaderboard(leaderboard);
    renderActivity(activity);
    loadRequests();
    $("status-dot").classList.add("live");
    $("status-text").textContent = "postgres live";
    $("server-time").textContent = health.server_time || "connected";
  } catch (error) {
    $("status-text").textContent = "database offline";
    $("server-time").textContent = error.message;
  }
}

// --- Event listeners -----------------------------------------------------

$("refresh").addEventListener("click", load);
$("close-matches").addEventListener("click", () => $("match-drawer").hidden = true);
$("load-requests").addEventListener("click", loadRequests);
$("refresh-my-skills").addEventListener("click", loadMySkills);
$("refresh-moderator").addEventListener("click", loadModerator);
$("refresh-community").addEventListener("click", loadCommunity);
$("community-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-report-user]");
  if (button) reportUser(button.dataset.reportUser);
});

$("moderator-panel").addEventListener("click", (event) => {
  const button = event.target.closest("[data-mod-action]");
  if (button) moderatorAction(button.dataset.modAction, button.dataset.id, button.dataset.status);
});

$("moderator-user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await api("/api/moderation", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action: "set-role", user_id: Number($("moderator-user-id").value), role: $("moderator-user-role").value})
  });
  const result = await response.json();
  $("moderator-user-message").textContent = response.ok ? "Role saved." : result.error;
  if (response.ok) loadModerator();
});

$("moderator-skill-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await api("/api/moderation", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action: "create-skill", name: $("moderator-skill-name").value,
      category: $("moderator-skill-category").value, description: $("moderator-skill-description").value})
  });
  const result = await response.json();
  $("moderator-skill-message").textContent = response.ok ? "Skill created." : result.error;
  if (response.ok) { event.target.reset(); loadModerator(); load(); }
});

$("moderator-slot-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await api("/api/moderation", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action: "create-slot", provider_id: Number($("moderator-slot-provider").value),
      skill_id: Number($("moderator-slot-skill").value), start_time: $("moderator-slot-start").value,
      end_time: $("moderator-slot-end").value})
  });
  const result = await response.json();
  $("moderator-slot-message").textContent = response.ok ? "Slot created." : result.error;
  if (response.ok) { event.target.reset(); loadModerator(); }
});

$("skill-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = $("skill-form-message");
  message.textContent = "";
  const response = await api("/api/user-skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      skill_id: Number($("skill-choice").value),
      skill_type: $("skill-type").value,
      proficiency_level: $("skill-level").value || null,
      description: $("skill-description").value.trim()
    })
  });
  const result = await response.json();
  message.textContent = response.ok ? "Saved to your profile." : result.error;
  if (response.ok) {
    $("skill-form").reset();
    loadMySkills();
    load();
  }
});

$("profile-button").addEventListener("click", () => {
  const menu = $("profile-menu");
  menu.hidden = !menu.hidden;
  $("profile-button").setAttribute("aria-expanded", String(!menu.hidden));
});

$("login-button").addEventListener("click", () => {
  $("profile-menu").hidden = true;
  $("login-panel").hidden = false;
  $("login-panel").scrollIntoView({ behavior: "smooth", block: "start" });
});

$("logout-button").addEventListener("click", async () => {
  await api("/api/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  });
  renderLearners(null);
  $("requests").innerHTML = '<div class="loading">Sign in to see your requests.</div>';
  $("match-drawer").hidden = true;
  $("profile-menu").hidden = true;
  $("login-panel").hidden = false;
});

$("skill-search").addEventListener("input", (event) => {
  const term = event.target.value.toLowerCase();
  renderSkills(skills.filter((skill) => `${skill.skill_name} ${skill.category_name}`.toLowerCase().includes(term)));
});

load();
