# Evaluation: openai/gpt-oss-120b (groq), 2026-11-19

30 cases: 22 answerable, 5 not in the documents, 3 tool calls. Scores are deterministic (guide 9.5); the hand-check list below is for a person.

| Metric | Result | Target | Met |
|---|---|---|---|
| Answer correctness (all key facts, grounded) | 17/22 (77%) | ≥ 80% | ❌ |
| Citation correctness | 17/20 (85%) | ≥ 90% | ❌ |
| Invented citation numbers | 0 | 0 | ✅ |
| Hit rate@5 | 18/22 (82%) | ≥ 85% | ❌ |
| MRR | 0.65 | (higher is better) | n/a |
| Correct refusals (not in documents) | 5/5 (100%) | ≥ 90% | ✅ |
| False refusals (answerable, said not found) | 5 | as few as possible | n/a |
| Latency p50 / p95 | 2.5 s / 3.7 s | p95 < 10 s | ✅ |
| Tokens per case (in / out, average) | 3770 / 147 | known | n/a |
| Failures | none | all logged | n/a |
| Fallbacks used | 0 | 0 (fallback is off) | n/a |
| Tool-call correctness | 3/3 (100%) | ≥ 90% | ✅ |
| **Stage 4 check:** 30+ page PDF, correct + cited | 9/10 (90%) | ≥ 8/10 | ✅ |

## Cases

| Case | Correct | Facts | Hit@5 | Cited ok | Latency | Error |
|---|---|---|---|---|---|---|
| fr-01 | yes | 2/2 | yes | 1/1 | 2.2 s |  |
| fr-02 | yes | 2/2 | yes | 2/2 | 3.1 s |  |
| fr-03 | yes | 2/2 | yes | 2/2 | 4.1 s |  |
| fr-04 | yes | 1/1 | yes | 1/1 | 3.4 s |  |
| fr-05 | yes | 3/3 | yes | 1/1 | 1.9 s |  |
| fr-06 | yes | 2/2 | yes | 1/1 | 3.0 s |  |
| fr-07 | yes | 2/2 | yes | 1/1 | 3.0 s |  |
| fr-08 | no | 0/2 | no | - | 2.5 s |  |
| fr-09 | yes | 2/2 | yes | 1/1 | 2.7 s |  |
| fr-10 | yes | 2/2 | yes | 1/1 | 2.4 s |  |
| fr-11 | yes | - | - | - | 3.0 s |  |
| fr-12 | yes | - | - | - | 2.0 s |  |
| th-01 | no | 0/2 | yes | - | 2.8 s |  |
| th-02 | yes | 2/2 | yes | 1/1 | 2.3 s |  |
| th-03 | no | 0/2 | no | - | 2.1 s |  |
| th-04 | yes | 2/2 | yes | 1/1 | 2.2 s |  |
| th-05 | yes | 2/2 | yes | 1/1 | 2.7 s |  |
| th-06 | yes | 2/2 | yes | 1/1 | 2.4 s |  |
| th-07 | yes | - | - | - | 2.8 s |  |
| ph-01 | yes | 2/2 | no | 0/1 | 2.2 s |  |
| ph-02 | yes | 2/2 | yes | 1/1 | 3.3 s |  |
| ph-03 | yes | 2/2 | yes | 1/1 | 3.2 s |  |
| ph-04 | yes | 2/2 | yes | 0/2 | 2.4 s |  |
| ph-05 | no | 0/1 | yes | - | 2.6 s |  |
| ph-06 | no | 0/1 | no | - | 3.3 s |  |
| ph-07 | yes | - | - | - | 2.0 s |  |
| ph-08 | yes | - | - | - | 3.7 s |  |
| tool-01 | yes | - | - | - | 2.2 s |  |
| tool-02 | yes | - | - | - | 1.5 s |  |
| tool-03 | yes | - | - | - | 1.5 s |  |

## Hand check (every 5th case, ~20%)

Read each answer: is the scored result right? Tick or note what's wrong.

- [ ] **fr-05** Which three men formed the Consulate after the coup of 18 Brumaire?<br>
  → The Consulate was created with three members: **Napoleon Bonaparte, Emmanuel Joseph Sieyès, and Roger Ducos** [1].
- [ ] **fr-10** What did the Phrygian cap, or Liberty cap, symbolise during the Revolution?<br>
  → The Phrygian (Liberty) cap was used as a symbol of **Roman republicanism and liberty**, evoking the ancient Roman ritual of manumission in which a freed slave received the cap as a sign of his newly‑won freedom [2].
- [ ] **th-03** Why was the zeroth law given that name instead of being numbered after the others?<br>
  → I couldn't find this in your documents.
- [ ] **ph-01** Why do most plants look green?<br>
  → Most plants appear green because their primary photosynthetic pigment, chlorophyll, absorbs light most strongly in the red and blue regions of the spectrum while reflecting and transmitting green wavelengths. The reflected green light is what we see, giving plants their characteristic green color [1].
- [ ] **ph-06** How old are the fossils thought to be of filamentous photosynthetic organisms?<br>
  → I couldn't find this in your documents.
- [ ] **tool-03** Save a note titled Carnot cycle that says it is the most efficient heat engine cycle<br>
  → Your note titled **“Carnot cycle”** has been saved. Let me know if you’d like to add anything else, tag it, or retrieve it later!
