# Enterprise AI Agents and Warehouse Robotics: Adoption Trends, an AMR Patentability Assessment, and the Future of Fulfilment Operations

**Date**: 2026-10-13  
**Mode**: Full research report  
**Prepared by**: Deep Research Team (Chief Editor Gu, with six specialist members)

---

## Contents

- [Introduction](#introduction)
- [1. Enterprise AI agents: capability definition, the agent-washing credibility lens, and the measured adoption reality](#1-enterprise-ai-agents-capability-definition-the-agent-washing-credibility-lens-and-the-measured-adoption-reality)
- [2. The enterprise agent technology and governance stack: orchestration frameworks, MCP/A2A standards, vendors, and the security frontier](#2-the-enterprise-agent-technology-and-governance-stack-orchestration-frameworks-mcpa2a-standards-vendors-and-the-security-frontier)
- [3. The AMR IDP project and the warehouse-robotics patent landscape: built reality versus roadmap vision, and crowded versus open ground](#3-the-amr-idp-project-and-the-warehouse-robotics-patent-landscape-built-reality-versus-roadmap-vision-and-crowded-versus-open-ground)
- [4. Prior art and patentability per candidate idea: a table-led assessment of proximity, novelty, and inventive step](#4-prior-art-and-patentability-per-candidate-idea-a-table-led-assessment-of-proximity-novelty-and-inventive-step)
- [5. Filing strategy for the AMR IDP candidates: scored triage, enablement gaps, freedom-to-operate, and the narrower-mechanism hunt](#5-filing-strategy-for-the-amr-idp-candidates-scored-triage-enablement-gaps-freedom-to-operate-and-the-narrower-mechanism-hunt)
- [6. Warehouse operations: structural problems, safety and standards, and the agentic and digital-twin future](#6-warehouse-operations-structural-problems-safety-and-standards-and-the-agentic-and-digital-twin-future)
- [Conclusion](#conclusion)
- [References](#references)
- [Outstanding items](#outstanding-items)

---

## Introduction

Enterprise artificial intelligence in 2026 presents a paradox: the capability is real, the deployment is not. Genuine AI agents — systems that run an observe–plan–act loop with tools and memory, rather than replaying a fixed script — are now a stable product category ([BCG, *AI Agents*](https://www.bcg.com/capabilities/artificial-intelligence/ai-agents)). Yet McKinsey's survey of roughly 2,000 organisations finds that while 88% use AI in at least one function and 62% are experimenting with agents, only about 23% have begun scaling them and fewer than 10% have scaled in any single function ([McKinsey, *The State of AI*](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)). MIT NANDA goes further, reporting that some 95% of enterprise generative-AI pilots show no measurable P\&L impact — a contested figure, but one whose central claim, an integration "learning gap" rather than a model-quality problem, is widely echoed ([MIT NANDA via Fortune](https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/); [critique](https://cloud.tencent.com/developer/article/2652336)). The distance between the demo and durable production value is organisational and governance-shaped, not model-shaped.

This report examines that gap from two directions and argues they are the same question. The first is enterprise AI agents as a market and a technology stack: what a genuine agent is, why "agent washing" makes the market hard to read, where adoption has actually landed, and why the enabling layer — orchestration frameworks, the MCP and A2A standards, observability, identity — has matured faster than the governance around it. The second is a concrete case: an autonomous mobile robot (AMR) integration project — a Raspberry Pi control stack, a digital twin, a layered safety architecture and spatial analytics — assessed honestly against the crowded warehouse-robotics patent landscape. Both inquiries ask the same thing: not what the technology can do in a demonstration, but what survives contact with reality — production, or patent examination.

The report proceeds in six chapters. Chapters 1 and 2 cover enterprise agents — capability and measured adoption, then the technology and governance stack. Chapters 3 to 5 turn to the AMR project — the built-versus-roadmap reality and the patent terrain, a table-led prior-art and patentability assessment of each candidate idea, and filing strategy spanning triage, enablement and freedom to operate. Chapter 6 sets both streams in their operating context: the structural problems, safety standards and future of warehouse operations.

The findings are deliberately unsentimental. Adoption of enterprise agents is broad but shallow, and the binding constraint is organisational and governance-shaped. On the AMR project, the patentability verdict is negative: no candidate clearly clears the novelty-and-inventive-step bar. What makes the two threads one report is the recurring pattern — capability and realised value, and usefulness and patentability, point in different directions.

---

## 1. Enterprise AI agents: capability definition, the agent-washing credibility lens, and the measured adoption reality

**Thesis.** Enterprise AI agents are now genuinely capable and genuinely deployed — but the evidence shows adoption that is broad yet shallow. The distance between the demo and durable production value is organisational and integration-shaped, not model-shaped. Read against the market's "agent-washing" problem, the honest conclusion is that the reader should discount vendor claims while still recognising a real and growing base of measurable value.


### Evidence

**What a real agent is.** BCG defines AI agents as AI that "use tools to accomplish goals," operating an **observe–plan–act** cycle with five components: agent-centric interfaces, a memory module, a profile module, a planning module, and an action module. Crucially, they "make decisions and take actions autonomously with minimal human oversight" ([BCG, AI Agents](https://www.bcg.com/capabilities/artificial-intelligence/ai-agents)). This distinguishes them from three prior categories: a **chatbot** answers single-turn queries; a **copilot** augments a human who stays in the loop; and **RPA** executes a fixed script. The agent's defining feature is an autonomous loop of plan→tool-call→observe that adapts to process change and edge cases rather than replaying a brittle script ([Tencent Cloud](https://cloud.tencent.com/developer/article/2673695); [BCG](https://www.bcg.com/capabilities/artificial-intelligence/ai-agents)).

**The agent-washing lens.** That definition is exactly what makes the market hard to read. Gartner warns that many vendors are engaged in **"agent washing" — "the rebranding of existing products, such as AI assistants, robotic process automation (RPA) and chatbots, without substantial agentic capabilities,"** and estimates that of thousands of self-styled agentic vendors, **only about 130 are real** ([Gartner, June 2025](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)). Any adoption statistic must be read through this lens: a rising "agent" penetration number may partly reflect relabelling.

**Measured adoption.** McKinsey's *State of AI 2025* (survey of ~2,000 organisations across 105 nations, June–July 2025) found **88% of organisations use AI in at least one business function** (up 10 percentage points year-on-year) and **62% are experimenting with agentic AI** — yet only **~39% report EBIT impact** from AI, only a minority (~23%) have begun scaling agentic systems, and **in any single function fewer than 10% have scaled** ([McKinsey, The State of AI](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)). The MIT NANDA *GenAI Divide* report (150 executive interviews, a 350-employee survey, 300 public deployments) is starker: **~95% of enterprise generative-AI pilots deliver no measurable P\&L impact**, with only ~5% achieving rapid revenue acceleration. **This headline is contested, and critics argue it overstates the underlying finding.** The report's own adoption funnel runs 100% surveyed → 60% explored → 20% piloted → 5% succeeded, so the denominator is ambiguous: counting the ~40% of firms that never began as "failures" inflates the rate, and measured against those that actually explored, the success share is closer to ~8%. The report itself notes its figures are "directionally accurate" interview judgements rather than audited outcomes, and its scope is custom, task-specific internal builds — not enterprise-wide AI adoption, which is separately rising through staff use of finished tools ([Tencent Cloud critique, 2026](https://cloud.tencent.com/developer/article/2652336)). MIT attributes the shortfall not to model quality but to a **"learning gap"** — generic tools do not learn from or adapt to enterprise workflows. It also found that **buying from specialised vendors and partnering succeeds ~67% of the time, while internal builds succeed only about a third of the time (~33%)** ([Fortune/MIT NANDA, Aug 2025](https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/)).

**The pilot-to-production gap, and two competing forecasts.** Gartner's two 2025 forecasts frame it precisely: it projects **>40% of agentic AI projects will be cancelled by end-2027** due to escalating costs, unclear business value and inadequate risk controls, while simultaneously forecasting that **40% of enterprise applications will embed task-specific AI agents by end-2026, up from <5% in 2025** ([Gartner, June 2025](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027); [Gartner via InfoQ](https://xie.infoq.cn/article/ee7822ee44c184612cca93649) — the embed-by-2026 figure is **secondary-sourced** here, as the primary Gartner page was not retrievable). It is essential to label the first figure correctly: the **>40% cancellation rate is a forecast, not a measurement** — it derives from analyst judgement, not from a sampled panel of outcomes. The poll in the same release (n=3,412, a self-selected webinar audience) measured *intent* — 19% significant investment, 42% conservative, 31% wait-and-see — not results ([Kieran Gilmurray, critical reading](https://kierangilmurray.com/why-over-40-of-agentic-ai-projects-may-fail/)). The two forecasts are not contradictory: Gartner is saying most *current attempts* will fail while the *underlying capability* embeds widely.

**Autonomy vs human-in-the-loop — the Klarna arc.** Gartner's guidance is "reliability before autonomy": most agents are "not reliable enough to operate autonomously in complex or business-critical environments" and fit best where several outcomes are acceptable and error impact is contained ([Gartner, AI agent reality check](https://www.gartner.com/en/articles/ai-agent-reality-check)). Klarna is the canonical case. In February 2024 it announced an OpenAI-powered assistant that handled **two-thirds of customer-service chats in its first month** — the work of ~700 agents, cutting average resolution time from 11 minutes to under 2, and projected to save ~$40M annually ([Klarna press, Feb 2024](https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/)). By 2025 Klarna was **rehiring human agents** after quality fell on complex tickets, moving to a hybrid model ([LCB](https://lcb.org/news/klarna-reverses-course-reintroduces-human-customer-support)). The lesson is not that agents failed, but that full replacement over-reached the reliability envelope.

**Where value actually lands.** Real, quantified value clusters in structured, high-volume, fault-tolerant workflows. BCG documents: a CPG company using agents for marketing content cut **costs by 95% and improved speed 50x**; a global bank cut customer-service **costs 10x**; a biopharma firm cut lead-generation **cycle time 25%**; and an IT department raised legacy-modernisation **productivity up to 40%** ([BCG](https://www.bcg.com/capabilities/artificial-intelligence/ai-agents)). McKinsey similarly finds the strongest gains in software engineering, IT and knowledge management, with revenue impact concentrated in marketing/sales ([McKinsey](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)).

### Analysis

Three things reconcile the bullish and bearish evidence. First, the "failures" are overwhelmingly integration and change-management failures, not capability failures — MIT's "learning gap" and Gartner's "costs, unclear value, controls" both point at the organisation, not the model. Second, agent-washing inflates the apparent base of success, so headline penetration should be treated as an upper bound. Third, the value distribution is bimodal: simple, bounded, fault-tolerant tasks deliver large multiples, while cross-functional or high-risk decisions remain stuck at pilot. The reader should therefore treat "we deployed an agent" as a claim requiring evidence of a bounded scope, a measurable baseline, and a human exception path.

### Summary

Enterprise agents are real and improving, but adoption is broad and shallow. The binding constraint is organisational integration and trust, not model intelligence. Where scope is narrow and error-tolerant, the returns are already material; where scope is broad or high-stakes, the pilot-to-production gap persists. The next chapter shows that the *technology stack* underneath has consolidated far faster than the *governance* around it.

### Key findings

- A genuine agent runs an autonomous observe–plan–act loop with tools and memory, distinct from chatbots (single-turn), copilots (human-in-loop) and RPA (fixed script) ([BCG](https://www.bcg.com/capabilities/artificial-intelligence/ai-agents)).
- **Agent washing is systemic**: Gartner estimates only ~130 of thousands of self-styled agentic vendors are genuine ([Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)).
- **88%** of enterprises use AI and **62%** are experimenting with agents, but only **~39%** see EBIT impact and **<10%** have scaled agents in any one function ([McKinsey](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)).
- **~95%** of gen-AI pilots show no measurable P\&L impact — a **contested** headline that critics argue overstates the finding (ambiguous denominator; ~40% who never started counted as failures; ~8% success among those who explored; scope = custom internal builds) — attributed to an integration "learning gap," not model quality; buy/partner (~67%) beats internal build (~33%) ([MIT NANDA via Fortune](https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/); counter-analysis: [Tencent Cloud critique](https://cloud.tencent.com/developer/article/2652336)).
- Gartner's **>40% cancellation** is a *forecast*, paired with a bullish **40%-of-apps-by-2026** forecast ([Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027); [InfoQ](https://xie.infoq.cn/article/ee7822ee44c184612cca93649)).
- Klarna automated two-thirds of chats then rehired humans — the reliability-envelope lesson ([Klarna](https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/); [LCB](https://lcb.org/news/klarna-reverses-course-reintroduces-human-customer-support)).

### Data summary

| Metric                                            | Value                                | Source                                                                                                                                                                                              |
| ------------------------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Organisations using AI in ≥1 function             | 88% (2025)                           | [McKinsey](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)                                                                                                         |
| Experimenting with agentic AI                     | 62%                                  | [McKinsey](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)                                                                                                         |
| Reporting EBIT impact from AI                     | ~39%                                 | [McKinsey](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)                                                                                                         |
| Gen-AI pilots with no measurable P\&L impact      | ~95% (contested)                     | [MIT NANDA / Fortune](https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/); [counter-analysis](https://cloud.tencent.com/developer/article/2652336) |
| Buy/partner vs internal-build success             | ~67% vs ~33%                         | [MIT NANDA / Fortune](https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/)                                                                          |
| Agentic projects forecast cancelled by end-2027   | >40% (forecast)                      | [Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)                                    |
| Enterprise apps embedding task agents by end-2026 | 40%, up from <5% (secondary-sourced) | [Gartner via InfoQ](https://xie.infoq.cn/article/ee7822ee44c184612cca93649)                                                                                                                         |
| Genuine agentic vendors (est.)                    | ~130 of thousands                    | [Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)                                    |

---

## 2. The enterprise agent technology and governance stack: orchestration frameworks, MCP/A2A standards, vendors, and the security frontier

**Thesis.** The enabling layer for enterprise agents has consolidated remarkably quickly — frameworks have stabilised, and two open protocols (MCP and A2A) have become vendor-neutral standards under the Linux Foundation. But this stack has matured faster than the governance around it. The most likely cause of the next wave of enterprise-agent failures is not model capability but **identity and accountability** — who an autonomous agent is, what it is permitted to do, and who answers when it acts wrongly.

### Evidence

**Orchestration frameworks have stabilised.** After two years of proliferation, the developer landscape has clustered. **LangGraph** dominates graph-based, stateful workflows; **CrewAI** leads role-based multi-agent collaboration; and Microsoft's **AutoGen + Semantic Kernel** are converging into a single **Microsoft Agent Framework**. Alongside these sit LlamaIndex Workflows, Google's **ADK**, PydanticAI and Smolagents ([CNBlogs framework survey](https://www.cnblogs.com/hanjg/p/19545638)). The commercial significance is consolidation: buyers now face a small number of durable platforms rather than dozens of experimental libraries.

**Interoperability protocols are the headline architectural shift.** Two open standards define how agents connect. **MCP (Model Context Protocol)**, introduced by Anthropic in November 2024, became the de-facto interface for connecting models to tools and data; on **9 December 2025** it was **donated to the Linux Foundation's new Agentic AI Foundation (AAIF)**, alongside Block's *goose* framework and OpenAI's *AGENTS.md* format ([Linux Foundation, AAIF](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)). **A2A (Agent2Agent)**, launched by Google in April 2025 with 100+ technology partners, standardises agent-to-agent communication and was **donated to the Linux Foundation in June 2025** ([Linux Foundation, A2A](https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project-to-enable-secure-intelligent-communication-between-ai-agents); [Google Developers Blog](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)). The commercial point is portability: because MCP and A2A are vendor-neutral, an enterprise can mix agents from Microsoft, Google, Salesforce and SAP without being locked to one vendor's runtime — which is precisely why rival vendors co-sponsor them.

**Observability and evaluation.** You cannot govern what you cannot see. The observability market has converged on tracing-plus-evaluation platforms — **LangSmith** (deep LangChain/LangGraph integration), **Langfuse** (open-source, self-hostable), and **Arize Phoenix** (OpenTelemetry/OpenInference-based) — which record nested spans across agents, retrievers and tools and attach eval scores to production traffic ([Langfuse](https://langfuse.com/); [Arize Phoenix](https://phoenix.arize.com/)). Academic work is building the evaluation substrate: **REALM-Bench** benchmarks multi-agent planning and scheduling ([arXiv](https://arxiv.org/html/2502.18836v2)); **IntellAgent** evaluates tool-augmented conversational agents ([arXiv](https://arxiv.org/pdf/2501.11067.pdf)); and an **ICML 2025 Spotlight** paper on automated failure attribution found that even the best method identified the failure-responsible agent only **53.5%** of the time and the decisive failure step just **14.2%** — with some methods below random, and frontier reasoning models (o1, DeepSeek R1) "fail[ing] to achieve practical usability" ([Zhang et al., ICML 2025](https://arxiv.org/abs/2505.00212)). That is a hard, quantified ceiling on how well anyone can currently debug a multi-agent system.

**Vendors and market.** The platform field is crowded and each player is betting differently: **Microsoft** on a governance "control plane" (Agent 365), the Agent Framework, and Foundry Agent Service with multi-agent workflows and persistent memory ([Microsoft 365 Dev Blog](https://devblogs.microsoft.com/microsoft365dev/ignite-2025-a-developers-guide-to-building-agents-for-microsoft-365/)); **Google** on Gemini Enterprise plus A2A and ADK; **Salesforce** on Agentforce; **ServiceNow** on its AI Agent Control Tower; **Anthropic** on the Claude Agent SDK and MCP; **OpenAI** on its Agents SDK (March 2025, successor to the experimental Swarm) ([Tencent Cloud](https://cloud.tencent.com/developer/news/2302074)); plus **AWS** (Bedrock agents), **SAP** (Joule), **IBM** (watsonx Orchestrate) and **NVIDIA**, which is betting on the compute and orchestration layer with its agent toolkit and AI-Q blueprint ([NVIDIA](https://www.nvidia.com/en-us/ai/)). Market sizing is aggressive and should be treated with caution: MarketsandMarkets projects the AI-agents market at **$5.26B (2024) → $52.62B (2030), ~46.3% CAGR** ([MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html)) — a figure that is vendor-adjacent and should be read as an optimistic scenario, not a settled number.

**The security and governance frontier.** Because agents act, their attack surface is larger than a chatbot's. Prompt injection, and **MCP-specific vulnerabilities**, are documented CISO concerns as MCP proliferates ([eSentire](https://www.esentire.com/blog/model-context-protocol-security-critical-vulnerabilities-every-ciso-should-address-in-2025)). The deeper structural problem is **non-human identity (NHI)** governance: non-human identities already outnumber human ones by roughly **50:1** in enterprises, and each agent is effectively a new identity with access permissions ([Vectra](https://www.vectra.ai/topics/agentic-ai-security)). Gartner formalises this: it predicts that **through 2028 more than 50% of AI initiatives will halt because of unresolved agentic identity challenges**, and stresses that agents "are not legal entities and cannot be held responsible" — accountability stays with humans ([Gartner, AI agent reality check](https://www.gartner.com/en/articles/ai-agent-reality-check)).

### Analysis

The stack is converging on a familiar enterprise pattern: open standards at the connection layer (MCP, A2A), a handful of competing runtimes above them, and a specialised observability tier. Standardisation reduces lock-in and accelerates adoption — but it also standardises the attack surface, which is why MCP vulnerabilities and NHI governance matter. The pivotal asymmetry is that *capability* is improving on a quarterly cadence while *governance* (identity, permissions, accountability, auditability) is improving on a yearly one. Gartner's ">50% of initiatives halt by 2028" and the ICML paper's 14.2% failure-step attribution accuracy point at the same conclusion: the binding constraint on scale is trust infrastructure, not model intelligence.

### Summary

Enterprise agents now sit on a consolidated, standards-based stack — LangGraph/CrewAI/Microsoft Agent Framework for orchestration; MCP and A2A for interoperability; LangSmith/Langfuse/Phoenix for observability; and a crowded vendor field led by Microsoft, Google, Salesforce, ServiceNow, Anthropic and OpenAI. The weak layer is governance. Identity and accountability — not capability — are the most probable cause of the next wave of enterprise-agent failures, and any responsible deployment plan must solve for them before granting agents more autonomy.

### Key findings

- Orchestration has consolidated around **LangGraph, CrewAI and the Microsoft Agent Framework** ([CNBlogs](https://www.cnblogs.com/hanjg/p/19545638)).
- **MCP was donated to the Linux Foundation's AAIF on 9 Dec 2025**; **A2A was donated in June 2025** — making tool-access and agent-to-agent communication vendor-neutral ([Linux Foundation AAIF](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation); [Linux Foundation A2A](https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project-to-enable-secure-intelligent-communication-between-ai-agents)).
- Observability has converged on **LangSmith / Langfuse / Arize Phoenix** ([Langfuse](https://langfuse.com/); [Arize Phoenix](https://phoenix.arize.com/)).
- The best automated failure attribution identifies the responsible agent only **53.5%** and the failure step **14.2%** of the time ([ICML 2025](https://arxiv.org/abs/2505.00212)).
- Market sizing ($5.26B→$52.62B, ~46.3% CAGR) is **vendor-adjacent and optimistic** ([MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html)).
- **NHIs outnumber humans ~50:1**; Gartner predicts **>50% of AI initiatives halt by 2028** over agentic identity/accountability ([Vectra](https://www.vectra.ai/topics/agentic-ai-security); [Gartner](https://www.gartner.com/en/articles/ai-agent-reality-check)).

### Data summary

| Metric                                             | Value                              | Source                                                                                                                                                                            |
| -------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MCP donation to Linux Foundation (AAIF)            | 9 Dec 2025                         | [Linux Foundation](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)                                                   |
| A2A launch / donation                              | Apr 2025 / Jun 2025, 100+ partners | [Linux Foundation](https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project-to-enable-secure-intelligent-communication-between-ai-agents) |
| Failure-attribution accuracy (agent / step)        | 53.5% / 14.2%                      | [ICML 2025](https://arxiv.org/abs/2505.00212)                                                                                                                                     |
| AI-agents market (2024→2030)                       | $5.26B → $52.62B, ~46.3% CAGR      | [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html)                                                                              |
| Non-human vs human identities                      | ~50:1                              | [Vectra](https://www.vectra.ai/topics/agentic-ai-security)                                                                                                                        |
| AI initiatives forecast to halt by 2028 (identity) | >50%                               | [Gartner](https://www.gartner.com/en/articles/ai-agent-reality-check)                                                                                                             |

---

## 3. The AMR IDP project and the warehouse-robotics patent landscape: built reality versus roadmap vision, and crowded versus open ground

**Thesis.** The AMR IDP is a genuine, well-tested software system — and, on the evidence, it sits squarely inside patent art that is crowded and standards-governed. This chapter establishes two things the rest of the report depends on: first, exactly what is *built* versus what is only *roadmap*; second, the patent terrain the built system occupies. The honest question that Chapter 4 then answers is narrow: does anything inside this integration survive?

### 1. Built reality, stated separately from roadmap vision

**What is built and tested.** A Raspberry Pi 5 Python control stack of **21,752 LOC across 19 packages**, backed by **1,618 passing tests** and a 6,622-line Flutter client, plus a hand-written WebGL operator console served from the same Python process. Its five load-bearing pieces are:

1. **A layered safety design.** Layer 1 runs on the Arduino (a 1000 ms communication watchdog plus an ultrasonic proximity stop); Layer 2 is the Pi-side `RobotState`; Layer 3 is the Pi `SafetyManager` (`PROCEED/WAIT/STOP`, with `TURN/REPLAN` reserved); Layer 3.5 is the `HazardManager` (`NORMAL→WARNING→SLOW→STOP→EMERGENCY`, worst-wins, latched emergency, escalate-only).
2. **A read-only 3D digital twin** (`map/twin.py`) fed from the *same* `MapSnapshot` the 2D map renders, so the two views "cannot disagree."
3. **An ops projection** (`telemetry/ops.py`) that publishes categorical `health.counts` and a `risk_frequency` histogram rather than a fabricated composite score.
4. **A dual heatmap** (`map/heatmap.py`): a severity-weighted hazard grid plus a traffic grid over one shared extent.
5. **A mock/simulation-first bring-up** — the whole robot runs in-process.

**What is roadmap only.** The chassis, motors, ultrasonic ring, RFID, gas/fire sensors, manipulator (`implemented:false`), vision ML, and any safety certification. Geometry is `null`; safety thresholds are `NOT_VERIFIED`.

**Why the mock-mode fact is load-bearing for patentability.** The entire system runs in **`--mock` mode**: commands are accepted and telemetry generated, but nothing reaches hardware. This matters because a patent must describe an *enabled* invention — an apparatus or method that a skilled person can make and use. A control stack that has never actuated a physical robot is, at best, an enabling description of *software*, and its safety claims rest on unvalidated test values.

### 2. The crowded patent terrain

Live Google Patents queries (2026-10-13) show saturation across every functional area the project touches:

| Functional area                    | Approx. hits | Representative holders                                                                                                                                              |
| ---------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Navigation / SLAM                  | ~32,000      | [US11752627B2 (Vecna)](https://patents.google.com/patent/US11752627B2/en), [US9463927B1 (Vecna)](https://patents.google.com/patent/US9463927B1/en)                  |
| Obstacle avoidance / sensor fusion | ~112,000     | [WO2023109281A1 (ForwardX)](https://patents.google.com/patent/WO2023109281A1/en), [EP4572923A1 (Boston Dynamics)](https://patents.google.com/patent/EP4572923A1/en) |
| Task allocation / fleet            | ~23,000      | [CN109117999B (Geek+)](https://patents.google.com/patent/CN109117999B/en), [US20240174445A1 (Dematic)](https://patents.google.com/patent/US20240174445A1/en)        |
| Safety / e-stop                    | ~74,000      | [EP4572923A1 (Boston Dynamics)](https://patents.google.com/patent/EP4572923A1/en), [US10684623B2 (Simbe)](https://patents.google.com/patent/US10684623B2/en)        |

The deep-portfolio holders are **Amazon Technologies** ([US9637310B1](https://patents.google.com/patent/US9637310B1/en)), **Vecna**, **Locus Robotics** ([US10513033B2](https://patents.google.com/patent/US10513033B2/en), [AU2023210596A1](https://patents.google.com/patent/AU2023210596A1/en)), **Fetch/Zebra** ([US20210018912A1](https://patents.google.com/patent/US20210018912A1/en), [US20220411188A1](https://patents.google.com/patent/US20220411188A1/en)), **Geek+** — reported as the #1 global AMR vendor by 2024 revenue in Interact Analysis' 2025 Mobile Robot Market Report, as reported by Chinese financial media ([CNFOL, reporting on the Interact Analysis 2025 ranking](http://hy.stock.cnfol.com/dianzixinxijishu/20251208/31849869.shtml); independently corroborated by [Jiemian News](https://www.jiemian.com/article/12945634.html)) — plus **Dematic**, **Invia** ([US11049067B2](https://patents.google.com/patent/US11049067B2/en)), **Ocado** ([CN106662874B](https://patents.google.com/patent/CN106662874B/en)), **ForwardX**, **Boston Dynamics**, and **Simbe**. On the standards side, AMR safety is governed by [ISO 3691-4:2023](https://www.iso.org/standard/83545.html) for driverless industrial trucks, with required performance levels assigned via [ISO 13849-1:2023](https://www.csagroup.org/store/product/iso_073481/).

### 3. The least-crowded niches — and the candidate mechanisms

Two areas are less saturated: **operator-facing telemetry presentation** and **dual-heatmap situational awareness**. But both lean toward *presentation-layer / algorithmic-output* subject matter, which faces serious patentable-subject-matter risk. This is the tension Chapter 4 must resolve.

The five candidate mechanisms the report assesses:

- **(A) Layered safety architecture** — Arduino watchdog + proximity stop, Pi `SafetyManager`, and `HazardManager` escalation.
- **(B) 3D digital twin from a telemetry payload** — read-only, raw WebGL, derived from `MapSnapshot`.
- **(C) Ops projection refusing a fabricated health score** — categorical counts, never a percentage.
- **(D) Mock-mode / simulation-first bring-up** — the whole stack runs in-process.
- **(E) Hazard/heatmap fusion** — severity-weighted hazard grid + traffic grid on one extent.

They are presented neutrally here; Chapter 4 judges each.

### Analysis

The project's real strength is **integration and rigour**, not a single novel mechanism. It couples safety layering, a digital twin, an honest telemetry projection, and spatial analytics into one coherent, heavily-tested stack — and it is unusually honest about what it does not know. But integration quality is not the same as patentability: each constituent idea already lives in crowded, standards-governed art, and the parts that are least crowded (presentation) are the parts least amenable to patent claims. The market context reinforces the "crowded" reading: warehouse automation is a large, mature field where AMRs are an established product category ([IFR](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1); [Industry 4.1](https://www.industry4-1.com/article/quick-hits-warehouse-automations-growing-painsfleet-bottlenecks-rising-costs-and-the-roi-reckoning-accelerating)).

### Summary

The AMR IDP is a strong, well-tested integration running entirely in mock mode. It sits inside a heavily patented, ISO-governed domain. Only two niches are meaningfully less crowded — telemetry presentation and heatmap analytics — and both carry subject-matter risk. Chapter 4 now tests whether any *narrow* mechanism inside the built code clears the bar.

### Key findings

- The system is **built and tested but never actuated** — mock mode is the honest boundary, and it constrains any patent's enabling disclosure.
- Every functional area the project touches is **crowded**: navigation (~32k), avoidance/fusion (~112k), tasking (~23k), safety (~74k) patent families.
- **Deep portfolios** (Amazon, Vecna, Locus, Fetch/Zebra, Geek+, Dematic, Invia, Ocado, ForwardX, Boston Dynamics, Simbe) cover the same ground.
- The **least-crowded niches are presentation-layer**, which carries non-patentable-subject-matter risk.
- **ISO 3691-4:2023 + ISO 13849-1:2023** define the safety baseline, so safety architecture is a compliance question as much as an IP one.

### Data summary

| Dimension                        | Value                                           | Source                                                                                                                                |
| -------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Built software size              | 21,752 LOC / 19 packages / 1,618 tests          | Project `PROJECT_STATE.md`                                                                                                            |
| Hardware status                  | Mock mode; Arduino/motors/sensors not connected | Project `PROJECT_STATE.md`                                                                                                            |
| Navigation/SLAM patent families  | ~32,000                                         | Google Patents query                                                                                                                  |
| Avoidance/sensor-fusion families | ~112,000                                        | Google Patents query                                                                                                                  |
| Task-allocation families         | ~23,000                                         | Google Patents query                                                                                                                  |
| Safety/e-stop families           | ~74,000                                         | Google Patents query                                                                                                                  |
| Core safety standard             | ISO 3691-4:2023 (ed. 2, under revision)         | [ISO](https://www.iso.org/standard/83545.html)                                                                                        |
| Global AMR #1 by 2024 revenue    | Geek+ (via Interact Analysis 2025)              | [CNFOL](http://hy.stock.cnfol.com/dianzixinxijishu/20251208/31849869.shtml); [Jiemian](https://www.jiemian.com/article/12945634.html) |

---

## 4. Prior art and patentability per candidate idea: a table-led assessment of proximity, novelty, and inventive step

**Thesis.** Judged narrowly and honestly, **none of the project's candidate ideas clearly clears the novelty-and-inventive-step bar**, and a deliberate hunt through the actual implementation for *narrower* mechanisms — which is what patentable inventions usually are — found candidates that are more specific but still sit inside established art. This chapter judges only; filing strategy is Chapter 5's remit. This is **not legal advice**; a full freedom-to-operate (FTO) search would be required before any filing.

### The patent landscape table

| Idea / contribution                                                                                           | Novelty rationale                                                                      | Relevant prior art / papers                                                                                                                                                                                                                                                                                              | Patentability assessment                                                                                 | Key differentiators                                                                      |
| ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **A. Layered safety architecture** (Arduino watchdog + proximity stop → Pi `SafetyManager` → `HazardManager`) | Independent lower layer that fails safe; escalate-only ladder with a latched emergency | [ISO 3691-4:2023](https://www.iso.org/standard/83545.html); [ISO 13849-1:2023](https://www.csagroup.org/store/product/iso_073481/); [EP4572923A1 (Boston Dynamics)](https://patents.google.com/patent/EP4572923A1/en)                                                                                                    | **Likely anticipated.** Standard functional-safety practice; compliance-grade, not novel                 | Two-processor split; worst-wins; latched EMERGENCY — all textbook                        |
| **B. 3D digital twin from telemetry** (read-only, raw WebGL, one `MapSnapshot`)                               | 2D map and 3D twin share one source of truth so they cannot disagree                   | [US12561660B2](https://patents.google.com/patent/US12561660B2/en); [US11396100B2 (FANUC)](https://patents.google.com/patent/US11396100B2/en); [NVIDIA Omniverse/Isaac](https://www.nvidia.com/en-us/use-cases/ai-for-virtual-factory-solutions/); [Schaeffler DT](https://www.nvidia.com/en-eu/case-studies/schaeffler/) | **High proximity.** Patented and commercial; raw-WebGL/zero-dependency is a preference, not an invention | "Single-source view" is an architecture pattern, generally non-patentable subject matter |
| **C. Ops projection refusing a fabricated health score**                                                      | Categorical `health.counts` + `risk_frequency` instead of a composite percentage       | Observability/data-integrity practice; no technical mechanism found (search scope: `telemetry/ops.py`, Google Patents, 2026-10-13)                                                                                                                                                                                       | **Not patentable subject matter.** A design principle, not a mechanism — and not novel as a principle    | Honesty rule is adoptable by anyone; weak as an IP differentiator                        |
| **D. Mock-mode / simulation-first bring-up**                                                                  | Full stack runs against in-process mocks before hardware                               | [ScienceDirect HIL](https://www.sciencedirect.com/topics/computer-science/hardware-in-the-loop-simulation); [OPAL-RT SIL](https://www.opal-rt.com/software-in-the-loop/); NVIDIA "simulation-first" at Schaeffler                                                                                                        | **No novelty.** Established SIL/HIL methodology, long predating the project                              | None identified                                                                          |
| **E. Hazard/heatmap fusion** (severity-weighted hazard grid + traffic grid, one extent)                       | Two density grids on one shared extent, hazard weighted by severity                    | [US10684623B2 (Simbe)](https://patents.google.com/patent/US10684623B2/en); heatmaps as grid-based density plots ([Atlassian guide](https://www.atlassian.com/ko/data/charts/heatmap-complete-guide)); [CN119960436B](https://patents.google.com/patent/CN119960436B/zh)                                                  | **Moderate-to-high proximity.** Any novelty extremely narrow and presentation-layer                      | Shared-extent dual grid; severity weighting — presentation choices                       |


### New roadmap concepts (G–K)

The five ideas below are **user-requested roadmap concepts, not implemented features**. Unlike candidates A–F, which exist in the project's code (though unvalidated on hardware), G–K exist only as intent — the project implements none of them today. This distinction matters for patentability, because a patent requires an *enabled* invention: an A–F idea at least has a working embodiment, whereas a G–K idea is presently only a direction. Every one of the five lands in occupied ground; none is open. Ranked by patentability headroom for a small independent build, the order is **J > H ≈ I > G ≈ K**. The two most crowded are **G** (a mature commercial category sitting on a dense patent thicket) and **K** (sitting inside an enormous predictive-maintenance and inspection-robot art field). Only **J** shows a plausible narrow angle.

| Idea / contribution                                                                                                                                                                                                                                                                             | Novelty rationale                                                                                                           | Relevant prior art / papers                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Patentability assessment                                                                                                                                                                                                  | Key differentiators                                                                                                                                                                                                                                  |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **G** — AMR automated inventory cycle counting / stock scanning *(roadmap-only)*: robot traverses aisles and scans shelf/pallet contents (barcode/QR/RFID/vision) to count stock and flag discrepancies, replacing or supplementing manual cycle counts.                                        | Robot-mediated autonomous stock counting with discrepancy flagging — conceptually a retail/warehouse inventory-audit robot. | Simbe [US10467587B2](https://patents.google.com/patent/US10467587B2/en), [US11593755B2](https://patents.google.com/patent/US11593755B2/en), [JP6925443B2](https://patents.google.com/patent/JP6925443B2/en), [US20260148186A1](https://patents.google.com/patent/US20260148186A1/en), [US11200537B2](https://patents.google.com/patent/US11200537B2/en), [US20210357851A1](https://patents.google.com/patent/US20210357851A1/en); Walmart [US20180247264A1](https://patents.google.com/patent/US20180247264A1/en), [US20190236530A1](https://patents.google.com/patent/US20190236530A1/en), [US11443276B2](https://patents.google.com/patent/US11443276B2/en); Sensormatic [US11763249B2](https://patents.google.com/patent/US11763249B2/en); IAM [US11348066B2](https://patents.google.com/patent/US11348066B2/en); Invia [US10466713B2](https://patents.google.com/patent/US10466713B2/en); B GARAGE [KR20230066323A](https://patents.google.com/patent/KR20230066323A/en); [WareVR (arXiv:2110.11052)](https://arxiv.org/abs/2110.11052). | **Layer: roadmap-only** (intent only — no code, no enabled embodiment; contrast A–F, implemented in code though unvalidated on hardware). **Extremely crowded** — mature commercial category with a dense patent thicket. | Little residual space. Incumbents already ship this — Simbe, Bossa Nova, Corvus, Verity, Gather AI, Dexory, Infinium, B GARAGE. Only a very narrow, implementation-specific improvement could be novel, and even that faces strong obviousness risk. |
| **H** — Real-time inventory DB reconciliation from robot scans *(roadmap-only)*: scan results continuously reconciled against a WMS/ERP, with discrepancy detection, exception routing and an auditable sync path.                                                                              | Continuous robot-scan → system-of-record reconciliation with exception routing and an audit trail.                          | Simbe [US20260148186A1](https://patents.google.com/patent/US20260148186A1/en) (perpetual inventory), [US20210357851A1](https://patents.google.com/patent/US20210357851A1/en); Locus [AU2018366020C1](https://patents.google.com/patent/AU2018366020C1/en) (WMS order coordination); incumbent WMS/ERP — SAP EWM, Manhattan, Blue Yonder ([overview](https://baijiahao.baidu.com/s?id=1860081849819193200)); [LeverX on SAP EWM + robotics](http://leverx.com/newsroom/sap-ewm-and-robotics).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | **Layer: roadmap-only** (intent only — no code, no enabled embodiment; contrast A–F). **Crowded** — largely standard WMS/ERP functionality plus extensions of the G patents.                                              | Narrow sliver only: a specific reconciliation / exception-routing mechanism (e.g. a particular auditable conflict-resolution path), not the concept itself.                                                                                          |
| **I** — Stock planning / replenishment from live inventory *(roadmap-only)*: the robot-maintained live inventory position drives reorder points, replenishment planning and demand-driven stocking.                                                                                             | Live (robot-maintained) inventory position used as the trigger for replenishment decisioning.                               | Reorder-point/auto-replenishment is long-standing practice ([NetSuite](https://www.netsuite.com/portal/resource/articles/inventory-management/inventory-replenishment.shtml); [ShipBob](https://www.shipbob.com/uk/blog/auto-replenishment/)); vendors [RELEX](https://www.relexsolutions.com/resources/unlocking-retail-efficiency-how-ai-reduces-cost-of-shelving/), [Flexport](https://www.flexport.com/products/replenishment/); shelf-visibility→replenishment already shipped by [Focal Systems](https://focal.systems/) (fixed cameras) and [Simbe Store Intelligence](https://www.simberobotics.com/) (robot data); Walmart [US11443276B2](https://patents.google.com/patent/US11443276B2/en).                                                                                                                                                                                                                                                                                                                                       | **Layer: roadmap-only** (intent only — no code, no enabled embodiment; contrast A–F). **Crowded** — replenishment decisioning is a mature ERP/supply-chain field.                                                         | Only arguably-new sliver is "reorder triggered specifically by robot-maintained live inventory," closely approached by Simbe and Focal.                                                                                                              |
| **J** — Cold-chain delivery with temperature monitoring and chain-of-custody *(roadmap-only)*: AMR transports temperature-sensitive goods while continuously monitoring temperature and maintaining a verifiable pick-to-drop custody record.                                                   | Active temperature-controlled AMR transport inside a warehouse combined with an auditable chain-of-custody record.          | [US20220004979A1 — "Autonomous Mobile Delivery Robot And Chain Of Custody System" (**assignee unverified**; inventors Allen/Melanson confirmed)](https://patents.google.com/patent/US20220004979A1/en); cold-chain art [CN120013403B](https://patents.google.com/patent/CN120013403B/en), [CN108502431B](https://patents.google.com/patent/CN108502431B/en), [CN106292461B](https://patents.google.com/patent/CN106292461B/en), [CN118278949B](https://patents.google.com/patent/CN118278949B/en), Trumed [US20240140709A1](https://patents.google.com/patent/US20240140709A1/en); incumbents [Sensitech](https://www.linkedin.com/company/sensitech/), [Tive](https://www.linkedin.com/company/tiveinc), [Emerson](https://b2b.baidu.com/slist/aca4acbbbaa6a7e9037c0378070b7f011e7e1e101b0e), [Thermo King](https://europe.thermoking.com/technologies).                                                                                                                                                                                    | **Layer: roadmap-only** (intent only — no code, no enabled embodiment; contrast A–F). **Moderate — least crowded of the five, but not open** (direct prior art exists: US20220004979A1).                                  | Defensible narrow angle: *active* temperature-controlled transport **inside a warehouse** with an auditable pick-to-drop custody record — narrower than the generic cold-chain monitoring art.                                                       |
| **K** — Warehouse equipment health monitoring by a mobile robot *(roadmap-only)*: AMR patrols and monitors health of warehouse equipment/infrastructure (conveyors, racking, doors, HVAC, other robots) via thermal/acoustic/vibration/vision sensing, feeding a predictive-maintenance signal. | One warehouse AMR acting as a mobile condition-monitoring platform for other warehouse assets.                              | Rdi Technologies [US11861820B1](https://patents.google.com/patent/US11861820B1/en) (very close — mobile unit doing repetitive equipment video monitoring); [WO2022131388A1](https://patents.google.com/patent/WO2022131388A1/en); Brooks [US9104650B2](https://patents.google.com/patent/US9104650B2/en); Intel [US10695907B2](https://patents.google.com/patent/US10695907B2/en); [CN112099448B](https://patents.google.com/patent/CN112099448B/en); IEEE [CASE 2024](https://eprints.whiterose.ac.uk/213611/), [DDCLS 2024](https://ieeexplore.ieee.org/document/10606581); PdM incumbents [Siemens Senseye](https://resources.sw.siemens.com/en-US/brochure-enabling-pm-through-industrial-connectivity/), [SKF](https://www.skf.com/id/products/condition-monitoring-systems), [Augury](https://baike.baidu.com/item/Augury/62905207).                                                                                                                                                                                                   | **Layer: roadmap-only** (intent only — no code, no enabled embodiment; contrast A–F). **Very crowded** — PdM is enormous and mobile inspection robots are already a category.                                             | Only narrow sliver: a single warehouse AMR monitoring *other warehouse assets* specifically; conceptually adjacent to a large body of inspection-robot art, so broad claims are unrealistic.                                                         |

### The hunt for narrower mechanisms (candidate F)

Patentable inventions are typically **narrow and specific**. Reading the implementation (`safety/safety_manager.py`, `safety/avoidance.py`, `hazard/manager.py`, `map/heatmap.py`, `map/twin.py`, `telemetry/ops.py`) surfaces three concrete mechanisms that are more specific than the broad concepts — and each is still judged candidly:

**F1 — In-place hazard-event correlation with an independent safety latch.** In `hazard/manager.py`, every hazard above `INFO` is recorded as **one event keyed by `kind:source`**, which *escalates in place* (`WARNING→CRITICAL`) rather than spawning a new event each control-loop tick; events never silently downgrade, and are resolved (with `cleared_at`/`duration_s`) when the reading disappears. Separately, an `EMERGENCY` **latches independently of event resolution**, and release is deliberately **two-step** (`hazard.acknowledge()` then `robot.request_mode(IDLE)`).  
*Proximity:* **High.** Event correlation/deduplication with severity escalation is long-established in alarm management (e.g. the [Simple Event Correlator](https://www.cs.umb.edu/~rouilj/sec/sec_paper.pdf)); independent latches with explicit operator reset are standard safety-interlock practice. The *combination* is specific but each half is old.

**F2 — A spatial heatmap built for temporal comparability.** In `map/heatmap.py`, the grid extent is the **configured geometry, not the data extent** (snapped outwards to whole cells), deliberately excluding the moving robot/goal/hazards so successive polls are *comparable with themselves*; out-of-extent samples are **counted in `clipped`**, and image-space-only hazards are counted in `unlocated` and **never placed** — while a severity-weighted hazard grid and a time-based ("sampling rate is the clock, not the odometer") traffic grid share one extent.  
*Proximity:* **Moderate.** This is the most concrete technical effect found (a stable frame enabling change-over-time comparison). But fixed-extent grids and clipped-sample accounting are known in analytics/GIS, and the mechanism is largely presentation-layer.

**F3 — Provably non-actuating presentation components.** The twin, heatmap, and console are enforced read-only by **static source inspection**: tests grep the modules for `RobotManager`/`Navigator`/`serial`/`gpio`/`pwm` and the JS for `estop(`/`forward(`/`"/command"`, failing the build if an actuation path appears.  
*Proximity:* **High / not patentable.** Static-analysis-enforced architectural isolation is a software-engineering practice; static analysis itself is decades old.

**Verdict on F:** the narrower mechanisms are real and specific, but none clearly clears the bar — F1 and F3 are close to established art, and F2, though the most promising, is still largely presentation-layer with only a narrow, hard-to-claim technical effect. **What would have to be different for protectability:** a mechanism that produces a **concrete technical improvement** (not a presentation choice) — e.g. a closed-loop control method with a measured effect on the robot's physical behaviour, validated on hardware, rather than a data-derivation or display rule. That is precisely what mock mode cannot yet supply.

### Analysis

The pattern is consistent: the project's ideas are **broad concepts living in crowded art**, and its narrower mechanisms, while more specific, are either (i) recombinations of established techniques (F1, F3) or (ii) presentation-layer with weak subject matter (F2). This is not a criticism of the engineering — it is the normal outcome for a well-built integration of mature components. The most defensible *technical* angle is F2's comparability mechanism, and even that would need a demonstrable technical effect to survive examination.

### Summary

A — anticipated. B — high proximity. C — non-patentable subject matter. D — no novelty. E — moderate-to-high proximity. G–K — all occupied, ranked J > H ≈ I > G ≈ K. F1/F2/F3 — narrow but still crowded or presentation-layer. **No candidate clearly clears the bar.** This is a candid negative finding, and the report presents it as such; where the verdict is negative, the constructive path is to specify what a protectable mechanism would require — the subject of Chapter 5.

### Key findings

- **A** is compliance-grade functional safety, anticipated by [ISO 3691-4:2023](https://www.iso.org/standard/83545.html)/[ISO 13849-1:2023](https://www.csagroup.org/store/product/iso_073481/) practice.
- **B** faces direct prior art: [US12561660B2](https://patents.google.com/patent/US12561660B2/en) and [US11396100B2](https://patents.google.com/patent/US11396100B2/en).
- **C** and **D** are a principle and an established methodology — not patentable subject matter.
- **E** is presentation-layer with moderate-to-high proximity ([US10684623B2](https://patents.google.com/patent/US10684623B2/en)).
- **G–K** all land in occupied ground; **J** is the least crowded, **G** and **K** the most.
- **F1/F2/F3** — the narrowest mechanisms found — are still crowded (event correlation, static analysis) or presentation-layer (comparability heatmap).
- A protectable idea would need a **hardware-validated, closed-loop technical effect**, which mock mode cannot supply; a real **FTO search** is required before any filing.

### Data summary

| Candidate                                | Closest prior art                                     | Proximity     | Verdict                       |
| ---------------------------------------- | ----------------------------------------------------- | ------------- | ----------------------------- |
| A. Layered safety                        | ISO 3691-4:2023 / ISO 13849-1:2023; EP4572923A1       | High          | Likely anticipated            |
| B. 3D digital twin                       | US12561660B2; US11396100B2; NVIDIA Omniverse/Isaac    | High          | Not novel                     |
| C. No-score ops projection               | (no technical mechanism found)                        | N/A           | Not patentable subject matter |
| D. Mock/sim-first bring-up               | ScienceDirect HIL; OPAL-RT SIL                        | Very high     | No novelty                    |
| E. Hazard/heatmap fusion                 | US10684623B2; CN119960436B; heatmap art               | Moderate–high | Narrow / presentation-layer   |
| F1. In-place event correlation + latch   | Simple Event Correlator; safety-interlock practice    | High          | Established art               |
| F2. Comparable-extent heatmap            | Fixed-extent/grid analytics art                       | Moderate      | Weak, presentation-layer      |
| F3. Static-analysis capability isolation | Static-analysis / architectural-enforcement practice  | High          | Not patentable                |
| G. Inventory cycle counting              | Simbe family; Walmart; Sensormatic                    | Extreme       | Extremely crowded             |
| H. Inventory DB reconciliation           | Simbe US20260148186A1; Locus AU2018366020C1           | High          | Crowded                       |
| I. Stock planning / replenishment        | NetSuite; Focal Systems; Walmart US11443276B2         | High          | Crowded                       |
| J. Cold-chain + custody                  | US20220004979A1 (assignee unverified); cold-chain art | Moderate      | Least crowded, not open       |
| K. Equipment health monitoring           | Rdi US11861820B1; PdM incumbents                      | Very high     | Very crowded                  |

---

## 5. Filing strategy for the AMR IDP candidates: scored triage, enablement gaps, freedom-to-operate, and the narrower-mechanism hunt

**Thesis.** Chapter 4 judged the prior art. The reviewer has now **scored all thirteen candidates** on three axes, and five new roadmap concepts (**G–K**) have been added — none implemented, all landing in occupied ground. This chapter turns that into a decision: what to *file*, what to *publish defensively*, and what to simply *build*. The single most decision-relevant finding is a **trade-off the user must see clearly: the ideas worth the most to the project are the least patentable, and the most patentable are the least useful.** This chapter is **not legal advice**; a registered patent attorney should be engaged before any filing.

### 1. The scored assessment

Every candidate was scored 0–10 on patentability, novelty and usefulness, then combined with a deliberate weighting: **usefulness 50% / novelty 25% / patentability 25%.** The rationale: a patent a small independent developer cannot afford to enforce has little value, so usefulness dominates — but novelty is kept as a separate axis because it drives both patentability and differentiation.

| ID     | Idea                                                  | Patentability /10 | Novelty /10 | Usefulness /10 | Composite |
| ------ | ----------------------------------------------------- | ----------------- | ----------- | -------------- | --------- |
| A      | Layered safety architecture                           | 1                 | 1           | 6              | 3.50      |
| B      | 3D digital twin from telemetry                        | 1                 | 2           | 5              | 3.25      |
| C      | Ops projection refusing a fabricated health score     | 1                 | 3           | 5              | 3.50      |
| D      | Mock-mode / simulation-first bring-up                 | 0                 | 0           | 7              | 3.50      |
| E      | Hazard/heatmap fusion                                 | 2                 | 3           | 5              | 3.75      |
| F1     | In-place hazard-event correlation + independent latch | 2                 | 3           | 5              | 3.75      |
| **F2** | **Heatmap built for temporal comparability**          | **4**             | **5**       | **4**          | **4.25**  |
| F3     | Provably non-actuating presentation components        | 1                 | 2           | 5              | 3.25      |
| G      | AMR inventory cycle counting / stock scanning         | 1                 | 1           | 9              | 5.00      |
| H      | Inventory DB reconciliation from robot scans          | 2                 | 3           | 8              | 5.25      |
| I      | Stock planning / replenishment from live inventory    | 2                 | 3           | 8              | 5.25      |
| **J**  | **Cold-chain delivery with chain-of-custody**         | **4**             | **5**       | **6**          | **5.25**  |
| K      | Warehouse equipment health monitoring by mobile robot | 1                 | 2           | 5              | 3.25      |

**One line per candidate:** **A** — safety compliance, not IP (patentability 1; anticipated by [ISO 3691-4:2023](https://www.iso.org/standard/83545.html)). **B** — high prior-art proximity ([US12561660B2](https://patents.google.com/patent/US12561660B2/en), [US11396100B2](https://patents.google.com/patent/US11396100B2/en)). **C** — a data-integrity principle, not a mechanism (novelty 3 but patentability 1). **D** — established methodology (0/0). **E/F1** — narrow but crowded, presentation/interlock art. **F2** — the highest novelty score (5); a concrete comparability mechanism, but low usefulness. **F3** — static-analysis practice. **G** — a mature commercial category (Simbe/Walmart/Sensormatic thicket); the highest usefulness (9) and the lowest novelty (1). **H/I** — occupied reconciliation/planning ground; useful (8), unpatentable. **J** — least crowded, the top patentability (4) among G–K; closest art [US20220004979A1](https://patents.google.com/patent/US20220004979A1/en) (assignee **unverified**). **K** — enormous PdM/inspection field; [US11861820B1 (Rdi Technologies)](https://patents.google.com/patent/US11861820B1/en) and its patented [Motion Amplification](https://rditechnologies.com/condition-monitoring/) are very close.

**No candidate scores ≥6 on patentability.** F2 and J tie for the highest (4/10).

### 2. Extended triage (A–K)

| Candidate                            | Action                                                   | Justification                                                                                      |
| ------------------------------------ | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| A. Layered safety                    | **No action (as IP)** — compliance                       | Anticipated; the real question is the required PL                                                  |
| B. 3D digital twin                   | **Defensive publication**                                | High proximity ([US12561660B2](https://patents.google.com/patent/US12561660B2/en))                 |
| C. No-score ops projection           | **Defensive publication**                                | Not patentable subject matter                                                                      |
| D. Mock/sim-first                    | **No action**                                            | Established SIL/HIL methodology                                                                    |
| E. Hazard/heatmap fusion             | **Defensive publication**                                | Moderate–high proximity ([US10684623B2](https://patents.google.com/patent/US10684623B2/en))        |
| F1. Event correlation + latch        | **Defensive publication**                                | Established alarm-correlation/interlock art                                                        |
| **F2. Comparable-extent heatmap**    | **Revisit-after-hardware** (possible provisional *then*) | Top patentability (4) + novelty (5); needs a measured effect                                       |
| F3. Non-actuating components         | **Defensive publication**                                | Static-analysis practice                                                                           |
| G. Inventory cycle counting          | **No action (IP)** — build it                            | Mature commercial category; usefulness 9, patentability 1                                          |
| H. Inventory reconciliation          | **No action (IP)** — build it                            | Occupied ground; usefulness 8, patentability 2                                                     |
| I. Stock planning                    | **No action (IP)** — build it                            | Occupied ground; usefulness 8, patentability 2                                                     |
| **J. Cold-chain + chain-of-custody** | **Revisit-after-hardware** (possible provisional *then*) | Least crowded of G–K; patentability 4                                                              |
| K. Equipment health monitoring       | **No action (IP)** — build it                            | Vast PdM/inspection field; [US11861820B1](https://patents.google.com/patent/US11861820B1/en) close |

**None of the thirteen warrants a provisional filing today.** The reason is uniform: the broad concepts are anticipated or non-patentable subject matter, the narrower mechanisms are crowded or presentation-layer, and — for the two best candidates (F2, J) — the system runs in mock mode, so the invention is not yet enabled.

### 3. The decision-relevant trade-off: usefulness and patentability diverge

This is the chapter's most important finding. **The highest usefulness scores (G=9, H=8, I=8) belong to the least patentable ideas; the most patentable (J and F2 at 4/10) are the least useful.** The user should therefore **build G, H and I and not expect to patent them** — their value is operational, not exclusionary. Conversely, **J and F2 are the only candidates worth a future filing, and their value is defensive/strategic, not operational.** A low patentability score must **not** be read as "bad idea": G and K in particular are excellent product features that simply sit in crowded art.

### 4. Recommended actions — "build this" versus "patent this"

These are different answers for different candidates:

- **Build (high usefulness, low patentability): G, H, I, K, D.** Ship them; protect them by *defensive publication*, not patents.
- **Build and revisit patenting after hardware: J, F2.** The only two with any patent headroom; a provisional is possible *later*, once enabled.
- **Defensive-publish: B, C, E, F1, F3.** Establish prior art so no one else can patent them.
- **Treat as compliance, not IP: A.** Invest in meeting the required PL, not in filing.

### 5. The enablement gap — the central strategic problem

A patent must describe an **enabled** invention a skilled person can make and use. Because the system runs **entirely in mock mode**, the best candidates are currently **unenableable**: safety thresholds are `NOT_VERIFIED`, robot geometry is `null`, and no actuator has ever moved. **What must be built and measured:** for **A**, measure `wheel_track_m`/`wheel_diameter_m`, characterise real stopping distances, validate thresholds, and demonstrate the watchdog + proximity stop halting a real chassis (only then can PL be assessed per [ISO 13849-1](https://www.csagroup.org/store/product/iso_073481/)); for **B/J**, a real robot producing real telemetry; for **E/F2**, real gas/fire/vision sources producing real hazard events (the grid is **always empty** on the shipped config); for **F2 specifically**, a demonstration that the stable-extent grid yields a *measurable operational benefit* on real data.

### 6. Freedom to operate — a different question from novelty

**Novelty** asks *"can I patent it?"*; **freedom to operate (FTO)** asks *"can I use it without infringing someone else's patent?"* They are independent — an unpatentable idea can be perfectly free to use (G, H, I, K), and a novel idea can still infringe. **Where an FTO search is prudent, and against whom:** the deep-portfolio holders — **Amazon, Locus, Geek+, Vecna, Fetch/Zebra, Dematic, Invia, Ocado, ForwardX, Boston Dynamics, Simbe** — across safety, twin, fleet and heatmap art; for the new concepts, **Simbe/Sensormatic** (inventory scanning, G), **Ocado/Amazon** (inventory reconciliation, H/I), and **Rdi Technologies** (equipment health, K). Separately, **ISO 3691-4 performance-level requirements** matter *regardless of patent status*: a safety function that fails the required PL is a **compliance** problem even if it infringes nothing. A software-only Pi stop is unlikely to meet a required PL d.

### 7. The narrower-mechanism hunt, continued

Beyond F1–F3, the specific mechanisms examined were: the worst-wins/escalate-only rule with an independent latch and two-step release; the counted-never-dropped `clipped`/`unlocated` accounting; the "extent from configured geometry, not data extent" rule (F2); the "sampling rate is the clock, not the odometer" traffic definition; and the single-`MapSnapshot` → multi-view consistency. **Honest answer: none clears the bar.** The class of mechanism that *would* be protectable is a **hardware-validated, closed-loop technical effect with a measured effect on physical behaviour** — e.g. a sensor-fusion method that measurably reduces real stopping distance or false stops, or a control method that provably holds a safety margin under measured dynamics. That is exactly what mock mode cannot supply.

### 8. Strategic alternatives — what protects the work

- **Defensive publication:** deliberately publishing establishes **prior art**, stopping others from patenting the work and preserving the project's freedom to operate even without its own patents. Correct default for A–F3, G–I, K.
- **Trade secret:** largely **unavailable** — trade secret requires secrecy, and the code is public on GitHub ([github.com/abhijeet1267/amr](https://github.com/abhijeet1267/amr)); publication destroys secrecy.
- **Open-source / own-publication-as-prior-art — the most important point in this chapter.** The GitHub publication itself creates prior art. In the **US**, an inventor's own public disclosure starts a **one-year grace period** to file ([USPTO MPEP 2152, AIA 35 U.S.C. 102(b)(1)](https://www.uspto.gov/web/offices/pac/mpep/s2152.html); [Wright State](https://www.wright.edu/research/technology-transfer/intellectual-property)). But **many jurisdictions apply absolute novelty with no general grace period** for the inventor's own pre-filing publication ([IP Australia on grace periods](https://manuals.ipaustralia.gov.au/patent/8.4.3.1-grace-period); [Korea's absolute-novelty rule](http://www.patentbaristas.com/page/49/)). **Consequence: publishing before filing can foreclose patenting entirely outside the US.** Because G–K are not yet implemented and J/F2 are the only filing candidates, **if the user ever intends to file on J or F2, that decision must be made before any further public disclosure** — including publishing the new roadmap concepts.

### Analysis

The picture is coherent and actionable. The broad concepts are unpatentable or anticipated; the narrow mechanisms are crowded or presentational; and the two best candidates (J, F2) are blocked by the enablement gap. Crucially, the scoring shows the project's *value* and its *patentability* point in opposite directions — so the rational strategy is to **build the useful, unpatentable ideas (G, H, I, K) and defensively publish them**, while treating J and F2 as the only future filing candidates and protecting them with an early decision on public disclosure.

### Summary

Scores integrated with a usefulness-weighted composite. **No candidate warrants a provisional filing today.** Build G/H/I/K and don't expect to patent them; revisit J and F2 after hardware; defensively publish B/C/E/F1/F3; treat A as compliance. Enablement is the binding constraint; FTO is separate from novelty; and — most importantly — the public GitHub code both destroys trade-secret protection and creates prior art that can foreclose non-US patenting unless filing intent is decided before further disclosure. **Engage a registered patent attorney before any filing.**

### Key findings

- **No candidate scores ≥6 on patentability**; F2 and J tie highest at 4/10. **None warrants a provisional filing today.**
- **Usefulness and patentability diverge** — G (9), H (8), I (8) are the most useful and least patentable; a low patentability score is **not** "bad idea."
- **Build vs patent are different answers:** build G/H/I/K/D; revisit patenting only for J/F2.
- **Enablement is the binding blocker** (mock mode, `NOT_VERIFIED` thresholds, `null` geometry).
- **Novelty ≠ FTO**; search against the named portfolios and meet **ISO 3691-4 PL** regardless of patents.
- **Own-publication creates prior art** — decide filing intent **before** further disclosure, especially for J/F2.

**Caveat:** IP-strategy analysis, **not legal advice**. Engage a registered patent attorney before any filing.

---

## 6. Warehouse operations: structural problems, safety and standards, and the agentic and digital-twin future

**Thesis.** Warehouse automation does not have a robot-availability problem. Global sales of professional service robots grew 30% in a single year to more than 205,000 units, and more than half of those units were built for transportation and logistics ([IFR, *World Robotics 2024 — Service Robots*](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1)). The binding constraint sits elsewhere — in labour economics, workflow orchestration, interoperability and safety governance. That is the lens through which the agentic-AI and digital-twin wave described in the preceding chapters must be read: it is arriving into an industry whose bottleneck has never been the robots.

### Movement 1 — Structural problems (current challenges)

**Labour scarcity is the demand driver.** The IFR attributes rising service-robot demand directly to labour shortage, noting the industry "suffers from a significant labour shortage" and that tasks such as loading and unloading are prime targets for automation ([IFR](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1)). In the United States, annual turnover in transportation and warehousing is widely reported at roughly 49% — near half the workforce replaced each year ([UAI, citing US Bureau of Labor Statistics](https://universalatomicintelligence.com/)). *Caveat:* the 49% figure could only be traced to secondary citation of BLS JOLTS data; a BLS primary table stating it verbatim was not located, so it is labelled "BLS-derived" rather than a direct BLS statistic.

**Throughput bottlenecks are displaced, not solved.** Automation deployed without coordinating labour and inventory flow creates isolated "islands of automation" in which robots and people operate in disconnected silos — "which ultimately creates new bottlenecks instead of removing them" ([AutoScheduler.AI, *FoodLogistics*](https://foodlogistics.com/warehousing/automation/article/22963056/autoschedulerai-overcoming-the-automation-roi-crisis-why-islands-of-automation-fail)). The named failure states are *starvation* (a robot mechanically ready but idle because upstream humans cannot decant fast enough, or the WMS is late releasing work) and *blocking* (high-speed automation obstructed because the downstream manual process is at capacity). **The specific figures often quoted for this pattern (a 28% picking-cycle-time cut, 18% idle time, ~$2.7M stranded on a $15M fleet) could not be verified to any primary or near-primary source** and should be treated as an illustrative composite unless the originator can supply the source. The underlying mechanism is independently supported.

**Congestion and mixed human/robot traffic** is now a first-class research and IP problem. Academic work targets safe shared-space navigation using control barrier functions integrated with the Open Robotics Middleware Framework (OpenRMF) to handle multi-robot, multi-agent scenarios with human pedestrians ([Farrell et al., *Safe Human Robot Navigation in Warehouse Scenario*, arXiv:2503.21141](https://arxiv.org/abs/2503.21141)). Commercially, Locus Robotics holds a patent reported to concern congestion management for robot fleets (AU2023210596A1, [patent record](https://patents.google.com/patent/AU2023210596A1/en)); *note:* the full claims text could not be read in this session, so the number and assignee are confirmed but the scope of "congestion management" is not.

**Brownfield incompatibility.** AS/RS and cube-storage architectures generally require rebuilding the facility; assessing existing layout, goods handled and automation level is a prerequisite, and retrofits are "particularly" challenging ([Swisslog](https://www.swisslog.com/en-us/knowledge/retrofitting-considerations-asrs-warehouse)). AMRs are frequently the only architecture that fits existing racking without structural change.

**Integration and interoperability** are the silent cost killers. Multi-vendor fleets historically required bespoke interfaces to the WMS/ERP; the emerging remedy is **VDA 5050**, a standardised JSON/MQTT interface between AGV/AMR fleets and fleet managers, now being adopted by vendors such as MiR ([MiR](https://mobile-industrial-robots.com.cn/zh/blog/mir-supports-interoperability-with-vda5050)) and Seegrid.

**ROI realism.** McKinsey stresses that the decisions made during initial strategy, scoping and planning "are critical" to outcomes, and that automation should be scoped to a real bottleneck rather than bought wholesale ([McKinsey, *Getting warehouse automation right*](https://www.mckinsey.com/capabilities/operations/our-insights/getting-warehouse-automation-right)). Practitioner economics are harsher: breakeven of 2–3 years assumes three-shift, 80%+ utilisation, and most single-shift sites see automation "idle 200+ days per year" ([FY Warehouse](https://www.fywarehouse.com/news/warehouse-automation-in-canada-what-actually-works-at-the-dock-d70905a1)). *The frequently cited "26–28 month payback / opex 22–28% of TCO" figures could not be traced to a primary source; the directional point (payback commonly exceeds the vendor-promised 18 months) holds.*

### Movement 2 — Safety and standards

**Injury burden.** UK trade sources state that forklift and pallet trucks are involved in more than 36,000 accidents each year ([STILL UK](https://www.still.co.uk/forklift-trucks/safety.html)) — this is a **trade-body figure and should be labelled indicative, not a government statistic.** The authoritative British source is the HSE, which reports 680,000 workers injured at work and 126 fatal workplace accidents in a recent year ([HSE, *Key figures for Great Britain*](https://www.hse.gov.uk/statistics/overview.htm)). For the US, OSHA publishes injury/illness datasets directly ([OSHA Data](https://www.osha.gov/data)); the frequently quoted "~85–100 fatalities / 35,000+ injuries from forklifts" is OSHA-derived but commonly repeated via secondary sources.

**The governing standards stack:**

- **ISO 3691-4:2023** — *Industrial trucks — Safety requirements and verification — Part 4: Driverless industrial trucks and their systems* — the core C-standard for AMRs/AGVs ([ISO](https://www.iso.org/standard/83545.html)).
- **ISO 13849-1:2023** — *Safety of machinery — Safety-related parts of control systems — Part 1* — defines performance level (PL), category and diagnostic coverage for safety functions ([CSA Group](https://www.csagroup.org/store/product/iso_073481/)).
- **ANSI/ITSDF B56.5-2024** — the US standard for driverless, automatic-guided industrial vehicles ([ANSI/ITSDF B56.5-2024](https://www.antpedia.com/standard/1284722648-10.html)).
- **VDA 5050** — the interoperability interface (above), a de-facto requirement for mixed fleets.

### Movement 3 — Future vision (5–10 years)

**Agentic AI entering operations.** DHL frames agentic AI as a strategic pillar, deploying "autonomous AI agents" to run routine coordination at scale ([DHL Group, 2025 Annual Report](https://reporting-hub.group.dhl.com/2025-fy/en/)), and its Logistics Trend Radar is the sector's benchmark foresight tool ([DHL Logistics Trend Radar](https://www.dhl.com/nl-en/home/insights-and-innovation/insights/logistics-trend-radar.html)). The operational logic is to insert a decision layer *on top of* the existing WMS/WES that autonomously re-routes labour and tasks against live cost — an approach its proponents report yields throughput gains while shifting the human role toward supervision and exception handling ([AutoScheduler.AI](https://foodlogistics.com/warehousing/automation/article/22963056/autoschedulerai-overcoming-the-automation-roi-crisis-why-islands-of-automation-fail)). *This last figure is vendor-reported and should be attributed, not presented as independent.*

**Digital twins as the operational layer.** NVIDIA positions industrial-facility and robot-fleet digital twins as the backbone of "physical AI," with partners including Dematic, Siemens, Schneider Electric and SAP connecting their tools to the Omniverse stack ([NVIDIA](https://nvidianews.nvidia.com/_gallery/download_pdf/67d9c8043d6332de871510cd/)). As a vendor-validated adoption datapoint, Schaeffler plans digital twins in more than half its global manufacturing sites by 2030 ([NVIDIA customer story — Schaeffler](https://www.nvidia.com/en-gb/customer-stories/schaeffler/)). *(Vendor source — used for what a vendor is doing, not as a market fact.)*

**Market scale.** Professional service robots grew 30% to >205,000 units in 2023; transportation and logistics accounted for ~113,000 units (+35%) ([IFR](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1)).

### Analysis

Read together, the three movements converge on one conclusion. The technology is available and cheapening; the failures are organisational. Displaced bottlenecks, brownfield constraints, multi-vendor integration and payback slippage are all workflow-and-governance problems. Agentic AI and digital twins are compelling precisely because they attack that layer — orchestration and simulation — rather than adding more iron.

### Summary

Warehouse automation's constraint is integration and workflow, not robot supply. Labour scarcity drives demand; automation displaces bottlenecks rather than removing them; brownfield and interoperability constraints dominate deployment risk; and safety is governed by a settled standards stack. The future vision — agentic decision layers and digital twins — targets the orchestration and simulation layer, which is exactly where the binding constraint sits.

### Key findings

- Warehouse automation's constraint is integration/workflow, not robot supply: >205,000 professional service robots shipped in 2023, +30% YoY ([IFR](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1)).
- Labour scarcity is the primary demand driver; US transportation & warehousing turnover ≈49% (BLS-derived, secondary citation) ([UAI/BLS](https://universalatomicintelligence.com/)).
- Automation displaces rather than removes bottlenecks ("islands of automation"; WMS starvation/blocking) ([AutoScheduler.AI](https://foodlogistics.com/warehousing/automation/article/22963056/autoschedulerai-overcoming-the-automation-roi-crisis-why-islands-of-automation-fail)).
- Mixed human/robot navigation is an active research and IP frontier (arXiv:2503.21141; Locus AU2023210596A1).
- Safety is governed by ISO 3691-4:2023 + ISO 13849-1:2023 + ANSI/ITSDF B56.5-2024; interoperability by VDA 5050.
- Agentic AI (DHL) and digital twins (NVIDIA/Schaeffler) target the orchestration/simulation layer, not hardware.

### Data summary

| Metric                                   | Data                                     | Source                                                                         |
| ---------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------ |
| Professional service robots, 2023        | >205,000 units, +30% YoY                 | [IFR](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1)          |
| Transportation & logistics segment, 2023 | ~113,000 units, +35%                     | [IFR](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1)          |
| US transport & warehousing turnover      | ≈49% annually (BLS-derived, secondary)   | [UAI/BLS](https://universalatomicintelligence.com/)                            |
| UK forklift/pallet-truck accidents       | >36,000/yr (trade, indicative)           | [STILL UK](https://www.still.co.uk/forklift-trucks/safety.html)                |
| UK workplace injuries / fatalities       | 680,000 injured; 126 fatal (recent year) | [HSE](https://www.hse.gov.uk/statistics/overview.htm)                          |
| Schaeffler digital-twin target           | >50% of plants by 2030                   | [NVIDIA/Schaeffler](https://www.nvidia.com/en-gb/customer-stories/schaeffler/) |

### Unverified figures (retained with labels, not presented as fact)

1. Pharma-distributor figures (28% cycle time, 18% idle, $2.7M/$15M) — **not traceable to a primary source**; mechanism supported, numbers are not.
2. "26–28 month payback / 22–28% opex of TCO" — not traceable; directional claim supported by FY Warehouse (2–3 yr best case).
3. 49% turnover — secondary citation of BLS only.
4. Locus patent AU2023210596A1 — number/assignee identified, full text not machine-readable; "congestion management" scope unconfirmed.

---

## Conclusion

Two questions framed this report: where enterprise AI agents actually stand, and what — if anything — in a specific AMR project is patentable. The evidence supports a clear answer to each, and the two answers share a shape.

On enterprise agents, the capability is real and the adoption is shallow. Genuine agents run an autonomous observe–plan–act loop with tools and memory, distinct from chatbots, copilots and RPA ([BCG](https://www.bcg.com/capabilities/artificial-intelligence/ai-agents)). But measured adoption is broad and thin: 88% of organisations use AI somewhere and 62% are experimenting with agents, yet fewer than 10% have scaled agents in any single function ([McKinsey](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)). The failures are integration and change-management failures, not capability failures — MIT's "learning gap," in which buying and partnering succeed roughly twice as often as internal builds ([MIT NANDA via Fortune](https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/)). The enabling stack has consolidated faster than the governance around it: MCP and A2A are now vendor-neutral standards under the Linux Foundation ([Linux Foundation, AAIF](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)), yet the best automated failure attribution identifies the responsible agent only 53.5% of the time ([Zhang et al., ICML 2025](https://arxiv.org/abs/2505.00212)), and non-human identities outnumber human ones roughly 50:1 ([Vectra](https://www.vectra.ai/topics/agentic-ai-security)). Identity and accountability — not model intelligence — are the likeliest cause of the next wave of failures. Klarna's arc, from automating two-thirds of chats to rehiring human agents ([Klarna](https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/)), is the reliability-envelope lesson in miniature: reliability must precede autonomy.

On the AMR project, the verdict is negative, and it should be stated plainly. No candidate idea clearly clears the novelty-and-inventive-step bar. Every functional area the project touches is crowded — navigation and SLAM, obstacle avoidance and sensor fusion, task allocation, safety and emergency stop — and the least-crowded niches are presentation-layer, where patentable subject matter is doubtful. No candidate scores 6 or higher on patentability, and none warrants a provisional filing today. Enablement is the binding constraint: the system runs entirely in mock mode, with unverified safety thresholds and null geometry, so the strongest candidates cannot yet support a claim.

The constructive finding is a divergence. Usefulness and patentability point in opposite directions: the most useful ideas — inventory cycle counting, reconciliation and replenishment — are the least patentable, while the two most patentable — a temporally comparable heatmap and cold-chain chain-of-custody — are the least useful. The rational strategy follows: build the useful, unpatentable ideas and publish them defensively, and treat the two filing candidates as future work contingent on hardware. Because the code is already public, the decision to file — if it is ever taken — must be made before any further disclosure, since publication can foreclose patenting outside the United States.

For enterprises, the corresponding priority is governance before autonomy: solve agent identity, permissions and accountability before granting agents more latitude. The unifying insight is the one the report set out to test. Capability and realised value, like usefulness and patentability, are not the same axis — and reading both honestly is the difference between a demonstration and a durable system.

---


## References

**Non-patent sources (68)**

- ANSI/ITSDF. (2024). *B56.5-2024: Safety standard for driverless, automatic guided industrial vehicles and automated functions of manned industrial vehicles*. [link](https://www.antpedia.com/standard/1284722648-10.html)
- Arize AI. (n.d.). *Phoenix: Open-source AI observability and evaluation*. [link](https://phoenix.arize.com/)
- Atlassian. (n.d.). *Heatmap: A complete guide*. [link](https://www.atlassian.com/ko/data/charts/heatmap-complete-guide)
- AutoScheduler.AI. (n.d.). *Overcoming the automation ROI crisis: Why islands of automation fail*. Food Logistics. [link](https://foodlogistics.com/warehousing/automation/article/22963056/autoschedulerai-overcoming-the-automation-roi-crisis-why-islands-of-automation-fail)
- Boston Consulting Group (BCG). (2025). *AI agents*. [link](https://www.bcg.com/capabilities/artificial-intelligence/ai-agents)
- CSA Group. (2023). *ISO 13849-1:2023 — Safety of machinery: Safety-related parts of control systems, Part 1*. [link](https://www.csagroup.org/store/product/iso_073481/)
- DHL Group. (2025). *2025 annual report*. [link](https://reporting-hub.group.dhl.com/2025-fy/en/)
- DHL. (n.d.). *Logistics trend radar*. [link](https://www.dhl.com/nl-en/home/insights-and-innovation/insights/logistics-trend-radar.html)
- Dilley, R. (n.d.). *Simple Event Correlator (SEC)*. [link](https://www.cs.umb.edu/~rouilj/sec/sec_paper.pdf)
- eSentire. (2025). *Model Context Protocol security: Critical vulnerabilities every CISO should address in 2025*. [link](https://www.esentire.com/blog/model-context-protocol-security-critical-vulnerabilities-every-ciso-should-address-in-2025)
- Farrell, M., et al. (2025). *Safe human–robot navigation in a warehouse scenario* (arXiv:2503.21141). arXiv. [link](https://arxiv.org/abs/2503.21141)
- Flexport. (n.d.). *Replenishment*. [link](https://www.flexport.com/products/replenishment/)
- Focal Systems. (n.d.). *Focal Systems*. [link](https://focal.systems/)
- Forrester. (n.d.). *Agentic AI and IT maturity: Bridging the gap between ServiceNow's vision and the IT reality*. [link](https://www.forrester.com/blogs/agentic-ai-and-it-maturity-bridging-the-gap-between-servicenows-vision-and-the-it-reality/)
- FY Warehouse. (n.d.). *Warehouse automation in Canada: What actually works at the dock*. [link](https://www.fywarehouse.com/news/warehouse-automation-in-canada-what-actually-works-at-the-dock-d70905a1)
- Gartner. (2025a). *Gartner predicts over 40% of agentic AI projects will be canceled by end of 2027* [Press release]. [link](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)
- Gartner. (2025b). *AI agent reality check*. [link](https://www.gartner.com/en/articles/ai-agent-reality-check)
- Gilmurray, K. (2025). *Why over 40% of agentic AI projects may fail*. [link](https://kierangilmurray.com/why-over-40-of-agentic-ai-projects-may-fail/)
- GitHub. (n.d.). *AMR project source code* [Computer software]. [link](https://github.com/abhijeet1267/amr)
- Google Developers Blog. (2025). *A2A: A new era of agent interoperability*. [link](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- Health and Safety Executive (HSE). (n.d.). *Key figures for Great Britain*. [link](https://www.hse.gov.uk/statistics/overview.htm)
- Industry 4.1. (n.d.). *Quick hits: Warehouse automation growing pains, fleet bottlenecks, rising costs, and the ROI reckoning*. [link](https://www.industry4-1.com/article/quick-hits-warehouse-automations-growing-painsfleet-bottlenecks-rising-costs-and-the-roi-reckoning-accelerating)
- IntellAgent. (2025). *A multi-agent framework for evaluating tool-augmented conversational agents* (arXiv:2501.11067). arXiv. [link](https://arxiv.org/pdf/2501.11067.pdf)
- Interact Analysis. (2025). *Mobile robot market report 2025* (Geek+ #1 global AMR vendor by 2024 revenue; reported via CNFOL). [link](http://hy.stock.cnfol.com/dianzixinxijishu/20251208/31849869.shtml)
- International Federation of Robotics (IFR). (2024). *Sales of service robots up 30% worldwide* (World Robotics 2024 — Service Robots). [link](https://ifr.org/news/sales-of-service-robots-up-30-worldwide/1)
- IP Australia. (n.d.). *Grace period for patents* (Patents Manual 8.4.3.1). [link](https://manuals.ipaustralia.gov.au/patent/8.4.3.1-grace-period)
- ISO. (2023). *ISO 3691-4:2023 — Industrial trucks: Safety requirements and verification, Part 4: Driverless industrial trucks and their systems*. [link](https://www.iso.org/standard/83545.html)
- Jiemian News. (2025). *Interact Analysis: Geek+ leads global AMR market share*. [link](https://www.jiemian.com/article/12945634.html)
- Klarna. (2024). *Klarna AI assistant handles two-thirds of customer service chats in its first month* [Press release]. [link](https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/)
- Langfuse. (n.d.). *Langfuse: Open-source LLM engineering platform*. [link](https://langfuse.com/)
- LCB. (n.d.). *Klarna reverses course, reintroduces human customer support*. [link](https://lcb.org/news/klarna-reverses-course-reintroduces-human-customer-support)
- LeverX. (n.d.). *SAP EWM and robotics*. [link](http://leverx.com/newsroom/sap-ewm-and-robotics)
- Linux Foundation. (2025a). *Linux Foundation announces the formation of the Agentic AI Foundation*. [link](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)
- Linux Foundation. (2025b). *Linux Foundation launches the Agent2Agent protocol project to enable secure, intelligent communication between AI agents*. [link](https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project-to-enable-secure-intelligent-communication-between-ai-agents)
- MarketsandMarkets. (n.d.). *AI agents market — Global forecast to 2030*. [link](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html)
- McKinsey & Company. (2025a). *The state of AI*. [link](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai)
- McKinsey & Company. (2025b). *Getting warehouse automation right*. [link](https://www.mckinsey.com/capabilities/operations/our-insights/getting-warehouse-automation-right)
- Microsoft. (2025). *Ignite 2025: A developer's guide to building agents for Microsoft 365*. Microsoft 365 Dev Blog. [link](https://devblogs.microsoft.com/microsoft365dev/ignite-2025-a-developers-guide-to-building-agents-for-microsoft-365/)
- MiR. (n.d.). *MiR supports interoperability with VDA 5050*. [link](https://mobile-industrial-robots.com.cn/zh/blog/mir-supports-interoperability-with-vda5050)
- NetSuite. (n.d.). *Inventory replenishment*. [link](https://www.netsuite.com/portal/resource/articles/inventory-management/inventory-replenishment.shtml)
- NVIDIA. (2025). *NVIDIA expands Omniverse physical AI* [Newsroom]. [link](https://nvidianews.nvidia.com/_gallery/download_pdf/67d9c8043d6332de871510cd/)
- NVIDIA. (n.d.-a). *AI agents*. [link](https://www.nvidia.com/en-us/ai/)
- NVIDIA. (n.d.-b). *AI for virtual factory solutions*. [link](https://www.nvidia.com/en-us/use-cases/ai-for-virtual-factory-solutions/)
- NVIDIA. (n.d.-c). *Schaeffler: Digital twins and simulation-first robotics* [Customer story]. [link](https://www.nvidia.com/en-gb/customer-stories/schaeffler/)
- OPAL-RT. (n.d.). *Software-in-the-loop*. [link](https://www.opal-rt.com/software-in-the-loop/)
- OSHA. (n.d.). *OSHA data*. [link](https://www.osha.gov/data)
- Rdi Technologies. (n.d.). *Condition monitoring*. [link](https://rditechnologies.com/condition-monitoring/)
- REALM-Bench. (2025). *A benchmark for multi-agent planning and scheduling* (arXiv:2502.18836). arXiv. [link](https://arxiv.org/html/2502.18836v2)
- RELEX Solutions. (n.d.). *Unlocking retail efficiency: How AI reduces cost of shelving*. [link](https://www.relexsolutions.com/resources/unlocking-retail-efficiency-how-ai-reduces-cost-of-shelving/)
- ScienceDirect. (n.d.). *Hardware-in-the-loop simulation*. [link](https://www.sciencedirect.com/topics/computer-science/hardware-in-the-loop-simulation)
- Sensitech. (n.d.). *Sensitech* [LinkedIn]. [link](https://www.linkedin.com/company/sensitech/)
- ShipBob. (n.d.). *Auto replenishment*. [link](https://www.shipbob.com/uk/blog/auto-replenishment/)
- Siemens. (n.d.). *Enabling predictive maintenance through industrial connectivity*. [link](https://resources.sw.siemens.com/en-US/brochure-enabling-pm-through-industrial-connectivity/)
- Simbe Robotics. (n.d.-a). *Simbe Robotics*. [link](https://www.simberobotics.com/)
- Simbe Robotics. (n.d.-b). *Store intelligence / Tally*. [link](https://www.simberobotics.com/store-intelligence/tally)
- SKF. (n.d.). *Condition monitoring systems*. [link](https://www.skf.com/id/products/condition-monitoring-systems)
- STILL UK. (n.d.). *Forklift truck safety*. [link](https://www.still.co.uk/forklift-trucks/safety.html)
- Swisslog. (n.d.). *Retrofitting considerations for AS/RS warehouses*. [link](https://www.swisslog.com/en-us/knowledge/retrofitting-considerations-asrs-warehouse)
- Tencent Cloud. (2025a). *什么是 AI Agent* [What is an AI Agent]. [link](https://cloud.tencent.com/developer/article/2673695)
- Tencent Cloud. (2025b). *OpenAI Agents SDK launch*. [link](https://cloud.tencent.com/developer/news/2302074)
- Tencent Cloud. (2026). *MIT 报告引爆科技圈：AI 项目落地的失败率真的高达 95% 吗？* [Does the MIT report really mean a 95% AI project failure rate?]. [link](https://cloud.tencent.com/developer/article/2652336)
- Thermo King. (n.d.). *Technologies*. [link](https://europe.thermoking.com/technologies)
- Tive. (n.d.). *Tive* [LinkedIn]. [link](https://www.linkedin.com/company/tiveinc)
- Universal Atomic Intelligence (UAI). (n.d.). *3PL automation* (citing US Bureau of Labor Statistics). [link](https://universalatomicintelligence.com/)
- USPTO. (n.d.). *MPEP § 2152 — AIA 35 U.S.C. 102(b)(1): Grace period inventor disclosures*. [link](https://www.uspto.gov/web/offices/pac/mpep/s2152.html)
- Vectra. (n.d.). *Agentic AI security*. [link](https://www.vectra.ai/topics/agentic-ai-security)
- WareVR. (n.d.). *WareVR* (arXiv:2110.11052). arXiv. [link](https://arxiv.org/abs/2110.11052)
- Wright State University. (n.d.). *Intellectual property*. [link](https://www.wright.edu/research/technology-transfer/intellectual-property)
- Zhang, Y., et al. (2025). *Which agent causes task failures and when?* (ICML 2025 Spotlight). arXiv. [link](https://arxiv.org/abs/2505.00212)

**Patents and patent applications (40)**

- Allen, M., & Melanson, D. (2022). *Autonomous mobile delivery robot and chain of custody system* (US Patent Application No. 20220004979A1; **assignee unverified**). Google Patents. [link](https://patents.google.com/patent/US20220004979A1/en)
- Amazon Technologies. (2017). *Mobile robot group* (US Patent No. 9637310B1). Google Patents. [link](https://patents.google.com/patent/US9637310B1/en)
- Boston Dynamics. (2024). *Systems and methods of guarding a mobile robot* (European Patent No. 4572923A1). Google Patents. [link](https://patents.google.com/patent/EP4572923A1/en)
- Brooks Automation. (n.d.). *Intelligent condition monitoring and fault diagnostics* (US Patent No. 9104650B2). Google Patents. [link](https://patents.google.com/patent/US9104650B2/en)
- Dematic Corp. (2023). *Adaptive autonomous mobile robot tasking* (US Patent Application No. 20240174445A1). Google Patents. [link](https://patents.google.com/patent/US20240174445A1/en)
- FANUC America. (2022). *Robot calibration for AR and digital twin* (US Patent No. 11396100B2). Google Patents. [link](https://patents.google.com/patent/US11396100B2/en)
- Fetch Robotics. (2019). *Robot management system* (US Patent Application No. 20210018912A1). Google Patents. [link](https://patents.google.com/patent/US20210018912A1/en)
- Fetch Robotics. (2022). *Automated transporter fleet control in order fulfilment facilities* (US Patent Application No. 20220411188A1). Google Patents. [link](https://patents.google.com/patent/US20220411188A1/en)
- ForwardX (灵动科技). (2022). *Method and device for controlling driving of an autonomous mobile robot* (WO Patent No. 2023109281A1). Google Patents. [link](https://patents.google.com/patent/WO2023109281A1/en)
- Geek+ (北京极智嘉). (n.d.). *Order picking and task allocation* (Chinese Patent No. 109117999B). Google Patents. [link](https://patents.google.com/patent/CN109117999B/en)
- IAM Robotics. (n.d.). *Picking and put-away with mobile manipulation robot* (US Patent No. 11348066B2). Google Patents. [link](https://patents.google.com/patent/US11348066B2/en)
- Intel. (n.d.). *Monitoring robot health in manufacturing* (US Patent No. 10695907B2). Google Patents. [link](https://patents.google.com/patent/US10695907B2/en)
- Invia Robotics. (n.d.-a). *Locate and map item locations using robots* (US Patent No. 10466713B2). Google Patents. [link](https://patents.google.com/patent/US10466713B2/en)
- Invia Robotics. (n.d.-b). *Workflow management system integrating robots* (US Patent No. 11049067B2). Google Patents. [link](https://patents.google.com/patent/US11049067B2/en)
- Locus Robotics. (2018). *Order grouping* (Australian Patent No. 2018366020C1). Google Patents. [link](https://patents.google.com/patent/AU2018366020C1/en)
- Locus Robotics. (2023). *Robot congestion management* (Australian Patent Application No. 2023210596A1). Google Patents. [link](https://patents.google.com/patent/AU2023210596A1/en)
- Locus Robotics. (n.d.). *Robot queuing* (US Patent No. 10513033B2). Google Patents. [link](https://patents.google.com/patent/US10513033B2/en)
- Ocado. (n.d.). *Controlling movement of transport equipment* (Chinese Patent No. 106662874B). Google Patents. [link](https://patents.google.com/patent/CN106662874B/en)
- Rdi Technologies. (n.d.). *Repetitive video monitoring of industrial equipment by mobile data acquisition units* (US Patent No. 11861820B1). Google Patents. [link](https://patents.google.com/patent/US11861820B1/en)
- Sensormatic Electronics. (n.d.). *Inventorying objects using a robot and reprogrammable markers* (US Patent No. 11763249B2). Google Patents. [link](https://patents.google.com/patent/US11763249B2/en)
- Simbe Robotics. (n.d.-a). *Detecting and responding to spills and hazards* (US Patent No. 10684623B2). Google Patents. [link](https://patents.google.com/patent/US10684623B2/en)
- Simbe Robotics. (n.d.-b). *How to track inventory levels in a store* (Japanese Patent No. 6925443B2). Google Patents. [link](https://patents.google.com/patent/JP6925443B2/en)
- Simbe Robotics. (n.d.-c). *Method for stock keeping in a store with fixed cameras* (US Patent No. 11593755B2). Google Patents. [link](https://patents.google.com/patent/US11593755B2/en)
- Simbe Robotics. (n.d.-d). *Method for tracking placement of products on shelves in a store* (US Patent No. 10467587B2). Google Patents. [link](https://patents.google.com/patent/US10467587B2/en)
- Simbe Robotics. (n.d.-e). *Method for tracking and characterizing perishable goods* (US Patent No. 11200537B2). Google Patents. [link](https://patents.google.com/patent/US11200537B2/en)
- Simbe Robotics. (n.d.-f). *Method for maintaining perpetual inventory within a store* (US Patent Application No. 20260148186A1). Google Patents. [link](https://patents.google.com/patent/US20260148186A1/en)
- Simbe Robotics. (n.d.-g). *Tracking and maintaining inventory* (US Patent Application No. 20210357851A1). Google Patents. [link](https://patents.google.com/patent/US20210357851A1/en)
- Strong Force VCN Portfolio 2019. (2024). *Digital-twin-enabled robot fleet management* (US Patent No. 12561660B2). Google Patents. [link](https://patents.google.com/patent/US12561660B2/en)
- Trumed Systems. (n.d.). *Automated smart cold storage of temperature-sensitive products* (US Patent Application No. 20240140709A1). Google Patents. [link](https://patents.google.com/patent/US20240140709A1/en)
- Vecna Robotics. (2013). *Transporting and sorting items with mobile robots* (US Patent No. 9463927B1). Google Patents. [link](https://patents.google.com/patent/US9463927B1/en)
- Vecna Robotics. (n.d.). *Autonomous device for transporting items* (US Patent No. 11752627B2). Google Patents. [link](https://patents.google.com/patent/US11752627B2/en)
- Walmart. (2018). *Inventory management systems, devices and methods* (US Patent Application No. 20180247264A1). Google Patents. [link](https://patents.google.com/patent/US20180247264A1/en)
- Walmart Apollo. (2019). *Product inventorying using image differences* (US Patent Application No. 20190236530A1). Google Patents. [link](https://patents.google.com/patent/US20190236530A1/en)
- Walmart Apollo. (n.d.). *Dynamic flex-space allocation* (US Patent No. 11443276B2). Google Patents. [link](https://patents.google.com/patent/US11443276B2/en)
- *Chinese Patent No. 106292461B* (cold-chain transport supervisory system). Google Patents. [link](https://patents.google.com/patent/CN106292461B/en)
- *Chinese Patent No. 108502431B* (temperature-zoned cold-chain warehouse). Google Patents. [link](https://patents.google.com/patent/CN108502431B/en)
- *Chinese Patent No. 118278949B* (intelligent cold-chain traceability). Google Patents. [link](https://patents.google.com/patent/CN118278949B/en)
- *Chinese Patent No. 119960436B* (dynamic obstacle avoidance). Google Patents. [link](https://patents.google.com/patent/CN119960436B/zh)
- *Chinese Patent No. 120013403B* (AI cold-chain route optimisation). Google Patents. [link](https://patents.google.com/patent/CN120013403B/en)
- *WO Patent No. 2022131388A1* (AI safety-management via mobile robot sensing). Google Patents. [link](https://patents.google.com/patent/WO2022131388A1/en)

---

## Outstanding items

1. **US20220004979A1 assignee is unverified.** The inventors (Allen/Melanson) are confirmed; no corporate assignee was established. Do not treat as a confirmed corporate holder.
2. **Four warehouse figures remain unverified** (see Chapter 6). They are retained with explicit labels rather than removed, so the reader can see what was claimed and what could not be substantiated.
3. **Five patent citations could not be independently re-resolved** in the final pass (WO2023109281A1, US20240174445A1, US20210018912A1, US20220411188A1, AU2023210596A1) because Google Patents rate-limited automated access. All twelve citations that *could* be re-resolved matched their stated title and assignee with zero mismatches. A manual browser spot-check of the five is advisable.
4. **This is not legal advice.** A registered patent attorney should be engaged before any filing, and a full freedom-to-operate search performed before any commercial use of the identified candidates.

---

> This report was generated by an AI deep-research team. Important decisions should be verified by qualified professionals. All cited sources should be independently re-verified for currency and accuracy before being relied upon — in particular, patent status, standards editions, and market statistics change.
