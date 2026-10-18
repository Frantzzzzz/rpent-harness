# Canary results and stop decision

These canaries are infrastructure and policy checks. They are not part of the
48-cell pilot and must not be pooled into its statistics.

## Current audited pair

The pair uses commit `dd26ba9`, GPT-5.6-sol with low reasoning effort, Pi0.5
checkpoint SHA-256 `4d9089c941793f170b625c2ed0ac7a3aa09b6f103e52dbbc82e67301529d6683`,
SAM3 checkpoint SHA-256
`9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`, and
GPT_5.5_xhigh revision `47f301ef33bf8d0e8c770342f16b3c39c6a0e8c1`.

| Run | Condition | Environment | Human video verdict | Memory audit |
|---|---|---:|---|---|
| [`r0_structured_t0_s1`](../../runs/research_canary/r0_structured_t0_s1) | R0 native | `terminated=true` | valid success; release is partial because the environment terminates immediately | 4 successful structured body reads |
| [`r1_structured_t0_s1_v2`](../../runs/research_canary/r1_structured_t0_s1_v2) | strict identity canary | `terminated=false` | valid failure; contact recovery visibly pushed the can out of the basket | 7 successful structured reads; correct task pair and family |

The older runs `r0_t0_s1`, `r0_clean_t0_s1`, and `r1_identity_t0_s1` are
background diagnostics only. They have stale preflight or missing memory-read
evidence and are excluded from all rates.

## Human review findings

The R0 video shows correct target identification, a successful grasp, and a
successful final placement. The R1 identity video shows the can inside the
basket but protruding above the rim after release; a subsequent `pi0_doubled`
contact action pushes it out onto its side, and a later grasp does not recover
it. The contact displacement is video-confirmed. The physical cause of the
initial protrusion is still a hypothesis and is not written as a fact.

## Stop decision

The formal queue is stopped. The current `strict_identity` implementation is a
provenance/task-identity gate, not the planned scene-compatibility gate. The
R1 result therefore does not test the paper question. Before a formal matrix,
the scene-drift policy must be implemented and audited on a new canary with
the same structured memory-read requirement. No baseline success rate or
harmful-memory rate is reported from these two episodes.
