/* Shared browser-side helpers for the ShopNest storefront.
 *
 * Every element the automation needs to reach carries a stable
 * data-testid. Those attributes are part of the application's contract
 * with the test suite: renaming one is a breaking change.
 */

const TOKEN_KEY = "shopnest.token";
const USER_KEY = "shopnest.user";

const Session = {
  token: () => localStorage.getItem(TOKEN_KEY),
  user: () => {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || "null");
    } catch (_) {
      return null;
    }
  },
  save(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  const token = Session.token();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, Object.assign({}, options, { headers }));
  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch (_) {
      body = { detail: text };
    }
  }
  if (!response.ok) {
    const message = (body && body.detail) || `Request failed with status ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return body;
}

function money(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

function flash(message, kind = "error") {
  const box = document.querySelector("[data-testid='flash']");
  if (!box) return;
  box.textContent = message;
  box.className = `alert ${kind}`;
  box.hidden = false;
}

function clearFlash() {
  const box = document.querySelector("[data-testid='flash']");
  if (box) {
    box.hidden = true;
    box.textContent = "";
  }
}

/* Marks the page as fully settled. Playwright waits on this instead of
 * sleeping, which is what keeps the UI suite free of flaky timing. */
function markReady(name) {
  document.body.setAttribute("data-page", name);
  document.body.setAttribute("data-ready", "true");
}

function renderNav() {
  const user = Session.user();
  const slot = document.querySelector("[data-testid='nav-session']");
  if (!slot) return;
  if (user) {
    slot.innerHTML = `
      <span class="muted" data-testid="nav-user">${user.email}</span>
      <a href="#" data-testid="nav-logout">Sign out</a>`;
    slot.querySelector("[data-testid='nav-logout']").addEventListener("click", (event) => {
      event.preventDefault();
      Session.clear();
      window.location.href = "/login";
    });
  } else {
    slot.innerHTML = `<a href="/login" data-testid="nav-login">Sign in</a>`;
  }
}

async function refreshCartCount() {
  const badge = document.querySelector("[data-testid='cart-count']");
  if (!badge) return;
  if (!Session.token()) {
    badge.textContent = "0";
    return;
  }
  try {
    const cart = await api("/api/cart");
    badge.textContent = String(cart.items.reduce((sum, item) => sum + item.quantity, 0));
  } catch (_) {
    badge.textContent = "0";
  }
}

function requireLogin() {
  if (!Session.token()) {
    window.location.href = "/login";
    return false;
  }
  return true;
}

document.addEventListener("DOMContentLoaded", () => {
  renderNav();
  refreshCartCount();
});
