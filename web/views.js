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
  $("catalogue-count").textContent =
    `${rows.length} ${rows.length === 1 ? "skill" : "skills"}`;
  $("skill-list").innerHTML = rows.length
    ? rows
        .map(
          (row) => `
    <button class="skill-button" data-skill-id="${row.skill_id}" type="button">
      <span class="skill-category">${escapeHtml(row.category_name || "Other")}</span>
      <span class="skill-name">${escapeHtml(row.skill_name)}</span>
      <span class="skill-meta">${number(row.teachers)} ${Number(row.teachers) === 1 ? "teacher" : "teachers"} · ${number(row.learners)} learning</span>
      <span class="skill-cta">Find a teacher <span aria-hidden="true">↗</span></span>
    </button>`,
        )
        .join("")
    : '<p class="loading">No skills found. Try another skill or a category like Music.</p>';
}

export function renderTotals(rows) {
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
    `${table(["#", "Name", "Taught", "Learned", "Total"], rows.map((row) => `<tr><td>${row.rank}</td><td>${escapeHtml(row.name)}</td><td>${row.sessions_taught}</td><td>${row.sessions_learned}</td><td>${row.total_sessions}</td></tr>`).join(""))}`;
}

export function renderActivity(rows) {
  if (!rows.length) {
    $("activity").innerHTML =
      '<p class="loading">No completed exchanges yet.</p>';
    return;
  }
  const max = Math.max(...rows.map((row) => Number(row.completed_sessions)), 1);
  $("activity").innerHTML = rows
    .map(
      (row) => `
    <div class="activity-row"><span>${escapeHtml(row.skill_name)}<b>${row.completed_sessions}</b></span><span class="bar"><i style="width:${(row.completed_sessions / max) * 100}%"></i></span></div>`,
    )
    .join("");
}

export function renderProfile(user) {
  const name = user?.name || "Sign in";
  $("profile-avatar").textContent = user ? name.charAt(0).toUpperCase() : "?";
  $("profile-name").textContent = name;
  $("profile-label").textContent = user ? "Your account" : "Welcome";
  $("profile-email").textContent = user?.email || "Sign in to get started";
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
    `${table(["Reported person", "Reported by", "Reason", "Date", "Action"], data.reports.map((row) => `<tr><td>${escapeHtml(row.reported_name)}</td><td>${escapeHtml(row.reporter_name || "Deleted user")}</td><td>${escapeHtml(row.reason)}</td><td>${new Date(row.created_at).toLocaleDateString()}</td><td>${moderatorButton(row.banned ? "unban-user" : "ban-user", row.reported_id, row.banned ? "unban" : "ban")}</td></tr>`).join(""))}`;
  $("moderator-users").innerHTML =
    `${table(["ID", "Name", "Role", "Action"], data.users.map((row) => `<tr><td>${row.user_id}</td><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.role)}</td><td>${moderatorButton("delete-user", row.user_id, "delete")}</td></tr>`).join(""))}`;
  $("moderator-requests").innerHTML =
    `${table(["ID", "Skill", "Status", "Action"], data.requests.map((row) => `<tr><td>${row.request_id}</td><td>${escapeHtml(row.skill_name)}</td><td>${row.status}</td><td>${moderatorButton("request-status", row.request_id, "accept", "accepted")}${moderatorButton("request-status", row.request_id, "reject", "rejected")}</td></tr>`).join(""))}`;
  $("moderator-slots").innerHTML =
    `${table(["ID", "Teacher", "When", "Status", "Action"], data.slots.map((row) => `<tr><td>${row.slot_id}</td><td>${escapeHtml(row.provider_name)}</td><td>${new Date(row.start_time).toLocaleString()}</td><td>${row.status}</td><td>${row.status === "open" ? moderatorButton("slot-status", row.slot_id, "cancel", "cancelled") : ""}</td></tr>`).join(""))}`;
  $("moderator-sessions").innerHTML =
    `${table(["ID", "Skill", "Status", "Action"], data.sessions.map((row) => `<tr><td>${row.session_id}</td><td>${escapeHtml(row.skill_name)}</td><td>${row.status}</td><td>${row.status === "scheduled" ? moderatorButton("session-status", row.session_id, "complete", "completed") : ""}${row.status !== "cancelled" ? moderatorButton("session-status", row.session_id, "cancel", "cancelled") : ""}</td></tr>`).join(""))}`;
  $("moderator-feedback").innerHTML =
    `${table(["ID", "Session", "Rating", "Action"], data.feedback.map((row) => `<tr><td>${row.feedback_id}</td><td>${row.session_id}</td><td>${row.rating}/5</td><td>${moderatorButton("delete-feedback", row.feedback_id, "delete")}</td></tr>`).join(""))}`;
  $("moderator-slot-skill").innerHTML =
    '<option value="">Skill</option>' +
    data.skills
      .map(
        (row) =>
          `<option value="${row.skill_id}">${escapeHtml(row.name)}</option>`,
      )
      .join("");
}

export function renderRequests(rows, user) {
  $("request-count").textContent = rows.length ? String(rows.length) : "";
  $("requests").innerHTML = rows.length
    ? rows
        .map((row) => {
          const outgoing = row.requester_id === user.user_id;
          return `<article class="request-row">
      <div><strong>${escapeHtml(row.skill_name)}</strong><small>${outgoing ? "Sent" : "Received"} ${new Date(row.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })} · Request #${row.request_id}</small></div>
      <span class="request-person">${outgoing ? "To " + escapeHtml(row.provider_name) : "From " + escapeHtml(row.requester_name)}</span>
      <span class="request-status">${escapeHtml(row.status)}</span>
      <button type="button" class="report-abuse" data-user-id="${outgoing ? row.provider_id : row.requester_id}">Report abuse</button>
    </article>`;
        })
        .join("")
    : '<p class="loading">No requests yet. <a href="#discover">Find a skill</a> and send your first request.</p>';
}

export function renderMySkills(rows) {
  $("my-skills-list").innerHTML = rows.length
    ? rows
        .map(
          (row) => `
    <article class="skill-card">
      <div><strong>${escapeHtml(row.skill_name)}</strong><small>${escapeHtml(row.proficiency_level || "Level not specified")}</small>${row.description ? `<p class="hint">${escapeHtml(row.description)}</p>` : ""}</div>
      <span class="skill-type">${row.skill_type === "TEACH" ? "Teaching" : "Learning"}</span>
    </article>`,
        )
        .join("")
    : '<p class="loading">Your skills belong here. Add something you can teach or want to learn.</p>';
}

export function renderMatches(rows) {
  $("match-list").innerHTML = rows.length
    ? rows
        .map(
          (row) => `
    <article class="match-card">
      <span class="avatar" aria-hidden="true">${escapeHtml(row.provider_name.charAt(0))}</span>
      <h3>${escapeHtml(row.provider_name)}</h3>
      <p>Teaches ${escapeHtml(row.matched_skill)}<br>${Number(row.rating) ? `${Number(row.rating).toFixed(1)} / 5 learner rating` : "No learner ratings yet"}</p>
      <button class="request-button" data-provider="${row.provider_id}" data-skill="${row.matched_skill_id}" data-similarity="${row.similarity}" type="button">Send request</button>
      <button class="report-abuse" data-user-id="${row.provider_id}" type="button">Report abuse</button>
    </article>`,
        )
        .join("")
    : '<p class="loading">No teacher matches for this skill yet. Your interest is saved in <a href="#my-skills">My Skills</a>; try another skill while the campus grows.</p>';
}

export function renderLearningPrompt(skill) {
  $("match-list").innerHTML =
    `<div class="learning-prompt"><h3>Make room for ${escapeHtml(skill.skill_name)}.</h3><p>Add it to your learning skills to find teachers. You can add your goals and experience in My Skills.</p><button class="primary" data-start-learning="${skill.skill_id}" type="button">I want to learn ${escapeHtml(skill.skill_name)}</button></div>`;
}
