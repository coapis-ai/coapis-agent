---
name: judgment_rubric
description: CoApis judgment-hub rubrics (level / advisor / acceptance). Use when the agent needs to know how CoApis judges whether a task needs planning, should be re-routed, or counts as done; the rubric is injected into every judging prompt, and users may override it with a same-named skill.
---

# Judgment Rubric

The judgment hub works at five touch points: **level, plan review,
in-flight re-route, tightening, acceptance**. These rubrics are the
searchable/reusable copy of the single definition in
`coapis/decision/rubric.py`.

**To customize**: create a skill directory whose name contains `判则` or
`rubric` inside your workspace `skills/` (e.g.
`rubric-our-team-standard/SKILL.md`) and write your standard there. The
hub overlays it on top of the built-in rubric and gives it priority —
rubrics are data, not code.

## 1. Level (complexity + thinking budget)

- simple: done in one step (look up, read, change one place).
- medium: 2–3 steps, needs reading files, writing content, calling tools.
- complex: chained steps, cross-system, produces a deliverable
  (report / deployment / refactor).
- Judge strict: when unsure, judge lower.

Thinking budget (off by default; the more expensive tiers must earn it):
- minimal: correct without thinking (lookups, single-step ops, facts).
- low: standard flow is enough (read file, write content, one tool).
- medium: needs step planning (multi-tool, dependencies).
- high: needs multi-round planning and self-check (cross-system, long
  chains, deliverables, root-cause analysis).
- To judge minimal you must be able to say why no thinking suffices.

## 2. In-flight re-route (advisor)

Judge after each tool round — only "is this execution drifting":
- continue: on track; errors with a clear next step.
- advise: same operation failed 2+ times the same way; 5+ reads/searches
  with no executable next step; the path clearly doesn't solve the user's
  problem; a new fact invalidates the plan's premise.
- Advice is one sentence, ≤ 60 chars, must state the next action.
- Unsure → continue. Interrupting costs more than missing.

## 3. Acceptance

All four must hold to pass:
1. the deliverable exists (concrete content/file/conclusion, not "I will");
2. verification was done (ran a command / read real output); code only
   with no verification fails;
3. no obvious leftovers (untested, unreported errors, skipped issues);
4. the result matches what the user asked for (count/scope/format).

Output `met`, or `unmet` plus **what exactly is missing** — each item
actionable ("add tests for X and show results", not "polish it a bit").
Unsure → unmet. Strict closing is the whole point of having a judge.

## 4. Discipline

- Output only the requested JSON. No explanation, no reassurance.
- If a rubric conflicts with an explicit user requirement, the user wins
  — and say so in the verdict.
- "Judge lower / judge unmet when unsure" is deliberate strictness.
