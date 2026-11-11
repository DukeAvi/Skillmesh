export const $ = (id) => document.getElementById(id);
export const number = (value) => Number(value || 0).toLocaleString();
export const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      })[char],
  );

function table(headers, body) {
  return `<table><thead><tr>${headers.map((label) => `<th scope="col">${label}</th>`).join("")}</tr></thead><tbody>${body || `<tr><td colspan="${headers.length}">Nothing here yet.</td></tr>`}</tbody></table>`;
}

export function renderSkills(rows) {
  const max = Math.max(
    ...rows.map((row) => Math.max(row.learners, row.teachers)),
    1,
  );
  $("skill-list").innerHTML = rows
    .map(
      (row, index) => `
    <button class="skill-row skill-button" data-skill-id="${row.skill_id}" type="button">
      <span class="rank">${String(index + 1).padStart(2, "0")}</span>
      <span class="skill-name">${escapeHtml(row.skill_name)}</span>
      <span class="meta">T ${row.teachers}</span>
      <span class="meta">L ${row.learners}</span>
      <span class="bar"><i style="width:${Math.max(3, (row.learners / max) * 100)}%"></i></span>
      <span class="gap ${row.demand_gap <= 0 ? "neutral" : ""}">gap ${row.demand_gap > 0 ? "+" : ""}${row.demand_gap}</span>
    </button>`,
    )
    .join("");
  $("open-demand").textContent = number(
    rows.reduce((sum, row) => sum + Number(row.learners), 0),
  );
  $("teaching-supply").textContent = number(
    rows.reduce((sum, row) => sum + Number(row.teachers), 0),
  );
  $("exchanges").textContent = number(
    rows.reduce((sum, row) => sum + Number(row.completed_sessions), 0),
  );
  $("skill-count").textContent = number(rows.length);
}

export function renderLeaderboard(rows) {
  $("leaderboard").innerHTML =
    `${table(["#", "NAME", "TAUGHT", "LEARNED", "TOTAL"], rows.map((row) => `<tr><td>${row.rank}</td><td>${escapeHtml(row.name)}</td><td>${row.sessions_taught}</td><td>${row.sessions_learned}</td><td>${row.total_sessions}</td></tr>`).join(""))}`;
}

export function renderActivity(rows) {
  const max = Math.max(...rows.map((row) => Number(row.completed_sessions)), 1);
  $("activity").innerHTML = rows
    .map(
      (row) => `
    <div class="activity-row"><span>${escapeHtml(row.skill_name)}<b>${row.completed_sessions}</b></span><span class="bar"><i style="width:${(row.completed_sessions / max) * 100}%"></i></span></div>`,
    )
    .join("");
}

export function renderProfile(currentUser) {
  const name = currentUser?.name || "Sign in / sign up";
  $("profile-avatar").textContent = name.charAt(0).toUpperCase() || "?";
  $("profile-name").textContent = name;
  $("profile-label").textContent = currentUser ? "Signed in as" : "Account";
  $("profile-email").textContent =
    currentUser?.email || "Choose a profile to continue";
  $("current-profile").textContent = currentUser
    ? `Searching as ${name}`
    : "Choose a profile above";
  $("current-profile").classList.toggle("ready", Boolean(currentUser));
}

export function populateSkillChoices(skills) {
  $("skill-choice").innerHTML =
    '<option value="">Choose a skill</option>' +
    skills
      .map(
        (skill) =>
          `<option value="${skill.skill_id}">${escapeHtml(skill.skill_name)}</option>`,
      )
      .join("");
}

function moderatorButton(action, id, label, status) {
  const statusAttr = status ? ` data-status="${status}"` : "";
  return `<button class="moderator-action" data-mod-action="${action}" data-id="${id}"${statusAttr}>${label}</button>`;
}

export function renderModerator(data) {
  $("moderator-reports").innerHTML =
    `${table(["REPORTED", "REPORTER", "REASON", "DATE", "ACTION"], data.reports.map((row) => `<tr><td>${escapeHtml(row.reported_name)}</td><td>${escapeHtml(row.reporter_name || "Deleted user")}</td><td>${escapeHtml(row.reason)}</td><td>${new Date(row.created_at).toLocaleDateString()}</td><td>${moderatorButton(row.banned ? "unban-user" : "ban-user", row.reported_id, row.banned ? "unban" : "ban")}</td></tr>`).join(""))}`;
  $("moderator-users").innerHTML =
    `${table(["ID", "NAME", "ROLE", "ACTION"], data.users.map((row) => `<tr><td>${row.user_id}</td><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.role)}</td><td>${moderatorButton("delete-user", row.user_id, "delete")}</td></tr>`).join(""))}`;
  $("moderator-requests").innerHTML =
    `${table(["ID", "SKILL", "STATUS", "ACTION"], data.requests.map((row) => `<tr><td>${row.request_id}</td><td>${escapeHtml(row.skill_name)}</td><td>${row.status}</td><td>${moderatorButton("request-status", row.request_id, "accept", "accepted")}${moderatorButton("request-status", row.request_id, "reject", "rejected")}</td></tr>`).join(""))}`;
  $("moderator-slots").innerHTML =
    `${table(["ID", "PROVIDER", "WHEN", "STATUS", "ACTION"], data.slots.map((row) => `<tr><td>${row.slot_id}</td><td>${escapeHtml(row.provider_name)}</td><td>${new Date(row.start_time).toLocaleString()}</td><td>${row.status}</td><td>${row.status === "open" ? moderatorButton("slot-status", row.slot_id, "cancel", "cancelled") : ""}</td></tr>`).join(""))}`;
  $("moderator-sessions").innerHTML =
    `${table(["ID", "SKILL", "STATUS", "ACTION"], data.sessions.map((row) => `<tr><td>${row.session_id}</td><td>${escapeHtml(row.skill_name)}</td><td>${row.status}</td><td>${row.status === "scheduled" ? moderatorButton("session-status", row.session_id, "complete", "completed") : ""}${row.status !== "cancelled" ? moderatorButton("session-status", row.session_id, "cancel", "cancelled") : ""}</td></tr>`).join(""))}`;
  $("moderator-feedback").innerHTML =
    `${table(["ID", "SESSION", "RATING", "ACTION"], data.feedback.map((row) => `<tr><td>${row.feedback_id}</td><td>${row.session_id}</td><td>${row.rating}/5</td><td>${moderatorButton("delete-feedback", row.feedback_id, "delete")}</td></tr>`).join(""))}`;
  $("moderator-slot-skill").innerHTML =
    '<option value="">Skill</option>' +
    data.skills
      .map(
        (row) =>
          `<option value="${row.skill_id}">${escapeHtml(row.name)}</option>`,
      )
      .join("");
}

export function renderRequests(rows, currentUser) {
  if (!rows.length) {
    $("requests").innerHTML =
      '<div class="loading">No requests yet. Search for a skill to start an exchange.</div>';
    return;
  }
  const learnerId = currentUser?.user_id;
  if (!learnerId) {
    $("requests").innerHTML =
      '<div class="loading">Choose a profile above to see your requests.</div>';
    return;
  }
  $("requests").innerHTML = rows
    .map(
      (row) => `
    <div class="request-row">
      <strong>${escapeHtml(row.skill_name)}</strong>
      <span>${row.requester_id === learnerId ? "to " + escapeHtml(row.provider_name) : "from " + escapeHtml(row.requester_name)}</span>
      <span>${escapeHtml(row.status)}</span><span>${new Date(row.created_at).toLocaleDateString()}</span>
      <button type="button" class="report-abuse" data-user-id="${row.requester_id === learnerId ? row.provider_id : row.requester_id}">Report abuse</button>
    </div>`,
    )
    .join("");
}

export function renderMySkills(rows) {
  $("my-skills-list").innerHTML = rows.length
    ? rows
        .map(
          (row) => `
    <article class="skill-card">
      <div><strong>${escapeHtml(row.skill_name)}</strong><small>${escapeHtml(row.proficiency_level || "level not specified")}</small></div>
      <span class="skill-type">${row.skill_type === "TEACH" ? "TEACHING" : "LEARNING"}</span>
    </article>`,
        )
        .join("")
    : '<div class="loading">Add a skill to start teaching or learning.</div>';
}

export function renderMatches(rows) {
  $("match-list").innerHTML = rows.length
    ? rows
        .map(
          (row) => `
    <article class="match-card">
      <h3>${escapeHtml(row.provider_name)}</h3>
      <p>Similarity ${(Number(row.similarity) * 100).toFixed(1)}%<br>Average rating ${row.rating}/5</p>
      <button class="request-button" data-provider="${row.provider_id}" data-similarity="${row.similarity}" type="button">send request</button>
      <button class="report-abuse" data-user-id="${row.provider_id}" type="button">Report abuse</button>
    </article>`,
        )
        .join("")
    : '<div class="loading">No teacher matches found for this skill.</div>';
}
