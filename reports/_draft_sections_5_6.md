# Sections 5 & 6 — Draft (writer-recommendation / Tan)

> Draft for the AMR patent-landscape report. Decision + build sketch. Not legal advice.

---

## Section 5 — Ranked Best-Upgrade Recommendation: Which Concept to Build

Section 4 concluded that concepts which *prove* or *explain* robot behaviour remain open, while concepts that *sense* or *simulate* are crowded — and that the **trust layer is the empty layer**. This section answers the question the user actually asked: *which single concept should be built next?* We rank the open and moderate candidates on three axes and weigh them explicitly:

1. **Novelty** — how much unoccupied claim space the prior-art sweep left.
2. **Enablement feasibility for *this* project** — which today runs entirely in mock mode: the Arduino, motors and sensors are unconnected, geometry is `null`, and `config/safety.yaml` carries `status: NOT_VERIFIED` ([`docs/safety.md`](../docs/safety.md); on the absent geometry, [`docs/digital_twin.md` §9](../docs/digital_twin.md)). A concept that needs real physical measurement to be enabled is harder to file on *now* than one that is purely software over data the project already produces.
3. **Usefulness to the user** — a small independent developer, not a funded competitor with a fleet and a legal department.

### Ranking table

| Rank | Concept | Novelty | Enablement barrier | Usefulness | Verdict |
|---|---|---|---|---|---|
| **1** | **1.3 Counterfactual twin** | **Highest** — adjacent art (twin fleet management, explainable RL, AV counterfactual sim) does not claim counterfactual replay of a *robot's own* telemetry | **Low** — pure software over the telemetry/replay the project already ships (C7/C14) | Very high — turns the existing twin from a display into a decision-and-trust instrument | **Build this** |
| **2** | **1.4 Safety case as code** | High — assurance-case tooling *manages* the case; nothing found *executes* it as a CI suite | Low — software, but coupled to the layered safety system | High — attacks the cost of certification | Strong second |
| **3** | **4.1 Floor-degradation mapping** | High — no patent found | **High** — needs real slip/odometry/vibration measurement | High — robot becomes a survey instrument | Build once hardware exists |
| **4** | **5.1 Spatial slip model** | High — spatial safety envelope unclaimed | High — needs per-zone physical traction data | High — fast where safe, slow where not | Natural sequel to 4.1 |
| — | 1.2 Explainable stop · 2.1 Peer-to-peer right-of-way · 1.1 Provenance-chained telemetry · 4.4 Self-rewriting slotting · 3.2 Handover protocol | Moderate | Low–moderate | Moderate | Keep as follow-ons |
| — | 3.1 Intention broadcasting · 6.1 Twin-in-the-loop · 6.2 Fleet memory · 2.2 Aisle auction · 4.2 Acoustic · 4.3 Gas/thermal · 5.2 MCSA · 3.3 Social force | Crowded / pre-claimed | — | — | **Do not file as novel** |

### Why 1.3 wins

The counterfactual twin asks: *"what would have happened if…?"* — replay the robot's own recorded telemetry through an alternative policy and show the divergent outcome side by side. Three properties make it rank 1.

**It has the strongest novelty.** The prior-art sweep found adjacent art but no claim on the specific combination. [US12561660B2](https://patents.google.com/patent/US12561660B2/en) (digital-twin-enabled robot fleet management) describes a library of robot twins for fleet management; [US11455576B2](https://patents.google.com/patent/US11455576B2/en) (architecture for explainable reinforcement learning) covers explanation inside an RL agent; [US20240303501A1](https://patents.google.com/patent/US20240303501A1/en) (imitation and reinforcement learning for multi-agent simulation, Waabi) does counterfactual simulation for *autonomous vehicles*, not warehouse robots. None claims replaying a *robot's own operational telemetry* through an alternative policy. "Counterfactual simulation" alone is not novel — but the tight coupling of a live twin, the robot's own recorded telemetry as the replay seed, and side-by-side divergence for incident and trust evidence is the open room.

**It has the lowest enablement barrier.** The project already ships the two hard parts: a deterministic, caller-driven replay engine (`TelemetryRecorder`/`ReplayPlayer`, C14) and a `MapSnapshot`-fed 3D twin (C10) that renders live state ([`docs/replay.md`](../docs/replay.md), [`docs/digital_twin.md`](../docs/digital_twin.md)). The counterfactual twin adds a re-simulation step over data the stack already produces — no new sensor, no new hardware.

**It is the purest expression of the trust layer.** Digital twins show *what is*; a counterfactual twin shows *what almost was*. That is the product the trust-layer thesis points at, and it compounds with the explainable stop (1.2) into an incident-investigation capability rather than a robot feature.

### Why ranks 2–4

**1.4 Safety case as code** is the natural second: also software, also trust-layer, and it binds directly to the layered safety system the project already runs. Assurance-case tooling is an established market — [Adelard's ASCE](https://www.adelard.com/media/0i5pchud/softcement2005_emmet_guerra_application_of_commercial_tool.pdf) is a representative example — but it *manages* the case; none found *executes* the safety argument as a continuously-run test suite that fails the build. Its risk is subject-matter: it may read as process/tooling rather than an invention.

**4.1 Floor-degradation mapping and 5.1 Spatial slip model** have strong novelty (no patent found for 4.1; spatial envelopes unclaimed for 5.1) and the strongest *technical effect* — a measured floor-health map and a per-zone stopping envelope. But both require real physical measurement the project cannot yet produce, so they rank below the two software concepts on enablement, not on merit. They are the natural next builds once hardware is connected.

### The crowded concepts — and why they are excluded

These are not softened: **3.1 intention broadcasting** is pre-claimed by [US9744672B2](https://patents.google.com/patent/US9744672B2/en) (University of South Florida; inventors Yu Sun, Michael David Coovert, Ivan Shindev — verified; priority 2011 — the "next few seconds" intention projection, now lapsed); **6.1 twin-in-the-loop** is covered by [US12561660B2](https://patents.google.com/patent/US12561660B2/en) and productised by [NVIDIA Isaac Sim / Mega](https://www.nvidia.com/en-us/use-cases/robotics-simulation/); **6.2 fleet memory** is covered by [US12535823B2](https://patents.google.com/patent/US12535823B2/en) (Brain Corporation) and marketed as [Brain Corp's BrainOS](https://www.braincorp.com/brainos); **2.2 aisle auction** is 25 years of market-based multi-robot task allocation research ([ScienceDirect MRTA review](https://www.sciencedirect.com/science/article/pii/S0921889022002032)); **4.2 acoustic** is the [DCASE machine-condition-monitoring challenge](https://arxiv.org/pdf/2305.07828v2); **4.3 gas/thermal** ships on [ANYbotics' ANYmal](https://www.anybotics.com/news/robotic-gas-leak-detection-anymal/); **5.2 MCSA** is decades-old [motor-current-signature analysis](https://www.scholarmate.com/S/pxQ4BQ); **3.3 social force** is a decades-deep [social-navigation field](https://arxiv.org/pdf/2103.05668v1). Treat all eight as occupied.

### The tension, stated honestly

A purely software concept is easier to enable *now* but faces patentable-subject-matter scrutiny — a "what-if display" can be characterised as an abstract idea or a UI feature. A hardware-measurement concept carries a stronger, more concrete technical effect (a physical floor map, a measured traction envelope) but is *currently unenableable*: mock mode means geometry is `null`, thresholds are `NOT_VERIFIED`, and no sensor has ever produced a real reading. **Our weighing:** rank by enablement-aware novelty *today*, because a concept the user cannot reduce to practice cannot support an enabled claim — but flag 4.1/5.1 as the higher-technical-effect builds to file the moment hardware exists. The winning move is to file 1.3 now on the software combination, and let the measured technical effect in Section 6 carry the weight.

This is a strategic recommendation, **not legal advice**. Any filing decision — including whether the subject matter is even eligible and whether it clears prior art — remains subject to a real, claim-level freedom-to-operate search. Nothing here substitutes for that.

### Key findings
- **1.3 counterfactual twin is the pick** — strongest novelty, lowest enablement barrier, purest trust-layer expression; it is software over telemetry and replay the project already has.
- **1.4 safety case as code is the strong second**; **4.1/5.1 are the higher-technical-effect builds** gated on real hardware.
- **Eight concepts are occupied** and must not be filed as novel — including 3.1 (pre-claimed), 6.1 and 6.2 (shipped by NVIDIA and Brain Corp).
- **The core tension:** software concepts enable now but risk subject-matter rejection; hardware concepts have stronger effect but are unenableable in mock mode. We resolve it by ranking on enablement-aware novelty and deferring the hardware builds.

---

## Section 6 — Implementation Sketch for the Top-Ranked Concept: Mechanism, Enablement Gap, and Measured Technical Effect

*Scoped to rank 1 (the counterfactual twin) only.*

### (a) The mechanism, in concrete engineering terms

The counterfactual twin is **not a new simulator**. It is a re-simulation stage bolted onto the deterministic replay engine the project already runs.

1. **Capture.** The existing `TelemetryRecorder` (C14) already writes one `ReplayFrame` per sample to a bounded JSONL file — pose, navigation, safety, hazards, mission ([`docs/replay.md`](../docs/replay.md)). To be *counterfactual* rather than merely historical, the recording must additionally capture the **inputs the policy consumed**, not only its outputs: the ultrasonic front/left/right/rear readings, the clearance value, and the obstacle report. Today `ReplayFrame` stores the safety *decision*, not the sensor *evidence* behind it.
2. **Choose an alternative policy.** An "alternative policy" is a parameterised variant of an existing decision layer — operationally, the safety/avoidance configuration in `config/safety.yaml` (`front_stop_distance_cm` default 20 cm, `watchdog_timeout_ms` default 1000 ms, `avoidance.turn_speed_scale`) plus the navigation speed cap ([`docs/safety.md`](../docs/safety.md)). A counterfactual run is "replay these recorded inputs under policy P′ instead of P."
3. **Re-simulate.** `ReplayPlayer` is caller-driven — no thread, no `sleep`, no internal clock — so the same `advance(dt)` sequence always yields the same frames ([`docs/replay.md`](../docs/replay.md)). That determinism is what makes a counterfactual *valid*: the divergence is reproducible, not a lucky simulation draw.
4. **Compute divergence.** Per timestep, compare the factual frame to the counterfactual frame: pose delta (lateral and longitudinal), speed-profile delta, and — the safety-relevant term — whether the two runs disagree on the verdict (`PROCEED` vs `STOP`/`WAIT`/`TURN`/`REPLAN`). Aggregate to a per-run divergence score and a **first-point-of-divergence** timestamp.
5. **Display.** Both trajectories render through the same `MapSnapshot`-fed 3D twin (C10): the factual path solid, the counterfactual path a translucent "ghost." The browser computes no robot state ([`docs/digital_twin.md`](../docs/digital_twin.md)), so the overlay is simply two converted paths.

### (b) What existing parts of the project it builds on

- **Python control stack** (`amr/...`) — the decision layers whose policy is varied.
- **`TelemetryCollector` / `TelemetrySnapshot` (C7)** — the read-only snapshot the recorder consumes ([`docs/telemetry.md`](../docs/telemetry.md)).
- **`TelemetryRecorder` / `ReplayPlayer` (C14)** — the capture-and-replay engine, reused verbatim.
- **`MapSnapshot`-fed 3D twin (C9/C10)** — the rendering surface, reused.
- **Layered safety system (`SafetyManager`, `HazardManager`, Layer-1 Arduino stop)** — the thresholds and verdicts being counterfactually varied.
- **Mock mode** — the enabler: the twin can run with no hardware because the whole stack is deterministic and simulated (`simulated: true`).

### (c) The enablement gap — what must be built and measured

Stated plainly, what is missing today:

1. **Replay does not re-simulate.** The C14 document says it directly: "Replay renders what was recorded — it does not re-simulate, so it cannot answer 'what would happen if…'." The counterfactual engine *is* that missing step.
2. **The recording stores outputs, not inputs.** `ReplayFrame` holds the safety decision, not the ultrasonic readings or clearance that drove it. Without the inputs a variant policy cannot be re-run; the recorder schema must be extended (a version bump from `"1.0"`).
3. **The policy is not pluggable.** Safety/avoidance parameters are read from config, not exposed as a swappable policy object with a stable interface.
4. **Mock mode means the evidence is synthetic.** Every recorded run today is simulation; geometry is `null` and thresholds are `NOT_VERIFIED`. A patent needs an *enabled* invention: at least one real recorded run on real hardware, with measured thresholds, is required before a filing could support a claim.

### (d) The measured technical effect it must demonstrate

This is the crux — what turns a useful feature into a patentable invention. The invention is not "show a what-if." It is a **method that uses counterfactual replay of a robot's own operational telemetry to revise a safety policy, producing a measurable reduction in false stops at no increase in safety-margin violation.**

- **Primary metric — false-stop rate.** On a recorded operational run, count safety stops the counterfactual shows were *unnecessary* (the alternative policy would have proceeded with no resulting hazard). Apply the revised policy; measure the change in false-stop rate.
- **Guardrail metric — safety-margin violation.** Confirm the revised policy does not shrink the minimum stopping margin below the ISO 3691-4 / ISO 13849-derived envelope ([ISO 3691-4:2023](https://www.iso.org/standard/83545.html); the standard's functional-safety basis is described in [TÜV Rheinland's AGV whitepaper](https://www.tuev.cn/content-media-files/master-content/services/industrial-services/pdf/tuv-rheinland-automated-guided-vehicle-whitepaper-2021.pdf)).
- **Secondary — operator response time** to safety events, and **repeat-incident rate** over a period. Counterfactual "what-if" analysis is an established decision-support technique in adjacent domains ([Microsoft Research, causality and counterfactuals](https://www.microsoft.com/en-us/research/group/causal-inference/)), and explanation is a known lever for operator trust in safety-critical autonomy ([XAI for safe autonomous driving, systematic review](https://arxiv.org/pdf/2402.10086v1)).

**What result constitutes evidence:** a statistically significant reduction in false stops (e.g. ≥ X% across N recorded runs) **with no statistically significant increase in safety-margin violations**, reproducible from the recorded JSONL. Determinism — two runs identical in input producing identical divergence output — is the *enabling* evidence; the false-stop reduction is the *technical-effect* evidence.

### (e) What to record as evidence

- **Raw recordings** — the JSONL files (schema-tagged), one per run, retained immutably.
- **Replay inputs** — the exact policy parameter set for each arm (factual vs counterfactual).
- **Divergence outputs** — per-timestep deltas, first-divergence timestamp, aggregate score.
- **Repeat runs** — each counterfactual repeated N times to demonstrate determinism.
- **Comparisons** — side-by-side trajectories (factual solid / counterfactual ghost) plus false-stop and safety-margin tables before and after revision.

This is an engineering sketch, **not legal advice**. Patentability — including whether the subject matter is even eligible and whether it clears prior art — remains subject to a real, claim-level freedom-to-operate search. Nothing here substitutes for that.

### Key findings
- The counterfactual twin is a **re-simulation stage on the existing deterministic replay engine** — not a new simulator.
- The concrete enablement gap is that **replay records policy outputs, not the sensor inputs a variant policy would need**; the recorder schema must be extended and a policy made pluggable.
- The patentable core is a **method to revise a safety policy from counterfactual replay, measured as a false-stop reduction with no safety-margin regression**.
- **Mock mode is the blocker**: at least one real recorded hardware run with measured thresholds is required before a filing could support a claim.
- This is engineering, not legal advice; patentability needs a claim-level FTO search.

---

## Sources used in Sections 5 & 6

**Patents (verified in Phase 1 via the Google Patents query API)**
- [US12561660B2 — Digital-twin-enabled robot fleet management](https://patents.google.com/patent/US12561660B2/en) — Strong Force VCN Portfolio 2019
- [US11455576B2 — Architecture for explainable reinforcement learning](https://patents.google.com/patent/US11455576B2/en) — UMNAI
- [US20240303501A1 — Imitation and reinforcement learning for multi-agent simulation](https://patents.google.com/patent/US20240303501A1/en) — Waabi Innovation
- [US9744672B2 — Systems and methods for communicating robot intentions to human beings](https://patents.google.com/patent/US9744672B2/en) — University of South Florida (expired)

**Standards**
- [ISO 3691-4:2023 — Driverless industrial trucks](https://www.iso.org/standard/83545.html)
- [TÜV Rheinland — ISO 3691-4:2020 AGV whitepaper](https://www.tuev.cn/content-media-files/master-content/services/industrial-services/pdf/tuv-rheinland-automated-guided-vehicle-whitepaper-2021.pdf)

**Industry / commercial**
- [NVIDIA — Robotics simulation (Isaac Sim / Mega)](https://www.nvidia.com/en-us/use-cases/robotics-simulation/)
- [Brain Corp — BrainOS over-the-air fleet learning](https://www.braincorp.com/brainos)
- [ANYbotics — robotic gas leak detection for ANYmal](https://www.anybotics.com/news/robotic-gas-leak-detection-anymal/)
- [Adelard — commercial assurance-case tooling (ASCE)](https://www.adelard.com/media/0i5pchud/softcement2005_emmet_guerra_application_of_commercial_tool.pdf)

**Research**
- [Market-based multi-robot task allocation (game-theoretic MRTA)](https://www.sciencedirect.com/science/article/pii/S0921889022002032)
- [DCASE 2023 Task 2 — anomalous sound detection for machine condition monitoring](https://arxiv.org/pdf/2305.07828v2)
- [Motor Current Signature Analysis (MCSA)](https://www.scholarmate.com/S/pxQ4BQ)
- [Core Challenges of Social Robot Navigation — a survey](https://arxiv.org/pdf/2103.05668v1)
- [Explainable AI for Safe and Trustworthy Autonomous Driving — a systematic review](https://arxiv.org/pdf/2402.10086v1)
- [Microsoft Research — causality and counterfactual reasoning](https://www.microsoft.com/en-us/research/group/causal-inference/)

**Project documents (primary source for the implementation sketch)**
- `docs/replay.md` (C14 telemetry recording and replay)
- `docs/telemetry.md` (C7 telemetry and dashboard)
- `docs/digital_twin.md` (C10 3D digital twin)
- `docs/safety.md` (layered safety system; `NOT_VERIFIED` thresholds)
