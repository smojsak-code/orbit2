/*
 * Orbit2 My Impact dashboard (R1-T07)
 *
 * Public-site-only, per the roadmap's own "Primary files/components" list
 * for this task — the Cowork dashboard's Dashboard tab is untouched, same
 * literal-scope pattern as R1-T06's home.js.
 *
 * Reads SNAPSHOT.impact, which scripts/build_web.py's
 * compute_impact_aggregates() (scripts/impact.py) precomputes at build time
 * — five categories (relationship/commercial/strategic/operational plus the
 * cross-cutting recognition view), a five-way financial breakdown that is
 * never combined across status or currency, and a deterministic narrative
 * paragraph. This file only renders what's already there.
 *
 * Depends on globals defined in the main inline <script> in
 * web/index_template.html: SNAPSHOT, esc(), money(), switchView().
 * Loaded with `defer`, so by the time SNAPSHOT is populated (inside the
 * fetch().then() callback) every function below is already defined.
 */

const IMPACT_CATEGORIES = ['relationship', 'commercial', 'strategic', 'operational'];
const IMPACT_RECOGNITION_STATUSES = ['unrecognised', 'logged', 'shared', 'acknowledged'];
const IMPACT_RECOGNITION_LABELS = {
  unrecognised: 'Unrecognised', logged: 'Logged', shared: 'Shared', acknowledged: 'Acknowledged',
};
const IMPACT_VALUE_STATUS_LABELS = {
  confirmed: 'Confirmed', estimated: 'Estimated', protected: 'Protected', potential: 'Potential',
};

function impactListItem(titleHtml, metaHtml) {
  const div = document.createElement('div');
  div.className = 'home-list-item';
  div.style.cursor = 'default';
  div.innerHTML = `<div class="title-row"><span>${titleHtml}</span></div><div class="meta-row">${metaHtml}</div>`;
  return div;
}

function renderImpactCategoryBlock(categoryKey, block) {
  const badge = document.getElementById('impactBadge-' + categoryKey);
  badge.textContent = String(block.count);
  badge.classList.toggle('zero', block.count === 0);

  const breakdown = document.getElementById('impactBreakdown-' + categoryKey);
  breakdown.innerHTML = '';
  Object.entries(block.contribution_type_counts || {}).forEach(([ct, n]) => {
    const chip = document.createElement('span');
    chip.className = 'impact-chip';
    chip.textContent = `${ct}: ${n}`;
    breakdown.appendChild(chip);
  });
  if (block.count) {
    const evChip = document.createElement('span');
    evChip.className = 'impact-chip';
    evChip.textContent = `${block.evidence_coverage_pct}% evidenced`;
    breakdown.appendChild(evChip);
  }

  const list = document.getElementById('impactList-' + categoryKey);
  list.innerHTML = '';
  if (!block.count) {
    list.innerHTML = '<div class="home-empty">Nothing logged in this category for this period.</div>';
    return;
  }
  block.entries.slice(0, 6).forEach(e => {
    list.appendChild(impactListItem(
      esc(e.title),
      `${esc(e.date || '')} · ${esc(e.contribution_type || 'unspecified')}${e.organisation ? ' · ' + esc(e.organisation) : ''}${e.value_amount ? ' · ' + money(e.value_amount, e.value_currency) + ' (' + esc(e.value_status || '') + ')' : ''}`
    ));
  });
  if (block.entries.length > 6) {
    const more = document.createElement('div');
    more.className = 'home-empty';
    more.textContent = `+ ${block.entries.length - 6} more logged this period.`;
    list.appendChild(more);
  }
}

function renderImpactRecognitionBlock(recognition) {
  const breakdown = document.getElementById('impactBreakdown-recognition');
  breakdown.innerHTML = '';
  IMPACT_RECOGNITION_STATUSES.forEach(status => {
    const n = (recognition.by_status[status] || { count: 0 }).count;
    const chip = document.createElement('span');
    chip.className = 'impact-chip';
    chip.textContent = `${IMPACT_RECOGNITION_LABELS[status]}: ${n}`;
    breakdown.appendChild(chip);
  });

  const list = document.getElementById('impactList-recognition');
  list.innerHTML = '';
  const unrecognised = (recognition.by_status.unrecognised || { entries: [] }).entries;
  if (!unrecognised.length) {
    list.innerHTML = '<div class="home-empty">Nothing unrecognised right now.</div>';
    return;
  }
  unrecognised.slice(0, 6).forEach(e => {
    list.appendChild(impactListItem(
      esc(e.title),
      `${esc(e.date || '')} · worth flagging up${e.value_amount ? ' · ' + money(e.value_amount, e.value_currency) : ''}`
    ));
  });
}

function renderImpactFinancial(financial) {
  const rows = document.getElementById('impactFinancialRows');
  rows.innerHTML = '';

  const statusesWithAmounts = Object.keys(IMPACT_VALUE_STATUS_LABELS).filter(
    s => financial.by_status[s] && Object.keys(financial.by_status[s]).length
  );

  if (!statusesWithAmounts.length && !Object.keys(financial.awaiting_validation || {}).length) {
    rows.innerHTML = '<div class="home-empty">No financial value logged against contributions this period.</div>';
    document.getElementById('impactFinancialNote').textContent = '';
    return;
  }

  statusesWithAmounts.forEach(status => {
    Object.entries(financial.by_status[status]).forEach(([currency, amount]) => {
      const row = document.createElement('div');
      row.className = 'impact-fin-row';
      row.innerHTML = `<span class="impact-fin-label">${esc(IMPACT_VALUE_STATUS_LABELS[status])} (${financial.counts_by_status[status]})</span><span class="impact-fin-amount">${esc(money(amount, currency))}</span>`;
      rows.appendChild(row);
    });
  });
  Object.entries(financial.awaiting_validation || {}).forEach(([currency, amount]) => {
    const row = document.createElement('div');
    row.className = 'impact-fin-row';
    row.innerHTML = `<span class="impact-fin-label">Awaiting validation (${financial.awaiting_validation_count})</span><span class="impact-fin-amount">${esc(money(amount, currency))}</span>`;
    rows.appendChild(row);
  });

  document.getElementById('impactFinancialNote').textContent =
    'Each figure is a separate total for its status and currency — never combined or netted against another. "Awaiting validation" is the subset of the above with unverified confidence.';
}

function renderImpactView() {
  if (!SNAPSHOT || !SNAPSHOT.impact) return;
  const impact = SNAPSHOT.impact;
  const periodSel = document.getElementById('impactPeriod');
  const period = (periodSel && periodSel.value) || 'quarter';
  const agg = impact.by_period[period];
  if (!agg) return;

  document.getElementById('impactNarrative').textContent = agg.narrative || '';

  IMPACT_CATEGORIES.forEach(cat => renderImpactCategoryBlock(cat, agg.categories[cat]));
  renderImpactRecognitionBlock(agg.recognition);
  renderImpactFinancial(agg.financial);
}

function setupImpactControls() {
  const sel = document.getElementById('impactPeriod');
  if (sel) sel.addEventListener('change', renderImpactView);
}
