# AMR IDP — Patent Roadmap: Plan and Top Ideas

**Date**: 2026-10-14
**Basis**: the deep-research report at `reports/AMR_AI_AGENTS_RESEARCH_REPORT.md`
**Status**: not legal advice — engage a registered patent attorney before filing

---

## 0. The one thing that decides everything

The research produced a single hard finding that governs this entire plan:

> **A patentable invention here needs a *hardware-validated, closed-loop technical effect* — a measured change in the robot's physical behaviour. Every idea you currently have fails for the same reason: it is either a broad concept in crowded art, or a presentation/data rule with no physical effect.**

Two consequences:

1. **Enablement is the gate.** A patent must describe an invention a skilled person can *make and use*. Right now the system runs entirely in `--mock` mode, geometry is `null`, and safety thresholds are `NOT_VERIFIED`. **No amount of software work fixes this.** Until the robot physically moves and you have measurements, nothing is patentable.
2. **You already own the hard part.** You have a working, tested, 21,752-line stack with a layered safety architecture, telemetry, a hazard manager, and a heatmap. What you lack is not code — it is *hardware contact and measurements*. That is a much smaller gap than it looks.

**The strategic inversion this enables:** stop trying to patent the *features* (all crowded) and instead patent the *measured closed-loop behaviours* that only exist once the robot moves. Those are narrow, specific, and — critically — the incumbents' patents describe *apparatus*, not *your measured control method*.

---

## 1. The plan

### Phase 0 — Enablement (prerequisite; nothing files without it)
**Goal: make the robot move and produce measurements.**

| # | Task | Why it's required |
|---|---|---|
| 0.1 | Connect Arduino → L298N → motors. Fix the `D4`/`D5` double-booking and move `ENB` off `D8` (it cannot do PWM) | You cannot characterise motion without working motors |
| 0.2 | Fit the ultrasonic ring; resolve the `TODO_VERIFY` pins | Every control idea below needs real distance data |
| 0.3 | **Measure** `wheel_track_m` and `wheel_diameter_m`; set them in `config/robot.yaml` | `null` geometry blocks odometry, and odometry is the measurement backbone |
| 0.4 | Run a controlled braking test at 3–4 speeds; record real stopping distances | This *is* the measurement that makes Phase 1 possible |
| 0.5 | Drop `--mock`; run the stack against real hardware | Confirms the whole chain actually actuates |
| 0.6 | Verify the safety chain physically: does the Arduino watchdog + proximity stop actually halt a moving chassis? | Required for ISO 13849 diagnostic coverage, and it's the foundation of idea #2 |

**Exit criterion:** you can command a speed, measure the resulting stopping distance, and repeat it reproducibly. That single capability unlocks everything below.

### Phase 1 — Build the two strongest ideas (highest patentability × lowest effort)
- **Idea 1 — Self-calibrating stopping-distance envelope**
- **Idea 2 — Safety-chain self-test with degraded-mode fallback**

### Phase 2 — Build the two measured-effect features
- **Idea 3 — Hazard-map-driven adaptive speed limiting** (converts your existing heatmap from a *display* into a *control input*)
- **Idea 4 — Corroborated obstacle detection with a measured false-stop rate**

### Phase 3 — Protect the work
- Run a **real claim-level FTO search** on the winner (see §4)
- File **one provisional** on the strongest idea — the US gives you a 1-year grace period from your own disclosure, but **many jurisdictions have none**, so decide *before* publishing more
- **Defensively publish** everything else (you have a public GitHub repo — this is free and it blocks others from patenting your work)

---

## 2. Top ideas, ranked by (ease × patentability)

Scored 0–10. **Ease** = effort for a solo developer with your existing stack. **Patent** = realistic claim strength *after* Phase 0. **Effect** = how concrete and measurable the technical effect is.

| # | Idea | Ease | Patent | Effect | Verdict |
|---|---|---|---|---|---|
| **1** | **Self-calibrating stopping-distance envelope** | 8 | **7** | 9 | **Best bet.** File this one |
| **2** | **Safety-chain self-test + degraded mode** | 9 | 6 | 7 | Strong second; ties to ISO 13849 DC |
| **3** | **Hazard-map-driven adaptive speed limiting** | 8 | 5 | 8 | Clever: upgrades an unpatentable feature |
| **4** | **Corroborated obstacle detection, measured false-stop rate** | 7 | 4 | 7 | Worth building; crowding risk |
| **5** | Cold-chain custody with active temperature control | 4 | 4 | 5 | Best of the *new* concepts, but needs new hardware |

---

### Idea 1 — Self-calibrating stopping-distance envelope ⭐ BEST BET

**What it is.** The AMR periodically performs a **controlled braking calibration**: at low speed, in a verified-clear path, it commands a stop and measures the actual stopping distance using wheel odometry plus ultrasonic ground truth. It repeats at 2–4 speeds and, optionally, with different payloads, and **fits a stopping-distance-vs-speed curve**. From that curve it *derives* the speed cap and stop threshold that guarantee stopping within the clearance the ultrasonic ring can see. The calibration re-runs periodically, so the envelope adapts as brakes wear, load changes, or the floor surface changes.

**Why this is the most patentable thing you can build here.**
- It is a **method producing a measured physical effect** — a guaranteed stopping margin — not a display rule. This is precisely the class of mechanism the research identified as protectable.
- It is **narrow and specific**: the calibration procedure, the curve derivation, and the threshold-setting rule. Narrow claims survive; broad ones don't.
- It **inverts the prior-art problem.** The crowded patents (ISO 3691-4 practice, Boston Dynamics `EP4572923A1`) describe *apparatus and configured thresholds*. Yours describes *deriving the threshold from the robot's own measured braking behaviour*. Configurable thresholds are prior art; **self-calibration is a different act**.
- The safety architecture you already have (layered `SafetyManager` + `HazardManager`) is the *host* for this — it's the thing the derived envelope feeds.

**Why it's easy.** You already have every component: ultrasonic ranging, wheel encoders (odometry), motor control, and a `SafetyManager` that accepts thresholds. The new work is a calibration routine (~200–300 lines) plus a curve fit — a lookup table is sufficient; you don't need real regression.

**What to build.**
1. A `calibrate()` routine: verify path clear → command fixed speed → command stop → measure distance → repeat per speed.
2. Store `{(speed, stopping_distance)}` samples; fit or tabulate.
3. Derive `speed_cap` and `stop_threshold` = `stopping_distance(speed) × safety_factor + margin`.
4. Feed the derived values into `SafetyManager` instead of the `NOT_VERIFIED` constants.
5. Re-run on a schedule and on payload change.

**What to measure (this is your patent evidence).** Stopping distance vs speed, repeated runs showing reproducibility, and the resulting reduction in required clearance or increase in safe speed. **Record every run** — the data *is* the enablement.

**Prior-art risk: MEDIUM.** Automotive AEB/AEBS self-calibration exists, and adaptive-braking art is broad. But AMR-specific self-calibration of a *safety envelope from measured braking* is a narrower field. **This needs a real claim-level search before filing** — but it is the only one of your ideas that plausibly survives one.

---

### Idea 2 — Safety-chain self-test with degraded-mode fallback

**What it is.** A periodic, automatic **end-to-end verification of the safety chain**: the Pi commands a controlled stop, confirms the Arduino actually halted motion, confirms the watchdog fires when comms are interrupted, and confirms the proximity stop triggers on a test target. It records an auditable pass/fail record, and if any element fails it **degrades the robot's capability** (caps speed, refuses autonomous missions) rather than continuing silently.

**Why it's patentable.** The technical effect is *verified safety-function integrity* — and it maps directly onto **ISO 13849-1 diagnostic coverage (DC)**, which is a standards-anchored, measurable property. A method that raises achieved DC by periodic end-to-end self-test, with a defined degraded-mode response, is specific and technical. It is not a display rule and not a generic "self-test" (self-test/BIT is old) — the narrower claim is the *safety-chain-specific* test sequence plus the degraded-mode policy.

**Why it's easy.** It is mostly a test procedure using your existing command path. The Arduino already has a watchdog; you need a controlled stop command, a comms-interruption test, and a result record.

**What to build.** A `self_test()` routine covering: (a) commanded stop → motion actually ceases; (b) watchdog → link-drop triggers stop within the timeout; (c) proximity → test target triggers Layer 1 stop. Record results with timestamps. Wire the outcome into a capability-limit flag.

**What to measure.** Time-to-stop on each test, pass/fail history, and the achieved diagnostic coverage figure.

**Prior-art risk: MEDIUM-HIGH.** Self-test and BIT are well established. Your defensible ground is the *safety-chain-specific* sequence and the *degraded-mode* policy — narrow. Build it regardless: it's good engineering and it strengthens idea #1.

---

### Idea 3 — Hazard-map-driven adaptive speed limiting

**What it is.** Your heatmap is currently **presentation-layer** — the research scored it 4/10 on patentability precisely because it only *displays* density. **Make it a control input.** The robot's speed cap becomes a function of the local hazard density under its planned path: high-hazard zones force a lower cap, and the cap updates as the map updates. This converts a display artifact into a **closed-loop motion effect**.

**Why this is clever.** It takes your weakest-patentability asset and makes it strong, by changing *what it does*. "A heatmap that shows hazards" is a display. "A method that limits vehicle speed as a function of a spatially-accumulated hazard density field" is a **control method** — and control methods with measured physical effects are exactly what survives patentable-subject-matter scrutiny.

**Why it's easy.** You already have the dual heatmap (`map/heatmap.py`) with a stable extent — which the research called the most concrete technical mechanism in your codebase (F2, novelty 5/10). You add a lookup from hazard density → speed cap, and feed it to the motion controller.

**What to build.** Expose a `hazard_density_at(x, y)` query on the heatmap; add a speed-cap curve (density → max speed); enforce it in the navigator; log the cap alongside the commanded speed.

**What to measure.** Speed reduction achieved in high-hazard zones, and any correlation with reduced near-miss events. The measured effect is the claim.

**Prior-art risk: MEDIUM.** Spatially-varying speed limits exist (geofencing, traffic). The narrower claim is *speed derived from a continuously-updated hazard-density field accumulated from the robot's own sensors*. This is genuinely narrower than geofencing — but it needs a search.

---

### Idea 4 — Corroborated obstacle detection with a measured false-stop rate

**What it is.** Ultrasonic-only obstacle detection produces false stops (floor reflections, soft surfaces, crosstalk between sensors). Add **cross-corroboration**: a stop requires agreement across time (N consecutive readings), across sensors (multiple faces), and consistency with odometry (is the obstacle approaching at a plausible rate?). Log every stop decision and compute a **false-stop rate**.

**Why it's patentable (weakly).** The technical effect is a *measurable reduction in false stops without increasing collision risk* — a real physical/operational effect, with the metric built in. The narrow claim is the specific corroboration rule.

**Why it's easy.** Pure software on the sensor stream you're already producing. The hard part is the *metric*, and you get that free by logging decisions.

**What to measure.** False-stop rate before/after, and — crucially — that *missed* obstacles did not increase. That pair is the claim.

**Prior-art risk: HIGH.** Sensor fusion is the single most crowded area (~112,000 patent families per the research). Build it because it makes the robot better, but treat patentability as unlikely. Its real value is that it *feeds ideas #1 and #3* with cleaner distance data.

---

### Idea 5 — Cold-chain custody with active temperature control

**What it is.** The best of your five new roadmap concepts (patentability 4/10 vs 1–2 for the rest). The AMR actively maintains a temperature-controlled compartment while transporting temperature-sensitive goods, and maintains a verifiable, tamper-evident **chain-of-custody record** from pick to drop.

**Why it's the best of the new five.** Cold-chain *monitoring* is a mature industry (Sensitech, Tive, Thermo King), but the narrow combination — **active** temperature control + transport **inside a warehouse** + an auditable pick-to-drop custody record — is less densely claimed than inventory scanning (which is a mature commercial category with a dense Simbe/Walmart/Sensormatic thicket).

**Why it's harder.** It needs new hardware: a temperature-controlled compartment, a temperature sensor, and a logging path. That's why it scores 4/10 on ease.

**Prior-art risk: MODERATE.** Closest art is `US20220004979A1` *"Autonomous Mobile Delivery Robot And Chain Of Custody System"* — **note its assignee is unverified** (inventors Allen/Melanson confirmed, corporate holder not). Read that application's claims *first* if you pursue this.

**Recommendation:** park this until Phases 1–2 are done. It is the strongest *new* idea but the weakest *easy* one.

---

## 3. What to avoid (and why)

| Don't chase | Reason |
|---|---|
| **AMR inventory cycle counting** (your idea G) | Mature commercial category — Simbe, Bossa Nova, Corvus, Verity, Gather AI, Dexory, B-GARAGE — sitting on a dense patent thicket. **Build it if useful; never as an IP play.** |
| **Stock planning / replenishment** (I) | Reorder-point replenishment is decades-old practice; Focal Systems already does shelf-visibility→replenishment with fixed cameras |
| **Warehouse equipment health monitoring** (K) | PdM is enormous (Siemens, SKF, Augury) and Rdi Technologies `US11861820B1` is *"mobile unit doing repetitive equipment video monitoring"* — very close |
| **The 3D digital twin** (B) | Direct prior art: `US12561660B2`, `US11396100B2`, NVIDIA Omniverse/Isaac |
| **The "honest ops projection"** (C) | A data-integrity principle — not patentable subject matter, and adoptable by anyone |
| **Mock-first bring-up** (D) | Established SIL/HIL methodology, zero novelty |

**But note:** "don't patent it" ≠ "don't build it". G scored **9/10 usefulness** — the highest of any candidate. Build the useful things; just don't spend money trying to patent them.

---

## 4. Before you file — the non-negotiables

1. **Do the enablement first.** Ideas 1–3 are unenableable today. The measurements in Phase 0 are not optional paperwork — they are the invention's disclosure.
2. **Run a claim-level freedom-to-operate search**, not a novelty search. They answer different questions: *novelty* asks "can I patent it?", *FTO* asks "can I use it without infringing someone else's?" You can be novel and still infringe.
   Search against: **Amazon, Locus, Geek+, Vecna, Fetch/Zebra, Dematic, Invia, Ocado, ForwardX, Boston Dynamics, Simbe** — plus automotive AEB/adaptive-braking art for idea #1.
3. **Decide before you publish.** Your GitHub repo is public. In the **US** your own disclosure starts a **1-year grace period**; in many jurisdictions there is **no grace period at all**, and publishing can foreclose patenting entirely. If you intend to file on idea #1, **do not publish the calibration method until you have filed.**
4. **Trade secret is not available to you** — the code is already public. Defensive publication is your realistic alternative for everything you don't file.
5. **Engage a registered patent attorney** before filing. This document is strategy, not legal advice.

---

## 5. If you only do three things

1. **Phase 0.1–0.4** — get the robot moving and measure real stopping distances. *Nothing is patentable until this exists.*
2. **Build Idea 1** (self-calibrating stopping envelope) and record every calibration run. It is your single best patent candidate and it uses hardware you're fitting anyway.
3. **Before publishing anything about Idea 1, decide whether you intend to file.** The grace-period asymmetry is the one irreversible mistake available here.

---

> This is an engineering and IP-strategy plan, not legal advice. Patentability assessments are preliminary, based on the prior-art sweep in `reports/AMR_AI_AGENTS_RESEARCH_REPORT.md`, and must be confirmed by a registered patent attorney and a professional freedom-to-operate search before any filing or commercial use.
