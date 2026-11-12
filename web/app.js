import { api, post, setCsrfToken } from "./api.js";
import {
  $,
  renderSkills,
  renderTotals,
  renderLeaderboard,
  renderActivity,
  renderProfile,
  populateSkillChoices,
  renderModerator,
  renderRequests,
  renderMySkills,
  renderMatches,
  renderLearningPrompt,
  renderReportPeople,
} from "./views.js";

let skills = [];
let currentUser = null;
let matchGeneration = 0;

function message(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle("error", error);
}

function closeProfileMenu() {
  $("profile-menu").hidden = true;
  $("profile-button").setAttribute("aria-expanded", "false");
}

function showPage(focus = false) {
  const requested = location.hash.slice(1) || "discover";
  const link = [...document.querySelectorAll(".dashboard-nav a")].find(
    (item) => item.hash === `#${requested}` && !item.hidden,
  );
  const page = link ? requested : "discover";
  document.querySelectorAll("[data-page-panel]").forEach((panel) => {
    panel.hidden = panel.id !== page;
  });
  document.querySelectorAll(".dashboard-nav a").forEach((item) => {
    if (item.hash === `#${page}`) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  if (focus && currentUser) {
    const heading = $(page).querySelector("h1, h2");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
}

function setCurrentUser(user) {
  const changed = currentUser?.user_id !== user?.user_id;
  currentUser = user;
  setCsrfToken(user?.csrf_token);
  renderProfile(user);
  $("login-panel").hidden = Boolean(user);
  $("dashboard").hidden = !user;
  $("moderator-setup").hidden = Boolean(user);
  $("logout-button").hidden = !user;
  $("login-button").hidden = Boolean(user);
  $("moderator-link").hidden = user?.role !== "admin";
  if (changed) {
    $("match-drawer").hidden = true;
    matchGeneration++;
  }
  $("community-report").hidden = !user || user.role === "admin";
  showPage();
  if (user) {
    loadMySkills();
    loadRequests();
    if (user.role !== "admin") api("/api/users").then(renderReportPeople).catch((error) => showError("community-report-message", error));
    if (user.role === "admin") loadModerator();
  }
}

function showError(id, error) {
  if (error.status === 401 && currentUser) {
    setCurrentUser(null);
    closeProfileMenu();
    message("auth-error", "Your session ended. Sign in again.", true);
    $("auth-email").focus();
  } else message(id, error.message, true);
}

async function runAction(control, action) {
  const target = control.closest("form, section");
  const output =
    target?.id === "moderator-panel"
      ? $("moderator-message")
      : target?.querySelector('[role="alert"], [role="status"], .form-message');
  const button = control.matches("button")
    ? control
    : control.querySelector('button[type="submit"]');
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  try {
    await action();
  } catch (error) {
    if (output) showError(output.id, error);
    else window.alert(error.message);
  } finally {
    if (button) {
      button.disabled = Boolean(button.dataset.completed);
      button.removeAttribute("aria-busy");
    }
  }
}

function on(id, type, action) {
  $(id).addEventListener(type, (event) => {
    const control =
      type === "submit" ? $(id) : event.target.closest("button") || $(id);
    runAction(control, () => action(event));
  });
}

function filterSkills() {
  const term = $("skill-search").value.trim().toLowerCase();
  renderSkills(
    skills.filter((skill) =>
      `${skill.skill_name} ${skill.category_name}`.toLowerCase().includes(term),
    ),
  );
}

async function loadMySkills() {
  message("my-skills-list", "Loading your skills…");
  try {
    renderMySkills(await api("/api/my-skills"));
  } catch (error) {
    showError("my-skills-list", error);
  }
}

async function loadRequests() {
  message("requests", "Loading your requests…");
  try {
    renderRequests(await api("/api/requests"), currentUser);
  } catch (error) {
    showError("requests", error);
  }
}

async function loadModerator() {
  message("moderator-message", "Loading moderation data…");
  try {
    renderModerator(await api("/api/moderation"));
    message("moderator-message", "");
  } catch (error) {
    showError("moderator-message", error);
  }
}

async function openMatches(skillId) {
  if (!currentUser) return;
  const generation = ++matchGeneration;
  const skill = skills.find((item) => item.skill_id === skillId);
  $("match-drawer").hidden = false;
  $("match-title").textContent = `Teachers for ${skill.skill_name}`;
  message("match-message", "");
  message("match-list", "Finding teachers…");
  $("match-title").focus({ preventScroll: true });
  $("match-drawer").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const mySkills = await api("/api/my-skills");
    if (generation !== matchGeneration) return;
    if (
      !mySkills.some(
        (item) => item.skill_id === skillId && item.skill_type === "LEARN",
      )
    ) {
      $("match-help").textContent = "Start with something you’d like to learn.";
      renderLearningPrompt(skill);
      return;
    }
    $("match-help").textContent =
      "Send a request to start an exchange. Follow its status in Requests.";
    const rows = await api(`/api/matches?skill_id=${skillId}`);
    if (generation !== matchGeneration) return;
    renderMatches(rows.filter((row) => row.matched_skill_id === skillId));
  } catch (error) {
    if (generation === matchGeneration) showError("match-list", error);
  }
}

async function startLearning(skillId) {
  const skill = skills.find((item) => item.skill_id === skillId);
  await post("/api/user-skills", {
    skill_id: skillId,
    skill_type: "LEARN",
    proficiency_level: "beginner",
    description: `I want to learn ${skill.skill_name}.`,
  });
  await openMatches(skillId);
  loadMySkills();
  skills = await api("/api/skills");
  filterSkills();
  renderTotals(skills);
}

async function createRequest(button) {
  const result = await post("/api/requests", {
    requester_id: currentUser.user_id,
    provider_id: Number(button.dataset.provider),
    skill_id: Number(button.dataset.skill),
    similarity_score: Number(button.dataset.similarity),
  });
  button.dataset.completed = "true";
  button.textContent = "Request sent";
  message(
    "match-message",
    `Request #${result.request_id} sent. You can follow its status in Requests.`,
  );
  loadRequests();
}

async function authenticate(path) {
  message("auth-error", "");
  const body = {
    email: $("auth-email").value.trim(),
    password: $("auth-password").value,
  };
  if (!$("auth-email").reportValidity() || !$("auth-password").reportValidity())
    return;
  if (path === "/api/register") {
    body.name = $("auth-name").value.trim();
    if (!body.name) {
      message("auth-error", "Add your name to create an account.", true);
      $("auth-name").focus();
      return;
    }
  }
  const user = await post(path, body);
  $("auth-password").value = "";
  location.hash = "discover";
  setCurrentUser(user);
  showPage(true);
}

async function moderatorAction(action, id, status) {
  if (
    ["delete-user", "delete-feedback", "ban-user"].includes(action) &&
    !window.confirm("Apply this action to the selected record?")
  )
    return;
  const target = {
    "delete-user": "user_id",
    "ban-user": "user_id",
    "unban-user": "user_id",
    "delete-feedback": "feedback_id",
    "request-status": "request_id",
    "slot-status": "slot_id",
    "report-status": "report_id",
    "session-status": "session_id",
  }[action];
  await post("/api/moderation", { action, [target]: Number(id), status });
  await loadModerator();
  message("moderator-message", "Moderation change saved.");
}

async function load() {
  message("catalogue-message", "Refreshing skills…");
  try {
    const [health, catalogue, leaderboard, activity, user] = await Promise.all([
      api("/api/health"),
      api("/api/skills"),
      api("/api/leaderboard"),
      api("/api/activity"),
      api("/api/me"),
    ]);
    skills = catalogue;
    populateSkillChoices(skills);
    setCurrentUser(user);
    filterSkills();
    renderTotals(skills);
    renderLeaderboard(leaderboard);
    renderActivity(activity);
    message("catalogue-message", "");
    $("status-dot").classList.add("live");
    message("status-text", "Connected");
    $("server-time").textContent = health.server_time;
  } catch (error) {
    $("status-dot").classList.remove("live");
    message("status-text", "Connection problem");
    showError("catalogue-message", error);
  }
}

on("auth-form", "submit", (event) => {
  event.preventDefault();
  return authenticate("/api/login");
});
on("register-button", "click", () => authenticate("/api/register"));
on("refresh", "click", load);
on("load-requests", "click", loadRequests);
on("refresh-my-skills", "click", loadMySkills);
on("refresh-moderator", "click", loadModerator);
on("skill-search", "input", filterSkills);
on("close-matches", "click", () => {
  $("match-drawer").hidden = true;
  matchGeneration++;
  $("skill-search").focus();
});
on("skill-list", "click", (event) => {
  const button = event.target.closest(".skill-button");
  if (button) return openMatches(Number(button.dataset.skillId));
});
on("match-list", "click", (event) => {
  const learn = event.target.closest("[data-start-learning]");
  if (learn) return startLearning(Number(learn.dataset.startLearning));
  const request = event.target.closest(".request-button");
  if (request) return createRequest(request);
});
$("moderator-panel").addEventListener("click", (event) => {
  const button = event.target.closest("[data-mod-action]");
  if (button)
    runAction(button, () =>
      moderatorAction(
        button.dataset.modAction,
        button.dataset.id,
        button.dataset.status,
      ),
    );
});
on("moderator-setup-form", "submit", async (event) => {
  event.preventDefault();
  await post("/api/moderator/setup", {
    code: $("moderator-setup-code").value,
    password: $("moderator-setup-password").value,
  });
  event.target.reset();
  message(
    "moderator-setup-message",
    "Moderator activated. Sign in as arjun@campus.edu.",
  );
});
on("moderator-user-form", "submit", async (event) => {
  event.preventDefault();
  await post("/api/moderation", {
    action: "set-role",
    user_id: Number($("moderator-user-id").value),
    role: $("moderator-user-role").value,
  });
  message("moderator-user-message", "Role saved.");
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
  message("moderator-skill-message", "Skill created.");
  event.target.reset();
  loadModerator();
  await load();
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
  message("moderator-slot-message", "Slot created.");
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
  message.classList.remove("error");
  $("skill-form").reset();
  await load();
});

on("profile-button", "click", () => {
  const open = $("profile-menu").hidden;
  $("profile-menu").hidden = !open;
  $("profile-button").setAttribute("aria-expanded", String(open));
});
on("login-button", "click", () => {
  closeProfileMenu();
  $("auth-email").focus();
});
on("logout-button", "click", async () => {
  await post("/api/logout", {});
  setCurrentUser(null);
  closeProfileMenu();
  message("auth-error", "");
  $("auth-email").focus();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("profile-menu").hidden) {
    closeProfileMenu();
    $("profile-button").focus();
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".header-actions")) closeProfileMenu();
  const button = event.target.closest(".report-abuse");
  if (!button) return;
  const reason = window.prompt("Describe the abuse (up to 1000 characters):");
  if (reason === null) return;
  runAction(button, async () => {
    await post("/api/reports", {
      reported_user_id: Number(button.dataset.userId),
      reason,
    });
    window.alert("Report sent to the moderator.");
  });
});
window.addEventListener("hashchange", () => showPage(true));
load();

on("community-report-form", "submit", async (event) => {
  event.preventDefault();
  await post("/api/reports", {reported_user_id: Number($("report-person").value), reason: $("report-reason").value});
  event.target.reset();
  message("community-report-message", "Report sent to the moderator.");
});
