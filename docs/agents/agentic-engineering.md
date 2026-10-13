<!-- Agentic Engineering Workflow v2026.09.02.1. Canonical source: ultron/docs/agents/agentic-engineering.md. Sibling copies are managed by Ultron. -->
# Agentic Engineering Workflow

> Scale agent execution, not agent authority.

Use this workflow for planning, building, fixing, or changing code. The human
owns architectural authority and merge. Agents receive bounded work, isolated
execution, and an independent verification budget.

When Matt and Superpowers both apply, read
`docs/agents/skill-orchestration.md`. Load every applicable skill, then execute
one combined phase under the owner named there. Do not repeat equivalent
ceremonies or create parallel artifacts merely because both suites describe
them. `using-superpowers` discovers applicable skills; `ask-matt` selects the
route when available.

Some harnesses expose Matt skills only as explicit human commands. If a named
owner is not model-invocable, do not skip its phase and do not claim to have
invoked it. Apply the route and combined completion criteria in the crosswalk
directly, using every available supporting skill, and record that fallback in
the durable ticket.

For non-trivial delivery, remediation, scout, experiment, recovery, or
delegation work, read and follow `docs/agents/evidence-bound-method.md`. Its
task vocabulary and recovery rules are defined in `docs/agents/task-runs.md`.

## 1. Establish intent and choose the path

Inspect the working tree and applicable repository guidance, then run the Matt
routing phase (`ask-matt` when available; otherwise apply this document
directly). Before repository exploration, read
`docs/agents/domain.md`; use its glossary and surface any ADR conflict. Read
`docs/agents/issue-tracker.md` before tracker operations and
`docs/agents/triage-labels.md` before triaging incoming work. Put durable intent
in the configured tracker:

- Single-repository work uses that repository's tracker.
- Cross-repository work starts in Ultron at `.scratch/<effort>/`. Create linked
  child tickets in every affected repository and point each child back to the
  Ultron map.

Every managed repository carries an Ultron-scoped mainline pointer,
`ultron/mainline`, so cross-repo policy and landing work has one stable branch
name to target regardless of whether a repository's native default is `main` or
`master`. `tools/sync_agentic_workflow.py --check` reports `MISSING-BRANCH`
drift when the branch is absent, and `--apply` creates it at the repository's
`base_branch` tip. The convention is ensure-exists only: an existing
`ultron/mainline` is never moved, force-updated, or deleted.

The **short path** is available only when every condition holds: one repository,
one session, reversible, narrowly scoped, and no public API or schema,
migration, security boundary, destructive data path, distributed or concurrency
invariant, production infrastructure, or architectural decision.

If any condition fails, use the **gated path**. Record the classification and
its evidence in the durable ticket before implementation begins.

## 2. Short path

Keep the primary context. Define the behavior, implement red-green slices, run
focused tests, perform the standard two-axis code review, and inspect the final
diff. Completion requires fresh verification evidence and human-owned merge.

## 3. Bug path

Before broad investigation, Matt's diagnosis loop must establish a fast command
that can turn red and minimize the failure. Then use Superpowers root-cause and
pattern analysis: rank three to five hypotheses, test one variable at a time,
and encode the verified cause as a failing regression test before fixing it.
After three failed fixes, stop patching and escalate to architectural review.
The crosswalk defines the full hard-bug recipe.

## 4. Gated path

Complete these gates in order:

1. **Intent:** Record the outcome, acceptance criteria, constraints, and explicit
   authority boundary in the tracker.
2. **Design:** Run Matt's stateful repository design flow with human
   participation. Resolve decisions in frontier rounds rather than forcing a
   one-question cadence. Completion means the repository has been explored,
   alternatives and tradeoffs are explicit, the human has approved the design,
   ambiguities have been self-reviewed, and every material decision is settled
   or represented by a decision ticket. This satisfies the Superpowers
   brainstorming phase.
3. **Independent critique:** Send the design to a separate context that did not
   inherit the design or implementation conversation. Prefer another model
   family when available. Reconcile every finding before advancing.
4. **Specification:** Write the precise spec in the tracker, subject it to
   adversarial review, and split it into blocker-linked tracer-bullet tickets.
   Each ticket declares requirements, exclusions, blockers, and verification
   evidence. The tracker spec and tickets are canonical; exact file-and-code
   micro-plans remain session-local. Do not duplicate them under
   `docs/superpowers/specs` or `docs/superpowers/plans`.
5. **Isolated execution:** Implement each ticket in its own worktree. Parallel
   agents receive non-overlapping tickets and never share a mutable checkout.
6. **Behavioral proof:** Approve the public test seam once during design or
   specification, then drive every behavior slice with visible red-green
   evidence. Only behavior-preserving cleanup follows green. Run focused tests
   first, then the repository's broader required checks.
7. **Ticket conformance:** Review every ticket on both Matt axes: repository
   Standards and ticket Spec. This satisfies the Superpowers request-review
   phase only when neither axis has unresolved blocking findings.
8. **Independent verification:** Run `roborev review --branch`. If branch review
   is unavailable, use a separate-context reviewer against the fixed base and
   spec. Passing tests do not replace this gate.
9. **Repair:** Fix findings and re-review for at most three iterations. Run
   `roborev refine --max-iterations 3` only on a clean isolated branch or
   worktree; otherwise repair through the implementing agent and submit a fresh
   review. Escalate non-convergence, uncertainty, or exhausted budget as
   attention-needed rather than silently extending authority or spend.
10. **Human control:** Present the reviewed branch, remaining risks, fresh
    completion evidence, and intent coverage. Commit, push, and pull-request
    creation each require explicit authorization. Only a human performs the
    merge; agents stop at the reviewed branch even when otherwise authorized.
11. **Distillation:** Update the living glossary, ADRs, and architecture docs
    with knowledge that remains useful after the task. Code and tests remain the
    durable truth alongside tracker specs and tickets; session-local
    micro-plans, execution checklists, and review traces are non-authoritative
    context.

## Operating boundaries

- Durable intent is external to prompts, conversations, agent memory, and
  commits.
- Background and parallel execution stays isolated from the human's checkout.
- Verification has its own budget and may cost as much as implementation when
  risk warrants it, but extending the three-iteration repair budget requires a
  human decision.
- Agents surface decisions, findings, patches, and evidence. Humans retain
  architecture authority and perform every merge.
- Skill text never grants Git authority. Commit, push, and pull-request actions
  require explicit authorization for the specific action.
- Preserve existing work and repository-specific rules. Direct user
  instructions and more specific repository guidance take precedence.

## Route recipes

### Short feature

1. Discover skills, then run the Matt routing phase to confirm the short path
   and durable intent location.
2. Explore and design to the combined approval criteria; approve the test seam.
3. Implement visible red-green slices in the current context unless isolation
   is otherwise required.
4. Run two-axis review, inspect the diff, and collect fresh completion evidence.
5. Stop before any Git action that lacks explicit authorization and before
   merge in all cases.

### Gated feature

1. Record durable intent and acceptance criteria, complete Matt design in
   frontier rounds, and reconcile an independent separate-context critique.
2. Produce the tracker spec and blocker-linked tracer-bullet tickets.
3. Give each ticket a fresh isolated worktree and non-overlapping execution
   context. Implement using visible red-green slices.
4. Complete Standards and Spec review per ticket, then run branch-level
   `roborev` over the assembled result.
5. Permit at most three repair and re-review rounds, collect fresh completion
   evidence, distill lasting knowledge, and hand the reviewed branch to a human.

### Hard bug

1. Route through Matt diagnosis and establish the smallest fast command that
   can turn red; minimize and localize the failure.
2. Investigate root cause and analogous patterns. Rank three to five hypotheses
   and test one variable at a time.
3. After three failed fixes, stop and request architectural review.
4. Encode the verified cause as a failing regression test, make it green, then
   perform behavior-preserving cleanup and risk-scaled review.
5. Re-run the tight command and broader required checks from the final state.

### Wayfinder effort

1. Use `wayfinder` to map unknowns, decisions, and dependencies without treating
   the map as an implementation plan.
2. Create bounded research, prototype, or grilling tickets for unresolved
   questions.
3. When the frontier is clear, pass through `to-spec` and `to-tickets` before
   implementation unless the Matt routing phase reclassifies the remaining work
   as short.

### Incoming triage

1. Put unshaped external requests through the repository triage rules.
2. Promote ready work into the appropriate short, gated, bug, or wayfinder
   route.
3. Matt-generated tickets that already satisfy tracker requirements bypass raw
   intake triage; they do not bypass design, evidence, review, or authority
   gates.

## Context boundaries

At every phase boundary, the Matt routing phase chooses whether to continue,
compact, hand off, or start a fresh isolated context. Prefer fresh contexts for
gated tickets and independent review. Context boundaries reduce contamination;
they never erase durable intent or loosen acceptance criteria.
