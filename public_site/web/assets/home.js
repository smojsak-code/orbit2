/*
 * Orbit2 Daily Alliance Manager homepage (R1-T06)
 *
 * Public-site-only, per the roadmap's own "Primary files/components" list
 * for this task — the Cowork dashboard's Dashboard tab is untouched.
 *
 * Reads SNAPSHOT.homepage, which scripts/build_web.py's
 * compute_homepage_aggregates() precomputes at build time (overdue/due-soon
 * actions, per-vendor metrics-at-risk/missing-evidence, and journal-derived
 * sections pre-bucketed by period). This file only renders what's already
 * there — it does no aggregation of its own, matching instruction #39
 * ("publish only the calculated view data needed by the page").
 *
 * Depends on globals defined in the main inline <script> in
 * web/index_template.html: SNAPSHOT, esc(), switchView(), openActivityModal().
 * Loaded with `defer`, so by the time SNAPSHOT is populated (inside the
 * fetch().then() callback, necessarily after full document parse) every
 * function below is already defined.
 */

function homeUnavailableNotice(actionLabel) {
  const el = document.getElementById('homeNotice');
  el.textContent = `${actionLabel} isn't available on this read-only public site — open the Orbit2 workspace in Cowork and ask Claude to do this there.`;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 6000);
}

function goToCategory(categoryKey) {
  switchView('dashboard');
  setTimeout(() => {
    const card = document.getElementById('catCard-' + categoryKey);
    if (!card) return;
    card.classList.add('open');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 50);
}

function goToActionsFiltered(duePeriod) {
  switchView('actions');
  const statusSel = document.getElementById('actFilterStatus');
  const periodSel = document.getElementById('actFilterDuePeriod');
  if (statusSel) statusSel.value = 'open_all';
  if (periodSel) periodSel.value = duePeriod;
  if (typeof renderActionsView === 'function') renderActionsView();
}

function homeListItem(titleHtml, metaHtml, onclick) {
  const div = document.createElement('div');
  div.className = 'home-list-item';
  div.innerHTML = `<div class="title-row"><span>${titleHtml}</span></div><div class="meta-row">${metaHtml}</div>`;
  // IR-D2 (2026-07-22): only rows with a real onclick are interactive —
  // give those (and only those) keyboard access, matching the assessment's
  // "every clickable non-button/link element is reachable via keyboard".
  if (onclick) {
    div.style.cursor = 'pointer';
    div.setAttribute('role', 'button');
    div.setAttribute('tabindex', '0');
    div.addEventListener('click', onclick);
    div.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
        ev.preventDefault();
        onclick(ev);
      }
    });
  }
  return div;
}

function setBadge(id, count, warnIfNonZero) {
  const el = document.getElementById(id);
  el.textContent = String(count);
  el.classList.toggle('zero', count === 0);
  el.classList.toggle('warn', warnIfNonZero && count > 0);
}

function renderHomeActionSection(listId, badgeId, actions, emptyText, duePeriod) {
  const list = document.getElementById(listId);
  setBadge(badgeId, actions.length, true);
  list.innerHTML = '';
  if (!actions.length) {
    list.innerHTML = `<div class="home-empty">${emptyText}</div>`;
    return;
  }
  actions.slice(0, 6).forEach(a => {
    const item = homeListItem(
      esc(a.description),
      `Due ${esc(a.due_date || 'no date')} · ${esc(a.priority || 'medium')} · ${esc(a.owner || '')}`,
      () => goToActionsFiltered(duePeriod)
    );
    list.appendChild(item);
  });
  if (actions.length > 6) {
    const more = document.createElement('div');
    more.className = 'home-list-item';
    more.style.cursor = 'pointer';
    more.style.color = '#2563eb';
    more.style.fontWeight = '600';
    more.textContent = `+ ${actions.length - 6} more — view all in Actions`;
    more.setAttribute('role', 'button');
    more.setAttribute('tabindex', '0');
    const goMore = () => goToActionsFiltered(duePeriod);
    more.addEventListener('click', goMore);
    more.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
        ev.preventDefault();
        goMore();
      }
    });
    list.appendChild(more);
  }
}

function renderHomeJournalSection(entries, total) {
  const list = document.getElementById('homeJournalList');
  setBadge('homeJournalBadge', total, false);
  list.innerHTML = '';
  if (!entries.length) {
    list.innerHTML = '<div class="home-empty">Nothing logged for this period yet. Use "+ Add Activity" above to capture what happened — it takes under a minute.</div>';
    return;
  }
  entries.forEach(e => {
    list.appendChild(homeListItem(
      esc(e.title),
      `${esc(e.date || '')} · ${esc(e.type || '')}${e.organisation ? ' · ' + esc(e.organisation) : ''}`
    ));
  });
}

function renderHomeValueSection(entries) {
  const list = document.getElementById('homeValueList');
  setBadge('homeValueBadge', entries.length, true);
  list.innerHTML = '';
  if (!entries.length) {
    list.innerHTML = '<div class="home-empty">No value delivered this period is sitting unrecognised — nothing to chase.</div>';
    return;
  }
  entries.forEach(e => {
    list.appendChild(homeListItem(
      esc(e.title),
      `${money(e.value_amount, e.value_currency)} · ${esc(e.value_status || '')} · ${esc(e.date || '')}`
    ));
  });
}

function renderHomeFollowupsSection(entries) {
  const list = document.getElementById('homeFollowupsList');
  setBadge('homeFollowupsBadge', entries.length, true);
  list.innerHTML = '';
  if (!entries.length) {
    list.innerHTML = '<div class="home-empty">Every logged next step has a tracked action, or nothing\'s been logged yet. Nothing to turn into an action right now.</div>';
    return;
  }
  entries.forEach(e => {
    const item = homeListItem(
      esc(e.next_action),
      `from "${esc(e.title)}" · ${esc(e.date || '')} — click to create an action for this`
    );
    item.addEventListener('click', () => openActionModal(e.next_action));
    list.appendChild(item);
  });
}

function renderHomeRiskSection(atRisk) {
  const list = document.getElementById('homeRiskList');
  setBadge('homeRiskBadge', atRisk.length, true);
  list.innerHTML = '';
  if (!atRisk.length) {
    list.innerHTML = '<div class="home-empty">No measured sub-metric is currently below 70. Nothing at risk right now.</div>';
    return;
  }
  atRisk.forEach(m => {
    list.appendChild(homeListItem(
      esc(m.sub_metric),
      `${esc(m.category_label)} · ${esc(m.actual)} / ${esc(m.target)} ${esc(m.unit)} · score ${m.score}`,
      () => goToCategory(m.category_key)
    ));
  });
}

function renderHomeEvidenceSection(missing) {
  const list = document.getElementById('homeEvidenceList');
  setBadge('homeEvidenceBadge', missing.length, true);
  list.innerHTML = '';
  if (!missing.length) {
    list.innerHTML = '<div class="home-empty">Every measured sub-metric has active evidence on file. Nothing missing right now.</div>';
    return;
  }
  missing.forEach(m => {
    list.appendChild(homeListItem(
      esc(m.sub_metric),
      `${esc(m.category_label)} · reported ${esc(m.actual)} ${esc(m.unit)} but no active evidence — add it from Cowork`,
      () => goToCategory(m.category_key)
    ));
  });
}

function renderHomeView() {
  if (!SNAPSHOT || !SNAPSHOT.homepage) return;
  const hp = SNAPSHOT.homepage;
  const period = document.getElementById('homePeriod').value || 'month';
  const periodData = hp.by_period[period] || { recent_journal: [], recent_journal_total: 0, unrecognised_value: [] };

  renderHomeActionSection('homeOverdueList', 'homeOverdueBadge', hp.overdue_actions || [], 'Nothing overdue. Good place to be.', 'overdue');
  renderHomeActionSection('homeDueSoonList', 'homeDueSoonBadge', hp.due_soon_actions || [], 'Nothing due in the next 7 days.', 'due_soon');
  renderHomeJournalSection(periodData.recent_journal || [], periodData.recent_journal_total || 0);
  renderHomeValueSection(periodData.unrecognised_value || []);
  renderHomeFollowupsSection(hp.followups_due || []);

  const vendor = currentVendor || (document.getElementById('vendorSelect') && document.getElementById('vendorSelect').value);
  const vendorHome = (hp.per_vendor && hp.per_vendor[vendor]) || { metrics_at_risk: [], missing_evidence: [] };
  renderHomeRiskSection(vendorHome.metrics_at_risk || []);
  renderHomeEvidenceSection(vendorHome.missing_evidence || []);
}

function setupHomeControls() {
  document.getElementById('homePeriod').addEventListener('change', renderHomeView);
}

/* --- Add Action modal (R1-T06) — standalone action, no linked activity --- */

function openActionModal(prefillDescription) {
  document.getElementById('actionModalOverlay').classList.add('open');
  document.getElementById('actionForm').style.display = '';
  document.getElementById('actionSuccess').classList.remove('show');
  document.querySelector('.wrap').setAttribute('inert', '');
  document.addEventListener('keydown', actionModalKeydown);
  if (prefillDescription) document.getElementById('actnDescription').value = prefillDescription;
  document.getElementById('actnDescription').focus();
}

function closeActionModal() {
  document.getElementById('actionModalOverlay').classList.remove('open');
  document.querySelector('.wrap').removeAttribute('inert');
  document.removeEventListener('keydown', actionModalKeydown);
  document.getElementById('actionForm').reset();
  document.getElementById('actionForm').style.display = '';
  document.getElementById('actionSuccess').classList.remove('show');
  document.getElementById('fieldActDescription').classList.remove('error');
}

function actionModalKeydown(e) {
  if (e.key === 'Escape') closeActionModal();
}

function submitActionForm(evt) {
  evt.preventDefault();
  const description = document.getElementById('actnDescription').value.trim();
  document.getElementById('fieldActDescription').classList.toggle('error', !description);
  if (!description) {
    document.getElementById('actnDescription').focus();
    return false;
  }

  const requestId = 'CR-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 6);
  const changeRequest = {
    request_id: requestId,
    created_at: new Date().toISOString(),
    type: 'action_create',
    action: {
      description,
      due_date: document.getElementById('actnDueDate').value || null,
      priority: document.getElementById('actnPriority').value || 'medium',
      dependency: document.getElementById('actnDependency').value.trim(),
      expected_impact: document.getElementById('actnExpectedImpact').value.trim(),
      related_metric: document.getElementById('actnRelatedMetric').value.trim(),
      visibility: document.getElementById('actnVisibility').value,
      evidence_required: document.getElementById('actnEvidenceRequired').checked,
      vendor: (SNAPSHOT && SNAPSHOT.app_config && SNAPSHOT.app_config.default_vendor) || undefined,
    },
  };
  const json = JSON.stringify(changeRequest, null, 2);

  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `action-${requestId}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);

  document.getElementById('actionForm').style.display = 'none';
  document.getElementById('actionSuccessJson').value = json;
  document.getElementById('actionSuccess').classList.add('show');
  document.getElementById('actionSuccess').querySelector('.btn-primary').focus();
  return false;
}
