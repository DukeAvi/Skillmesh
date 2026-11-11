let csrfToken = null;

export function setCsrfToken(token) {
  csrfToken = token || null;
}

export async function api(path, options = {}) {
  const headers = { ...options.headers };
  if ((options.method || "GET").toUpperCase() !== "GET" && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("Could not reach SkillMesh. Please try again.");
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      "The server returned an unreadable response. Please try again.",
    );
  }
  if (!response.ok)
    throw new Error(data?.error || `Request failed (${response.status}).`);
  return data;
}

export function post(path, payload) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
