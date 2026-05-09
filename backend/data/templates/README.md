# Clinician-Authored Therapeutic Templates

This directory holds **clinician-authored** message templates consumed by
agent modules in `backend/app/services/`.

> **Empty by design.** Each template ships as a stub with
> `_meta.status = "awaiting_clinician_authoring"`. Loaders are required to
> treat empty/stub templates as **fail-closed** — return `None` and log a
> `<template>_unavailable` event rather than emit engineer-default text.
> Therapeutic surfaces touching survivors must never be authored by
> engineers.

---

## Why fail-closed-with-silence (not fail-closed-with-default-text)

Quoting the Phase 3 build review (Note 3, `nate_checkin_agent.py`):

> A default "welcome back" string in code that hasn't been clinician-reviewed
> is exactly the kind of well-intentioned therapeutic overreach the entire
> bridge is designed to prevent. Better to send no message until clinician
> authors it than to ship engineer-written welcome text to a survivor
> returning from silence mode.

The same principle applies to every template that lands here.

---

## File naming convention

```
<template_name>_<locale>.json
```

Where `<locale>` is BCP-47 (`en-US`, `es`, `es-MX`, `pt-BR`, …). The
locale-aware fallback chain (per `data/lexicons/README.md` Gap S) applies:

```
<requested_locale>  →  <language>  →  en-US  →  fail-closed (no template)
```

| Template name      | Filename                                | Loader                                                |
| ------------------ | --------------------------------------- | ----------------------------------------------------- |
| `welcome_back`     | `welcome_back_<locale>.json`            | `nate_checkin_agent._load_welcome_back_template`      |

---

## Required `_meta` block

Every template ships with a top-level `"_meta": { ... }` containing:

| Field                   | Type    | Notes                                                            |
| ----------------------- | ------- | ---------------------------------------------------------------- |
| `version`               | string  | `MAJOR.MINOR.PATCH-YYYY-MM-DD` (e.g., `0.0.0-empty-pre-clinician-authoring`) |
| `locale`                | string  | BCP-47                                                           |
| `clinician_authored_by` | ?str    | NULL until clinician authors                                     |
| `reviewed_by`           | array   | Two-clinician sign-off required before status flips              |
| `last_review_date`      | ?str    | NULL on stub                                                     |
| `status`                | enum    | `awaiting_clinician_authoring` \| `clinician_authored`           |
| `loader`                | string  | Module path of the consuming code                                |
| `notes`                 | array   | Free-form clinical context for reviewers                         |

Loaders MUST refuse to use a template whose `status != "clinician_authored"`
or whose `body` field is empty/missing.

---

## Two-clinician review requirement

Same as the lexicon directory (see `data/lexicons/README.md`):

1. Two independent clinician reviews recorded in `_meta.reviewed_by`.
2. Authoring clinician excluded from the reviewer list.
3. Each reviewer drops a PR comment of the form
   `TEMPLATE-REVIEW-OK: <reviewer-id>: <date>`.
4. PR description names the authoring clinician and includes a clinical
   rationale (e.g., why this welcome-back framing avoids questioning the
   user's absence — Plan §7).
5. No content from automated suggestions. Templates are clinical
   instruments.

---

## What this directory is NOT

- **Not for engineer-default copy.** Defaults belong in code only when the
  surface is non-therapeutic (e.g., HTTP error pages). Therapeutic surfaces
  fail-closed.
- **Not a translation memory.** Translated templates require independent
  clinician review per locale.
- **Not where dynamic per-user content goes.** Per-user safety plans live
  in `user_safety_codewords` and `user_trigger_dates` tables.
