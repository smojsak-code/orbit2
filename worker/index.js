/*
 * Orbit2 access gate (2026-07-22, Steve's request to lock the public site
 * behind a login while still being reachable from anywhere).
 *
 * Uses plain HTTP Basic Authentication — the browser's own native
 * username/password prompt. Chosen over a custom login page because it
 * needs no session/cookie code, works identically on desktop and mobile
 * browsers, and every browser already knows how to remember it. The
 * "username" field is where Steve types his email; "password" is the
 * shared password. Cloudflare stores both as encrypted Secrets set in the
 * dashboard (Settings -> Variables and Secrets) — this file never sees or
 * stores the actual values, only compares against them at request time.
 *
 * run_worker_first is set to true in wrangler.jsonc specifically so THIS
 * check runs before any static file (including data/web_snapshot.json and
 * reports/*) is served — without that setting, Cloudflare serves static
 * assets directly and this file would never even run. See
 * wrangler.jsonc's own comment for why that matters.
 *
 * public_site/ (what env.ASSETS serves) is a curated allowlist built by
 * scripts/stage_public_site.py — it does NOT contain the raw data/*.csv
 * files, old superseded reports, or the Cowork dashboard artifacts. This
 * gate protects that folder; it was never meant to be the only line of
 * defence for the rest of the repo, which simply isn't copied in here.
 */

function timingSafeEqual(a, b) {
  // Plain string comparison leaks timing information (how many leading
  // characters matched) that could theoretically help a remote attacker
  // guess the password faster. This is a low-stakes single-user tool, not
  // a bank, but a constant-time compare costs nothing here, so use one.
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

function unauthorized() {
  return new Response("Authentication required.", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Orbit2", charset="UTF-8"',
      "Content-Type": "text/plain",
    },
  });
}

export default {
  async fetch(request, env) {
    const expectedEmail = env.AUTH_EMAIL;
    const expectedPassword = env.AUTH_PASSWORD;

    if (!expectedEmail || !expectedPassword) {
      // Misconfiguration — the secrets haven't been set in Cloudflare yet.
      // Fail closed (deny), never fail open.
      return new Response(
        "Orbit2 access gate is not configured yet — set the AUTH_EMAIL and AUTH_PASSWORD secrets in the Cloudflare dashboard (Workers & Pages -> orbit2 -> Settings -> Variables and Secrets).",
        { status: 503, headers: { "Content-Type": "text/plain" } }
      );
    }

    const authHeader = request.headers.get("Authorization") || "";
    if (!authHeader.startsWith("Basic ")) {
      return unauthorized();
    }

    let email = "";
    let password = "";
    try {
      const decoded = atob(authHeader.slice(6));
      const sep = decoded.indexOf(":");
      email = decoded.slice(0, sep);
      password = decoded.slice(sep + 1);
    } catch (e) {
      return unauthorized();
    }

    const emailOk = timingSafeEqual(email, expectedEmail);
    const passwordOk = timingSafeEqual(password, expectedPassword);
    if (!emailOk || !passwordOk) {
      return unauthorized();
    }

    // Authenticated — hand the request to the static asset set.
    return env.ASSETS.fetch(request);
  },
};
