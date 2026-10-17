# Detail teaching: local execution, fast foreground

This SOP is for explicitly requested direct tutoring only. The default detail
role organizes external chat/TXT records using `learning-records.md`; it does
not retrieve sources, start a lesson or answer every recorded question merely
because the learner submits a transcript.

## Once on takeover

The learner should not have to ask separately to analyze their TXT. On takeover,
"continue learning", a return after a break, or a supplied/updated record,
read local state and inspect `record_sync` automatically. If pending_analysis,
follow `learning-records.md`, process the changed fragment (and further slices
if needed) and merge the resulting cursor/question updates before presenting
the resumption summary. If unchanged, do not reanalyze the file. Keep checks
at these natural resume/update boundaries, not every tiny follow-up. Ordinary
chat questions and confirmations are still recorded inline without another
user instruction. No background listener is implied.

Use role `detail`. Call `prepare_teaching(course_id, role='detail', profile='local',
include_lesson=True, lesson_scope='unit')` once. It returns the subsection cursor,
local questions, next planned item and lesson_background: the current teaching
unit's full outline and saved lesson(s). Use 'section' for a narrower grouping
when that is the actual teaching range. This is background, not an instruction
to explain every item at once. The number of items follows the real plan, never
a quota. Do not load
the whole course, history or repository. If the lesson is missing, reuse the
main teacher's supplied text or request it; source retrieval is a fallback
for missing/suspect facts, not a routine step.

Main plans the hierarchy and saves the complete range lesson on its unit/section
item with `save_lesson_artifact(node_id, mode='intro', teaching_item_id, content)`;
separate subsection lessons also work. A range lesson is returned once without
duplicating its descendants' lesson text. Otherwise available child lessons
are collected in plan order; missing_item_ids explicitly identify missing parts.
Do not impose a fixed number of subsections or fixed project-specific route.

## Each user message

1. Interpret the user's intent inline, without a separate judging agent.
   Answer the current confusion using the lesson and existing chat context.
   Do not answer every planned subsection just because all are visible.
2. The formal cursor stays at the subsection. A new question gets a `question`
   item under that subsection, or under the parent question when recursive.
   Keep its note short: confusion, what remains, parent to return to.
3. Distinguish the states:
   - Discussion/another question: keep it `open`; cursor does not advance.
   - You have explained it: `awaiting_confirmation`, NOT `resolved`.
   - User says the question is clear/finished: `resolved` for that question
     only. Return to any unfinished parent discussion.
   - User explicitly confirms the subsection: `self_reported_understood`;
     offer/continue the next planned subsection as requested. This does not
     set formal mastery, chapter approval, or parent completion.
   - User defers/skips: mark `deferred` and continue as requested; don't gate.
   Ambiguous replies are not confirmation. Ask naturally if needed, not a
   compulsory confirmation ritual on every turn.
4. One merged `commit_teaching_turn` saves relevant changes AND raw text:
   `turn_record={item_id: subsection_id, question_id?: existing_question_id,
   user_text: original_question, assistant_text: actual_answer,
   user_confirmation?: actual_user_words}`. Do not summarize the raw answer
   away or copy tool outputs into it. New questions can be added in this same
   commit; their first record is linked through item_id and items_add. Use the
   returned record_id/state_version, not a second read or second write.
5. No foreground note consolidation, knowledge linking, retrospective
   assessment, source rescanning or full-state audit. Already loaded lesson
   and chat memory handle ordinary turns; `local` is only needed on resume,
   an actual transition, or a stale-version recovery. Cross-window memory is
   not automatic: raw records allow targeted recovery when needed.

## On subsection transition

In the same commit, record user confirmation, move to the next planned item,
and leave `handoff={kind:'organize_followups', item_id: previous_subsection_id,
record_ids:[...], summary: short_scope, remaining_questions:[...]} `.
If record_ids are unavailable, item_id is enough for a paginated lookup.
Unfinished questions are a reminder, not a hard gate; don't silently erase
them. Reuse the range background while moving between its subsections. Only
load another full range on a new window, a range change, or a revised lesson;
after context compression, keep the outline/position and fetch needed text.

Main later reads `get_teaching_state(course_id, records_for_item=..., after_id=0,
limit=5)`, follows next_after_id when has_more, and organizes useful content
into knowledge blocks. Foreground proceeds without waiting. This is a stored
handoff, NOT automatic chat messaging or a running background worker. Do not
promise delivery/processing that has not occurred.

If an old cursor sits on a question, use its existing return position or
explicitly restore the enclosing subsection once; preserve the question's
status. Do not batch-rewrite old evidence to guess what the user understood.
