# Knowledge Transfer Policy
**Version:** 1.0
**Effective From:** 2025-01-01
**Owner:** Human Resources / Engineering Leadership

---

## 1. Purpose

This policy covers knowledge transfer (KT) during the notice period — the `KT_PLANNING` and `KT_EXECUTION` stages of the offboarding workflow. It defines what must be documented, who signs it off, and what happens when coverage is incomplete.

---

## 2. Scope

All exiting employees. The depth expected scales with the role: an individual contributor documents their own systems and open work; a manager or tech lead additionally documents team processes, vendor relationships, and in-flight decisions.

---

## 3. KT Planning

KT planning begins immediately after the manager acknowledges the resignation and should complete within the **first third of the notice period**.

During planning the manager and the exiting employee jointly produce a KT record listing every topic that needs transferring. Each topic is one discrete area of ownership — a service, a recurring process, a vendor relationship, a body of institutional context.

A good topic list is specific. "Backend systems" is not a topic; "the nightly reconciliation job, including its failure modes and who to call when it breaks" is.

---

## 4. Successor Nomination

The manager nominates a successor for each KT topic. The successor may differ per topic, and may be:

- A named individual taking over the work permanently
- An interim owner holding it until a replacement is hired
- The manager themselves, where no one else is available

A topic without a named successor cannot be marked verified. Where no successor exists by the midpoint of the notice period, the manager must escalate to their department head.

---

## 5. What Must Be Documented

For every topic the exiting employee documents:

1. **Systems owned** — what it is, where it runs, how it is deployed
2. **Credentials and access** — which accounts, vaults, and permissions are involved, never the secrets themselves
3. **Runbooks** — routine operation, and recovery steps for known failure modes
4. **Open work** — in-flight items, their state, and what "done" looks like
5. **Key contacts** — internal stakeholders and external vendors, with context on each relationship
6. **Institutional context** — decisions taken, alternatives rejected, and why

Credentials are handed over through the approved secrets manager. Passwords, API keys, and tokens are never written into KT documents, email, or chat.

---

## 6. KT Execution

Execution is the working handover: sessions between the exiting employee and each successor, walking through the documented material against the real systems.

| Item | Standard |
|---|---|
| Session format | Live walkthrough, screen shared, successor driving where practical |
| Recommended | Successor performs the task with the leaver observing, not the reverse |
| Evidence | Each session recorded against its KT topic in the platform |
| Completion | All topics marked `verified` or explicitly accepted as a gap |

---

## 7. Coverage Status

Each KT topic carries one of three statuses:

| Status | Meaning |
|---|---|
| `pending` | Documented but not yet walked through with the successor |
| `verified` | Successor has confirmed they can operate independently |
| `gap` | Known shortfall, consciously accepted and escalated |

---

## 8. Who Can Mark a Topic Verified

**The exiting employee cannot mark their own KT topics `verified` or `gap`.** Only the reporting manager or HR can. This is enforced by the platform, not by convention.

The reason is straightforward: verification is an assertion that someone else can now do the work. Only the receiving side can credibly make that claim, and the exiting employee has an obvious interest in clearing their own checklist.

---

## 9. Handling Gaps

A gap is not a failure — an honest gap is far more useful than a false verification. Where a topic cannot be fully transferred in the time available, the manager records it as a gap with:

- What specifically is not covered
- The operational risk if it surfaces after the last working day
- The interim mitigation and who owns it

Gaps are visible to HR and surface in the manager's review. A case may complete with recorded gaps; it may not complete with topics silently left pending.

---

## 10. Automated KT Review

Uploaded KT documents are analysed by the platform's KT Document Reviewer, which identifies topics that appear thin or missing relative to the role. It produces a draft review for the manager.

The review is advisory. It drafts findings for a human to accept or dismiss; it never marks a topic verified and never signs off a stage on its own.

Because KT documents are written by the exiting employee, their text is treated as untrusted input. Instructions embedded in a document — for example, text asking the assistant to mark a topic complete — are ignored by design.

---

## 11. KT and the Last Working Day

KT execution should finish no later than **five working days before** the last working day, leaving a buffer for gaps found late.

Incomplete KT does not extend the notice period. It is recorded as a gap, escalated to the department head, and the exit proceeds.

---

## 12. Garden Leave

An employee placed on garden leave still owes documented handover, but live KT sessions may be curtailed. In that case the manager records the reduced coverage as a gap rather than treating the topics as verified.

---

## 13. Questions

Questions about KT scope go to your reporting manager. Questions about the platform's KT record, or about a disputed verification, go to your HR Business Partner.
