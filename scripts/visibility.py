#!/usr/bin/env python3
"""
Orbit2 shared visibility service (Improvement Roadmap IR-A1/A2/C1).

Single source of truth for "is this record safe to publish on the public
GitHub Pages site." Extracted from scripts/contacts.py's Contacts Phase 4
implementation (the first feature to build this check, confirmed with
Steve at the time) so every other feature that needs the same decision
imports it from here instead of re-deriving its own copy.

Why this module exists: Objectives and Actions both shipped on the public
site (via scripts/build_web.py) with NO visibility check at all — every
row, regardless of its own `visibility` field, was embedded into
data/web_snapshot.json unfiltered. This was found and confirmed live
during the 2026-07-22 platform assessment: an objective marked
communardo_internal, including a private working note quoting Steve's own
job description, was reachable on the actual public URL. That gap is
exactly the bug class this module exists to prevent recurring — see
docs/data_dictionary.md's "Shared visibility service" section for the
full incident writeup and docs/data_dictionary.md's Objectives/Actions
sections for what's filtered where.

PUBLIC_VISIBILITY_TIERS / is_public_visible() are deliberately simple — a
flat allow-list against the standard visibility scale (personal_only,
communardo_internal, communardo_management, atlassian_shareable,
customer_approved, anonymised, public). A record is public ONLY if its
own `visibility` field is explicitly set to one of the four
sharing-approved tiers; every other value — including blank/missing,
which defaults to the strictest reading — stays private. This is
deliberately the same rule for every entity type today (contacts,
objectives, actions). If a future entity genuinely needs different
tiering semantics, give it its own constant/function here rather than
overloading this one, and update its caller explicitly — don't silently
branch inside is_public_visible() based on entity type.
"""

PUBLIC_VISIBILITY_TIERS = {"atlassian_shareable", "customer_approved", "anonymised", "public"}


def is_public_visible(row):
    """True only if this record's own `visibility` field explicitly marks
    it cleared for external/public sharing (see PUBLIC_VISIBILITY_TIERS
    above). Blank, personal_only, communardo_internal, and
    communardo_management — including every record's usual default — are
    never public. Same rule regardless of entity type; callers pass in
    whatever dict-like row has a `visibility` key (a contacts.csv row, an
    objectives.csv row, an actions.csv row, ...)."""
    return (row.get("visibility") or "") in PUBLIC_VISIBILITY_TIERS
