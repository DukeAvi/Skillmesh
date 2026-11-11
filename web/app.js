import { api, post, setCsrfToken } from "./api.js";
import {
  $,
  renderSkills,
  renderLeaderboard,
  renderActivity,
  renderProfile,
  populateSkillChoices,
  renderModerator,
  renderRequests,
  renderMySkills,
  renderMatches,
} from "./views.js";

async function runAction(control, action) {
  const message = control
    .closest("form, section")
    ?.querySelector('[role="status"], [role="alert"], .form-message');
  const button = control.matches("button")
    ? control
    : control.querySelector('button[type="submit"]');
  if (button) button.disabled = true;
  try {
    await action();
  } catch (error) {
    if (message) message.textContent = error.message;
    else window.alert(error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

function on(id, event, action) {
  $(id).addEventListener(event, (e) => runAction($(id), () => action(e)));
}

let skills = [];
let selectedSkill = null;
let currentUser = null;

function setCurrentUser(user) {
  currentUser = user;
  setCsrfToken(user?.csrf_token);
  renderProfile(currentUser);
  $("login-panel").hidden = Boolean(currentUser);
  $("dashboard").hidden = !currentUser;
  $("moderator-setup").hidden = Boolean(currentUser);
  $("logout-button").hidden = !currentUser;
  $("login-button").hidden = Boolean(currentUser);
  $("moderator-link").hidden = !currentUser || currentUser.role !== "admin";
  $("moderator-panel").hidden = !currentUser || currentUser.role !== "admin";
  if (currentUser) loadMySkills();
  if (currentUser?.role === "admin") loadModerator();
}

async function loadMySkills() {
  try {
    const result = await api("/api/my-skills");
    const rows = result;
    renderMySkills(rows);
  } catch (error) {
    $("my-skills-list").textContent = error.message;
  }
}

async function loadModerator() {
  try {
    const result = await api("/api/moderation");
    renderModerator(result);
  } catch (error) {
    $("moderator-message").textContent = error.message;
  }
}

async function moderatorAction(action, id, status) {
  if (
    action === "delete-user" ||
    action === "delete-feedback" ||
    action === "ban-user"
  ) {
    if (!window.confirm("Apply this destructive action?")) return;
  }
  await post("/api/moderation", {
    action,
    [`${["delete-user", "ban-user", "unban-user"].includes(action) ? "user" : action === "delete-feedback" ? "feedback" : action === "request-status" ? "request" : action === "slot-status" ? "slot" : "session"}_id`]:
      Number(id),
    status,
  });
  $("moderator-message").textContent = "Moderation change saved.";
  loadModerator();
}

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
    if (!nameVal) {
      $("auth-error").textContent = "Enter your name";
      return;
    }
    body.name = nameVal;
  }

  const result = await post(path, body);
  $("auth-error").textContent = "";
  $("auth-password").value = "";
  setCurrentUser(result);
  loadRequests();
}

on("auth-form", "submit", (event) => {
  event.preventDefault();
  return authenticate("/api/login");
});
on("register-button", "click", () => authenticate("/api/register"));

on("moderator-setup-form", "submit", async (event) => {
  event.preventDefault();
  const message = $("moderator-setup-message");
  try {
    await post("/api/moderator/setup", {
      code: $("moderator-setup-code").value,
      password: $("moderator-setup-password").value,
    });
    $("moderator-setup-form").reset();
    message.textContent = "Moderator activated. Sign in as arjun@campus.edu.";
  } catch (error) {
    message.textContent = error.message;
  }
});

async function loadRequests() {
  try {
    const userId = currentUser?.user_id;
    if (!userId) return;
    const rows = await api(`/api/requests?user_id=${userId}`);
    renderRequests(rows, currentUser);
  } catch (error) {
    $("requests").textContent = error.message;
  }
}

async function openMatches(skillId) {
  try {
    const learnerId = currentUser?.user_id;
    selectedSkill = skills.find((skill) => skill.skill_id === skillId);
    if (!learnerId) return;
    $("match-drawer").hidden = false;
    $("match-title").textContent = `Teachers for ${selectedSkill.skill_name}`;
    $("match-list").innerHTML =
      '<div class="loading">finding semantic matches...</div>';
    $("match-drawer").scrollIntoView({ behavior: "smooth" });
    const rows = await api(
      `/api/matches?learner_id=${learnerId}&skill_id=${skillId}`,
    );
    renderMatches(rows.filter((row) => row.matched_skill_id === skillId));
    document.querySelectorAll(".request-button").forEach((button) => {
      button.addEventListener("click", () =>
        runAction(button, () => createRequest(button)),
      );
    });
  } catch (error) {
    $("match-list").textContent = error.message;
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest(".report-abuse");
  if (!button) return;
  const reason = window.prompt("Describe the abuse (up to 1000 characters):");
  if (reason === null) return;
  try {
    await post("/api/reports", {
      user_id: Number(button.dataset.userId),
      reason,
    });
    window.alert("Report sent to the moderator.");
  } catch (error) {
    window.alert("Could not send the report. Please try again.");
  }
});

async function createRequest(button) {
  button.disabled = true;
  const result = await post("/api/requests", {
    requester_id: currentUser.user_id,
    provider_id: Number(button.dataset.provider),
    skill_id: selectedSkill.skill_id,
    similarity_score: Number(button.dataset.similarity),
  });
  button.textContent = `request #${result.request_id} sent`;
  loadRequests();
}

async function load() {
  try {
    const [health, skillRows, leaderboard, activity, userRows] =
      await Promise.all([
        api("/api/health"),
        api("/api/skills"),
        api("/api/leaderboard"),
        api("/api/activity"),
        api("/api/me"),
      ]);
    skills = skillRows;
    populateSkillChoices(skills);
    setCurrentUser(userRows);
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

on("refresh", "click", load);
on("close-matches", "click", () => ($("match-drawer").hidden = true));
on("load-requests", "click", loadRequests);
on("refresh-my-skills", "click", loadMySkills);
on("refresh-moderator", "click", loadModerator);

on("moderator-panel", "click", (event) => {
  const button = event.target.closest("[data-mod-action]");
  if (button)
    return moderatorAction(
      button.dataset.modAction,
      button.dataset.id,
      button.dataset.status,
    );
});

on("moderator-user-form", "submit", async (event) => {
  event.preventDefault();
  await post("/api/moderation", {
    action: "set-role",
    user_id: Number($("moderator-user-id").value),
    role: $("moderator-user-role").value,
  });
  $("moderator-user-message").textContent = "Role saved.";
  loadModerator();
});

on("moderator-skill-form", "submit", async (event) => {
  event.preventDefault();
  await post("/api/moderation", {
    action: "create-skill",
    name: $("moderator-skill-name").value,
    category: $("moderator-skill-category").value,
    description: $("moderator-skill-description").value,
  });
  $("moderator-skill-message").textContent = "Skill created.";
  event.target.reset();
  loadModerator();
  load();
});

on("moderator-slot-form", "submit", async (event) => {
  event.preventDefault();
  await post("/api/moderation", {
    action: "create-slot",
    provider_id: Number($("moderator-slot-provider").value),
    skill_id: Number($("moderator-slot-skill").value),
    start_time: $("moderator-slot-start").value,
    end_time: $("moderator-slot-end").value,
  });
  $("moderator-slot-message").textContent = "Slot created.";
  event.target.reset();
  loadModerator();
});

on("skill-form", "submit", async (event) => {
  event.preventDefault();
  const message = $("skill-form-message");
  message.textContent = "";
  await post("/api/user-skills", {
    skill_id: Number($("skill-choice").value),
    skill_type: $("skill-type").value,
    proficiency_level: $("skill-level").value || null,
    description: $("skill-description").value.trim(),
  });
  message.textContent = "Saved to your profile.";
  $("skill-form").reset();
  load();
});

on("profile-button", "click", () => {
  const menu = $("profile-menu");
  menu.hidden = !menu.hidden;
  $("profile-button").setAttribute("aria-expanded", String(!menu.hidden));
});

on("login-button", "click", () => {
  $("profile-menu").hidden = true;
  $("login-panel").hidden = false;
  $("login-panel").scrollIntoView({ behavior: "smooth", block: "start" });
});

on("logout-button", "click", async () => {
  await post("/api/logout", {});
  setCurrentUser(null);
  $("requests").innerHTML =
    '<div class="loading">Sign in to see your requests.</div>';
  $("match-drawer").hidden = true;
  $("profile-menu").hidden = true;
  $("login-panel").hidden = false;
});

on("skill-search", "input", (event) => {
  const term = event.target.value.toLowerCase();
  renderSkills(
    skills.filter((skill) =>
      `${skill.skill_name} ${skill.category_name}`.toLowerCase().includes(term),
    ),
  );
});

load();

on("skill-list", "click", (event) => {
  const button = event.target.closest(".skill-button");
  if (button) return openMatches(Number(button.dataset.skillId));
});
