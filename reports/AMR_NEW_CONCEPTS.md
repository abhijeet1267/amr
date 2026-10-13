# AMR IDP — New Concepts: How to Be Genuinely Different

**Date**: 2026-10-14
**Brief**: new technology and concepts that differentiate the project, solve many problems at once, and produce useful outcomes. Feasibility deliberately not considered.
**Companion**: `reports/AMR_AI_AGENTS_RESEARCH_REPORT.md` (what exists / what's crowded), `reports/AMR_PATENT_ROADMAP.md` (what to file)

---

## The differentiator thesis

Most warehouse AMRs compete on the same three axes: navigation accuracy, payload, and cost per pick. They are **interchangeable** — Locus, Fetch, Geek+, Vecna and the rest all answer the same questions. Copying them means competing in a crowded market with crowded patents.

**Your project already has a personality that none of them have: it refuses to lie.** It publishes categorical health instead of a fabricated score, it marks thresholds `NOT_VERIFIED`, it keeps the twin read-only so it cannot contradict the map, and its hazard ladder only ever escalates. That instinct — *evidence over assertion* — is the seed of every idea below.

The strategic move: **stop building a robot that moves boxes, and build a robot that produces trustworthy, verifiable, physically-grounded evidence about a warehouse.** Nobody sells that. It solves problems the incumbents structurally cannot, and it makes the robot's byproducts more valuable than its labour.

---

## Theme 1 — Trust and verifiability

### 1.1 Provenance-chained telemetry
Every telemetry record is hashed with its predecessor, forming a tamper-evident chain. An operator, insurer, or auditor can later prove *exactly* what the robot reported and when, and detect any after-the-fact edit.

**Solves:** liability disputes, insurance claims, incident reconstruction, regulatory audit, "prove the robot did what you say it did."
**Why different:** everyone logs. Almost nobody makes logs *provable*. A log you can't trust is a liability; a log you can prove is an asset.

### 1.2 The explainable stop
When the robot stops, it emits an **evidence bundle**: which sensors fired, their raw readings, which rule matched, what the threshold was, and what the confidence was. Never "it just stopped."

**Solves:** the single biggest reason operators distrust AMRs — unexplained stops. Turns a support ticket into a self-service answer.
**Why different:** incumbents surface a fault code. An evidence bundle is a *reconstructable argument*.

### 1.3 The counterfactual twin
Your digital twin already renders live state. Extend it to answer: **"what would have happened if…?"** — if the robot hadn't stopped, if it had gone 20% faster, if the aisle had been occupied. Replay the same telemetry through an alternative policy and show the outcome side by side.

**Solves:** incident investigation, safety-case evidence, operator training, and *trust* — you can show someone the accident that didn't happen.
**Why different:** digital twins show *what is*. A counterfactual twin shows *what almost was*. That is a fundamentally different product.

### 1.4 Safety case as code
Express the ISO 3691-4 / ISO 13849 safety argument as **executable tests that run continuously**, not a PDF written once for certification. Every claim in the safety case has a corresponding test that fails the build if it stops being true.

**Solves:** the enormous cost of certification and the fact that safety cases rot the moment the code changes.
**Why different:** safety is universally treated as a document. Treating it as a *living test suite* makes the safety case impossible to silently invalidate.

---

## Theme 2 — Robots that negotiate with each other

### 2.1 Peer-to-peer right-of-way (no central fleet manager)
Robots negotiate aisle priority directly with each other, the way vehicles negotiate at an unmarked intersection. No central fleet server deciding who goes.

**Solves:** the central fleet manager is a single point of failure, a scaling bottleneck, and a vendor lock-in mechanism. Every incumbent has one.
**Why different:** Locus, Fetch and Zebra all route through a central brain. A fleet that self-organises has no brain to fail.

### 2.2 Aisle-access auction
Congested aisle time is allocated by **auction**: each robot bids based on the urgency of its task and the cost of waiting. High-priority work wins the aisle; low-priority work routes around it voluntarily.

**Solves:** congestion, which is a first-class warehouse problem and a patented battleground (Locus holds congestion-management patents).
**Why different:** congestion is normally solved by *scheduling rules*. Solving it with an *economic mechanism* means the fleet self-optimises against whatever objective you price — and it degrades gracefully.

### 2.3 Self-healing task graph
When one robot fails, its remaining tasks are re-planned and absorbed by neighbours without central re-dispatch.

**Solves:** a single failure stalling a whole wave of work.
**Why different:** resilience is normally central. This is resilience by protocol.

---

## Theme 3 — Robots that communicate with humans

### 3.1 Intention broadcasting
The robot continuously announces its **next three seconds of motion** — a floor light strip that shows the projected path, a direction indicator, a subtle audible cue on direction change. Humans can predict it instead of guessing.

**Solves:** mixed human/robot traffic, which is a first-class safety and research problem (and where AMRs get blamed for accidents).
**Why different:** today's AMRs *stop* to be safe, which makes them slow and frustrating. An AMR that *communicates* can keep moving safely. That is a genuinely different safety philosophy — and it is the opposite of "when in doubt, stop."

### 3.2 The handover protocol
A defined, teachable ritual for human→robot and robot→human task handover: the robot signals readiness, the human acknowledges, custody transfers, both parties log it. Borrowed from aviation and surgical teamwork.

**Solves:** the awkward, accident-prone "who moves first" moment — the highest-risk interaction in mixed warehouses.
**Why different:** nobody has standardised this. It is a *social* protocol, not a technical one, and it is what actually causes injuries.

### 3.3 Social-force yielding
The robot models human *discomfort* — personal space, trajectory convergence, hesitancy — and yields proactively rather than at the last safe moment.

**Solves:** the feeling that robots are rude and unpredictable, which drives operator resistance and shadow-banning of robots.
**Why different:** yields are computed against a *comfort* model, not just a collision model.

---

## Theme 4 — The warehouse as a sensed organism

### 4.1 Floor-degradation mapping
The robot detects where the floor is failing — from slip events, odometry anomalies, vibration signatures — and builds a **floor health map** alongside the hazard map.

**Solves:** floor damage is discovered only when it damages a robot or injures someone. This predicts it.
**Why different:** nobody maps floor condition from robot motion. The robot becomes a *survey instrument* as a byproduct of doing its job.

### 4.2 Acoustic warehouse awareness
A microphone array detects events while the robot works normally: a dropped pallet, a forklift approaching from a blind aisle, a conveyor running rough, glass breaking.

**Solves:** detection of events the robot's cameras cannot see (behind racks, around corners).
**Why different:** passive, free sensing that requires no extra travel. The robot hears the warehouse.

### 4.3 Air-quality and thermal mapping as a byproduct
Instead of point gas detection, the robot builds a **concentration map** over time. Cold storage CO₂, battery-room hydrogen, solvent storage, and electrical hot spots in racking all become spatial fields rather than alarms.

**Solves:** fixed sensors detect only where they are installed. A moving sensor with memory maps the whole volume.
**Why different:** converts a *detection* problem into a *mapping* problem — and your dual-heatmap machinery already does exactly this for hazards.

### 4.4 Slotting that rewrites itself
The robot observes *actual* pick frequency as it moves, and recommends (or performs) re-slotting — moving fast-movers to accessible locations based on observed demand, not a quarterly spreadsheet.

**Solves:** slotting is planned once and drifts out of date immediately. Observed demand beats assumed demand.
**Why different:** closes the loop between *observing* the warehouse and *changing* it.

---

## Theme 5 — Self-* systems

### 5.1 Spatial slip model
The robot learns braking and traction characteristics **per floor zone** — this aisle is polished concrete, that one is worn epoxy, the dock apron is often damp — and adapts its speed and stopping envelope spatially.

**Solves:** the safety envelope is a single worst-case number today, which makes the robot unnecessarily slow everywhere. A spatial model lets it be fast where it's safe and slow where it isn't.
**Why different:** this is the self-calibrating envelope extended from *time* into *space*. Nobody does spatial safety envelopes.

### 5.2 Self-diagnosis from motor signatures
The robot reads its own motor current, encoder and vibration signatures and predicts its *own* component failures — bearing wear, wheel flat spots, gearbox degradation — before they strand it.

**Solves:** unplanned downtime, which is the real cost driver in AMR fleets.
**Why different:** predictive maintenance is normally applied *to the warehouse's machines*. Applying it to the robot's own drivetrain, from the control loop it already runs, is free.

### 5.3 Graceful degradation ladder
Define explicit capability tiers as sensors fail: full autonomy → reduced speed → supervised → teleop → safe stop. The robot never falls off a cliff; it steps down.

**Solves:** the binary failure mode where a sensor fault removes the robot entirely, or worse, leaves it operating with degraded perception it doesn't know about.
**Why different:** most systems have a fault state. A *ladder* keeps the robot useful as it degrades — and makes the degradation auditable.

---

## Theme 6 — The twin as an active asset

### 6.1 Twin-in-the-loop policy testing
The live twin doubles as a simulation environment. Before a new navigation or safety policy touches the real robot, it runs against **live warehouse conditions** replayed in the twin.

**Solves:** you cannot safely experiment on a working warehouse floor.
**Why different:** the twin stops being a *visualisation* and becomes a *test bench* — the same digital state serving both display and validation.

### 6.2 Fleet memory
One robot's hard-won knowledge — this corner has a blind spot, that pallet overhangs, this floor is slippery when wet — propagates to every other robot as a **shared world model**, not as raw data.

**Solves:** every new robot relearns every lesson; fleets don't get smarter over time.
**Why different:** the fleet accumulates institutional memory. New robots start experienced.

---

## Top five picks — the ones that would actually set you apart

| Rank | Concept | Why it's the differentiator |
|---|---|---|
| **1** | **Counterfactual twin** (§1.3) | Turns your existing twin from a *display* into a *decision and trust instrument*. Nobody sells "show me the accident that didn't happen." |
| **2** | **Explainable stop** (§1.2) | Attacks the #1 reason operators distrust AMRs, and it is a direct extension of the honesty instinct already in your code |
| **3** | **Spatial slip model** (§5.1) | Makes the robot *fast where it's safe and slow where it isn't* — the opposite of the worst-case-everywhere approach everyone uses |
| **4** | **Intention broadcasting** (§3.1) | A genuinely different safety philosophy: communicate instead of stop. Solves the mixed-traffic problem the whole industry is stuck on |
| **5** | **Aisle-access auction** (§2.2) | Solves congestion with an economic mechanism instead of scheduling rules — and congestion is a patented battleground, so a different mechanism matters |

## Combinations that compound

- **§1.2 + §1.3** — an explainable stop, plus the counterfactual of what would have happened if it hadn't stopped. Together these are an *incident investigation product*, not a robot feature.
- **§4.1 + §5.1** — floor degradation map feeding the spatial slip model. The robot gets safer *because* it noticed the floor failing.
- **§2.1 + §2.2 + §2.3** — peer negotiation + auction + self-healing. Together: a fleet with no central brain that still optimises and still survives failures.
- **§1.1 + §1.2** — provenance-chained telemetry carrying evidence bundles. An auditable, provable record of every safety decision the fleet ever made.
- **§4.3 + §4.2 + §4.1** — gas, sound and floor mapped simultaneously as the robot works. The robot stops being a box-mover and becomes a **mobile sensor platform** — and its sensing byproduct is arguably more valuable than its labour.

---

## The reframe worth considering

Every idea above points the same direction:

> **You are not building a robot that moves boxes. You are building a robot that produces trustworthy, verifiable, physically-grounded evidence about a warehouse — and moves boxes while it does.**

Box-moving is a commodity with crowded patents and funded incumbents. **Warehouse evidence is not.** The trust layer is empty, it is where your project's existing instincts already point, and it makes every other capability more valuable rather than competing with it.

---

> Ideation document — concepts only, feasibility deliberately out of scope per the brief. None of these has been assessed for patentability or prior art; the crowded/open analysis in `reports/AMR_AI_AGENTS_RESEARCH_REPORT.md` and the filing triage in `reports/AMR_PATENT_ROADMAP.md` still apply before any IP decision.
