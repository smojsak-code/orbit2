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

/* --- Objectives status (R1-T08 instruction #50) ---
 * Read-only. SNAPSHOT.objectives is the same array the Cowork dashboard's
 * Objectives tab renders from, each row already carrying a computed
 * `progress` object (official_pct/raw_pct/overachievement_pct/basis) from
 * scripts/objectives.py's compute_progress(), injected at build time by
 * build_web.py so this view and the dashboard never disagree. Independent
 * of the impact period selector above — an objective's own `period` field
 * (e.g. "2026-Q3") is a fixed assignment, not a rolling window, so it isn't
 * re-filtered by week/month/quarter/year the way journal-derived sections
 * are. */
function impactCategoryBadge(category) {
  const c = category || '';
  const cls = ['relationship', 'commercial', 'strategic', 'operational', 'recognition'].includes(c) ? c : 'uncategorised';
  const label = c || 'uncategorised';
  return `<span class="obj-category-badge obj-category-${cls}">${esc(label)}</span>`;
}

function renderImpactObjectives() {
  const list = document.getElementById('impactObjectivesList');
  if (!list) return;
  const all = SNAPSHOT.objectives || [];
  const categorySel = document.getElementById('impactObjFilterCategory');
  const category = categorySel ? categorySel.value : '';
  const active = all
    .filter(o => o.status === 'on_track' || o.status === 'at_risk')
    .filter(o => !category || o.category === category)
    .sort((a, b) => (a.target_date || '9999-99-99').localeCompare(b.target_date || '9999-99-99'));

  list.innerHTML = '';
  if (!active.length) {
    list.innerHTML = '<div class="home-empty">No active objectives match this filter. Add one from the Objectives tab in Cowork.</div>';
    return;
  }
  active.forEach(o => {
    const p = o.progress || { official_pct: 0, overachievement_pct: 0 };
    const fillClass = o.status === 'at_risk' ? 'at-risk' : '';
    const overBadge = p.overachievement_pct > 0 ? `<span class="obj-over-badge">+${esc(p.overachievement_pct)}% over</span>` : '';
    const row = document.createElement('div');
    row.className = 'obj-status-row';
    row.innerHTML = `
      <div>
        <button type="button" class="obj-name-link obj-title" onclick="openObjectiveDetailModal('${esc(o.objective_id)}')">${esc(o.objective)}</button> ${impactCategoryBadge(o.category)}
        <div class="obj-meta">${esc(o.period)}${o.target_date ? ' · due ' + esc(o.target_date) : ''}</div>
      </div>
      <div class="obj-progress-wrap">
        <div class="obj-progress-track"><div class="obj-progress-fill ${fillClass}" style="width:${p.official_pct}%"></div></div>
        <div class="obj-progress-label">${esc(p.official_pct)}%${overBadge}</div>
      </div>
      <span class="objective-status-pill objective-status-${esc(o.status)}">${esc(o.status.replace('_', ' '))}</span>`;
    list.appendChild(row);
  });
}

function setupImpactObjectivesFilter() {
  const sel = document.getElementById('impactObjFilterCategory');
  if (sel) sel.addEventListener('change', renderImpactObjectives);
}

// --- Objective detail click-through view (2026-07-21) ---
// Same SNAPSHOT.objectives[].detail every objective carries (computed
// once at build time by scripts/objectives.py's compute_objective_detail(),
// shared verbatim with the Cowork dashboard's own detail modal — see
// dashboard.html's renderObjectiveDetailHtml() for the twin implementation
// and its own doc comment). The only difference here: evidence is
// metadata-only (no file download) — the actual evidence_library/ files
// stay inside the private Cowork dashboard, never published to this
// public page. filesAvailable=false below is what drives that.
function objectiveCategoryBadge(category) {
  return impactCategoryBadge(category);
}

function openObjectiveDetailModal(objectiveId) {
  const o = (SNAPSHOT.objectives || []).find(x => x.objective_id === objectiveId);
  if (!o || !o.detail) return;
  document.getElementById('objectiveDetailTitle').textContent = o.detail.objective || objectiveId;
  document.getElementById('objectiveDetailBody').innerHTML = renderObjectiveDetailHtml(o.detail, false);
  document.getElementById('objectiveDetailModalOverlay').classList.add('open');
  document.querySelector('.wrap').setAttribute('inert', '');
  document.addEventListener('keydown', objectiveDetailModalKeydown);
}

function closeObjectiveDetailModal() {
  document.getElementById('objectiveDetailModalOverlay').classList.remove('open');
  document.querySelector('.wrap').removeAttribute('inert');
  document.removeEventListener('keydown', objectiveDetailModalKeydown);
}

function objectiveDetailModalKeydown(e) {
  if (e.key === 'Escape') closeObjectiveDetailModal();
}

function renderObjectiveDetailHtml(d, filesAvailable) {
  const p = d.progress || { official_pct: 0, overachievement_pct: 0, basis: '' };
  const fillClass = d.status === 'completed' ? 'completed' : (d.status === 'at_risk' ? 'at-risk' : '');
  const overBadge = p.overachievement_pct > 0 ? `<span class="obj-over-badge">+${p.overachievement_pct}% over</span>` : '';

  const metaGrid = `
    <div class="obj-detail-meta-grid">
      <div><div class="label">Category</div>${objectiveCategoryBadge(d.category)}</div>
      <div><div class="label">Period</div>${esc(d.period)}</div>
      <div><div class="label">Status</div><span class="objective-status-pill objective-status-${esc(d.status)}">${esc(d.status.replace('_', ' '))}</span></div>
      <div><div class="label">Target date</div>${esc(d.target_date) || '—'}</div>
      <div><div class="label">Target</div>${d.target ? esc(d.target) + ' ' + esc(d.target_unit || '') : '—'}</div>
      <div><div class="label">Communardo priority</div>${esc(d.communardo_priority) || '—'}</div>
      <div><div class="label">Atlassian priority</div>${esc(d.atlassian_priority) || '—'}</div>
      <div><div class="label">Vendor</div>${esc(d.vendor) || '—'}</div>
    </div>`;

  const evidenceHtml = d.linked_evidence.length ? d.linked_evidence.map(e => {
    if (!e.found) return `<div class="obj-evidence-item"><span class="obj-evidence-dangling">${esc(e.evidence_id)} — no longer on file</span></div>`;
    return `<div class="obj-evidence-item">
      <div class="filename">${esc(e.evidence_id)} — ${esc(e.description) || esc(e.filename)}</div>
      <div class="meta">${esc(e.filename)} · ${esc(e.category)} / ${esc(e.sub_metric)} · ${esc(e.quarter)} · added ${esc(e.date_added)} · ${esc(e.status)}</div>
      ${filesAvailable ? '' : `<div class="meta" style="margin-top:4px;">File stays inside the private Cowork dashboard.</div>`}
    </div>`;
  }).join('') : '<div class="empty">No evidence linked yet.</div>';

  const activityHtml = d.linked_activities.length ? d.linked_activities.map(a => {
    if (!a.found) return `<div class="obj-activity-item"><span class="obj-evidence-dangling">${esc(a.activity_id)} — no longer on file</span></div>`;
    const value = a.value && a.value.amount ? `${a.value.amount} ${a.value.currency || ''} (${a.value.status || ''})` : '';
    return `<div class="obj-activity-item">
      <div class="title">${esc(a.title) || a.activity_id}</div>
      <div class="meta">${esc(a.date)} · ${esc(a.type) || ''} ${a.organisation ? '· ' + esc(a.organisation) : ''} ${value ? '· ' + esc(value) : ''}</div>
      ${a.outcome ? `<div style="margin-top:4px;">${esc(a.outcome)}</div>` : ''}
      ${a.next_action ? `<div class="meta" style="margin-top:2px;">Next: ${esc(a.next_action)}</div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">No activities linked yet.</div>';

  const actionPointsHtml = d.action_points.length ? d.action_points.map(a => `
    <div class="obj-action-point">
      <span class="source">${esc(a.source)}${a.date ? ' · ' + esc(a.date) : ''}</span>
      <span>${esc(a.text)}</span>
    </div>`).join('') : '<div class="empty">No open action points.</div>';

  return `
    ${metaGrid}
    <div class="obj-detail-section" style="margin-top:16px;">
      <h4>Progress</h4>
      <div class="obj-progress-wrap" style="min-width:100%;">
        <div class="obj-progress-track"><div class="obj-progress-fill ${fillClass}" style="width:${p.official_pct}%"></div></div>
        <div class="obj-progress-label">${p.official_pct}%${overBadge} — ${esc(p.basis)}</div>
      </div>
    </div>
    <div class="obj-detail-section">
      <h4>Summary</h4>
      <div class="obj-detail-summary">${esc(d.summary_text)}</div>
    </div>
    <div class="obj-detail-section">
      <h4>Evidence (${d.linked_evidence.length})</h4>
      ${evidenceHtml}
    </div>
    <div class="obj-detail-section">
      <h4>Linked activities (${d.linked_activities.length})</h4>
      ${activityHtml}
    </div>
    <div class="obj-detail-section">
      <h4>Action points</h4>
      ${actionPointsHtml}
    </div>
    <div class="obj-generated-note">Generated ${esc(d.generated_at)}</div>`;
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
  renderImpactObjectives();
}

function setupImpactControls() {
  const sel = document.getElementById('impactPeriod');
  if (sel) sel.addEventListener('change', renderImpactView);
}
