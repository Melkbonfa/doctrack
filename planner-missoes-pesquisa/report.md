# Relatório de Pesquisa — Referências para o módulo *Missões* (kanban nativo)

> Como o Microsoft Planner e o Microsoft Project funcionam — modelo de dados, ordenação, dependências, atribuição, views e colaboração — como referência para projetar o módulo kanban nativo "Missões" no DocTrack (Flask/SQLAlchemy), offline, sem Microsoft Graph.

*Itens pesquisados: 11 · gerado a partir de `results/*.json` contra `fields.yaml` (27 campos em 7 categorias).*

## Índice

1. [Microsoft Planner (Basic)](#item-1-microsoft-planner-basic) — **COPY · ADAPT · AVOID**
2. [Microsoft Planner Premium / Project for the web](#item-2-microsoft-planner-premium-project-for-the-web) — **COPY · ADAPT · AVOID**
3. [Microsoft Project (desktop / Project Online)](#item-3-microsoft-project-desktop-project-online) — **COPY · ADAPT · AVOID**
4. [Modelo de dados do Graph (plannerTask / plannerTaskDetails)](#item-4-modelo-de-dados-do-graph-plannertask-plannertaskdetails) — **COPY · ADAPT · AVOID**
5. [Order Hint (Planner)](#item-5-order-hint-planner) — **ADAPT**
6. [Fractional indexing (Figma / tldraw / Notion / Linear)](#item-6-fractional-indexing-figma-tldraw-notion-linear) — **COPY · ADAPT · AVOID**
7. [Jira LexoRank + Trello pos + Asana rank](#item-7-jira-lexorank-trello-pos-asana-rank) — **COPY · ADAPT · AVOID**
8. [Trello](#item-8-trello) — **COPY · ADAPT · AVOID**
9. [GitHub Projects (v2)](#item-9-github-projects-v2) — **COPY · ADAPT · AVOID**
10. [Notion / Linear](#item-10-notion-linear) — **COPY · ADAPT · AVOID**
11. [Views derivadas de um único dataset](#item-11-views-derivadas-de-um-único-dataset) — **COPY · ADAPT · AVOID**

<a id="item-1-microsoft-planner-basic"></a>
## 1. Microsoft Planner (Basic)

### Modelo de dados

**entidades e hierarquia** — Three strictly flat levels: plannerPlan -> plannerBucket -> plannerTask. A plan is the board (owned 1:1 by a Microsoft 365 Group). A bucket is a named column inside one plan. A task belongs to exactly one plan and to zero-or-one bucket. There is NO native subtask/WBS nesting in Basic Planner: tasks cannot contain tasks. The only in-task 'hierarchy' is a flat checklist (up to 20 items) that lives in plannerTaskDetails, not as real child tasks. So the model is a pure 2-level kanban (columns + cards), which maps cleanly onto a flat Missao/Coluna/Cartao model without recursion.

**relacionamentos fk cascade** — task.planId is a required FK to plannerPlan; task.bucketId is an optional FK to plannerBucket (a task can exist with no bucket and still show on the board's default position). bucket.planId is a required FK to the plan. Deleting a plan cascades to its buckets and tasks (the whole plan is removed); deleting a bucket does NOT delete its tasks in the service data model — orphaned tasks keep planId but lose bucketId. Each plannerTask has exactly one plannerTaskDetails (1:1, shared id namespace). appliedCategories are label slots referencing labels defined at plan level in plannerPlanDetails.categoryDescriptions.

**granularidade detalhes** — Yes — this is the canonical split to copy. The lightweight plannerTask holds only board-render fields (title, bucketId, orderHint, assignments, percentComplete, priority, dates, appliedCategories, plus rollup counters hasDescription, checklistItemCount, activeChecklistItemCount, referenceCount, previewType). The heavy content lives in a separate 1:1 plannerTaskDetails entity: description (String), checklist (map of plannerChecklistItem), references (map of plannerExternalReference), previewType. Recommendation for Cartao: keep a slim cartoes table for the board query and a 1:1 cartao_detalhes table (or a details JSON column) for description/checklist/attachments, so the board list endpoint never loads long text.

**mapeamento missoes** — plannerPlan = Missao (the board). plannerBucket = Coluna. plannerTask = Cartao. orderHint (per task within bucket, and per bucket within plan) = campo 'ordem'. plannerTaskDetails = tabela cartao_detalhes 1:1. appliedCategories category1..25 = labels/etiquetas fixas por Missao. There is no native (ref_tipo, ref_id) equivalent: Planner links external entities only weakly via plannerExternalReference URLs in details — DocTrack's typed (ref_tipo, ref_id) FK to Equipamento/Projeto/Documento is a DocTrack-specific superset with no Planner counterpart.

### Ordenação

**mecanismo** — orderHint: a fractional-lexicographic STRING (not an integer, not a float). Characters range over ordinals 32 (space) to 126 (~); strings are compared ordinal-by-ordinal, and a shorter prefix sorts before a longer string ('a' < 'ab' < 'abc', 'abc' < 'abd'). The service — not the client — computes the final short value. To move a card between two neighbors, the client PATCHes orderHint to the literal string '<prevHint> <nextHint>!' (previous hint, a space, next hint, suffixed with '!'); missing neighbor => empty string on that side ('' + space + next + '!'). The service then replaces it with a compact value that still sorts into that gap. Separate independent orderHint chains exist for tasks-in-bucket, buckets-in-plan, and assignments; there is also an assigneePriority hint for the 'assigned to' board view.

**custo reordenar e rebalanceamento** — A move is O(1): only the moved item's orderHint is rewritten; neighbors are untouched, so no whole-column reindex. Precision never 'runs out' the way integer gaps do — the string simply grows (each subtle insertion can append characters like the documented 'adhg ! !' or ' 5637! 5637 adhg!!'). Because the SERVER recomputes a short canonical value on every PATCH, unbounded string growth is amortized away server-side; there is no exposed periodic global rebalance job. For an offline SQLAlchemy clone you must replicate that 'shorten' step yourself (compute a midpoint string between neighbors) or accept slow string growth, because you have no service doing the compaction for you.

**concorrencia conflito** — Optimistic concurrency via @odata.etag. Every plannerTask/plannerBucket/plannerPlanDetails carries an ETag; updates and deletes must send it in an If-Match header. If two users move the same card, the second PATCH gets HTTP 412 Precondition Failed and must re-read and retry — last-writer does NOT silently win, and there is no CRDT merge. Practically, concurrent moves resolve to a consistent order because each accepted PATCH yields a fresh service-computed hint; the loser just retries against the new state.

### Atributos do cartão

**responsaveis cardinalidade** — N assignees per task (0..N). assignments is an open dictionary keyed by the user's AAD objectId (userId) -> plannerAssignment. Each plannerAssignment carries its own payload: orderHint (position in the 'assigned to' board), assignedBy (identitySet), and assignedDateTime. So the assignment itself is an association object that can hold extra data — the natural place to add units/effort if ever needed. No single 'owner' field; ownership is just the set of keys. Recommendation for Cartao: an association table cartao_responsavel(cartao_id, user_id, assigned_at, assigned_by, ordem) rather than a scalar owner column.

**datas** — Four DateTimeOffset fields, all ISO 8601 in UTC: startDateTime, dueDateTime, createdDateTime (read-only), completedDateTime (read-only, set when percentComplete hits 100). All are nullable except createdDateTime. Planner stores instants in UTC and renders in the viewer's local timezone; there is no per-task timezone field. completedBy/createdBy are identitySets recorded alongside. Recommendation: store all timestamps as UTC (SQLAlchemy DateTime, timezone-aware) and convert at the edge.

**prioridade encoding** — Integer 0..10 where LOWER number = HIGHER priority. The service buckets it into 4 UI tiers: 0-1 = Urgent, 2-4 = Important, 5-7 = Medium, 8-10 = Low. When the UI sets a tier it writes the canonical representative value: Urgent=1, Important=3, Medium=5 (default), Low=9. Recommendation for Cartao: store priority as a small Int with the same 0..10 semantics (cheap to sort/range-query) and map to 4 chips in the UI — this is more flexible than an enum and matches Planner exactly. If you prefer, collapse to the 4 canonical values {1,3,5,9} to keep it simple.

**estados workflow** — There is NO configurable status enum. State is driven by the integer percentComplete (0..100), which the UI collapses to exactly three buckets: 0 = Not started, 1-99 = In progress (UI writes 50), 100 = Completed (also stamps completedDateTime/completedBy). This single number simultaneously drives the completion chip AND the 'Progress' board grouping (group-by percentComplete tier). Trade-off vs a Notion/Linear configurable-status enum: Planner's 3-state model is dead simple, needs no per-board status config, and makes 'group by progress' free — but it cannot express custom workflow columns (Blocked, In Review) except by using buckets/labels. For Missoes, percentComplete 0/50/100 is a strong COPY if you want zero-config; a configurable status enum is the ADAPT if teams need custom stages.

**checklist progresso** — Flat checklist (up to 20 plannerChecklistItem entries) lives in plannerTaskDetails.checklist as a map (each item: title, isChecked, orderHint, lastModified). Progress is NOT a stored percentage; the lightweight task exposes two rollup counters — checklistItemCount and activeChecklistItemCount (unchecked) — and the card shows 'checked/total' (e.g. 2/5). Recommendation: store checklist rows child of cartao_detalhes and compute 'done/total' on read; optionally cache the two counts on the card row for the board query.

**vinculos externos** — Weak/untyped only. plannerTaskDetails.references is a map keyed by a percent-encoded URL -> plannerExternalReference (alias, type such as PowerPoint/Word/Excel/Other, previewPriority, lastModified). It is essentially an attachment/link list, not a typed foreign key to another domain entity. referenceCount is rolled up onto the task. This is weaker than DocTrack's need: to link a Cartao to an Equipamento/Projeto/Documento you should add an explicit, typed, nullable (ref_tipo, ref_id) pair on the card rather than mimic Planner's URL-bag.

### Views

**views disponiveis** — Basic Planner exposes Board (grouped by Bucket, by Progress, by Assigned-to, by Priority, by Due date, or by Label), Grid/list, Schedule (a month calendar by due date), Charts (built-in status/priority/bucket aggregations), and 'My Tasks' across plans. No Gantt/timeline in Basic (that is Premium).

**derivacao do mesmo dado** — All Basic views are pure group-by / sort / filter over the SAME plannerTask table — no extra entity per view. Board 'group by' just switches the grouping key (bucketId, percentComplete tier, assignee, priority, dueDateTime, or an applied category). The board rendering positions are persisted as small per-view format hints on the task (bucketTaskBoardFormat, progressTaskBoardFormat, assignedToTaskBoardFormat, each carrying its own orderHint) so each grouping remembers its own manual ordering — but the underlying rows are unchanged. This is the key lesson for Missoes: add future views by adding group-by/sort/filter, not new tables.

**my tasks cross** — Yes — 'My Tasks' / 'Assigned to me' aggregates a user's tasks across ALL plans, i.e. a query filtering tasks by the caller's userId in assignments. Cost: it's a cross-board scan by assignee; in SQLAlchemy this is a single indexed query on the assignment association table (index on user_id), cheap if you index cartao_responsavel.user_id.

### Dependências & scheduling

**modelo dependencia** — None in Basic Planner. Tasks have no predecessor/successor relationships and no FS/SS/FF/SF dependency types; ordering is purely manual via orderHint and buckets. (Dependencies exist only in Planner Premium / Project for the web.) For Missoes this means dependencies are an opt-in feature to add later, not part of the core kanban.

**calculo datas** — No auto-scheduling. start/due dates are whatever the user types; nothing recalculates them. This is exactly the behavior to KEEP for an offline app — no scheduling engine, no cascade. AVOID importing any auto-date-shifting logic.

**rollup progresso** — No parent/summary rollup exists because there is no task nesting. The only rollup is the per-task checklist counters (activeChecklistItemCount/checklistItemCount), computed by the service and surfaced on the card. Nothing rolls up across tasks.

### Colaboração

**templating reuso** — Planner supports creating a new plan from a template / copying an existing plan (copy plan duplicates buckets, tasks, labels, and structure; the 2026 update adds richer custom templates). For Missoes: a 'create from template' that clones Colunas + label definitions + optionally Cartoes (resetting progress, dates, assignees) is the analog.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY: (1) the flat plan->bucket->task shape mapped to Missao/Coluna/Cartao; (2) the light task / heavy details 1:1 split; (3) percentComplete 0/50/100 three-state driving both chip and grouping; (4) integer priority 0..10 bucketed into 4 tiers; (5) fixed per-plan label slots (appliedCategories) instead of a free-tag table; (6) N assignees via an assignment association object; (7) views as group-by/sort/filter over one table. ADAPT: order hints — copy the fractional-lexicographic idea but implement your own midpoint/compaction because no service will shorten strings for you; ADAPT task chat down to a plain comments table (drop the group-mailbox backing). AVOID: the conversationThreadId / M365-group-mailbox indirection for comments; any dependency on Graph webhooks for realtime; and (since Basic has none) any auto-scheduling engine.

**recomendacao sqlalchemy** — missoes(id, nome, ...). colunas(id, missao_id FK ondelete=CASCADE, nome, ordem String). cartoes(id, missao_id FK CASCADE, coluna_id FK ondelete=SET NULL nullable, titulo, ordem String, percent_complete SmallInteger default 0, prioridade SmallInteger default 5, inicio_em DateTime(tz) null, prazo_em DateTime(tz) null, concluido_em DateTime(tz) null, labels_aplicadas (JSON bitmask of slot keys), checklist_total SmallInteger, checklist_feitos SmallInteger, versao Integer for optimistic lock, ref_tipo String null, ref_id Integer null). cartao_detalhes(cartao_id PK/FK 1:1, descricao Text, ...). cartao_responsavel(cartao_id FK, user_id FK, ordem String, atribuido_em, atribuido_por) with index on user_id for 'My Tasks'. missao_labels(missao_id, slot SmallInt 1..25, nome, cor). Composite index on (coluna_id, ordem) for the board query and (missao_id, coluna_id, ordem).

**riscos** — Order-hint strings grow without a server to compact them — implement rebalancing or a midpoint generator or they bloat over time. ETag/optimistic-lock must actually be enforced on every card move or concurrent drags silently clobber order. The 25-label ceiling and fixed slots are inflexible if teams want unlimited tags. percentComplete's 3-state cannot express custom workflow stages, so teams may abuse buckets/labels as status. Denormalized checklist counters can drift from the checklist rows if not updated in the same transaction.

> Campos marcados como incertos (não consolidados): `comentarios_chat`, `tempo_real`, `notificacoes_activity_feed`, `labels_encoding`

---

<a id="item-2-microsoft-planner-premium-project-for-the-web"></a>
## 2. Microsoft Planner Premium / Project for the web

### Modelo de dados

**relacionamentos fk cascade** — msdyn_projecttask has a required lookup to msdyn_project and optional lookups to its bucket/sprint and to a parent (summary) task; msdyn_projecttaskdependency holds two lookups (predecessor task, successor task) forming the dependency edge as its own row (a true association entity). msdyn_resourceassignment links task<->resource N:N. Deleting a project cascades to its tasks, buckets, dependencies and assignments (Dataverse cascade on the project lookup). Scheduling tables cannot be written directly: create/update/delete goes through the Project Schedule APIs batched in OperationSets, and the scheduling engine writes the rows — direct Dataverse writes to scheduling entities are blocked.

**mapeamento missoes** — msdyn_project = Missao. msdyn_projectbucket = Coluna; a Sprint = a Coluna with start/end dates (i.e. add nullable sprint_inicio/sprint_fim to the coluna, or a coluna.tipo='sprint'). msdyn_projecttask = Cartao, with an added optional self-FK cartao_pai_id if you choose nestable cards. ordem = task order within bucket. msdyn_projecttaskdependency = a new dependencias table (cartao_pred_id, cartao_suc_id, tipo). Goal = a new lightweight objetivos table with a link table objetivo_cartao (rollup of child task completion). msdyn_resourceassignment = cartao_responsavel. The DocTrack-specific (ref_tipo, ref_id) still has no native equivalent — it stays a DocTrack superset.

### Ordenação

**mecanismo** — Within a bucket/sprint, task ordering is still a manual order value (an order hint / sort field on msdyn_projecttask), the same fractional-ordering idea as Basic. But Premium adds a scheduling dimension: when auto-scheduling is on, start/finish are computed from dependencies+duration, so the timeline/Gantt order is derived from dates, while the board order inside a bucket remains a manual hint. Two independent orderings coexist: manual board order (hint) and schedule order (dates).

**concorrencia conflito** — Dataverse rows have their own optimistic-concurrency (rowversion/ETag) and the Schedule APIs serialize edits through OperationSets (a transactional batch executed by the scheduling engine), so concurrent schedule edits are queued/validated rather than blindly merged. No CRDT. Effect for a Flask clone: if you add dependencies you should serialize the recompute (single transaction / advisory lock per Missao) so two concurrent schedule-affecting edits don't race.

### Atributos do cartão

**responsaveis cardinalidade** — N resources per task via msdyn_resourceassignment rows (task<->bookable resource), and each assignment can carry effort/units (allocated hours, percent allocation) — richer than Basic's assignment map. So the association object here explicitly holds work/effort data. Recommendation: if DocTrack ever needs effort tracking, put it on the cartao_responsavel association row (horas, alocacao_pct), mirroring msdyn_resourceassignment.

**datas** — Tasks carry start (msdyn_start), finish (msdyn_finish), duration, effort, and percent-complete-derived actuals; dates are Dataverse datetime (UTC-stored). In auto-schedule mode start/finish are engine-computed from dependencies+calendar; in manual mode they are user-set. Sprints add sprint-level start/end on the bucket. Nullability: dates can be empty until scheduled. Same UTC guidance as Basic.

**prioridade encoding** — Priority remains an integer 0..10 with the same Urgent/Important/Medium/Low bucketing as Basic (Premium is a superset of the Basic task). Recommendation unchanged: small Int, 4-tier UI mapping.

**labels encoding** — Premium keeps Basic's fixed label slots (categories per plan) and adds richer custom fields (single-select/choice columns in Dataverse) for structured metadata. So the pattern is: fixed label slots for quick color tags PLUS optional typed custom fields for structured attributes. For Missoes, keep fixed label slots; treat 'custom fields' as a later, optional feature.

**estados workflow** — State is still percentComplete driven (Not started / In progress / Completed), but Premium layers Sprints and Goals on top: a task belongs to a sprint (time-box) and can be linked to a Goal for objective rollup. There is no free-form configurable status enum out of the box; workflow stages are expressed by buckets/sprints. Trade-off for Missoes: percentComplete stays the completion signal; sprints/goals are orthogonal groupings, not a replacement for status.

**checklist progresso** — Checklist behaves as in Basic (per-task checklist, done/total). Premium's more meaningful progress rollup is at the summary-task and Goal level (children roll up to parent/objective) rather than the checklist.

**vinculos externos** — Premium adds first-class Goals: a task can be linked to a Goal so completion rolls up to an objective — this is the closest Microsoft analog to DocTrack's (ref_tipo, ref_id) 'card points at another entity' idea, except Goals point at an internal objective, not an arbitrary domain object. Dependencies (msdyn_projecttaskdependency) link task-to-task. Map: Goals -> objetivos + objetivo_cartao link table; keep DocTrack's typed (ref_tipo, ref_id) for Equipamento/Projeto/Documento as a separate, DocTrack-specific mechanism.

### Views

**views disponiveis** — Grid, Board (by bucket), Sprint (board grouped by dated sprint buckets), Timeline/Gantt (bars + dependency arrows + critical path), People/Assignments (workload), Goals, and Charts. This is the superset that Basic lacks (adds Sprint, Timeline/Gantt, Goals, workload).

**derivacao do mesmo dado** — Board, Grid and Sprint are group-by/sort/filter over the same msdyn_projecttask table (Sprint = group by the dated bucket). Timeline/Gantt is also the same task rows but rendered on a date axis using start/finish + the dependency table for arrows — no new task entity, just an extra join to msdyn_projecttaskdependency. So even the 'heavy' views reuse the one task table plus two relational side-tables (dependencies, assignments). Reinforces the Missoes principle: add views without re-modeling the card table.

**my tasks cross** — Yes — 'Assigned to me' / My Tasks aggregates across projects by querying msdyn_resourceassignment (or task assignee) for the current user. Same cost profile as Basic: indexed query on the assignment table.

### Dependências & scheduling

**calculo datas** — Auto-scheduling: the Planner/Project scheduling engine recomputes successor start/finish from predecessor dates + duration + calendar when a dependency or duration changes (executed via OperationSets). This is powerful but heavy and stateful. For an OFFLINE Flask app the recommendation is to AVOID replicating the engine: store dependencies as metadata/annotations and, at most, surface a soft warning ('this card starts before its predecessor finishes') rather than auto-shifting dates. Do not build a constraint solver.

### Colaboração

**comentarios chat** — Same trajectory as Basic — task comments, moving to the 2026 task-chat experience (@mentions, rich text). Premium historically had a Whiteboard tab which is being retired in the 2026 update. Minimal model to copy is identical: a comentarios table per card; skip the group-mailbox backing.

**notificacoes activity feed** — Assignment, due/late, completion, @mention notifications; Dataverse also provides audit history on rows (a fuller activity log than Basic's Graph surface). For Missoes, an append-only atividade log plus targeted notifications suffices; you do not need Dataverse-grade auditing.

**tempo real** — No public realtime socket; freshness via polling + Dataverse change tracking, and schedule edits are serialized through OperationSets. Map to DocTrack: SocketIO best-effort broadcast, DB+version as truth, serialize any schedule-affecting edit per Missao.

**templating reuso** — Project for the web supports project templates (clone structure: buckets/sprints, tasks, dependencies) and the 2026 Planner update adds custom templates. Map: 'create Missao from template' cloning Colunas/Sprints + label defs + optionally Cartoes and their dependency graph.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY: dependencies-as-their-own-row table (predecessor/successor + type); Sprint = dated bucket (reuse the Coluna table with start/end dates instead of inventing a Sprint entity); Goals as a light objetivos + link table for objective rollup; assignment-as-association-with-effort. ADAPT: dependency link TYPES (FS/SS/FF/SF) — store them, but render as informational arrows/warnings, not as inputs to an auto-scheduler; summary/parent rollup — allow nestable cards but compute rollups on read. AVOID (do NOT replicate offline): the auto-scheduling engine and its cascade recomputation, OperationSet-style transactional schedule batching, direct dependence on Dataverse, and any critical-path solver. The single biggest lesson: Sprints/Goals/dependencies are mostly ATTRIBUTES + small side-tables over the SAME task table — very little is a genuinely new task-shaped entity.

**recomendacao sqlalchemy** — Reuse the Basic schema and ADD: on colunas -> tipo Enum('bucket','sprint'), sprint_inicio DateTime(tz) null, sprint_fim DateTime(tz) null. On cartoes -> cartao_pai_id self-FK null (nestable), duracao/esforco null. New dependencias(id, missao_id FK, cartao_pred_id FK, cartao_suc_id FK, tipo Enum('FS','SS','FF','SF') default 'FS', UniqueConstraint(pred,suc)). New objetivos(id, missao_id FK, titulo, progresso computed) and objetivo_cartao(objetivo_id FK, cartao_id FK). Extend cartao_responsavel with horas/alocacao_pct. Index dependencias on both cartao_pred_id and cartao_suc_id.

**riscos** — Adding dependencies invites the temptation to auto-schedule — resist it; a naive cascade recompute in a request/response Flask cycle is a performance and consistency trap. Nestable cards + rollups can drift if rollups are stored rather than derived, and recursive parent queries need care (depth limits / cycle guards). Sprint-as-dated-bucket is clean; a separate Sprint entity would duplicate ordering logic. Goals rollup must define what 'done' means (count vs weighted) or it will confuse users.

> Campos marcados como incertos (não consolidados): `granularidade_detalhes`, `custo_reordenar_e_rebalanceamento`, `rollup_progresso`, `modelo_dependencia`, `entidades_e_hierarquia`

---

<a id="item-3-microsoft-project-desktop-project-online"></a>
## 3. Microsoft Project (desktop / Project Online)

### Modelo de dados

**entidades e hierarquia** — Deeply RECURSIVE hierarchy, unlike Planner's flat model. The core entity is the Task; tasks form a Work Breakdown Structure (WBS) via an OutlineLevel and indentation. Any task that has indented children automatically becomes a Summary Task (a parent whose dates/duration/%complete are ROLLED UP from its children, not entered directly). Nesting is arbitrarily deep (multi-level summary tasks nested within summary tasks). A special zero-row Project Summary Task (WBS 0) rolls up the whole plan. Milestones are tasks with zero duration. There is no 'bucket/column' concept — grouping is the outline itself. So the shape is: Project -> recursive Task tree (summary tasks + leaf tasks + milestones), with dependencies (Links) as a separate relation. This is the opposite end of the spectrum from Planner Basic's flat plan->bucket->task.

**relacionamentos fk cascade** — Each task references its Project and, implicitly, its parent via outline position (WBS code / OutlineLevel). Task dependencies (predecessor/successor links) are a separate many-to-many relation keyed by task UID, with a link type and lag. Resource assignments are a separate Assignment entity (task UID + resource UID + units/work). Deleting a summary task deletes its entire subtree (cascade down the outline). Deleting a task removes its links. Constraints are attributes ON the task (ConstraintType + ConstraintDate), not separate rows.

**granularidade detalhes** — Project does NOT split light board fields from heavy detail fields into a 1:1 table — a Task is one very wide record with hundreds of fields (dozens of them, e.g. Baseline1..10, custom Text1..30/Number1..20/Flag1..20). This is the opposite of Planner's plannerTask/plannerTaskDetails split and is a maintenance/perf anti-pattern for a web board. Recommendation for Cartao: do NOT copy Project's single-wide-row design; keep DocTrack's light card + 1:1 details split. Take from Project only the recursive parent/child idea, not the wide-row schema.

**mapeamento missoes** — Project = Missao (one plan). Summary Task = an OPTIONAL grouping concept — either map to a Coluna (if you stay flat) or to a nestable Cartao-with-children (if you allow nesting). Leaf Task = Cartao. Milestone = a Cartao with zero duration / a flag. WBS/OutlineLevel = a self-FK cartao_pai_id + computed path. Dependency links = a dependencias side-table. Constraints (ConstraintType/Date) = optional attributes on the card. ordem = manual sort within siblings. As with the others, DocTrack's typed (ref_tipo, ref_id) has no Project equivalent.

### Ordenação

**mecanismo** — Ordering is positional by OUTLINE, not by a fractional hint. Each task has an integer ID (row number, contiguous) and a WBS code (e.g. 1, 1.1, 1.2, 2) derived from its position in the tree; siblings are ordered by their sequence under the parent. Moving a task re-sequences row IDs. There is no order_hint/LexoRank string — it is a classic ordered-tree with renumbering.

**custo reordenar e rebalanceamento** — Because ordering is contiguous integer row IDs within an outline, a move/indent/outdent can RENUMBER many rows (all rows below the insertion point shift), i.e. O(n) reindex of the affected range — the exact cost Planner's order hints were designed to avoid. Indenting/outdenting also recomputes WBS codes for the subtree. There is no incremental rebalance; the whole affected span is rewritten. For a web kanban this is the pattern to AVOID; prefer Planner-style fractional hints. If nesting is used, store a manual sibling-order hint per node rather than global row numbers.

### Atributos do cartão

**responsaveis cardinalidade** — N resources per task through Assignment records (task UID + resource UID + Units, Work, actual/remaining work). Each assignment carries effort data (Units %, Work hours) — a rich association object, like Project-for-the-web. Recommendation unchanged: association table with optional effort fields; do not force a single owner.

**datas** — Rich date set per task: Start, Finish, Duration, plus Actual Start/Finish, Baseline Start/Finish (10 baselines), Early/Late Start/Finish (from CPM), Deadline, and ConstraintDate. In auto-schedule mode Start/Finish are ENGINE-COMPUTED from duration+links+calendar+constraints; in manual mode they are free text/dates the user types. Stored per the project calendar/working time (not a simple UTC instant — Project uses working-time calendars). For Missoes, keep it simple: start/due as nullable UTC datetimes; ignore Project's calendar/baseline machinery.

**labels encoding** — No fixed label slots like Planner. Categorization is via custom fields (Text1..30, Flag1..20, Outline Codes, custom Number/Cost fields) and Outline Codes (hierarchical lookup tables). Very flexible but heavyweight/enterprise. For Missoes, prefer Planner's fixed label slots over Project's open custom-field machinery.

**estados workflow** — No status enum and no percentComplete-as-3-states chip like Planner. Progress is % Complete (0..100, continuous) and % Work Complete; status (Not Started / In Progress / Complete / Late) is DERIVED from %complete + dates, not a stored enum. Milestones and deadlines flag schedule state. Trade-off for Missoes: Project's continuous %complete is finer but lacks Planner's clean 3-bucket grouping; the Planner 0/50/100 model is the better fit for a kanban chip.

**checklist progresso** — No checklist concept. The equivalent of 'sub-steps' is real subtasks under a summary task, whose %complete rolls up (duration-weighted) to the parent. So Project uses genuine child tasks where Planner uses a lightweight checklist. For Missoes, keep the lightweight checklist for intra-card steps; reserve nesting for real sub-cards.

### Views

**views disponiveis** — Gantt Chart (default), Task Sheet/Grid, Network Diagram (PERT), Calendar, Timeline, Task Usage / Resource Usage, Resource Sheet, Team Planner, and various reports/charts. No native kanban 'Board' in classic desktop Project (that is Planner/Project for the web).

**derivacao do mesmo dado** — Views are largely group-by/sort/filter + a rendering choice over the SAME task/assignment tables (Gantt vs Sheet vs Calendar vs Network Diagram are different renderers of one task list; Usage views pivot assignments by time). Tables + Filters + Groups + Views are composable definitions applied to one dataset — the same 'one table, many views' principle as Planner, just with heavier renderers (Gantt/Network need dates + links). Reinforces: Missoes can add views by changing group/sort/filter, not schema.

**my tasks cross** — In Project Online/Server, 'Tasks'/'My Work' aggregates assignments for the current resource across projects (timesheet/My Tasks). Desktop single-file has no cross-project 'my tasks' by itself. Cost/pattern identical to the others: indexed query on the assignment table by resource.

### Dependências & scheduling

**modelo dependencia** — Full predecessor/successor links with all four types: Finish-to-Start (FS, default), Start-to-Start (SS), Finish-to-Finish (FF), Start-to-Finish (SF), each supporting Lead/Lag (negative/positive offset, absolute or % of duration). Links are a separate relation keyed by task UID. This is the fullest dependency model of the three references.

**calculo datas** — This is the crux of what to AVOID. Auto-scheduled tasks are driven by a Critical Path Method engine: Start/Finish are computed from duration + links + calendars + constraints + resource leveling, and changes cascade through successors automatically. Manually Scheduled tasks (introduced in Project 2010; Task Mode field per task) OPT OUT of the engine — the user's dates 'stay put' and are not recalculated, and manual summary tasks do NOT roll up unless links are enforced (Respect Links). For an offline Flask app: replicate NOTHING of the CPM/leveling engine. If dependencies are wanted, adopt the 'manually scheduled' philosophy (dates are user-owned; dependencies are advisory arrows/warnings), never auto-recalculation.

### Colaboração

**comentarios chat** — Classic desktop Project has only per-task Notes (rich-text note field), no threaded chat. Collaboration/comments come from the surrounding platform (Project Online + SharePoint/Teams), not the task model itself. Minimal model to copy: a plain note/comment field or a comentarios table — do not look to desktop Project for a chat model (use Planner's task-chat instead).

**notificacoes activity feed** — Desktop Project has no notification feed; Project Server/Online adds alerts/reminders (task assignment, status update requests, timesheet) and a change history. For Missoes, this is not a useful model to copy — Planner's assignment/@mention notifications are the better reference.

**tempo real** — No realtime co-editing in desktop (.mpp is single-user); Project Online uses queue-based publish, not live sync. Do NOT model realtime on Project. Keep the SocketIO best-effort + DB-as-truth approach from Planner.

**templating reuso** — Strong templating: project templates (.mpt), Organizer for copying calendars/views/tables/custom fields between plans, and enterprise global templates in Project Server. Map: 'create Missao from template' cloning the card tree + label/field defs; the Organizer idea (share view/field definitions across Missoes) is a nice-to-have, not core.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY (concept only): the recursive parent/child WBS idea IF DocTrack decides cards should nest — a single self-FK cartao_pai_id with computed rollups; also the four dependency types as stored metadata. ADAPT: Task Mode -> adopt the 'Manually Scheduled' semantics as the DEFAULT and only mode (dates are user-owned, dependencies are advisory), which is exactly right for offline; summary rollups -> compute on read (min start / max finish / weighted %), never persist engine output; constraints -> if kept, store ConstraintType+Date as optional per-card hints that produce warnings, not schedule changes. AVOID (explicitly do NOT replicate): the auto-scheduling CPM engine, resource leveling, the 0..1000 leveling priority, working-time calendars, contiguous integer row-ID ordering (O(n) renumber), the single wide task row, whole-project pessimistic locking, and constraint-driven date recalculation (ASAP/ALAP/SNET/SNLT/FNET/FNLT/MSO/MFO all only matter to an auto-scheduler you should not build). DECISION for Missoes: default to a FLAT kanban (cards in columns, Planner-style) and treat nesting as an optional later feature; if you nest, keep it manual-scheduled and rollup-on-read.

**recomendacao sqlalchemy** — If flat (recommended default): use the Planner Basic schema unchanged. If nestable: add cartoes.cartao_pai_id (self-FK, ondelete=CASCADE, nullable), cartoes.nivel SmallInt (cached outline level), cartoes.eh_resumo Boolean (derived: has children), and compute parent inicio=min(child inicio)/prazo=max(child prazo)/percent=weighted-avg on read (guard against cycles, cap recursion depth). Add cartoes.task_mode fixed to 'manual' semantics (no engine). For constraints (only if needed): cartoes.restricao_tipo Enum('ASAP','ALAP','SNET','SNLT','FNET','FNLT','MSO','MFO') null + restricao_data null, used ONLY to render warnings. Dependencies table as in Premium (tipo FS/SS/FF/SF + lag_dias Int). Index (cartao_pai_id, ordem).

**riscos** — The overwhelming risk is scope creep into a scheduling engine: once you add dependencies + constraints, users expect auto date recalculation, resource leveling and critical path — a huge, stateful, bug-prone build entirely inappropriate offline. Contiguous row-ID ordering causes O(n) renumbering on every move (use fractional hints instead). Recursive parent queries risk cycles and deep-recursion cost — enforce acyclicity and depth limits. Wide single-row task design bloats the card table — keep the light/heavy split. Persisting rolled-up summary values invites drift — compute them.

> Campos marcados como incertos (não consolidados): `prioridade_encoding`, `concorrencia_conflito`, `rollup_progresso`, `vinculos_externos`

---

<a id="item-4-modelo-de-dados-do-graph-plannertask-plannertaskdetails"></a>
## 4. Modelo de dados do Graph (plannerTask / plannerTaskDetails)

### Modelo de dados

**entidades e hierarquia** — The Microsoft Graph Planner object graph is: plannerPlan (the board, owned 1:1 by a Microsoft 365 Group via container/owner) -> plannerBucket (column) -> plannerTask (card). Two sibling 'details' entities carry the heavy content: plannerPlanDetails (1:1 with plan; holds sharedWith and categoryDescriptions = the label names) and plannerTaskDetails (1:1 with task; holds description, checklist, references, previewType). There is no nesting of tasks. The defining design choice to study is that Graph deliberately models each card as TWO resources — a slim plannerTask for lists/boards and a fat plannerTaskDetails fetched on demand — sharing the same id.

**relacionamentos fk cascade** — plannerTask.planId (required FK -> plannerPlan) and plannerTask.bucketId (optional FK -> plannerBucket). plannerBucket.planId (required FK -> plannerPlan). plannerTaskDetails shares the task's id (1:1, same key namespace). Deleting a plan removes its buckets, tasks and details (whole-board cascade). Deleting a bucket leaves its tasks (they keep planId, lose bucketId). assignments and appliedCategories are open dictionaries embedded in the task, not separate tables in the API surface. Recommendation to mirror: FK cartao.coluna_id ondelete=SET NULL, FK coluna.missao_id and cartao.missao_id ondelete=CASCADE, cartao_detalhes 1:1 sharing the card id.

**granularidade detalhes** — This is the headline pattern. plannerTask (light) exposes only what a board needs: title, planId, bucketId, orderHint, assignments, appliedCategories, percentComplete, priority, start/due/created/completed dates, previewType and rollup counters (hasDescription, checklistItemCount, activeChecklistItemCount, referenceCount). plannerTaskDetails (heavy) is a separate GET: description (free text), checklist (map of up to 20 items), references (map of external links), previewType. The board list call therefore never drags long descriptions/checklists over the wire. Direct SQLAlchemy translation: cartoes (slim, indexed for board) + cartao_detalhes (1:1, lazy) OR a details JSON column loaded only on card open.

**mapeamento missoes** — plannerPlan = Missao; plannerPlanDetails.categoryDescriptions = missao_labels (label slot names); plannerBucket = Coluna; plannerTask = Cartao; plannerTaskDetails = cartao_detalhes (1:1); orderHint = ordem; assignments (dict keyed by userId) = cartao_responsavel association table; @odata.etag = a 'versao'/updated_at optimistic-lock column on Cartao. plannerExternalReference (URL bag) is the closest Planner analog to DocTrack's (ref_tipo, ref_id), but it is untyped — DocTrack should keep an explicit typed nullable (ref_tipo, ref_id) pair on the card instead.

### Ordenação

**mecanismo** — orderHint fractional-lexicographic string on every ordered relationship (tasks in a bucket, buckets in a plan, assignments, and per-board-view format hints). It is a String, compared ordinal-by-ordinal over printable ASCII, where a prefix sorts before its extensions. The client expresses an insertion as the composite string '<beforeHint> <afterHint>!' and the service replaces it with a compact canonical value. See the dedicated Order_Hint item for the full format.

**custo reordenar e rebalanceamento** — O(1) per move: only the moved row's orderHint changes; no sibling reindex. There is no exposed global rebalance because the SERVICE recomputes a short value on each accepted PATCH, so string growth is contained server-side. An offline clone must own that compaction: generate a midpoint string between neighbors and, if strings drift long, run an occasional per-container renormalization. This is the single most important thing you inherit responsibility for when leaving Graph.

**concorrencia conflito** — Strong optimistic concurrency: every plannerTask, plannerBucket, plannerPlanDetails and plannerTaskDetails carries an @odata.etag. PATCH/DELETE MUST send If-Match: <etag>; a stale etag yields HTTP 412 Precondition Failed, forcing re-read + retry. There is no server-side merge/CRDT. This is the exact model to replicate for a multi-user Flask app: a version/etag column plus 'UPDATE ... WHERE id=? AND versao=?' and a 409 on zero rows affected — cheap, correct, no CRDT machinery.

### Atributos do cartão

**responsaveis cardinalidade** — 0..N assignees. assignments is an open map keyed by the assignee AAD objectId -> plannerAssignment, and each plannerAssignment is an association object carrying orderHint (position in the 'Assigned to' board), assignedBy (identitySet) and assignedDateTime. There is no distinguished single owner. This is a clean argument for modeling responsaveis as an association table (cartao_responsavel) rather than a scalar column — and the association can hold extra columns later (effort/units) without schema churn.

**datas** — startDateTime, dueDateTime, createdDateTime (read-only), completedDateTime (read-only). All are Edm.DateTimeOffset serialized as ISO 8601 in UTC; all nullable except createdDateTime. completedDateTime is auto-stamped when percentComplete reaches 100. No per-task timezone is stored — instants are UTC and localized in the client. Mirror: timezone-aware UTC DateTime columns, convert at the edge only.

**prioridade encoding** — priority is Int32 0..10, lower = more important, bucketed by the UI into Urgent(0-1)/Important(2-4)/Medium(5-7)/Low(8-10); canonical writes are 1/3/5/9 with 5 as default. Storing the raw integer keeps range-sort cheap and leaves room for finer ordering than a 4-value enum.

**estados workflow** — No status enum in the data model — state is the integer percentComplete (0..100), which the UI collapses to Not started (0) / In progress (writes 50) / Completed (100). completedDateTime and completedBy are set at 100. One number drives both the completion chip and the 'group by Progress' board. A configurable status enum is a DocTrack ADAPT choice, not something the Graph model provides.

**checklist progresso** — Checklist lives in plannerTaskDetails.checklist as a map of up to 20 plannerChecklistItem (title, isChecked, orderHint, lastModifiedBy/DateTime). Progress is not a stored percentage; the light task carries rollup counters checklistItemCount and activeChecklistItemCount, and the card shows done/total. Recommendation: compute done/total on read, optionally cache both counts on the card row for the board query.

**vinculos externos** — plannerTaskDetails.references: a map keyed by percent-encoded URL -> plannerExternalReference (alias, type e.g. Word/Excel/PowerPoint/Other, previewPriority, lastModified). It is an attachment/link bag, untyped, non-relational. referenceCount rolls up to the task. It is strictly weaker than a typed FK, so DocTrack should add an explicit nullable typed (ref_tipo, ref_id) to link Equipamento/Projeto/Documento rather than emulate the URL bag.

### Views

**views disponiveis** — The Graph data itself is view-agnostic; the same plannerTask set is rendered by clients as Board (grouped by bucket/progress/assignee/priority/due/label), Grid/list, Schedule (calendar), Charts, and cross-plan 'My Tasks'. Timeline/Gantt is a Premium (Project for the web) capability, not in the classic Graph Planner surface.

**derivacao do mesmo dado** — All classic views are group-by/sort/filter over one plannerTask table — no per-view entity. The only view-specific persisted data are small board-format hints on the task (bucketTaskBoardFormat, progressTaskBoardFormat, assignedToTaskBoardFormat), each with its own orderHint so each grouping remembers its manual order. Lesson for Missoes: derive new views from query shape, and if a view needs its own manual ordering add a per-view order hint rather than a new table.

**my tasks cross** — Yes: /me/planner/tasks returns the caller's assigned tasks across ALL plans — effectively a filter by userId over the assignment map. In SQLAlchemy this is one indexed query on cartao_responsavel.user_id; index that column and it is cheap.

### Dependências & scheduling

**modelo dependencia** — None in the classic Graph Planner model — no predecessor/successor, no FS/SS/FF/SF. Dependencies exist only in Premium/Project for the web (msdyn_projecttaskdependency), which is a different Dataverse-backed API, not classic plannerTask. So for a Planner-shaped clone, dependencies are an explicit future add-on.

**calculo datas** — No auto-scheduling in classic Planner: start/due are user-entered and nothing recalculates them on change. This is the behavior to keep offline — zero scheduling engine. AVOID pulling in any cascade/auto-shift logic from the Premium/Project engine.

**rollup progresso** — No cross-task rollup because tasks do not nest. The only rollup is per-task checklist counters computed and surfaced on the card. Any parent/goal rollup is a Premium concept (Goals) outside the classic model.

### Colaboração

**templating reuso** — Graph supports copying a plan (duplicating buckets/tasks/labels/structure), and the 2026 update adds richer templates. Clone analog for Missoes: 'create from template' duplicating Colunas + label definitions + optionally Cartoes with progress/dates/assignees reset.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY: (1) the light-task / heavy-details 1:1 split (single biggest performance win); (2) @odata.etag optimistic concurrency -> a version column + If-Match-style guarded UPDATE; (3) assignments as an association object (N assignees + per-assignment metadata); (4) percentComplete 0/50/100; (5) fixed per-plan label slots; (6) integer 0..10 priority; (7) view-agnostic single table + small per-view order hints. ADAPT: orderHint (own your midpoint/compaction) and comments (plain table, drop conversationThreadId). AVOID: Graph webhook realtime dependence; conversationThreadId/mailbox indirection; any Premium/Dataverse OperationSet or auto-scheduling machinery.

**recomendacao sqlalchemy** — cartoes(id, missao_id FK CASCADE, coluna_id FK SET NULL null, titulo, ordem String, percent_complete SmallInteger default 0, prioridade SmallInteger default 5, inicio_em/prazo_em/concluido_em DateTime(timezone=True) null, labels_aplicadas JSON, checklist_total SmallInteger, checklist_feitos SmallInteger, versao Integer default 0, ref_tipo String null, ref_id Integer null). cartao_detalhes(cartao_id PK+FK 1:1, descricao Text, previewtype String). cartao_responsavel(cartao_id FK, user_id FK, ordem String, atribuido_em, atribuido_por) index(user_id). missao_labels(missao_id FK, slot SmallInteger, nome, cor). Guarded update pattern: UPDATE cartoes SET ..., versao=versao+1 WHERE id=:id AND versao=:v -> 0 rows => 409.

**riscos** — orderHint growth without a compaction step; forgetting If-Match/version check turns concurrent drags into silent clobbers; denormalized checklist counters drift if not updated in the same transaction; the light/heavy split adds a second table/JOIN or lazy load you must remember to actually keep off the board query; 25-slot label cap and per-plan scoping limit free tagging.

> Campos marcados como incertos (não consolidados): `labels_encoding`, `comentarios_chat`, `notificacoes_activity_feed`, `tempo_real`

---

<a id="item-5-order-hint-planner"></a>
## 5. Order Hint (Planner)

### Modelo de dados

**entidades e hierarquia** — Order Hint is not an entity; it is a single String property attached to every item that participates in an ordered relationship in Planner: a task's position within its bucket (plannerTask.orderHint), a bucket's position within its plan (plannerBucket.orderHint), an assignment's position in the 'Assigned to' view (plannerAssignment.orderHint), and each per-view board format (bucketTaskBoardFormat/progressTaskBoardFormat/assignedToTaskBoardFormat, each with its own orderHint). So ordering is a per-container, per-view attribute of the ordered item, never a separate ordering table.

**relacionamentos fk cascade** — There is no FK — the hint is a scalar on the row it orders. Ordering scope is implicit in the container: task hints are only comparable within the same bucketId; bucket hints only within the same planId. Moving a task to another bucket changes bucketId and assigns a new orderHint valid in the destination; the source needs no reindex. No cascade semantics: deleting a neighbor never requires touching another row's hint.

**granularidade detalhes** — The hint is a light board-render field on the slim task — it must stay on the list/board query path, never in a details blob, because it is exactly what the board sorts by. It is small (a short ASCII string) precisely so the board list stays cheap.

**mapeamento missoes** — orderHint maps directly to the Cartao.ordem and Coluna.ordem fields in the Missoes plan. The plan currently proposes 'ordem = integer reindexed by the server from a list of ids'. Order Hint is the alternative: a per-container string that makes a move a single-row write. If Missoes keeps integer reindex it accepts O(n) rewrites per move but total simplicity; if it adopts an order-hint/fractional string it gets O(1) moves at the cost of writing a midpoint generator. This item exists to make that trade-off explicit.

### Ordenação

**mecanismo** — A fractional-lexicographic STRING over printable ASCII (ordinals 32 'space' to 126 '~'). Comparison is ordinal-by-ordinal, and a shorter string sorts before a longer one that shares its prefix (space < '!' < ... < '~'; 'a' < 'ab' < 'abc'; 'abc' < 'abd'). To insert between two neighbors the client PATCHes the literal composite string '<previousHint> <nextHint>!' (previous hint, a single space, next hint, a trailing '!'); if a neighbor is missing you pass an empty string on that side (top of list: '' + ' ' + nextHint + '!'; bottom: previousHint + ' ' + '' + '!'). The SERVICE, not the client, then replaces that composite with a compact canonical value that still sorts into the requested gap. The trailing '!' and the space are a documented convention that guarantees the composite sorts strictly between the two neighbors before the server compacts it.

**custo reordenar e rebalanceamento** — A move is O(1): only the moved item's hint is rewritten; neighbors are never touched, so no whole-column renumber (contrast with integer position, which is O(n)). Precision does not 'run out' like integer gaps — instead the string can GROW as repeated insertions happen in the same gap (documented examples show values like 'adhg ! !' and ' 5637! 5637 adhg!!'). Because the service recomputes a short canonical value on each PATCH, growth is amortized away server-side and there is no exposed periodic global rebalance job. Critical caveat for an offline clone: you have no service doing the compaction, so YOU must implement a midpoint-string generator (and optionally an occasional per-container renormalization pass) or your strings slowly bloat.

**concorrencia conflito** — Works hand-in-hand with @odata.etag optimistic concurrency. Two users moving the same card each send If-Match; the second gets 412 and retries against the fresh hint the first move produced. Because every accepted move yields a new server-computed hint, concurrent moves converge to a consistent total order without CRDT — the loser simply recomputes '<prev> <next>!' against the now-current neighbors. No silent last-write-wins clobber of position.

### Atributos do cartão

**responsaveis cardinalidade** — Not applicable to the ordering mechanism itself, except that assignments also carry their own orderHint (each plannerAssignment has an orderHint for the 'Assigned to' board), showing the same per-relationship ordering pattern is reused for the N-assignee association objects.

**datas** — Not applicable — order hint is independent of dates. (Ordering by due date is a separate group-by/sort view, not driven by orderHint.)

**prioridade encoding** — Not applicable — priority is a separate Int field; when a board is grouped by priority the manual within-group order is still an orderHint (via the relevant board-format hint).

**labels encoding** — Not applicable to ordering.

**estados workflow** — Not applicable directly; note only that the 'group by Progress' board keeps its own manual order via progressTaskBoardFormat.orderHint, i.e. each grouping remembers a distinct order hint chain for the same task.

**checklist progresso** — Checklist items themselves are ordered by their own per-item orderHint inside plannerTaskDetails.checklist — the same string mechanism, one level down.

**vinculos externos** — Not applicable to ordering.

### Views

**views disponiveis** — Order Hint underpins every manually-ordered view: Board grouped by bucket, by progress, by assignee — each grouping has an independent hint chain so re-grouping does not destroy the manual order of the other groupings.

**derivacao do mesmo dado** — The key architectural point: instead of one canonical position, Planner stores SEVERAL order hints per task (one per board grouping via the *TaskBoardFormat hints). All are on the same task row; the view chooses which hint to sort by. Lesson for Missoes: if you ever want per-view manual ordering, add another order column/hint rather than a new table — but for an MVP a single ordem per (coluna) is enough.

**my tasks cross** — The 'Assigned to me' view uses assigneePriority / assignment orderHint so a user can manually order their own cross-plan task list independently of each board's order.

### Dependências & scheduling

**modelo dependencia** — None — order hint is pure manual positioning, unrelated to dependencies. It expresses 'the user dragged this here', not 'this must follow that'.

**calculo datas** — None — ordering never triggers date recalculation.

**rollup progresso** — None — ordering does not roll up.

### Colaboração

**comentarios chat** — Not applicable.

**tempo real** — Order hints make realtime reconciliation robust: because a move is a single-row write of a self-describing string, a client that missed an event can re-fetch and re-sort deterministically. Broadcast the moved card's new ordem via SocketIO; clients that reconnect just re-sort by ordem. No ordering CRDT needed.

**templating reuso** — When a plan/board is cloned, hints are copied so the template preserves the manual order of buckets and tasks.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — ADAPT. The order-hint IDEA (a per-container fractional key so moves are single-row writes) is worth adopting, but you must implement the midpoint/compaction the Planner service hides. Two concrete offline options: (A) Simplest / plan's current choice: integer 'ordem' reindexed from a submitted id-list on every reorder — O(n) writes per move but trivial, no growth, no compaction; perfectly fine for boards with tens of cards per column. (B) Scalable: a String/Decimal fractional key generated as the midpoint between neighbors (fractional indexing) or LexoRank — O(1) moves, but you own a midpoint generator and an occasional renormalization. Recommendation for the Missoes MVP: keep option (A) integer reindex (matches the plan, dead simple), and note (B) as the upgrade path if a column ever holds hundreds of cards or reordering becomes hot.

**recomendacao sqlalchemy** — MVP: cartoes.ordem = Integer; on POST /reordenar receive {coluna_id, ids:[...]} and do a bulk UPDATE setting ordem=index in one transaction; guard each card with its version. Upgrade path: cartoes.ordem = String(length up to ~64); generate_between(prev, next) returns a midpoint string; on move write only the moved card's ordem; add a maintenance job renormalize(coluna_id) that rewrites the column's ordem to evenly spaced values when max length exceeds a threshold. Composite index (coluna_id, ordem) either way.

**riscos** — If you copy the string form without the compaction step, hints grow unbounded. If you keep integer reindex, remember it is O(n) per move and must run in a single transaction to avoid transient duplicate positions. Mixing manual order with 'sort by due date' needs a clear rule about which wins. Concurrent moves MUST be guarded by the version/etag or two drags can interleave into an inconsistent order.

> Campos marcados como incertos (não consolidados): `notificacoes_activity_feed`

---

<a id="item-6-fractional-indexing-figma-tldraw-notion-linear"></a>
## 6. Fractional indexing (Figma / tldraw / Notion / Linear)

### Modelo de dados

**entidades e hierarquia** — Fractional indexing is a technique, not an entity: each ordered item stores one 'index' key (a string) that lexicographically sorts it among siblings. It is the generalization behind Planner's orderHint and Figma's 'positions'. The item keeps its key inline; ordering is 'SELECT ... ORDER BY index'. It applies at any level of a hierarchy independently (cards within a column, columns within a board), each container being its own key space.

**relacionamentos fk cascade** — No FK and no separate table — the key is a column on the ordered row, scoped to its container (parent_id). Moving an item across containers = change parent_id + assign a new key between the destination neighbors; the source is untouched (no reindex, no cascade). Figma stores this as a position string on each object keyed by parent.

**granularidade detalhes** — The index is a tiny string kept on the light/board row (it is the sort key, so it must be on the list query). Keys are meant to stay short but can grow with repeated same-gap inserts.

**mapeamento missoes** — The index maps to Cartao.ordem / Coluna.ordem. Versus the plan's integer-reindex approach: fractional indexing makes a move a single-row write (write only the moved card's key = midpoint(prev, next)), at the cost of (a) keys that can grow in length and (b) needing a key generator. It is the 'option B' upgrade path referenced from the Order_Hint item, and the CRDT-friendly choice if Missoes ever wants realtime multi-user editing beyond best-effort SocketIO.

### Ordenação

**mecanismo** — Assign each item a key between its neighbors so keys sort into the desired order. Two common encodings: (1) base-N digit strings compared lexicographically (e.g. base-62/base-95 over printable ASCII) where you find a string strictly between prev and next (this is what Planner's orderHint and tldraw use); (2) rational/decimal midpoints (Trello's float 'pos' is the degenerate 1-dimensional case: new_pos = (prev+next)/2). Insert at head = key before the first; at tail = key after the last; between = a value strictly between neighbors. The canonical library (Observable/@rocicorp 'fractional-indexing', after Figma/David Greenspan) generates base-62 strings and supports generateNKeysBetween for bulk inserts.

**custo reordenar e rebalanceamento** — Move/insert = O(1), a single-row write; siblings never move. The failure mode is key-length growth, not precision exhaustion: repeatedly inserting into the SAME gap makes keys longer by ~1 char each time (float pos hits 64-bit precision after ~50 same-gap inserts and must renormalize; string keys grow unbounded but slowly). Mitigations: (a) periodic renormalization/rebalance of a container to evenly spaced short keys; (b) Figma/tldraw add a small random 'jitter' suffix so two clients inserting at the same spot concurrently produce DIFFERENT keys and never collide/interleave. There is no central server required to compact — but SOMETHING (a job or on-write heuristic) should renormalize occasionally.

**concorrencia conflito** — This is fractional indexing's headline advantage and why Figma/tldraw/Notion use it: keys are generated purely from the two neighbors, so two offline/concurrent clients can insert without a lock and MERGE deterministically — it is CRDT-friendly / commutative. The jitter suffix prevents identical-key collisions when two clients target the exact same gap (worst case the two land in a stable but arbitrary relative order, never corrupt). This contrasts with integer position (needs a server to renumber) and is stronger than Planner's etag-retry: no 412/retry needed because there is no shared counter to contend on. For Missoes with only best-effort SocketIO + a DB, this is over-engineering for the MVP but the right foundation if true realtime is ever desired.

### Atributos do cartão

**responsaveis cardinalidade** — Not applicable — fractional indexing concerns position only.

**datas** — Not applicable to the mechanism (dates are separate sort keys for date-sorted views).

**prioridade encoding** — Not applicable; when a view sorts by priority, manual order within a priority group would use a separate fractional key.

**labels encoding** — Not applicable.

**estados workflow** — Not applicable, except that (as in Planner) each grouping/state can keep its own fractional key so manual order survives re-grouping.

**checklist progresso** — Checklist item order can itself use a fractional key, the same mechanism one level down.

**vinculos externos** — Not applicable.

### Views

**views disponiveis** — Enables any manually-ordered view (board/list) to persist drag order cheaply; Figma uses it for layer order, tldraw for shape z-order, Notion/Linear for row/issue order.

**derivacao do mesmo dado** — Like orderHint, you can keep MULTIPLE fractional keys per item (one per view) so each view has independent manual ordering, all on the same row. For an MVP a single key per container is enough; add another only when a second manually-ordered view appears.

**my tasks cross** — A per-user manual ordering of a cross-container list is just another fractional key scoped to (user_id), letting each user arrange their own list independently.

### Dependências & scheduling

**modelo dependencia** — None — purely positional, unrelated to dependencies.

**calculo datas** — None.

**rollup progresso** — None.

### Colaboração

**comentarios chat** — Not applicable.

**notificacoes activity feed** — A reorder is a single-key change; broadcast it as a lightweight event, not a notification.

**tempo real** — Best-in-class for realtime: because keys are computed from neighbors and are commutative, missed events reconcile by re-fetching and re-sorting; concurrent inserts merge without a server arbiter. Figma's 'Realtime Editing of Ordered Sequences' is the canonical write-up. For DocTrack, this is the mechanism to adopt IF you later move from best-effort SocketIO to genuine collaborative editing; for the MVP it is optional.

**templating reuso** — Cloning a container copies keys as-is (they remain valid because comparisons are relative), preserving order in templates.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — ADAPT (as an upgrade path), not MVP-mandatory. For the Missoes MVP the plan's integer reindex is simpler and fine. Adopt fractional indexing when: a column can hold hundreds of cards, reordering is frequent/hot, or you want realtime multi-user without lock contention. If adopted, COPY the proven approach: base-62 string keys via a small pure function generateKeyBetween(prev, next) (port the well-known algorithm), plus a jitter suffix if concurrent inserts are possible, plus an occasional renormalize job. AVOID hand-rolling float midpoints for anything but the most trivial case (64-bit precision runs out fast and forces frequent renormalization).

**recomendacao sqlalchemy** — cartoes.ordem = String(64), NOT NULL, indexed as part of (coluna_id, ordem). Pure helpers: gerar_ordem_entre(prev: str|None, next: str|None) -> str (base-62 midpoint); reindexar(coluna_id) to rewrite evenly spaced keys when the longest key in the column exceeds a threshold. On move: write only the moved card's ordem = gerar_ordem_entre(neighbor_prev, neighbor_next) within a transaction guarded by the card version. Keep a small unit test for head/tail/between and for the 'repeated same-gap insert' growth case.

**riscos** — Key-length growth if you never renormalize; float variants exhaust precision quickly; forgetting the jitter suffix lets two concurrent inserts at the same gap collide; comparison MUST be a stable byte/ordinal comparison (watch out for DB collation — use a binary/ASCII collation on the ordem column or keys may sort differently than your generator assumes). This collation pitfall is the most common real bug when porting fractional indexing to SQL.

---

<a id="item-7-jira-lexorank-trello-pos-asana-rank"></a>
## 7. Jira LexoRank + Trello pos + Asana rank

### Modelo de dados

**entidades e hierarquia** — These are ordering MECHANISMS, not full data models; each stores a single scalar order key per item. Jira LexoRank: one RANK value per issue per (rank-field, context/board), format '<bucket>|<rank>' e.g. '0|i0000o:' (issue-to-rank is 1:1 within a context). Trello: a single 64-bit float column 'pos' on both the card row (ordered within its list) and the list row (ordered within its board). Asana: an opaque server-maintained insertion order, exposed only relatively (insert_before/insert_after via API), no public numeric column. The hierarchy (board->list->card / project->section->task) is external to the key; the key itself is FLAT - exactly one scalar per item within its ordered container. Mapping: the order key lives directly on the item, scoped to its immediate container.

**relacionamentos fk cascade** — The order value is a plain column on the item row - no separate table, no FK, no join. Scope/context is implicit: a Trello pos is meaningful only within its list; a LexoRank rank only within its (field, context). Moving between containers just rewrites the key (and, for Trello, the idList FK). No cascade concerns: deleting an item simply drops its key; neighbors keep their values and the resulting gap is harmless (gaps are expected, not errors).

**granularidade detalhes** — The order key is the lightest possible board field - a single indexed scalar - deliberately kept apart from heavy card content. Trello puts 'pos' on the light card object; Jira keeps the rank on the searchable issue index, not in issue detail blobs. Recommendation for Cartao: store 'ordem' as a light, indexed column on the board row itself, never inside a 1:1 details/heavy table, so board rendering never has to touch card bodies.

**mapeamento missoes** — Missao ~= board/context; Coluna ~= list/status (the key is scoped per Coluna, so a move to another Coluna re-scopes/rewrites it); Cartao ~= card/issue carrying the key; ordem ~= the pos float (Trello) or the '<bucket>|<rank>' string (LexoRank); (ref_tipo, ref_id) is NOT part of the ordering key and stays orthogonal. Asana's relative insert_before/insert_after maps to a 'move card X after card Y in column C' server operation.

### Ordenação

**mecanismo** — Three real-world points on one spectrum. (1) Trello = numeric pos, a 64-bit IEEE double: a new card between neighbors A and B gets pos=(A+B)/2; special string inputs 'top'/'bottom' resolve server-side to min-delta / max+delta. It is a fractional index implemented as a float. (2) Jira LexoRank = base-36 lexicographic string (digits 0-9a-z) with a numeric bucket prefix, 'bucket|rank'; a move computes a midpoint STRING between the two neighbor ranks by lexical interpolation. Base-36 packs finer subdivision per character than decimal, so keys stay short. (3) Asana = opaque server-maintained rank, surfaced only as relative insert_before/insert_after. LexoRank is the engineered middle ground: fractional-index-like (near-unbounded precision) but string-based so it sorts by plain DB collation, WITH an explicit rebalancing story via rotating buckets that a pure float pos lacks.

**custo reordenar e rebalanceamento** — A single move updates exactly ONE row (write the moved item's new key) - the entire point of these schemes. Precision exhaustion differs by encoding. Trello floats carry ~52 mantissa bits; repeatedly inserting into the same shrinking gap eventually brings two positions within ~0.0001, at which point Trello renumbers the offending cards - usually just a few nearby, but in degenerate cases up to the whole list - back to evenly spaced values. LexoRank strings instead grow in length; Jira schedules a rebalance when a rank reaches 128 characters, and forces an immediate rebalance if length hits 160 characters within 12 hours. A rebalance rewrites every rank in the context into a fresh, evenly gapped bucket; the three buckets rotate 0->1->2->0 so the list stays lexicographically valid and viewable throughout the migration. Net: amortized O(1) per move, with a rare O(n) full reindex/rebalance.

### Atributos do cartão

**datas** — Not applicable - the order key carries no date semantics and does not encode time. Sorting a board by date is a separate ORDER BY on a date column, fully orthogonal to the manual key.

**prioridade encoding** — Not encoded in the key. Manual rank and priority are distinct sort keys: when a board sorts by priority the manual key is ignored, and drag-to-reorder only makes sense under manual sort. Recommendation: keep 'ordem' for manual order and priority as its own small Int-bucketed column.

**labels encoding** — Not applicable to ordering - labels/tags never participate in the order key.

**estados workflow** — The status/column change is precisely what re-scopes the key: moving a card to another Coluna rewrites its order within the target column's range (Trello sets a new pos in the target list; LexoRank recomputes within the new context). The workflow state itself is stored elsewhere (the column membership), never inside the rank.

**checklist progresso** — Not applicable - the order key has no relationship to checklist state or progress.

**vinculos externos** — Not applicable to ordering - the key never references another entity; (ref_tipo, ref_id) stays independent of 'ordem'.

### Views

**views disponiveis** — The order key feeds any view that shows a MANUAL order - board columns and ordered lists - acting as the primary sort for the 'manual' arrangement. Date/priority views ignore it and sort by their own column.

**derivacao do mesmo dado** — Yes - a single order-key column drives both board-column order and flat-list order via ORDER BY; switching to a by-date or by-priority view simply ORDER BYs a different column, introducing no new entity. One scalar, many sorts.

**my tasks cross** — A cross-container 'my cards' MANUAL order is NOT expressible with one global key per item, because the key is scoped to a single container. Cross-missao manual ordering requires a separate per-user ordering table/key; in practice cross views fall back to sort-by-date or sort-by-priority, which need no manual key at all.

### Dependências & scheduling

**modelo dependencia** — Not applicable - a pure ordering mechanism carries no predecessor/successor or FS/SS/FF/SF relationships.

**calculo datas** — Not applicable, and a design guardrail: never couple the order key to scheduling or auto-date calculation. The key must stay a dumb positional scalar; AVOID any temptation to derive dates from order.

**rollup progresso** — Not applicable - the order key has no parent/child rollup semantics.

### Colaboração

**comentarios chat** — Not applicable - ordering is unrelated to comments/chat.

**notificacoes activity feed** — A reorder emits a lightweight 'card moved' activity in these products (Trello logs an updateCard action carrying pos and/or idList). Minimal event model to replicate: (item_id, actor, old_column/old_pos, new_column/new_pos, timestamp).

**tempo real** — Because a move is a single small-scalar row write, it is cheap to broadcast: Trello pushes the new pos over its WebSocket; LexoRank rebalances run server-side and clients simply re-read the ordered list. Map to SocketIO best-effort: on a move, emit {card_id, new_key, column_id} to the Missao room and let clients re-sort locally; after a server-side rebalance, tell clients to refetch the column order.

**templating reuso** — Not applicable directly - cloning a board copies keys verbatim, or (cleaner) regenerates fresh evenly spaced keys for the new board so the clone starts with maximum headroom.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY the single-row-write move idea (Trello float midpoint OR a LexoRank-style string key) for 'ordem'. For DocTrack scale (tens to low hundreds of cards per column), ADAPT to the simpler end: either a fractional string index or a sparse Float/Int with occasional renormalization - you do not need the full bucket machinery. AVOID Jira's three-bucket rotation and background rebalance jobs (over-engineered for a single-server offline app with small data) and AVOID any CRDT/realtime merge - server-authoritative last-write-wins is enough.

**recomendacao sqlalchemy** — On Cartao add ordem = Column(String(64), index=True) holding a fractional/LexoRank-lite key (or Numeric/Float if you prefer numeric midpoints), plus a composite index (coluna_id, ordem) for board render. On move: compute a key strictly between the two target-column neighbors and write ONLY that row. Add a threshold/nightly renormalize(coluna_id) that rewrites evenly spaced keys when any key exceeds a length threshold or two keys collide. Keep an updated_at/version column for optimistic concurrency and a stable secondary sort on id to break ties deterministically.

**riscos** — Float precision exhaustion causes silent collisions/ties, so a renormalize fallback is mandatory; string keys grow unbounded without a rebalance; ties resolve non-deterministically unless you add a stable secondary sort (id); a single global key cannot express per-user or cross-column manual order; and string keys must sort by byte/ASCII, not locale - pin the column collation or lexical ordering breaks.

> Campos marcados como incertos (não consolidados): `concorrencia_conflito`, `responsaveis_cardinalidade`

---

<a id="item-8-trello"></a>
## 8. Trello

### Modelo de dados

**entidades e hierarquia** — A flat three-level hierarchy: Board -> List -> Card (with Workspace/Organization above the board, and Label, Checklist/CheckItem, Attachment, Comment below the card). Cards do NOT nest - there are no sub-cards or WBS; checklists are the lightweight stand-in for subtasks (advanced checklists and card-to-card links only approximate them). A card belongs to exactly one list, a list to exactly one board. Mapping: Board ~= Missao, List ~= Coluna, Card ~= Cartao. The model is intentionally flat, not nestable - which is exactly the minimalist kanban Missoes targets.

**relacionamentos fk cascade** — Card.idList (FK to List), Card.idBoard (denormalized FK to Board for fast cross-list queries), List.idBoard (FK to Board). Deleting a board cascades to its lists and cards; labels are board-scoped so they die with the board; checklists and check-items belong to a card and are removed with it. A card references labels via an idLabels array (many-to-many in practice, but the label set is fixed per board) and members via idMembers. Optional links - attachments, card-to-card references - are soft and do NOT cascade.

**granularidade detalhes** — Trello does NOT split a card into a light board row plus a heavy 1:1 details table in its public model: the card object itself carries the board-light fields (name, pos, idList, idBoard, due, idLabels, idMembers) PLUS 'desc' (a markdown description) and a 'badges' rollup of counts. The genuinely heavy sub-objects - checklists, comments (actions), attachments - live in separate child collections fetched on demand, not in one giant details row. Recommendation for Cartao: keep the board-light columns on the row, keep the (small) description inline, and move checklists/comments/attachments to child tables loaded lazily so board rendering stays cheap.

**mapeamento missoes** — Board -> Missao; List -> Coluna; Card -> Cartao; Card.pos -> ordem; Card.due/start -> Cartao due/start; Card.idMembers -> responsaveis (assoc table); Card.idLabels -> labels (board-scoped); a card's external link (an attachment URL or a custom field pointing at another entity) -> the optional (ref_tipo, ref_id); checklists -> a child items table.

### Ordenação

**mecanismo** — A numeric 'pos' field - a 64-bit IEEE double (float) - on both cards (ordered within their list) and lists (ordered within their board). A new item's pos is set to the average midpoint of its neighbors; the special string inputs 'top' and 'bottom' resolve server-side to (current_min - delta) / (current_max + delta). It is a fractional index implemented as a float, not a contiguous integer sequence.

### Atributos do cartão

**responsaveis cardinalidade** — N members per card - idMembers is an array, a many-to-many card<->member relationship - and the membership carries NO extra payload (no per-assignee effort, units, or order; it is plain membership). This is simpler than Planner's assignments-with-order map. Map to a straightforward association table cartao_responsavel(cartao_id, user_id).

**datas** — The card has 'due' (due datetime), 'dueComplete' (boolean marking the due as done), 'start' (start date), plus 'dateLastActivity'; creation time is derivable from the card id (a Mongo ObjectId embeds a timestamp). All timestamps are stored in UTC as ISO-8601 with a 'Z' suffix and rendered in the viewer's local timezone. All date fields are nullable - a card may have no dates at all.

**prioridade encoding** — Trello has NO native priority field. Teams encode priority with a label or a Custom Field (a dropdown or number field via the Custom Fields power-up). So priority is a label slot or a custom field, never a first-class enum. Recommendation for Missoes: do NOT copy Trello here - a small dedicated Int-bucketed priority column is cleaner than overloading labels.

**labels encoding** — Labels are board-scoped objects (id, name, color) defined once per board; a card references them through an idLabels array (many-to-many, but the label universe is FIXED per board). Colors come from a finite palette and names are optional. This is the 'fixed slots per plan' model (like Planner's appliedCategories) rather than free global tags. Cost/benefit: a cheap join, consistent categorization within a board, but labels do not roam across boards - moving a card to another board drops its labels.

**estados workflow** — There is NO explicit status enum - the workflow state IS the list (column) the card sits in. A separate 'closed'/archived boolean and the 'dueComplete' flag exist, but the true state is column membership. Trade-off for Missoes: column-as-status is the canonical minimalist choice (map Coluna = status); if you need a terminal 'done' independent of column, add a light boolean rather than a full status enum.

**checklist progresso** — A card has 0..N checklists, each with 0..N check-items in state complete/incomplete. Progress is completed/total check-items, surfaced on the card badge (e.g. '3/7'); it is COMPUTED on read, not stored as a percent. Advanced checklists can additionally assign a member and a due date per item.

**vinculos externos** — A card links to external things via Attachments (arbitrary URLs, including links to OTHER Trello cards) and via Custom Fields; Power-Ups add typed links (e.g. a GitHub PR). There is no first-class typed FK to an arbitrary domain entity. Map to the Missoes (ref_tipo, ref_id): prefer an explicit optional typed-link column pair (e.g. ref_tipo in {Equipamento, Projeto, Documento}, ref_id) over Trello's loose attachment-URL approach, so the link is queryable.

### Views

**views disponiveis** — The Board (kanban) is the primary and free view. Additional views - Calendar, Timeline, Table (across boards), Dashboard, Map - exist but are mostly gated behind paid tiers or Power-Ups. The core free product is the single board.

**derivacao do mesmo dado** — Yes - every view reads the same card set: Calendar groups cards by due date, Timeline by start/due, Table filters and sorts the same cards. No view introduces a new entity; each is a filter/group-by/sort over the cards table. This is the property to preserve in Missoes so new views cost only a query, not a re-model.

**my tasks cross** — Yes - the 'Cards' / 'Your Items' view (formerly 'My Cards') aggregates every card where you are a member, ACROSS all boards, queried by idMembers; there is also a Highlights/Inbox. Cost: an index on member->card and a cross-board aggregation query. Directly maps to a 'meus cartoes' cross-missao view via an index on cartao_responsavel(user_id).

### Dependências & scheduling

**modelo dependencia** — No native task dependencies - no predecessor/successor, no FS/SS/FF/SF, no lead/lag. Dependencies exist only through third-party Power-Ups. Core Trello is intentionally dependency-free.

**calculo datas** — No auto-scheduling engine; dates ('due', 'start') are set manually. There is nothing to avoid replicating here - Trello already omits a scheduling engine, which is exactly the right posture for an offline app: keep dates manual and never auto-compute them.

**rollup progresso** — No parent/summary rollup - the model is flat with no summary tasks. The only progress rollup is the per-card checklist badge (completed/total check-items), computed on read, not a stored parent percentage.

### Colaboração

**comentarios chat** — Comments on a card are stored as Actions of type commentCard - a flat, chronological list, NOT threaded (reactions exist; replies are just @-mention convention). Minimal model to replicate: comentario(cartao_id, autor_id, texto, criado_em).

**notificacoes activity feed** — The card's activity feed is its Actions log (created, moved, due changed, member added/removed, comment, checklist item toggled). Notifications fire on @mention, being added to a card, due-date reminders, and changes to cards you follow (watch). A simple per-card append-only activity table plus a per-user notification queue reproduces this.

**templating reuso** — Board templates and card templates exist. Cloning a board duplicates its lists, labels, cards, and checklists; copying a card can carry over its checklists, labels, and members. Map: 'create Missao from template' clones Colunas + labels + Cartoes in one operation.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY the flat Board->List->Card model, column-as-status, the float 'pos' ordering (single-row moves), board-scoped labels, per-card checklists with computed progress, and the cross-board 'my cards' query. ADAPT: give priority a real dedicated column (do not overload labels as Trello forces users to), and add an explicit optional typed (ref_tipo, ref_id) link instead of loose attachment URLs. AVOID native dependencies and any scheduling engine (Trello itself avoids them) and AVOID any CRDT/realtime-merge machinery - server-authoritative sync is enough.

**recomendacao sqlalchemy** — Tables: Missao; Coluna(missao_id FK, ordem); Cartao(coluna_id FK, missao_id denormalized FK, ordem Float or String indexed, titulo, descricao Text, due DateTime, start DateTime, done Boolean, ref_tipo nullable, ref_id nullable). Association tables cartao_responsavel(cartao_id, user_id) and cartao_label(cartao_id, label_id) with Label(missao_id, nome, cor). Checklist and check-item child tables. Indexes: (coluna_id, ordem) for board render, user_id on cartao_responsavel for 'meus cartoes', and (ref_tipo, ref_id) for reverse lookups.

**riscos** — Float pos precision can drift, so keep an occasional renormalize routine. The denormalized missao_id/idBoard must be kept consistent whenever a card moves (update both coluna_id and missao_id in the same transaction). Board-scoped labels mean a card moved across boards loses its labels - decide and document that policy. Checklist progress recomputed each render is cheap but risks N+1 queries if check-items are not eager-loaded.

> Campos marcados como incertos (não consolidados): `custo_reordenar_e_rebalanceamento`, `concorrencia_conflito`, `tempo_real`

---

<a id="item-9-github-projects-v2"></a>
## 9. GitHub Projects (v2)

### Modelo de dados

**entidades e hierarquia** — Project (v2) -> ProjectItems. An item is a thin wrapper whose 'content' is an Issue, a Pull Request, or a project-local Draft Issue. Fields are defined at the PROJECT level (ProjectV2Field, ProjectV2SingleSelectField, ProjectV2IterationField, plus built-ins), and each item stores field VALUES (ProjectV2ItemFieldValue subtypes) keyed by (item, field). There is no columns table: the board's 'columns' are simply the options of a chosen single-select/iteration field (typically the built-in Status). The structure is flat (a project holds items); any nesting comes indirectly from issue sub-issues/task-lists, not from the project itself. A project may hold up to 50 fields total (built-in + custom). Mapping: Project ~= Missao; the grouping field's options ~= Colunas; ProjectItem ~= Cartao; the linked issue/PR ~= (ref_tipo, ref_id).

**relacionamentos fk cascade** — A ProjectItem references its content (issue/PR) by GraphQL node id - a LOOSE link, not a cascade. Closing or even deleting the underlying issue does NOT delete the project item (it is archived/redacted, not cascaded away); removing an item from the project does not touch the issue. Field definitions belong to the project, so deleting a single-select field removes its values from all items. Draft issues are OWNED by the project and are deleted with it. The item<->content link is deliberately soft and optional - an item can be a bare draft with no external content at all.

**granularidade detalhes** — Strong light/heavy separation: the ProjectItem (board-light - its position and field values) is distinct from the heavy content (the issue/PR body, comments, timeline) which lives entirely in the Issues/PR subsystem. Field values are stored as separate typed value objects keyed by (item, field), not as fixed columns on the item row - an extreme, fully generic version of the plannerTask<->plannerTaskDetails split where the 'details' are literally a whole issue in another system. Recommendation for Cartao: keep board-light fields on the row, but note GitHub's fully generic (item, field, value) EAV is heavier than a small offline app needs.

**mapeamento missoes** — Project -> Missao; the chosen Status/single-select field's options -> Colunas; ProjectItem -> Cartao; the item's order within its column -> ordem; the linked Issue/PR content -> (ref_tipo, ref_id) e.g. ('issue'|'pr', id), with a draft item leaving it null; custom fields -> either fixed Cartao columns or a small EAV.

### Atributos do cartão

**responsaveis cardinalidade** — Assignees are INHERITED from the underlying Issue/PR (multiple assignees, a many-to-many relationship) and shown as a read-through 'Assignees' field, not a native project field; there is no core people-type custom field. Draft issues can also carry assignees. Map to Missoes: N responsaveis via the linked entity or a plain association table cartao_responsavel(cartao_id, user_id).

**datas** — A built-in Date custom-field type plus an Iteration field type (a dated range with a start date + duration, optionally with breaks); issues additionally bring created/closed/merged timestamps. Custom date fields are arbitrary. Date fields are date-only; underlying issue/PR timestamps are UTC. Iteration fields are the distinctive one - they carry start + duration and define recurring time-boxes used as board columns or roadmap bands.

**prioridade encoding** — Priority is conventionally a custom Single-select field (options such as P0/P1/P2 or Low/Medium/High), i.e. an enum of option ids - NOT a numeric scale; there is no built-in numeric priority. Each option has an id, name, color, and description. Recommendation: a single-select enum maps cleanly to a small lookup table or an Int bucket in Missoes.

**labels encoding** — Two coexisting systems. (1) Labels inherited from the Issue/PR are repo-scoped label objects in a many-to-many relationship, shown as a read-through field. (2) Within the project, categorization is usually a custom Single-select field with a FIXED set of options per project - the 'fixed slots per plan' model. So free-ish repo labels for source-of-truth tagging, plus fixed project single-selects for board-local categorization.

**estados workflow** — The signature feature: workflow state is a CONFIGURABLE Single-select 'Status' field (Todo / In Progress / Done plus custom options), each option having id/name/color/description, and the board's columns ARE those options. This is the Notion/Linear-style configurable enum, NOT Planner's fixed 0/50/100 percentComplete; the same field drives both the status chip and the board grouping. It is the strongest inspiration here if Missoes ever wants user-configurable columns instead of fixed Coluna rows.

**vinculos externos** — This is the CORE idea and the best reference for Missoes: an item is LINKED to an Issue or a Pull Request by node id (PRs linked to issues also surface that relationship), and an item may instead be a bare Draft Issue with no external link. content = {Issue | PullRequest | DraftIssue} is exactly the optional typed (ref_tipo, ref_id) pattern - a first-class, queryable, OPTIONAL link where 'draft/none' is a valid state. Copy this shape directly.

### Views

**views disponiveis** — Table (a high-density spreadsheet), Board (kanban), and Roadmap (timeline). Each saved view keeps its own layout; there is also a Slice panel and Insights/Charts built on the same items.

**derivacao do mesmo dado** — Yes - this is the killer property: every view is a group-by / sort / filter / slice over the SAME items+field-values dataset, with NO new entity per view. The board's column-field, the table's visible columns, and the roadmap's date/iteration fields are all just field selections over one item set; adding a view never re-models data. This is precisely the property Missoes should preserve: many views, one table.

### Dependências & scheduling

**modelo dependencia** — No first-class predecessor/successor dependencies in Projects v2 - no FS/SS/FF/SF, no lead/lag. Relationships come from issue<->PR links and from sub-issues (parent/child) and tracking/tracked-by, which express hierarchy and linkage, not a scheduled dependency graph.

**calculo datas** — No auto-scheduling engine: start/target dates and iterations are set manually and the roadmap merely visualizes them. Nothing needs to be avoided by replicating GitHub - it deliberately omits a scheduler, which is the correct offline posture; keep dates manual.

**rollup progresso** — Sub-issue progress rolls up ON THE ISSUE (a completed/total sub-issue bar). At the project level, Insights/Charts aggregate counts by field, but there is no stored parent-percentage on the item - roll-ups are computed/aggregated on demand, not persisted.

### Colaboração

**comentarios chat** — There is no project-item comment thread; discussion lives on the underlying Issue/PR as a threaded timeline. Draft issues have limited fields and must be converted to real issues to gain a comment thread. Minimal model for Missoes: attach comments to the linked entity, or add a simple flat card-comment table.

**notificacoes activity feed** — Notifications originate from the Issue/PR (assignment, @mention, review requested, state change); project field changes emit webhooks (project_v2_item, with previous+current values) and appear in the project's activity/history, but are not a rich per-user notification feed. Map: keep your own activity log on field/status/position changes plus a per-user notification queue.

**tempo real** — There is no public realtime browser socket; synchronization is GraphQL polling plus webhooks (project_v2 and project_v2_item events carrying previous and current field values). Map to SocketIO best-effort: on a server-side field/status/position change, emit to the Missao room; note GitHub's own model is webhook/poll, not push-to-browser - so treat live sync as a best-effort layer over authoritative REST reads.

**templating reuso** — Project templates exist - an organization can mark a project as a template, and 'copy project' duplicates the field schema, views, and workflows, optionally including draft items (but not the linked issues). Map: 'create Missao from template' clones the Colunas (status/single-select options) + custom fields + saved views, without dragging along external links.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY the item-links-to-external-entity pattern (content = issue/PR/draft) as the optional (ref_tipo, ref_id) with draft-only cards allowed, and COPY 'many views over one dataset' (group/sort/filter, no new entity per view). ADAPT the configurable Single-select Status-as-columns - powerful, but you can start with fixed Coluna rows and only later promote to a generic status field; ADAPT custom fields but resist a full generic EAV, preferring a few typed columns plus an optional JSON blob. AVOID the fully generic (item, field, value) EAV, the GraphQL-node-id indirection, and the webhook/no-realtime posture as literal designs, and AVOID auto-scheduling (there is none anyway).

**recomendacao sqlalchemy** — Cartao(missao_id FK, coluna_id FK, ordem, titulo, descricao, ref_tipo nullable, ref_id nullable) where ref_tipo/ref_id implement the GitHub content link (Equipamento/Projeto/Documento, or null = draft). For flexible fields prefer a few typed columns (status via coluna_id, prioridade Int, due Date) and only add a light cartao_campo(cartao_id, campo_id, valor) EAV if user-defined fields are truly required. Store views as saved filter/group/sort configs (JSON), NOT as tables. Indexes: (missao_id, coluna_id, ordem) for board render and (ref_tipo, ref_id) for reverse lookups.

**riscos** — A generic EAV/custom-field system is a maintenance and query-performance trap for a small Flask app (N+1 reads, no simple ORDER BY on a value, weak constraints) - keep fields fixed unless genuinely needed. The soft item<->content link means orphan handling (a linked Equipamento/Documento deleted) needs an explicit policy since there is no cascade. 'Many views from one dataset' is cheap only while the base query stays indexable - complex saved filters can degrade. And relying on webhooks/polling with no realtime means stale boards unless you add your own SocketIO push.

> Campos marcados como incertos (não consolidados): `mecanismo`, `custo_reordenar_e_rebalanceamento`, `concorrencia_conflito`, `checklist_progresso`, `my_tasks_cross`

---

<a id="item-10-notion-linear"></a>
## 10. Notion / Linear

### Modelo de dados

**entidades e hierarquia** — Notion: a Database is a collection of Pages; each Page is a row whose columns are typed Properties (Status, Select/Multi-select, Person, Date, Relation, etc.). A board is just a database rendered as a Board view grouped by a Select/Status property — the 'column' is a property VALUE, not a stored entity. Pages can nest arbitrarily (a page inside a page), giving free-form hierarchy. Linear: the core entity is an Issue belonging to a Team; issues have a workflow State, optional parent Issue (sub-issues, one level of nesting emphasized), Project and Cycle (iteration) associations, Labels, assignee, priority. In both, the 'column' of a board is a field value (Status/State), so adding a column = adding an option to that field, not creating a Bucket row. This is the opposite of Planner/Trello where a column (bucket/list) is a first-class row.

**relacionamentos fk cascade** — Notion: Status/Select options are defined on the property schema (database level); a page references an option by id. Relations are explicit N:N link tables between databases. Sub-pages reference a parent page id. Linear: Issue.stateId FK -> WorkflowState (team-scoped), Issue.parentId self-FK for sub-issues, Issue.projectId/cycleId FKs, Issue<->Label is N:N. Deleting a state usually requires migrating issues off it (states are reference data, not cascade-deleted under issues). Key contrast for Missoes: if a column is a status VALUE (Notion/Linear) you never cascade-delete cards when removing a column — you reassign them; if a column is a Bucket ROW (Planner/plan) you decide cascade vs orphan.

**granularidade detalhes** — Notion page 'content' (the body blocks) is separate from its row properties — analogous to the light/heavy split (board reads properties, opening the page loads blocks). Linear keeps the issue description (markdown) with the issue but board/list queries select only the light fields. Both keep the board query off the heavy body.

**mapeamento missoes** — Two modeling philosophies to choose from. PHILOSOPHY A (Planner/Trello, and the current Missoes plan): Coluna is a real row (MissaoColuna) and Cartao.coluna_id FKs it — flexible arbitrary columns, matches drag-between-columns naturally. PHILOSOPHY B (Notion/Linear): the 'column' is a status enum value on the Cartao and the board groups by it — fewer tables, but arbitrary user-named columns become 'status options' you must manage. For DocTrack's 'A fazer / Fazendo / Concluido' default plus user-added columns, Philosophy A (the plan's MissaoColuna) is the better fit; borrow from B only the idea of an optional status/estado field for reporting. Linear's priority int and label N:N map to Cartao.prioridade and an etiquetas model; Linear sub-issues (parentId) map to a future optional Cartao.parent_id if nesting is ever wanted.

### Ordenação

**mecanismo** — Both use fractional-index-style sort keys. Linear stores a 'sortOrder' (a floating/rational-like value) per issue per context (board position, and separate keys for sub-lists), computed as a midpoint between neighbors — the classic fractional approach. Notion persists manual drag order in the view configuration using fractional-index strings per row per view. In both, dragging writes only the moved item's key (single-row write), and each VIEW can hold its own manual order.

**custo reordenar e rebalanceamento** — O(1) per move (write one key). Same growth/precision caveat as fractional indexing: Linear's float sortOrder can need renormalization after many same-gap inserts; Notion's string keys grow slowly. Both amortize with occasional rebalancing. No whole-list reindex on a normal move.

**concorrencia conflito** — Linear is famously offline-first with a local sync engine (client-side mutations reconciled against a server log), so ordering and edits merge across clients; conflicts resolve via the sync engine rather than hard 412s. Notion syncs collaboratively too. This is heavier than DocTrack needs — the takeaway is that fractional keys make their concurrent reordering merge cleanly; a Flask app can get 90% of the benefit with a version column + best-effort broadcast without building a sync engine.

### Atributos do cartão

**datas** — Linear: createdAt, updatedAt, startedAt, completedAt, canceledAt, dueDate, plus cycle start/end. Notion: any number of Date properties, each optional, stored as ISO with optional time and timezone. Both store timestamps in UTC-ish ISO and localize in UI. Lesson: a small fixed set of dates (criado, inicio, prazo, concluido) covers the card; avoid unbounded user date fields for the MVP.

**prioridade encoding** — Linear priority is an INTEGER 0..4 with fixed meaning: 0 = No priority, 1 = Urgent, 2 = High, 3 = Medium, 4 = Low (note: 1 is highest, similar spirit to Planner's low-number-is-urgent). This maps almost directly onto a small-int prioridade. Notion models priority as a Select property with user-defined options (strings + colors). The int encoding (Linear) is the cleaner, sort-friendly choice for Missoes; reserve Select-style for fully custom taxonomies.

**labels encoding** — Both use N:N free-form labels/tags: Linear Labels are team- or workspace-scoped, can be grouped, and an issue has many; Notion Multi-select is an open set of options per property. This is the OPPOSITE of Planner's 25 fixed slots. Trade-off vs Planner: N:N labels are unlimited and global/reusable but need a join table and a labels catalog; Planner slots are capped but denormalized/cheap. For Missoes, per-Missao labels (either a small join table or a JSON list) is fine; go global N:N only if labels must be shared across Missoes.

**checklist progresso** — Linear has sub-issues with a progress rollup on the parent (n/m done) and native checklist-like sub-issue lists; Notion uses to-do blocks or a related sub-tasks database. Both compute progress from children rather than storing a percentage. Matches the 'compute done/total on read' recommendation.

**vinculos externos** — Both link richly: Linear links issues to each other (blocks/blocked-by/relates-to), to PRs/commits via integrations, and to Projects; Notion Relations link pages across databases (true typed N:N). Notion Relations are the closest to a typed (ref_tipo, ref_id): a strongly-typed link to another collection. This validates DocTrack's plan to give Cartao an explicit typed nullable (ref_tipo, ref_id) to Equipamento/Projeto/Documento.

### Views

**views disponiveis** — Notion: Board, Table, List, Calendar, Timeline (Gantt-like), Gallery — all over the same database. Linear: Board, List, and for projects a Timeline/roadmap; plus filtered views, 'My Issues', cycles.

**derivacao do mesmo dado** — Textbook 'many views, one dataset': in both tools every view is a saved group-by + sort + filter over the SAME rows; switching Board<->Table<->Calendar changes only the rendering and the grouping/sort, never the underlying entity. Board grouping is by a chosen property (Status/State/assignee/priority/label). This is the strongest endorsement of the plan's intent to keep one Cartao table and add views as query shapes.

**my tasks cross** — Both have a first-class 'My Issues' / 'Assigned to me' cross-project view = filter by assignee across teams/databases. Cheap in SQL: indexed query on assignee. Linear also lets users manually order their own 'My Issues' via a per-user sort key.

### Dependências & scheduling

**modelo dependencia** — Linear: issue relations include blocks / blocked-by / relates-to / duplicate — lightweight dependency semantics WITHOUT a scheduling engine (no auto date math). Notion: dependencies exist in Timeline view as explicit relation properties (blocking/blocked-by) that draw arrows but do not auto-reschedule by default. This is exactly the 'ADAPT' sweet spot for Missoes: store a simple relation type (blocks/blocked-by/relates) and RENDER it as a chip/warning, with no auto-scheduling.

**calculo datas** — Neither auto-schedules by default the way MS Project does; dates are user-set. Notion Timeline can offset dependent bars visually but does not run a CPM engine. Keep dates manual offline.

**rollup progresso** — Linear rolls up sub-issue completion to the parent and issue completion to Project/Cycle progress; Notion has Rollup properties that aggregate a related database (e.g. % of sub-tasks done). Both derive rollups rather than storing them — compute on read if Missoes ever nests.

### Colaboração

**comentarios chat** — Both have rich threaded comments per item with @mentions, reactions, and markdown; Linear threads comments on the issue and on sub-threads. Minimal clone: a comentario table (cartao_id, autor_id, corpo markdown, criado_em, parent_id for threads).

**notificacoes activity feed** — Both keep a per-item activity/history feed (state changes, assignments, comments, label changes) and notify assignee/subscribers/@mentions via inbox + email/push. For Missoes, an append-only atividade log plus targeted notifications on assignment/@mention/completion is the pragmatic subset.

**tempo real** — Both are genuinely realtime/collaborative (Linear via its offline-first sync engine, Notion via collaborative editing). This is beyond DocTrack's best-effort SocketIO. Adopt only the principle (broadcast changes, reconcile on reconnect); the DB stays source of truth.

**templating reuso** — Both support templates: Notion database/page templates (including default property values and body), Linear issue templates and project templates. Analog: 'create Missao from template' cloning Colunas, label catalog, and optionally seeded Cartoes.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY: (1) integer priority with fixed meaning (Linear 0..4) — clean and sort-friendly; (2) 'many views, one table' as the guiding principle; (3) typed relations as the model for DocTrack's (ref_tipo, ref_id); (4) compute-on-read progress rollups. ADAPT: configurable workflow states — offer them ONLY if the 3-state/columns model is insufficient; a good middle path is MissaoColuna rows tagged with a todo/doing/done category. Also ADAPT lightweight dependency relations (blocks/blocked-by rendered as chips, no scheduling). AVOID: building an offline-first sync engine / CRDT collaborative editor (Linear-grade) — massive scope for a Flask module; N:N labels are fine but do not over-generalize into a full EAV property system like Notion databases (that is the GitHub-Projects-v2 AVOID as well).

**recomendacao sqlalchemy** — Keep the plan's MissaoColuna rows (Philosophy A). Add cartoes.prioridade SmallInteger (0..4 Linear-style OR the plan's baixa/media/alta/urgente mapped to ints). etiquetas: either JSON list per card (MVP) or cartao_etiqueta(cartao_id, etiqueta_id) N:N + etiquetas(missao_id, nome, cor) if labels must be reusable. Optional cartao.estado_categoria Enum('todo','doing','done') on the COLUMN for reporting. Optional future cartao.parent_id self-FK for sub-cards. cartao_relacao(cartao_id, alvo_cartao_id, tipo Enum('bloqueia','bloqueado_por','relaciona')) for lightweight dependencies. comentario(cartao_id, autor_id, corpo, criado_em, parent_id).

**riscos** — Configurable states add UI/management complexity (migrating cards when a state is removed) — only worth it if genuinely needed. N:N labels need a catalog and cleanup of orphans. Sub-issues (parent_id) reopen the flat-vs-nested question and complicate the board (do sub-cards show as cards?). Copying Linear's sync-engine mental model would balloon scope; resist it for an MVP.

> Campos marcados como incertos (não consolidados): `estados_workflow`, `responsaveis_cardinalidade`

---

<a id="item-11-views-derivadas-de-um-único-dataset"></a>
## 11. Views derivadas de um único dataset

### Modelo de dados

**entidades e hierarquia** — Across Planner, Trello, GitHub Projects v2, Notion and Linear the recurring architecture is: ONE canonical set of task/card rows, and every visualization (Board, Grid/Table, Timeline/Gantt, Calendar, Charts, My Tasks) is a projection of those same rows. No view introduces a new core entity. The only per-view state is (a) view configuration (which grouping/sort/filter) and (b) small per-view ordering hints so manual drag order survives switching or re-grouping. Hierarchy is unchanged by the view; a Board just groups the flat task list by a field value.

**relacionamentos fk cascade** — Views are read models; they add no FKs to the domain. What may be persisted is a saved-view config row (belongs to a Missao and/or user) and optional per-view order-hint columns on the task. None of these cascade into task data; deleting a saved view never touches cards.

**granularidade detalhes** — Views select only light board/list fields; the heavy details (description/checklist) load on card open regardless of view. So the light/heavy split pays off in EVERY view — the board, table and calendar all run off the slim row.

**mapeamento missoes** — The Missoes MVP ships exactly ONE view — the Board grouped by Coluna (bucketId). This item's lesson is forward-looking: because Cartao already carries the fields other views need (prazo -> Calendar/Timeline, prioridade -> group/sort, responsaveis -> My Tasks, percent/estado -> progress charts), future views are pure query changes (group-by/sort/filter) with NO new tables and NO re-modeling. Design the Cartao row now so those fields exist; add views later as endpoints/renderers.

### Ordenação

**mecanismo** — Manual order per view is a per-view sort key (order hint / fractional index) on the task; automatic-sort views (by due date, priority) just ORDER BY that field. Planner persists distinct board-format order hints per grouping (bucket/progress/assignee) so each grouping remembers its own manual order.

**custo reordenar e rebalanceamento** — If you only ever manually order ONE view (the Board by Coluna), you need one 'ordem' per card — cheap. Each additional manually-orderable view costs one more order column/hint per card. Auto-sorted views cost nothing extra (they sort by an existing field). Recommendation: give the MVP a single ordem for the Board; add per-view order only if/when a second manually-ordered view is actually built.

**concorrencia conflito** — Views are read-mostly, so concurrency is mainly about the underlying card edits (guarded by the card version). Saved-view config edits are low-contention; last-write-wins on a view config is acceptable.

### Atributos do cartão

**responsaveis cardinalidade** — The 'My Tasks' view is the direct consumer of assignee cardinality: with N assignees it filters cards where the user is in the assignment set. Ensure the assignee relation is indexed by user_id for this view to be cheap.

**datas** — Calendar and Timeline/Gantt views are projections of the card's date fields (prazo/inicio). Storing start+due enables a Timeline for free later; storing only due still enables a Calendar. This is why the date fields belong on the card even though the MVP board does not group by them.

**prioridade encoding** — A 'group by priority' board and a priority chart are free once prioridade is a sortable small int. No extra modeling.

**labels encoding** — A 'group by label' board and label-filtered views derive from the etiquetas relation; slot/JSON labels are filterable directly, N:N labels via a join.

**estados workflow** — A progress/status chart and a 'group by estado' board derive from percent_complete or the column's category. If columns are tagged todo/doing/done, a cross-column progress rollup becomes a trivial aggregate.

**checklist progresso** — Charts can aggregate checklist completion (sum of checklist_feitos/checklist_total) once those counters exist on the card.

**vinculos externos** — A 'cards linked to Equipamento X' view is just a filter on (ref_tipo, ref_id) — an example of a valuable view that costs nothing beyond the field already in the plan.

### Views

**views disponiveis** — Superset observed across the references: Board (group-by field), Grid/Table (spreadsheet), Timeline/Gantt (dates + optional dependencies), Calendar (by date), Charts/Insights (aggregations), and My Tasks/Assigned-to-me (cross-container by assignee). Planner Basic has all but Gantt; Premium/Project-web adds Timeline+dependencies; Trello centers on Board; GitHub v2 and Notion/Linear expose Table+Board+Timeline uniformly.

**derivacao do mesmo dado** — The core finding: EVERY listed view = group_by + sort + filter over one row set + a renderer. Board = group by a field, render columns. Table = no grouping, render rows. Calendar = filter has-date, render by date. Timeline = render start..due bars. Charts = aggregate. My Tasks = filter by assignee across Missoes. Implementation implication for DocTrack: a single board endpoint returning the card list, plus client-side (or query-param) grouping/sort/filter, can grow into all these views without schema changes.

**my tasks cross** — The one view worth building EARLY after the board, because it is high-value (a personal landing page) and cheap (indexed filter by responsavel across all Missoes). Linear/Planner/Trello all ship it. Recommend it as the first fast-follow to the MVP board.

### Dependências & scheduling

**modelo dependencia** — Only the Timeline/Gantt view consumes dependencies (to draw arrows). Since the MVP has no dependencies, the Timeline view is deferred; if lightweight blocks/blocked-by relations are added later (see Notion/Linear), a read-only Timeline can render them as arrows without a scheduling engine.

**calculo datas** — Views never compute dates; they only display card dates. Keep it that way offline.

**rollup progresso** — Charts/insights views derive rollups (counts by column/status/priority, % complete) as aggregate queries over the card table — computed on read, nothing stored.

### Colaboração

**comentarios chat** — Not applicable to views (comments live on the card, shown when opened from any view).

**notificacoes activity feed** — Not applicable to views.

**tempo real** — A card move/edit broadcast via SocketIO should update whatever view is open by re-applying the client-side grouping/sort; because all views derive from the same rows, one incremental patch keeps every open view consistent. Reconnect => refetch the row set and re-project.

**templating reuso** — Saved views can themselves be templated/shared (GitHub Projects, Notion, Linear all share view configs), but this is a later nicety, not MVP.

### Replicável offline (veredito p/ DocTrack)

**veredito copy adapt avoid** — COPY the 'many views, one table' architecture as the guiding constraint: model the Cartao row now with the fields future views need (dates, prioridade, responsaveis, estado/percent, etiquetas, ref_tipo/ref_id) so no view ever requires a new table. Build ONLY the Board (group by Coluna) for the MVP, then fast-follow with My Tasks (cheap, high value). ADAPT Timeline/Charts as later query-only additions. AVOID: creating per-view entities, denormalizing cards into view-specific tables, or building a generic saved-view/config engine before there is a second view to justify it.

**recomendacao sqlalchemy** — No new tables for the MVP: one board endpoint GET /api/missoes/<id> returns colunas with nested cartoes ordered by (coluna_id, ordem). Later views are new endpoints or query params over the same Cartao query: /api/missoes/<id>/cartoes?group_by=prioridade, /api/meus-cartoes?responsavel=<uid> (index cartao_responsavel.user_id or a responsaveis lookup), /api/missoes/<id>/timeline (select cards with prazo). Optional later: saved_view(missao_id, user_id, config JSON) only when saved views are actually requested.

**riscos** — Premature view abstraction (a saved-view/config engine) is wasted scope before a second view exists. Adding a manually-ordered second view later requires a second order key per card — cheap only if the pattern is anticipated. Client-side grouping/filtering must page/limit large card sets to stay fast. Ensure the single board query stays on the light row (light/heavy split) or every view inherits a slow query.

---
