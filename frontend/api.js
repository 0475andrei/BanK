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
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      message = body?.error?.message || message;
    } catch {
      /* non-JSON error body, keep the generic message */
    }
    const error = new Error(message);
    error.status = res.status;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}

function formatMoney(amountMinor, currency) {
  const major = amountMinor / 100;
  const amount = major.toLocaleString("ro-RO", {
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
