---
name: learning-orchestrator
description: Guide a learner from their chosen scope and desired explanation to a saved, self-contained lesson; register project settings and materials through LO. Also organize learning records, notes, knowledge links and original-question review batches.
---

# Learning Orchestrator

LO stores learning position, formal notes, graph references, questions and review
records. The host AI analyzes and writes; ordinary web chats can teach from an
exported lesson or review pack without access to the repository.

## User-facing entry

The learner specifies what to learn and what explanation/output they want, with
materials when available. Carry that request through to the saved result. The
connected AI performs registration, configuration, material selection, generation,
submission and readback; the learner need not fill the workflow board or move JSON.

Resolve the project/course and range from existing state first. If they are new,
register the requested scope using `register_curriculum`; reuse returned IDs. Read
the relevant process controls with `get_workflow_board`. Derive missing settings
from the user's request and the existing defaults, and save them yourself with
`save_workflow_controls`, preserving unrelated settings and using base_version.
Keep reusable writing/teaching preferences in saved controls; pass today's scope,
goal and material ranges to `prepare_workflow`. Do not overwrite durable preferences
with a one-off request or save another identical configuration on every turn.

Ask a short, concrete question only when missing information changes the result
(for example, which textbook or chapter). Explain a reasonable default when one
suffices. Empty form fields, no custom skill or no manually chosen strategy are
not reasons to make the user configure LO. Once the necessary information is
available, continue through generation, commit and readback in the current task.
Return the actual lesson/note or its usable document link and a brief saved-status
message. A prepared ticket or exported task prompt is an intermediate result.

The board is where users inspect and adjust AI-saved settings. Manual task export
and JSON return are optional for an AI without LO access; use that route only when
requested or when the chosen AI cannot call LO. State any missing connection
plainly; do not claim to have registered content without a successful tool result.

## Choose the current operation

Read only the relevant reference and material scope. Existing desktop conversation
can remain the background; do not rebuild full project history every turn.

- **Prepare a lesson:** [lesson-preparation.md](references/lesson-preparation.md).
  Project and authored-course strategies differ. Existing plan positions remain
  stable; prepare distant stages only when requested.
- **Organize learning chat/TXT:** [learning-records.md](references/learning-records.md).
  Read the increment, recover subsection position, recursive questions, unanswered
  and explained-but-unconfirmed items. This request includes synchronization.
- **Publish notes, organize knowledge, or use another strategy:**
  [content-workflows.md](references/content-workflows.md). Use the shared
  prepare/commit contract and the project's KNOWLEDGE_STANDARD.md.
- **Register externally answered questions or resume their review:**
  [review-batches.md](references/review-batches.md). Start with the existing
  original questions; preserve the batch, actual answers and unresolved branches.
- **Direct tutoring when requested:** [detail-teaching.md](references/detail-teaching.md).
  Older session-specific details are in [legacy-tutoring.md](references/legacy-tutoring.md).
  They are not the default workflow or a required project route.

## Shared meanings

Teaching plans describe the route and position; formal knowledge nodes describe
reusable concepts and project modules/flows. A temporary question is a process
record unless it has become useful permanent knowledge.

Prepared content, explained content, user-confirmed understanding and tested
understanding are distinct. Closing a recursive child never closes its parent or
siblings. Keep the normal cursor at the subsection and record question ancestry;
on continuation, mention unfinished branches without blocking user navigation.

Existing node/question IDs win. Public knowledge has one formal body; project
flows explain their use and link to it. Project flow pages show directly relevant
project questions; basic questions belong to the corresponding knowledge pages.
Do not infer mastery, interview provenance or review dates from content creation.

## Calling discipline

- Restore via compact state. Request material only for the current job. On local
  follow-ups, reuse the loaded lesson unless additional evidence is needed.
- Use stable request IDs for retries; a new real answer uses a new attempt ID.
  Keep source/range evidence and unresolved branches when analyzing increments.
- Merge a turn's learning writes. Pass the last state_version when moving a
  teaching cursor; routine commits return short receipts, not full history.
- Discover an operation with `get_workflow_contract(operation?)`, then use
  `prepare_workflow(operation=..., scope=..., inputs=...)` and `commit_workflow`.
  The ticket identifies the operation; stage is old compatibility, not dispatch.
  Existing focused APIs remain valid; no task needs all eight stages.
- The workflow board at `/workflows.html` manages four processes: lesson,
  record, note and associate. `prepare_workflow` loads that project's saved
  goal, input/output requirements, selected constraint modules and material
  references. Reuse these settings. If `ready=false`, clarify the missing
  project fields from the user's request/defaults, save_workflow_controls and
  prepare again. Ask the user only for unresolved information that matters.
- Use list_documents/read_document to select existing materials; save_document
  imports text/files with versions. Pass inputs.document_selections for a
  task-specific range. A selected record supplies its transcript automatically.
- A source-file save does not itself trigger analysis. When the learner asks to
  check an updated record, analyze its increment and sync without requiring them
  to issue separate commands for parsing, recording and resumption.

Main/detail/control are operation roles, not mandatory physical windows. Keep
existing plan ownership rules; a stored handoff is not an automatically sent
message or a running background agent.
