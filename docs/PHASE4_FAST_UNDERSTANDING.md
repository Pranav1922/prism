# Phase 4 Report — Fast Understanding and Response-Relevant Turn Classification

| | |
|---|---|
| Date | 2026-09-30 |
| Plan mapping | [`PHASE2_PLAN.md`](PHASE2_PLAN.md) Phase 3 ("fast understanding, deterministic T0"). Reported here as "Phase 4", as requested. |
| Result | **258 tests pass on Python 3.12 and 3.10**; ruff and mypy clean; **47/47 black-box scenarios pass** (34 original + 13 understanding); replay byte-identical |
| New decisions | D11 (goal switch withholds re-dispatch), D12 (unfilled retraction is reverted), both recorded in [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md) §16 |

All metrics here are **INTERNAL PRISM-STYLE** measurements on this project's own corpus and scenarios. They are not Samsung scores and not real-world accuracy.

## 1. Architecture

```
user.text ──► Kernel.on_user_text ──► understand_context(turn)      (ACTIVE goal only: slots + schemas + history,
                    │                                                 asked clarifications, last 12 closed utterances)
                    ├──► recognize(text, payload, ctx) ─► Understanding(cls, writes, confirm, attributed, cues)
                    │        agent/understand_rules.py:  pure, bounded (≤ 64 tokens), no I/O, no model
                    └──► the kernel applies: LWW slot writes (source T0), F5 supersession + cancel, D11 flag,
                         and journals T0.classify {cls, cues, attributed, writes}
```

- **Interface.** The recogniser sits behind the existing `Kernel(understand=...)` port, so the kernel remains the only writer of state. `LocalAgent(understanding="rules")` is the default. `--understanding scripted` keeps the Phase 1–3 per-utterance table **for comparison only** (`impl_a_scripted`).
- **Provenance.** Every write is journaled with its cues (for example `role:to->destination`, `named:date`, `retract:destination`), so every decision can be explained from the trace. Replay uses the backend recorded in the journal header.
- **Internal annotations.** An explicit `payload["t0"]` annotation still wins (kernel tests only). The wire format cannot carry one.

## 2. Classification model

Rules run in a fixed order; the first match wins.

| # | Class | Condition |
|---|---|---|
| 1 | BACKCHANNEL | only fillers |
| 2 | GOAL_SWITCH | a switch phrase ("never mind", "forget that", "something else", …). No slot writes. |
| 3 | STATUS_QUERY | a status phrase on the raw tokens, or a question opener + "yet" ("is it booked yet?"), and no slot claims |
| 4 | ANSWER(confirm) / BACKCHANNEL | every token is an acknowledgement. It is an ANSWER only if a confirmation was **asked** and the utterance affirms. |
| 5 | CORRECTION | a repair marker ("no", "wait", "actually", "instead", "change", "make it", "I meant", …) after stripping a narrow lead ("I", "um", …) |
| 6 | ANSWER | the claimed slots overlap an asked clarification |
| 7 | REQUEST (no writes) | a filled value changes, but ≥ 2 content words are unexplained by the claims (a new request whose value belongs to another goal) |
| 8 | CORRECTION | a filled slot changes value without a marker ("to Mumbai") |
| 9 | REQUEST | otherwise |

Paraphrases generalise through lexicons of **function words and dialogue acts**, not whole utterances. There is no exact-string matching of any utterance; a test (§8) checks that no scenario utterance appears in the source.

## 3. Slot extraction

Candidate slots come only from the ACTIVE goal's registers. Each value is validated against the tool's JSON-schema parameter (`enum`, `pattern`, `type`, numeric bounds). There are four attribution passes, in order:

1. **named:** a slot name followed by a connector ("change the **date to** Saturday", "passengers should be 3").
2. **role:** a preposition mapped to slot-name fragments ("**to** Goa" → destination, "**from** Pune" → origin, "**on** Sunday" → date).
3. **typed:** a value that fits exactly one slot's schema ("Saturday" → the only weekday enum). Tokens are scanned from last to first, so in a self-repair the last value wins.
4. **bare** (only if a marker is present and nothing else was claimed): exactly one capitalised token that is not first and is not a slot-name word. It is attributed to the single compatible string slot, or to the slot most recently mentioned in the goal's utterances; otherwise the recogniser abstains.

**Canonicalisation.** A value is canonical if it validates. Otherwise it is looked up in **aliases** learned from the session: planner writes paired with the surface form the user used for that slot in the based-on utterance (for example "Mumbai" → BOM, after the planner once resolved it).

**Retraction (D12).** If the value is attributed to a filled slot but cannot be made schema-valid, the recogniser writes `None`. The stale call leaves the desired set in the same step and is cancelled, and the planner supplies the canonical value. If the planner saw the utterance and does not fill the slot, the kernel restores the previous value (`T0.retraction_reverted`).

The recogniser **never** writes a slot that the goal does not have, never writes a value that fails the schema, and never creates goals.

## 4. Partial-transcript behaviour

Each `user.text` chunk is its own kernel step, classified with the open turn's text so far as context.

| Chunk | What happens immediately |
|---|---|
| "I actually want" | REQUEST. The lead "I" is stripped only when a marker *starts* the rest, and "actually" inside "I actually want" is not a repair. No cancel. |
| "no wait" | CORRECTION with no attribution → F5: supersede and cancel the active goal's in-flight **read-only** calls now, without waiting for the value or for end of turn |
| "to Goa" | CORRECTION attributed by role → write or retract `destination`. The replacement call is dispatched only after end of turn (D5/INV-12). |
| end of turn | dispatch, acknowledgement, planner request |

A chunk may trigger interruption immediately only when it contains a repair marker or a changed attributed value. Hesitations, fillers, acknowledgements and incomplete leads never cancel anything. State-changing calls are never dispatched from a partial transcript, because dispatch requires a closed turn (INV-14).

## 5. Safety boundary

| The fast path **MAY** | The fast path **MUST NOT** |
|---|---|
| classify the turn into one of six classes | create, suspend or abandon a goal (only the planner's proposal can, applied by the kernel) |
| propose LWW writes (source T0) to the ACTIVE goal's existing slots, with schema-valid values | write a slot that the goal does not have, or a value that fails its schema |
| retract (write `None`) an attributed slot whose new value it cannot canonicalise | invent a slot for an unattributable correction; instead it abstains and F5 applies |
| trigger F5 supersession + cancel of in-flight **read-only** calls | cancel or dispatch a state-changing call on its own authority. State-changing work only moves through reconciliation under the commit barrier, hold and provenance (INV-13–16). |
| confirm an **asked** confirmation | confirm anything that was not asked |
| select a truthful status or acknowledgement template | report completion or progress that the state does not show (INV-20) |
| read the last 12 closed utterances of the session | read other goals' slots (no cross-goal leakage) or any scenario/fixture file |

This is enforced **structurally** and **by tests**:
- Structurally: `recognize()` returns only an `Understanding` value, and the kernel is the only state mutator.
- By tests: `test_recogniser_is_pure_and_deterministic`, `test_recogniser_can_only_express_an_interpretation`, `test_recogniser_only_writes_slots_of_the_context_and_schema_valid_values`, `test_input_is_bounded`, `test_no_goal_means_no_slot_writes_and_no_goal_creation`, `test_fast_path_never_dispatches_a_state_changing_call_itself`, `test_goal_isolation_a_correction_only_touches_the_active_goal`. Every kernel test also runs through the invariant checker (`CheckedKernel`).

## 6. Response policy

At each **closed** user turn, exactly one substantive response is spoken (no speech while the user holds the floor, INV-20):

| Situation | Speech |
|---|---|
| a call was dispatched (read-only or state-changing) | `Working on it: <tool>` (ack) |
| STATUS_QUERY, call running | `Still working on it: <tool>. No result yet.` |
| STATUS_QUERY, result already delivered | `I've already given you the <intent> result.` |
| STATUS_QUERY, waiting on the user | `I'm waiting on your answer: <question>` |
| STATUS_QUERY, nothing running | `Nothing is running right now.` |
| GOAL_SWITCH | `Okay, leaving <intent> for now.` |
| CORRECTION with T0 writes | `Okay, updating the <slots>.` |
| BACKCHANNEL | nothing |

These rules guarantee:
- a status answer never claims completion or progress beyond the call states;
- "Done" is emitted only as a FINAL grounded on a DESIRED+OK call or a COMMITTED operation;
- backchannels never produce speech, so there are no fillers.

## 7. Test corpus

[`tests/data/fast_understanding_corpus.json`](../tests/data/fast_understanding_corpus.json) contains 7 contexts (flight, flight without utterance history, booking, ticket, date asked, confirmation asked, no goal) and two splits:

| Split | Items | Composition |
|---|---|---|
| `items` (development, tuned on) | 85 | 34 CORRECTION, 17 BACKCHANNEL, 12 STATUS_QUERY, 12 REQUEST, 5 GOAL_SWITCH, 5 ANSWER, including ambiguity, repeats, cross-goal and no-goal items |
| `holdout_items` | 45 | 19 CORRECTION, 8 REQUEST, 6 STATUS_QUERY, 5 BACKCHANNEL, 4 ANSWER, 3 GOAL_SWITCH |

The corpus reports four measures:
- **classification accuracy:** class + confirm flag exact;
- **slot accuracy:** the write set is exact;
- **false-correction rate:** a non-correction classified CORRECTION or GOAL_SWITCH;
- **unsafe-interpretation rate:** any slot written that the user did not refer to, or a wrong value.

| Split | Classification | Slot | False correction | Unsafe |
|---|---|---|---|---|
| development (tuned on) | 100% | 100% | 0% | 0% |
| **held-out, first run (the honest generalisation estimate)** | **97.8%** | **93.3%** | **0%** | **4.4% (2/45)** |
| held-out after fixing those errors (no longer independent) | 100% | 100% | 0% | 0% |

Errors found and fixed on the first held-out run:
- **Unsafe:** "hang on a second" and "no that's not right" were retracted as the destination. Fix: a bare value must be capitalised and must not be the first token.
- **Other:**
  - self-repair kept the first value instead of the last;
  - "please" was not treated as an acknowledgement;
  - an answer to an asked slot was classified as a correction.

After the fixes, the held-out split has been used for tuning; a fresh held-out set is needed for a new estimate.

The small corpus, written by the implementer, **does not measure real-world accuracy**.

## 8. Adversarial tests

All are in [`tests/test_understanding.py`](../tests/test_understanding.py) (kernel level, real recogniser, every step through the invariant checker) or run as black-box scenarios in [`evaluation/scenarios/understanding/`](../evaluation/scenarios/understanding/).

| Case | Test / scenario |
|---|---|
| "no wait" | `test_correction_word_alone_is_unattributed_f5`; `no_wait_to_mumbai` |
| "no no" / "actually …" | corpus; `test_attributed_correction_cancels_only_in_the_same_step_and_retracts`; `change_the_destination` |
| ambiguous correction | `test_unattributable_bare_value_does_not_invent_a_slot`, `test_value_fitting_two_slots_abstains` |
| two slot changes in one utterance | `test_two_slot_changes_in_one_utterance`; `two_slots_one_utterance` |
| correction + immediate end of turn | `test_correction_immediately_followed_by_end_of_turn`; `correction_with_immediate_turn_end` |
| correction 1 ms before / after the old result | `test_correction_just_before_or_after_the_old_result[2.749/2.751]`; `correction_after_result` |
| repeated corrections | `test_repeated_corrections_keep_the_last_value`; `repeating_the_same_value` (same value: nothing changes) |
| status question during a tool | `test_status_question_answered_truthfully_while_running`; `status_question_during_search`, `are_you_still_searching` |
| status question after completion / idle | `test_status_question_after_completion_and_with_nothing_running` |
| backchannel during a tool | `test_backchannels_during_a_tool_do_nothing`; `backchannels_during_search` |
| clarification answer | `test_clarification_answer_resolves_the_open_question` |
| unrelated / new request in another goal | `test_goal_isolation_a_correction_only_touches_the_active_goal`; corpus `cross_goal` |
| partial transcript | `test_partial_transcript_waits_until_a_repair_is_actually_signalled`; `partial_transcript_marker_then_value` |
| unknown slot | `test_recogniser_only_writes_slots_of_the_context_and_schema_valid_values`; `correction_to_unknown_slot` |
| multiple plausible slots | `test_value_fitting_two_slots_abstains` |
| goal-switch paraphrase | `test_goal_switch_withholds_the_abandoned_work_until_the_planner_answers_d11`; `goal_switch_paraphrase` |
| D12 unfilled retraction | `test_retraction_the_planner_cannot_fill_is_reverted_d12` |
| scenario leakage | `test_recogniser_does_not_depend_on_scenario_fixtures`; `test_scenarios_contain_no_agent_internals` |

The new tests found a **real bug**: "ticket for my cracked screen on Monday", said during a flight goal, wrote Monday into the *flight* goal's date (a value-only correction). Classification rule 7 fixes it, and the case is now in the corpus.

## 9. Benchmarks

Run with `python -m scripts.bench_understanding 200`. Wall-clock on the dev machine, indicative only.

| Measure | p50 | p95 | p99 | max |
|---|---|---|---|---|
| `recognize()` on development corpus (17 000 calls) | 0.019 ms | 0.051 ms | 0.091 ms | 0.243 ms |
| `recognize()` on held-out corpus (9 000 calls) | 0.024 ms | 0.055 ms | 0.067 ms | 0.114 ms |
| in-process `handle()` of the correction line → `tool.cancel`, rules | 0.326 ms | 0.341 ms | 0.353 ms | 0.378 ms |
| same, scripted table | 0.301 ms | 0.314 ms | 0.354 ms | 0.354 ms |

The recogniser adds about 0.03 ms to a correction step. Virtual interruption → cancel is 0.00 s in every scenario (next section).

## 10. Before/after baseline

Same 47 scenario files and the same evaluator. BEFORE = the Phase 3 agent (scripted understanding, no status/ack policy), recorded in [`evaluation/reports/phase4_before/`](../evaluation/reports/phase4_before/report.md). AFTER = [`evaluation/reports/phase4_after/`](../evaluation/reports/phase4_after/report.md). INTERNAL PRISM-STYLE metrics.

| Metric | BEFORE | AFTER (rules) |
|---|---|---|
| scenarios passing all checks | 41/47 | **47/47** |
| mean internal score | 96.6 | 99.9 |
| mean interruption_recovery / response_latency | 0.91 / 0.93 | 1.00 / 0.99 |
| first substantive response, all turns p50 / p99 | 0.25 / 2.95 s | 0.25 / 1.55 s |
| first substantive response, status-question scenarios p50 / p99 | 1.15 / 1.55 s | **0.25 / 0.25 s** |
| first substantive response, booking scenarios p50 / p99 | 0.65 / 2.95 s | **0.25 / 0.25 s** |
| interruption → cancel, max (n) | 0.65 s (19) | **0.00 s** (16) |
| turns with no substantive response | 15 | 12 |
| end-to-end to last final, median | 2.75 s | 2.75 s |

**Attribution of the gains.** A third run uses the Phase 4 kernel with the *old* scripted table ([`compare_scripted_vs_rules.md`](../evaluation/reports/phase4_after/compare_scripted_vs_rules.md)):
- The **booking-turn** gain (0.65 → 0.25 s) comes from the response policy: it also appears with the scripted table.
- The **six corrections** that failed BEFORE, the **status-question** p99 and the **cancel latency** (0.65 → 0.00 s) come from the recogniser: with the scripted table they are still 41/47, 1.55 s and 0.65 s.

**Honest regressions.** Ten original scenarios end **0.25 s later** end-to-end (one planner round trip):
- B_destination_correction, E, E2, H, H2, twin_still_pending, revert_value_reruns, two_interruptions_before_result, and interrupt_1ms_before/after_completion.
- The BEFORE scripted table was an **oracle**: it handed the kernel the canonical IATA code for "to Mumbai".
- The real recogniser can only retract the destination (cancel still at 0.00 s) and must wait for the planner to resolve "Mumbai" → BOM, unless the alias was already learned in the session.
- For the same reason, the number of cancels drops from 19 to 16: rapid follow-up corrections find no replacement call in flight to cancel.

One scenario improves end-to-end: correction_to_unknown_slot, 2.75 → 1.70 s.

## 11. Known limitations

- **Canonicalisation needs the planner** for values outside the schema's enum or pattern, unless the value is an already-learned alias. This costs one planner round trip after a correction (see §10). A gazetteer or tool-provided value lists would remove it; the requirements do not provide either.
- **Bare values depend on capitalisation** and are **single-token only** ("no, New Delhi" abstains, and F5 then applies). An ASR that lower-cases everything disables the bare pass.
- **Unattributed markers churn.** "no wait" alone cancels in-flight read-only work (F5), even if the user then repeats the same value. The work is re-dispatched at turn close; this is correct but wasteful.
- **Alias learning** depends on planner writes. With the scripted planner, it is only as good as its fixtures.
- **English only.** Lexicons are small and hand-written. Negation scope, sarcasm, numbers written as words above twelve and relative dates ("the day after") are not handled; the recogniser abstains and the planner decides.
- **Corpus.** It is small and written by the implementer, and the held-out split has since been used for tuning (§7).

## 12. Next step

Phase 5 — planner / deep reasoning (`PHASE2_PLAN.md` Phase 4):
- a real reasoner behind the existing `reason` effect port, with schema-constrained proposals;
- model evaluation against the same black-box scenarios;
- the scripted planner remains the deterministic fallback.

The fast path defined here remains the only component allowed to act before the model answers.
