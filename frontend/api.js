/**
 * Backend API client. The backend uses cookie-based sessions, so every
 * call needs credentials: "include" - this is a separate origin (backend
 * on :8000, this static site on :8080), so the cookie only round-trips if
 * the backend's CORS_ORIGINS lists this origin with credentials allowed
 * (already configured, see backend/.env.example).
 */

const API_BASE_URL = "http://localhost:8000/api/v1";

async function apiFetch(path, options = {}) {
  const res = await fetch(API_BASE_URL + path, {
    credentials: "include",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    let code = null;
    let details = null;
    try {
      const body = await res.json();
      message = body?.error?.message || message;
      code = body?.error?.code || null;
      details = body?.error?.details || null;
    } catch {
      /* non-JSON error body, keep the generic message */
    }
    const error = new Error(message);
    error.status = res.status;
    error.code = code;
    error.details = details;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}

function formatMoney(amountMinor, currency) {
  const major = amountMinor / 100;
  const language = document.documentElement.lang || "ro";
  const amount = major.toLocaleString(language, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const symbols = { EUR: "€", USD: "$" };
  const symbol = symbols[currency];
  return symbol ? `${symbol} ${amount}` : `${amount} ${currency}`;
}

/** Redirects to login if there's no valid session; returns the user otherwise. */
async function requireSession() {
  try {
    return await apiFetch("/users/me");
  } catch (err) {
    if (err.status === 401) {
      window.location.href = "login.html";
      return null;
    }
    throw err;
  }
}

/**
 * Show/hide toggle for every password field on the page. Looks for
 * `.password-toggle-btn[data-target="<input id>"]` (see register.html,
 * login.html, forgot-password.html, index.html's change-password form for
 * the markup) - wired here, once, so any page just needs the markup and
 * gets the behavior automatically, instead of every page re-wiring it.
 */
function wirePasswordToggles() {
  document.querySelectorAll(".password-toggle-btn").forEach((btn) => {
    const input = document.getElementById(btn.dataset.target);
    if (!input) return;
    btn.addEventListener("click", () => {
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      btn.innerHTML = `<i data-lucide="${showing ? "eye" : "eye-off"}"></i>`;
      if (window.lucide) lucide.createIcons();
    });
  });
}

document.addEventListener("DOMContentLoaded", wirePasswordToggles);
