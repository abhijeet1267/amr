## 研究摘要：New AMR concepts — prior art (trust, human interaction, twin)

**Mode**: Phase 1 initial scouting · 9 concepts · 40+ sources
**Method note**: Patent metadata (number / title / assignee / priority date) gathered via the Google Patents query API; where a claim rests on a secondary source I say so. No patent number or URL below is invented. "Not verified" is used where I could not confirm.

---

### 1.1 Provenance-chained telemetry
- **What it is**: Each telemetry record hash-chained to its predecessor → tamper-evident log; operator/auditor/insurer can prove what the robot reported and when.
- **Prior patents (well-established in security, thinner in robotics)**:
  - [US11032065B2 — Verifiable redactable audit log](https://patents.google.com/patent/US11032065B2/en) — Palantir Technologies, priority 2013-12-30. Hash-chain audit log with verifiable redaction.
  - [US8977860B2 — Method and apparatus for tamper proof camera logs](https://patents.google.com/patent/US8977860B2/en) — Ricoh Co., priority 2008-10-02. Tamper-proof logs for a *camera* (a sensor-carrying device, close analogue).
  - [US6795759B2 — Secure logging of vehicle data](https://patents.google.com/patent/US6795759B2/en) — IBM, priority 2002-08-26. Secure event-data logging for vehicles — the closest "mobile platform" prior art.
- **Research papers**: The field is mature in security — e.g. [Secure Audit Logging with Tamper-Resistant Hardware](https://link.springer.com/chapter/10.1007/978-0-387-35691-4_7); [Keeping Authorities "Honest or Bust" with Decentralized Witness Cosigning](https://arxiv.org/pdf/1503.08768). Robot-specific: [A Survey on Blockchain in Robotics: Issues, Opportunities, Challenges and Future Directions](https://xueshu.baidu.com/s?wd=paperuri:(145d0e80xv4m0g10bg140000yk572496)) (Aditya et al., *JNCA* 2021). A 2026 caution: [LLM Agents Can Easily Tamper With Their Own Traces](https://arxiv.org/html/2609.30266v1).
- **Commercial**: Tamper-evident logging is now productised for AI agents, not robots — [AgentLens](https://www.mcpworld.com/en/detail/4b4b24a21bd6dfc76728c935a1928b78) (SHA-256 hash-chained agent logs), [Agnys](https://agnys.net/) (per-agent hash chain anchored to WORM storage). No AMR vendor was found selling provable telemetry.
- **Proximity / crowdedness**: **Crowded in the abstract, open in the robotics application.** Hash-chain logging is textbook prior art (2002–2013 patents), so a bare "hash-chained log" claim is dead. What is *not* clearly claimed is the robot-specific combination — sensor-rich telemetry + safety-stop evidence + third-party (insurer/auditor) verification of a *physical* robot's reported behaviour. Differentiator must be the application and the verification workflow, not the hash chain itself.

### 1.2 The explainable stop
- **What it is**: Every safety stop emits an evidence bundle — which sensors fired, raw readings, matched rule, threshold, confidence.
- **Prior patents**: [US20230273603A1 — System and Method for Adjusting Fail-Safe Monitoring in an Industrial [environment]](https://patents.google.com/patent/US20230273603A1/en) — Siemens, priority 2020-07-08. Fail-safe monitoring configuration. [US10962972B2 — Safety architecture for autonomous vehicles](https://patents.google.com/patent/US10962972B2/en) — Carnegie Mellon University, priority 2016-01-05 (safety monitor architecture; not an "evidence bundle").
- **Research papers**: [Explainable AI for Robot Failures: Generating Explanations that Improve User Assistance in Fault Recovery](https://xueshu.baidu.com/s?wd=paperuri:(1s440r30qb2x0xy0gm5y0v20ay345180)) (Das, Banerjee, Chernova, 2021) — directly on point; [TRACE: Transparent Reasoning Architecture for Credible Execution](https://xueshu.baidu.com/s?wd=paperuri:(1d5k0gd0rw6k0t407n3r0210p8693555)) (Temel, 2026) — traces every autonomous action; [Explainable Robotics in Human-Robot Interactions](https://www.sciencedirect.com/science/article/pii/S1877050920321001); [Explaining Explanations to Mitigate Robot Conversational Failures](https://arxiv.org/pdf/2307.04462v1).
- **Commercial**: Fault *codes* are ubiquitous (every AMR vendor). No vendor found shipping a reconstructable, human-readable "evidence bundle" for a stop. [Charles River Analytics](https://cra.com/robotics-and-autonomy/) builds explainable human-robot interfaces (adjacent).
- **Proximity / crowdedness**: **Moderately open.** Explainable-AI-for-failures is an active research area, but the specific *product* framing — a self-service, per-stop evidence bundle an operator can read without a support ticket — is not what the patents or vendors show. The novelty risk is low-moderate; the "obviousness" risk is that it reads as a UI/reporting feature rather than a technical invention.

### 1.3 The counterfactual twin
- **What it is**: Extend the live twin to answer "what would have happened if…?" — replay telemetry through an alternative policy and show the divergent outcome.
- **Prior patents (adjacent, none found claiming counterfactual replay for robots)**: [US12561660B2 — Digital-twin-enabled robot fleet management](https://patents.google.com/patent/US12561660B2/en) — Strong Force VCN Portfolio 2019, priority 2020-12-18 (a library of robot digital twins for fleet management — describes the twin, not counterfactual replay). [US11455576B2 — Architecture for explainable reinforcement learning](https://patents.google.com/patent/US11455576B2/en) — UMNAI, priority 2020-11-12. [US20240303501A1 — Imitation and reinforcement learning for multi-agent simulation](https://patents.google.com/patent/US20240303501A1/en) — Waabi Innovation, priority 2023-03-07 (counterfactual simulation for AVs, not robots).
- **Research papers**: [Using Counterfactual Reasoning and Reinforcement Learning for Decision-Making in Autonomous Driving](https://xueshu.baidu.com/s?wd=paperuri:(123p0x601d0m0xw0vx650400hk659212)) (Hart & Knoll, 2020); [Fractional Collisions: A Framework for Risk Estimation of Counterfactual Conflicts using Autonomous Driving Behavior Simulation](https://arxiv.org/pdf/2506.07540) (Nuro AI); [SVCE: Shapley Value Guided Counterfactual Explanation for ML-Based Autonomous Driving](https://www.ablesci.com/scholar/paper?id=rnPaoZnME) (IEEE TITS 2024); [What-If Explanations Over Time: Counterfactuals for Time-Series](https://arxiv.org/html/2603.27792v1).
- **Commercial**: Counterfactual simulation is productised in AV tooling (Waabi) and, per the patent, digital-twin fleet management. No product found that sells "replay *this robot's* telemetry through *another* policy and show the accident that didn't happen" for warehouse AMRs.
- **Proximity / crowdedness**: **Genuinely the most open of the nine — but adjacent art is dense.** Counterfactual simulation is heavily developed in AVs and XAI; the *unoccupied* space is the tight coupling of (a) a live operational twin, (b) the robot's own recorded telemetry as the replay seed, and (c) side-by-side divergence for incident/trust evidence. This is the strongest "differentiator" candidate, but must be claimed at that specific combination, because "counterfactual simulation" alone is not novel.

### 1.4 Safety case as code
- **What it is**: The ISO 3691-4 / ISO 13849 safety argument expressed as executable tests that run continuously and fail the build if a safety claim stops being true.
- **Prior patents**: [US20210342144A1 — Guided safety analysis for cyber physical systems](https://patents.google.com/patent/US20210342144A1/en) — University of Notre Dame, priority 2018-10-18. [US11745732B2 — Certified control for self-driving cars](https://patents.google.com/patent/US11745732B2/en) — Toyota Research Institute, priority 2019-07-09. [US10962972B2 — Safety architecture for autonomous vehicles](https://patents.google.com/patent/US10962972B2/en) — CMU. None found claiming "safety case as an executable, continuously-run test suite."
- **Research papers**: [Employing Field Monitoring and Runtime Safety Verification for Cumulative Operational Safety Assurance in a SafetyDevOps Process](https://xueshu.baidu.com/s?wd=paperuri:(1d0n0xs08e1f0ta0mf4u0e90jp675773)) (Laxman, Schweizer, Reich, 2024) — *closest conceptual match*; [Evaluating Assurance Cases as Text-Attributed Graphs for Structure and Provenance Analysis](https://arxiv.org/html/2604.20577v1); [Safety Cases: Provenance, Traceability and Delivery](https://xueshu.baidu.com/s?wd=paperuri:(1v4604t0xk7002k0h9630xw0t3459869)) (Cleland & Emmet, Adelard, 2008).
- **Commercial**: Assurance-case tooling is an established market — [Adelard ASCE](https://www.adelard.com/media/0i5pchud/softcement2005_emmet_guerra_application_of_commercial_tool.pdf); [Critical Systems Labs](https://criticalsystemslabs.com/); [TRL safety cases](https://www.trl.co.uk/solutions/safety-cases-for-automated-vehicle-technology-trials). [ISO 3691-4:2023](https://www.iso.org/standard/88615.html) is the governing standard. Tooling *manages* the case; none found *executes* it as a CI test suite.
- **Proximity / crowdedness**: **Open, but an active adjacent field.** Assurance-case automation (GSN, CAE, Adelard, York CfAA) is well developed, and "SafetyDevOps"/runtime verification is emerging. The "safety case as code that fails the build" variant — treating each safety claim as a continuously-executed test — appears unclaimed and is a plausible differentiator. Risk: it may read as process/tooling rather than patentable subject matter.

### 3.1 Intention broadcasting
- **What it is**: Robot continuously announces its next ~3 seconds of motion (floor light strip / indicator / audible cue).
- **Prior patents — this is the sharpest hit of the nine**: [US9744672B2 — Systems and methods for communicating robot intentions to human beings](https://patents.google.com/patent/US9744672B2/en) — University of South Florida St. Petersburg, priority 2011-11-16, granted 2017-08-29. Its claims explicitly cover visually communicating a **short-term intention** "a movement the robot will make in the immediate future," with the spec stating τ "can be set to 3 seconds," and projecting an arrow whose direction = heading and size = speed. This is essentially concept 3.1, pre-claimed in 2011. **Status: Expired – Fee Related** (i.e. lapsed for non-payment) — relevant to freedom-to-operate even though the claims are no longer enforceable. Also [JP2022082550A — Systems and methods for autonomous cart robots](https://patents.google.com/patent/JP2022082550A/en) — Toyota Research Institute, priority 2018-03-29; [US11958183B2 — Negotiation-based human-robot collaboration via augmented reality](https://patents.google.com/patent/US11958183B2/en) — SUNY, priority 2019-09-19.
- **Research papers (large active field)**: [External Human-Machine Interface on Delivery Robots: Expression of Navigation Intent of the Robot](https://link.springer.com/article/10.1007/s12369-023-01064-3) (Kannan, Lee, Min, IEEE RO-MAN 2021 — cited here); [The Impact of External Human-Machine Interfaces on Pedestrian Crossing Intention](https://xueshu.baidu.com/s?wd=paperuri:(1c4c0pu0gj110at0ww050ap0sh315933)) (Cui & Oca, IEEE RO-MAN 2025); [Can the Indication of Yielding from an Automated Vehicle Using an eHMI Have the Same Function as a Driver's Hand Signal?](https://link.springer.com/article/10.1007/s13177-025-00607-4) (2025).
- **Commercial**: Indicator lights/status bars exist on AMRs ([HUBTEX AGV](https://www.hubtex.com/en-us/products/automated-guided-vehicle-systems/technologies-agv-amr) — "LED status bar, acoustic warning signal"); eHMI "blue lights" are being standardised for AVs (GB 4785 revision, China). No AMR found shipping *projected next-3-seconds trajectory*.
- **Proximity / crowdedness**: **Crowded — the most occupied of the nine.** The core idea (visualise a robot's imminent intended motion to humans, including the ~3-second horizon) is explicitly claimed by an expired USF patent, and eHMI is a very large active field (mostly AVs, transferring to robots). Do **not** treat "intention broadcasting" as novel. A differentiator would have to be narrow: e.g. the *specific* mixed-traffic safety logic ("communicate instead of stop") or a novel modality — not the general concept.

### 3.2 The handover protocol
- **What it is**: A defined, teachable ritual for human↔robot task handover (signal, acknowledge, transfer custody, log).
- **Prior patents (object handover is crowded; "protocol/custody" framing is thinner)**: [US10913151B1 — Object hand-over between robot and actor](https://patents.google.com/patent/US10913151B1/en) — X Development LLC (Google X), priority 2018-06-01. [JP7619784B2 — Machine learning control of object handover](https://patents.google.com/patent/JP7619784B2/en) — NVIDIA, priority 2020-07-28. [US12454050B2 — Reactive interactions for robotic applications](https://patents.google.com/patent/US12454050B2/en) — NVIDIA, priority 2022-03-20. Also relevant: [US20220004979A1 — Autonomous Mobile Delivery Robot And Chain Of Custody System](https://xueshu.baidu.com/s?wd=paperuri:(1j370e10fd1w06g0hs6q0ju0r6317906)) (secondary source; application, not verified grant) — "chain of custody" for a delivery robot.
- **Research papers**: [Human-to-robot handovers based on multimodal perception](https://www.sciencedirect.com/science/article/abs/pii/S0925231225011075) (2025); [Preemptive Motion Planning for Human-to-Robot Indirect Placement Handovers](https://xueshu.baidu.com/s?wd=paperuri:(177a00k0mw1306h0ep6b089050596208)) (Choi, Jawed, Joo, 2022); [HAnD-AI project](https://www.uni-muenster.de/Sportwissenschaft/en/Neuromotor-Behavior/forschung/handai/index.html); [Framework and Benchmark for Robot-to-Human Object Handovers](https://arxiv.org/html/2606.21011v1).
- **Commercial**: Handover is engineered per-robot; no standardised human-robot *handover protocol* product was found.
- **Proximity / crowdedness**: **Split.** The *physical* object-handover problem is crowded (NVIDIA, X Development, many papers). The *social/procedural* protocol — a teachable ritual with explicit acknowledge/custody-transfer/log steps borrowed from aviation/surgery — appears open, because the literature and patents attack the manipulation problem, not the coordination ritual. Differentiator is real but may be hard to patent (process/social, not technical).

### 3.3 Social-force yielding
- **What it is**: Model human discomfort (personal space, trajectory convergence, hesitancy) and yield proactively, not at the last safe moment.
- **Prior patents**: [METHOD AND SYSTEM FOR SOCIALLY COMPLIANT ROBOTIC PATH PLANNING](https://xueshu.baidu.com/s?wd=paperuri:(1r4y0pd0cp5f0vx0rb520vu08q374136)) (Ansari, Tourani, Kumar) — patent found via secondary source; publication number not verified here. Social-navigation patents exist broadly; exact numbers not confirmed.
- **Research papers (very crowded)**: [A Game of Social Forces: Integrating Non-cooperative Game Theory with Social Force Model for a Socially-acceptable Mobile Robot Navigation](https://link.springer.com/article/10.1007/s10846-025-02318-0) (*JINT*, 2025); [On Legible and Predictable Robot Navigation in Multi-Agent Environments](https://ece.uwaterloo.ca/~sl2smith/papers/2023ICRA-Legible_and_Predictable.pdf) (ICRA 2023); [Human-Aligned Benchmarking in Social Robot Navigation](https://arxiv.org/html/2510.02941v2); [HuNavSim: Simulator for Benchmarking Human-Aware Robot Navigation](https://motion-planning-workshop.kavrakilab.org/papers/hunavsim.pdf). The Social Force Model (Helbing) is foundational.
- **Commercial**: [Falcon (ICRA'25)](https://baijiahao.baidu.com/s?id=1828173623880536489) reports ~90% personal-space compliance; social-navigation stacks are common in service robots.
- **Proximity / crowdedness**: **Crowded academically, open commercially for warehouses.** Social-force/comfort-aware navigation is a mature research field (decades of work, dedicated benchmarks). The warehouse-specific twist — yielding against a *comfort* model in mixed human/AMR aisles — is less directly claimed, but the core mechanism (social force / personal-space / proactive yielding) is not novel. Differentiator would be application and the comfort metric, not the mechanism.

### 6.1 Twin-in-the-loop policy testing
- **What it is**: The live twin doubles as a simulation environment; new navigation/safety policies are validated against live warehouse conditions before touching the real robot.
- **Prior patents**: [US12561660B2 — Digital-twin-enabled robot fleet management](https://patents.google.com/patent/US12561660B2/en) — Strong Force VCN Portfolio 2019, priority 2020-12-18. [US20220138094A1 — Computer-implemented method and test unit for approximating a subset of test [cases]](https://patents.google.com/patent/US20220138094A1/en) — dSPACE, priority 2019-08-21. [SG11202012059QA — System and methodology for performance verification of multi-agent autonomous [systems]](https://patents.google.com/patent/SG11202012059QA/en) — Elta Systems, priority 2018-06-05.
- **Research/commercial (heavily productised)**: [NVIDIA "Mega" Omniverse Blueprint for industrial robot fleet digital twins](https://blogs.nvidia.com/blog/three-computers-robotics/) (Jan 2025) — explicitly markets "robot fleet software-in-the-loop testing"; [NVIDIA Isaac](https://developer.nvidia.com/blog/introducing-nvidia-isaac-for-healthcare-an-ai-powered-medical-robotics-development-platform/) ("policies fully trained in the digital twin"); [Arendai Harmony Digital Twin](https://www.arendai.com/) ("test changes in simulation before they reach production"); [CoppeliaSim](https://www.coppeliarobotics.com/) ("safety double-checking ... digital twin").
- **Proximity / crowdedness**: **Crowded.** NVIDIA Mega, Arendai and others already sell exactly this — a live twin used as a test bench / software-in-the-loop. Treat as occupied; a differentiator would need to be a genuinely new mechanism (e.g. seeding the twin with the robot's *own* live telemetry rather than a synthetic scenario library), not the concept.

### 6.2 Fleet memory
- **What it is**: One robot's learned knowledge (blind corners, overhanging pallets, slippery floors) propagates to all others as a shared world model.
- **Prior patents**: [US20240385620A1 — Autonomous Mobile Robot Fleet And Control Method Thereof](https://xueshu.baidu.com/s?wd=paperuri:(1t150rs0h2760at05n4y0ja04d279518)) (secondary source; number from USPTO news, not independently verified). [CA2999272C — Networked robotic manipulators](https://patents.google.com/patent/CA2999272C/en) — Amazon Technologies, priority 2015-09-21. [US12535823B2 — Systems and methods for detection of features within data collected by a [robot]](https://patents.google.com/patent/US12535823B2/en) — Brain Corporation, priority 2020-01-09.
- **Research/commercial**: [Interactive Fleet Learning](https://bair.berkeley.edu/blog/2023/04/06/ifl/) (BAIR, 2023) — fleets that continually learn; [World Model for Robot Learning: A Comprehensive Survey](https://baijiahao.baidu.com/s?id=1865341704958147247); federated learning for robot fleets is a large literature ([Multi-Center Federated Learning](https://arxiv.org/pdf/2005.01026v1)). Commercial: [Brain Corp BrainOS](https://www.braincorp.com/brainos) — "Over-the-air fleet learning. Every mile driven by a BrainOS-powered machine feeds data back."
- **Proximity / crowdedness**: **Crowded.** "Fleet learning" is explicitly a marketed BrainOS feature, Amazon patents networked robots, and federated/continual learning for fleets is a dense research area. The *framing* (shared world model vs raw data) is nice but the mechanism is not novel.

---

## Cross-cutting candid verdict

| Concept | Crowdedness | Note |
|---|---|---|
| 1.1 Provenance-chained telemetry | Crowded in security; **open in robotics** | Hash-chain is prior art; robot+audit application is the room |
| 1.2 Explainable stop | **Moderate / open** | XAI-for-failures researched; product framing unclaimed |
| 1.3 Counterfactual twin | **Most open** | Adjacent AV/XAI art dense; the live-twin replay combo unclaimed |
| 1.4 Safety case as code | **Open** | Assurance automation exists; "as code / CI test" variant unclaimed |
| 3.1 Intention broadcasting | **Crowded (worst)** | US9744672B2 pre-claims the 3-second intention (now lapsed) |
| 3.2 Handover protocol | Split | Object handover crowded; *protocol/ritual* open |
| 3.3 Social-force yielding | Crowded (academic) | Comfort-navigation mature; warehouse twist is the only gap |
| 6.1 Twin-in-the-loop | **Crowded** | NVIDIA Mega / Arendai already ship it |
| 6.2 Fleet memory | **Crowded** | BrainOS "fleet learning" is a marketed feature |

**Three concepts worth deeper Phase-3 work**: 1.3 (counterfactual twin), 1.4 (safety case as code), 1.2 (explainable stop). **Three to de-prioritise as "novel"**: 3.1, 6.1, 6.2.

---

## 已收集来源池 (Source pool)

### Patents
1. [US9744672B2 — Systems and methods for communicating robot intentions to human beings](https://patents.google.com/patent/US9744672B2/en) — Univ. South Florida; claims short-term ("next few seconds") intention via projection; **expired**
2. [US11032065B2 — Verifiable redactable audit log](https://patents.google.com/patent/US11032065B2/en) — Palantir; hash-chain audit log
3. [US8977860B2 — Method and apparatus for tamper proof camera logs](https://patents.google.com/patent/US8977860B2/en) — Ricoh; tamper-proof sensor logs
4. [US6795759B2 — Secure logging of vehicle data](https://patents.google.com/patent/US6795759B2/en) — IBM; secure vehicle event logging
5. [US12561660B2 — Digital-twin-enabled robot fleet management](https://patents.google.com/patent/US12561660B2/en) — Strong Force VCN Portfolio 2019
6. [US11455576B2 — Architecture for explainable reinforcement learning](https://patents.google.com/patent/US11455576B2/en) — UMNAI
7. [US20240303501A1 — Imitation and reinforcement learning for multi-agent simulation](https://patents.google.com/patent/US20240303501A1/en) — Waabi Innovation
8. [US10962972B2 — Safety architecture for autonomous vehicles](https://patents.google.com/patent/US10962972B2/en) — Carnegie Mellon University
9. [US11745732B2 — Certified control for self-driving cars](https://patents.google.com/patent/US11745732B2/en) — Toyota Research Institute
10. [US20210342144A1 — Guided safety analysis for cyber physical systems](https://patents.google.com/patent/US20210342144A1/en) — Univ. of Notre Dame
11. [US20230273603A1 — System and Method for Adjusting Fail-Safe Monitoring in an Industrial [environment]](https://patents.google.com/patent/US20230273603A1/en) — Siemens
12. [US10913151B1 — Object hand-over between robot and actor](https://patents.google.com/patent/US10913151B1/en) — X Development LLC
13. [JP7619784B2 — Machine learning control of object handover](https://patents.google.com/patent/JP7619784B2/en) — NVIDIA
14. [US12454050B2 — Reactive interactions for robotic applications](https://patents.google.com/patent/US12454050B2/en) — NVIDIA
15. [US11958183B2 — Negotiation-based human-robot collaboration via augmented reality](https://patents.google.com/patent/US11958183B2/en) — SUNY
16. [JP2022082550A — Systems and methods for autonomous cart robots](https://patents.google.com/patent/JP2022082550A/en) — Toyota Research Institute
17. [US20220138094A1 — Computer-implemented method and test unit for approximating test cases](https://patents.google.com/patent/US20220138094A1/en) — dSPACE
18. [SG11202012059QA — System and methodology for performance verification of multi-agent autonomous systems](https://patents.google.com/patent/SG11202012059QA/en) — Elta Systems
19. [CA2999272C — Networked robotic manipulators](https://patents.google.com/patent/CA2999272C/en) — Amazon Technologies
20. [US12535823B2 — Systems and methods for detection of features within data collected by a robot](https://patents.google.com/patent/US12535823B2/en) — Brain Corporation
21. [US11724395B2 — Robot congestion management](https://xueshu.baidu.com/s?wd=paperuri:(197k0gf0pr0f0c00441u0p50dw476034)) — Locus Robotics (via secondary source; not independently verified)
22. [US20240385620A1 — Autonomous Mobile Robot Fleet And Control Method Thereof](https://xueshu.baidu.com/s?wd=paperuri:(1t150rs0h2760at05n4y0ja04d279518)) — (secondary source; not verified)
23. [US20220004979A1 — Autonomous Mobile Delivery Robot And Chain Of Custody System](https://xueshu.baidu.com/s?wd=paperuri:(1j370e10fd1w06g0hs6q0ju0r6317906)) — (secondary source; not verified)
24. [METHOD AND SYSTEM FOR SOCIALLY COMPLIANT ROBOTIC PATH PLANNING](https://xueshu.baidu.com/s?wd=paperuri:(1r4y0pd0cp5f0vx0rb520vu08q374136)) — Ansari/Tourani/Kumar (number not verified)

### Papers
25. [Explainable AI for Robot Failures](https://xueshu.baidu.com/s?wd=paperuri:(1s440r30qb2x0xy0gm5y0v20ay345180)) — Das, Banerjee, Chernova, 2021
26. [TRACE: Transparent Reasoning Architecture for Credible Execution](https://xueshu.baidu.com/s?wd=paperuri:(1d5k0gd0rw6k0t407n3r0210p8693555)) — Temel, 2026
27. [Explainable Robotics in Human-Robot Interactions](https://www.sciencedirect.com/science/article/pii/S1877050920321001) — ScienceDirect
28. [Explaining Explanations to Mitigate Robot Conversational Failures](https://arxiv.org/pdf/2307.04462v1) — arXiv
29. [Using Counterfactual Reasoning and RL for Decision-Making in Autonomous Driving](https://xueshu.baidu.com/s?wd=paperuri:(123p0x601d0m0xw0vx650400hk659212)) — Hart & Knoll, 2020
30. [Fractional Collisions: Counterfactual Conflicts via AV Behavior Simulation](https://arxiv.org/pdf/2506.07540) — Nuro AI
31. [SVCE: Shapley Value Guided Counterfactual Explanation](https://www.ablesci.com/scholar/paper?id=rnPaoZnME) — IEEE TITS 2024
32. [What-If Explanations Over Time: Counterfactuals for Time Series](https://arxiv.org/html/2603.27792v1) — arXiv 2026
33. [Employing Field Monitoring and Runtime Safety Verification ... SafetyDevOps](https://xueshu.baidu.com/s?wd=paperuri:(1d0n0xs08e1f0ta0mf4u0e90jp675773)) — Laxman, Schweizer, Reich, 2024
34. [Evaluating Assurance Cases as Text-Attributed Graphs](https://arxiv.org/html/2604.20577v1) — arXiv 2026
35. [Safety Cases: Provenance, Traceability and Delivery](https://xueshu.baidu.com/s?wd=paperuri:(1v4604t0xk7002k0h9630xw0t3459869)) — Cleland & Emmet (Adelard), 2008
36. [A Survey on Blockchain in Robotics](https://xueshu.baidu.com/s?wd=paperuri:(145d0e80xv4m0g10bg140000yk572496)) — Aditya et al., JNCA 2021
37. [LLM Agents Can Easily Tamper With Their Own Traces](https://arxiv.org/html/2609.30266v1) — arXiv 2026
38. [Secure Audit Logging with Tamper-Resistant Hardware](https://link.springer.com/chapter/10.1007/978-0-387-35691-4_7) — Springer
39. [Keeping Authorities "Honest or Bust" (witness cosigning)](https://arxiv.org/pdf/1503.08768) — arXiv
40. [External Human-Machine Interface on Delivery Robots: Expression of Navigation Intent](https://link.springer.com/article/10.1007/s12369-023-01064-3) — Kannan, Lee, Min, RO-MAN 2021
41. [The Impact of eHMI on Pedestrian Crossing Intention](https://xueshu.baidu.com/s?wd=paperuri:(1c4c0pu0gj110at0ww050ap0sh315933)) — Cui & Oca, RO-MAN 2025
42. [Can eHMI Yielding Indication Replace a Driver's Hand Signal?](https://link.springer.com/article/10.1007/s13177-025-00607-4) — Springer 2025
43. [Human-to-robot handovers based on multimodal perception](https://www.sciencedirect.com/science/article/abs/pii/S0925231225011075) — ScienceDirect 2025
44. [Preemptive Motion Planning for Human-to-Robot Indirect Placement Handovers](https://xueshu.baidu.com/s?wd=paperuri:(177a00k0mw1306h0ep6b089050596208)) — Choi, Jawed, Joo, 2022
45. [Framework and Benchmark for Robot-to-Human Object Handovers](https://arxiv.org/html/2606.21011v1) — arXiv
46. [A Game of Social Forces (GTSFM)](https://link.springer.com/article/10.1007/s10846-025-02318-0) — JINT 2025
47. [On Legible and Predictable Robot Navigation](https://ece.uwaterloo.ca/~sl2smith/papers/2023ICRA-Legible_and_Predictable.pdf) — ICRA 2023
48. [Human-Aligned Benchmarking in Social Robot Navigation](https://arxiv.org/html/2510.02941v2) — arXiv
49. [HuNavSim: Benchmarking Human-Aware Robot Navigation](https://motion-planning-workshop.kavrakilab.org/papers/hunavsim.pdf) — workshop paper
50. [Interactive Fleet Learning](https://bair.berkeley.edu/blog/2023/04/06/ifl/) — BAIR, 2023
51. [World Model for Robot Learning: A Comprehensive Survey](https://baijiahao.baidu.com/s?id=1865341704958147247) — survey
52. [Multi-Center Federated Learning](https://arxiv.org/pdf/2005.01026v1) — arXiv
53. [ISO 3691-4:2023 — Driverless industrial trucks](https://www.iso.org/standard/88615.html) — standard

### Commercial / industry
54. [NVIDIA Mega Omniverse Blueprint — industrial robot fleet digital twins / software-in-the-loop](https://blogs.nvidia.com/blog/three-computers-robotics/) — Jan 2025
55. [NVIDIA Isaac — policies trained in the digital twin](https://developer.nvidia.com/blog/introducing-nvidia-isaac-for-healthcare-an-ai-powered-medical-robotics-development-platform/)
56. [Arendai Harmony Digital Twin — test changes in simulation before production](https://www.arendai.com/)
57. [CoppeliaSim — robot simulation / digital twin](https://www.coppeliarobotics.com/)
58. [Brain Corp BrainOS — over-the-air fleet learning](https://www.braincorp.com/brainos)
59. [Locus Robotics — warehouse AMR vendor](https://www.locusrobotics.com/)
60. [Adelard — assurance/safety case tooling (ASCE)](https://www.adelard.com/media/0i5pchud/softcement2005_emmet_guerra_application_of_commercial_tool.pdf)
61. [Critical Systems Labs — safety assurance cases (GSN)](https://criticalsystemslabs.com/)
62. [AgentLens — tamper-evident observability for AI agents](https://www.mcpworld.com/en/detail/4b4b24a21bd6dfc76728c935a1928b78)
63. [Agnys — tamper-evident AI agent audit trails](https://agnys.net/)
64. [HUBTEX — AGV/AMR with LED status bar and acoustic warning](https://www.hubtex.com/en-us/products/automated-guided-vehicle-systems/technologies-agv-amr)
65. [Falcon social navigation (ICRA'25) — personal-space compliance](https://baijiahao.baidu.com/s?id=1828173623880536489)
