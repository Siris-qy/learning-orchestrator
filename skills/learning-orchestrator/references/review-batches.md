# External review and record recovery

The current preferred path starts with original interview questions already
answered or discussed by the learner. Do not replace them with a fresh generated
quiz just because review is requested.

1. Find the originals in the question bank; reuse question_id. Save an ordered
   batch with save_review_batch(request_id,batch_id,title,items,project_id?). Each
   item names question_id, label and the project/knowledge node_ids it actually
   covers. The batch is always accessible independently of due dates.
2. export_review_batch returns self-contained Markdown and a manifest. Select
   node_ids for the desired background; missing formal bodies are listed rather
   than silently replaced by old summaries. Default export withholds answers.
3. After external discussion, call prepare_review_record(batch_id,transcript,
   source_key). It returns the unprocessed delta, original questions and open gaps.
   Match answers by meaning even if the TXT has no IDs; preserve ambiguous text
   in unmatched. The AI does semantic matching, not a keyword-only program.
4. Merge the analysis into commit_review_record(request_id,batch_id,...):
   - attempts: question_id, kind=answer/explanation/confirmation, text, optional
     result=pass/deepen (actual answers only), coverage=[{node_id,...}], source_ref.
   - gaps: stable id, title, question_id/node_id as applicable, parent_id for
     recursion, state=open/explained/resolved/deferred. Only explicit closure of
     that question resolves it; another successful answer doesn't clear it.
   - unmatched: original text and the ambiguity; source_ticket from preparation
     advances the processed offset only when the merged analysis commits.
   - optional recall_results: existing node-level review results, only for
     knowledge explicitly covered by actual answers in this record. This reuses
     existing schedules; it doesn't create a separate question calendar.
5. Report the original-question batch entry, actual progress and the remaining
   unconfirmed points. Don't expand all historical answers into the reply.

The same operations are available through the unified workflow:
`review.save` registers membership and `record.review` prepares/commits external
analysis. With `record.review`, read the delta and source_ticket from
`job.context.state.record`. Its artifact uses the attempts/gaps/unmatched fields
above. Pass the original job.ticket to commit_workflow. Export and resume remain
export_review_batch/get_review_batch; they use the same stored identities.

Use list_review_batches/get_review_batch to resume. The page is
`/review-batches.html`; a project page links to its own batches. Registered dates
provide due information; they are not an active notification worker. Set a reminder
only when the user asks for one.
