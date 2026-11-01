const $ = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString();

function renderSkills(rows) {
  const max = Math.max(...rows.map((row) => Math.max(row.learners, row.teachers)), 1);
  $("skill-list").innerHTML = rows.map((row, index) => `
    <div class="skill-row">
      <span class="rank">${String(index + 1).padStart(2, "0")}</span>
      <span class="skill-name">${row.skill_name}</span>
      <span class="meta">T ${row.teachers}</span>
      <span class="meta">L ${row.learners}</span>
      <span class="bar"><i style="width:${Math.max(3, row.learners / max * 100)}%"></i></span>
      <span class="gap ${row.demand_gap <= 0 ? "neutral" : ""}">gap ${row.demand_gap > 0 ? "+" : ""}${row.demand_gap}</span>
    </div>`).join("");
  $("open-demand").textContent = number(rows.reduce((sum, row) => sum + Number(row.learners), 0));
  $("teaching-supply").textContent = number(rows.reduce((sum, row) => sum + Number(row.teachers), 0));
  $("exchanges").textContent = number(rows.reduce((sum, row) => sum + Number(row.completed_sessions), 0));
  $("skill-count").textContent = number(rows.length);
}

function renderLeaderboard(rows) {
  $("leaderboard").innerHTML = `<table><thead><tr><th>#</th><th>NAME</th><th>TAUGHT</th><th>LEARNED</th><th>TOTAL</th></tr></thead><tbody>${
    rows.map((row) => `<tr><td>${row.rank}</td><td>${row.name}</td><td>${row.sessions_taught}</td><td>${row.sessions_learned}</td><td>${row.total_sessions}</td></tr>`).join("")
  }</tbody></table>`;
}

function renderActivity(rows) {
  const max = Math.max(...rows.map((row) => Number(row.completed_sessions)), 1);
  $("activity").innerHTML = rows.map((row) => `
    <div class="activity-row"><span>${row.skill_name}<b>${row.completed_sessions}</b></span><span class="bar"><i style="width:${row.completed_sessions / max * 100}%"></i></span></div>`).join("");
}

async function load() {
  try {
    const [health, skills, leaderboard, activity] = await Promise.all([
      fetch("/api/health").then((response) => response.json()),
      fetch("/api/skills").then((response) => response.json()),
      fetch("/api/leaderboard").then((response) => response.json()),
      fetch("/api/activity").then((response) => response.json())
    ]);
    if (health.error || skills.error) throw new Error(health.error || skills.error);
    renderSkills(skills); renderLeaderboard(leaderboard); renderActivity(activity);
    $("status-dot").classList.add("live"); $("status-text").textContent = "postgres live";
    $("server-time").textContent = health.server_time || "connected";
  } catch (error) {
    $("status-text").textContent = "database offline";
    $("server-time").textContent = error.message;
  }
}

$("refresh").addEventListener("click", load);
load();
