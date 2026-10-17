# Content workflows

For a connected AI, the normal entry is the user's requested scope and desired
result. Follow SKILL.md's user-facing entry: register missing scope and save
request-derived process settings yourself. The board reflects these settings;
it is not a required form for the learner. Carry prepare → generate/analyze →
commit → readback through to the requested result. Exporting a task to another
AI is an optional handoff, not completion of a request to produce a lesson/note.

`get_workflow_contract()` lists operations. Request one operation to read its
scope/input/artifact schemas, effects and strategies. Prepare with
`prepare_workflow(operation=..., scope=..., inputs=..., strategy_id=...)`. The
returned ticket identifies this operation and scope. Produce the artifact, then call
`commit_workflow(request_id, ticket, artifact)`; exact retries reuse the receipt.

| operation | scope | artifact |
| --- | --- | --- |
| curriculum.register | course_id | title, kind=course/project, sections |
| plan.save | course_id, section_id | milestones, optional stage_key |
| context.prepare | node_ids, optional project_id/profile | goal, materials, targets, missing |
| lesson.publish | node_ids, profile=project/course, optional teaching_item_id | documents=[{node_id,body}] |
| record.learning | course_id, optional section_id | analysis={source_ref,summary,...}, items_add/items_update, optional position |
| record.review | batch_id, optional project_id | attempts, gaps, unmatched, source_ticket, optional recall_results |
| assessment.record | optional project_id | explicit assessments/recall_results; project use names context_edge_id |
| note.publish | node_ids, profile=project/course, optional project_id | documents=[{node_id,body,area?,source_refs?}], optional edges/question_links |
| graph.commit | optional project_id | nodes, edges, findings, question_links, legacy_bindings |
| questions.commit | empty | entries=[{question_id or client_key/stem, source_ref?, links?,...}] |
| review.save | batch_id, optional project_id | title, items=[{question_id,label,node_ids}], optional source_ref string |

Record context is under context.state.record; note/lesson material is under
context.targets/materials. Learning position contains current_item_id or
current_item_key and optional base_state_version. Prepared context is bounded,
not a replay of every input. Stage-only calls are compatibility for older clients.

Context preparation reads selected registered material; for unregistered code or
PDFs select and read sources first, then pass excerpts via inputs.materials. The
strategy doesn't inspect a whole repository or download textbooks by itself.

The board `/workflows.html` persists controls separately for lesson, record,
note and associate. `get_workflow_board(project_id)` is for configuring or
inspecting them; routine calls need only prepare_workflow, which applies the
selected process controls automatically. Save clarified fields using
save_workflow_controls(project_id,process,values,base_version). Values include
goal, input_requirements, output_requirements, strategy_id, constraint_ids,
extra_instructions and material_selections. Constraints state whether they
affect input processing, analysis or output; all are available before generation.
Prepare returns ready/clarification. Missing requirements prompt a focused
clarification; settled project fields remain intact. Clarification is not a
learning-completion gate or a reason to infer preferences.

Use list_documents/read_document for existing sources, lessons and canonical
notes. save_document accepts text or an allowed local file, preserving versions
under workspace/documents. inputs.document_selections=[{document_id,version?,
start_line?,end_line?,page_start?,page_end?,max_chars?}] overrides saved selections
for this task. Omit version to follow the latest; a prepared ticket records the
actual version/fingerprint used. For record tasks select one kind=record document;
LO supplies its text and returns the bounded increment via context.state.record.

For project steps, note.publish and graph.commit accept flow_steps=[{flow_id,
steps:[{id,title,description,knowledge:[{node_id,usage,used_parts?}]}],
connections?:[{from,to,relation:next/fails_to,conditions?}]}]. Steps use kind=step,
belong to a flow and reference canonical knowledge; they are not public concepts.
Keep stable IDs when revising. Omitted connections default to sequential next.
Branching flows explicitly provide connections. Ordinary prose headings remain
prose; do not manufacture a step or knowledge node for every heading.
The flow reader shows steps, formal body, direct project questions and a separate
top-K preview of public knowledge questions. A preview is a query, not a copy of
questions or a new project association. Mastery continues to come from assessment.

For external handoffs across windows, save_workflow_task(task) stores the exact
ticket and handoff in the document library. get_workflow_task(document_id)
restores that task, its stable request_id and any existing receipt. Use that
request_id for submitting the returned artifact; repeated submission reuses the
receipt. Saving a task is explicit; ordinary prepare remains read-only.

For note/lesson tasks, the focused `prepare_content_task` and
`commit_content_task` are also supported. They take the same documents and
read back formal publication. Whole-block revision preserves uncovered additions;
explicitly name covered_entry_ids only after incorporating them. When editing a
point within a shared block, revise the containing block and keep canonical node
IDs; do not replace an atomic point with an unrelated whole-block body.

Project prose should let a reader reconstruct purpose, inputs/outputs, the normal
route, important decisions and relevant failure branches. Embed short code or an
example when useful. Course prose follows the chosen material's concepts and
examples. Use natural headings. Summary fields and bookkeeping don't replace a
readable body. Notes can be generated from established records without changing
learning or review state.

For multiple prepared lessons within one section, use its existing teaching_item_id
in scope. Formal project nodes can also have a prepared lesson without publishing
it as knowledge. New workspaces register courses/projects via register_curriculum.

Python extensions register with `orch.register_workflow_strategy(strategy_id,
operation,instructions,prepare?,transform?,profile?)`. Registrations belong to
that workspace; do not mutate module-global templates during a live session.
An optional prepare hook selects material and a transform processes the artifact.
The common business handler
still handles publication, identity and replay. A workspace lists module names in
lo.json strategy_modules; each module implements register(orch). The selected
strategy alone is loaded into the AI job, not all strategy instructions.
