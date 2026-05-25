# EU AI Act Compliance Audit — Job Search Automation

**Project:** `portero-aylagas/job_search_automation`  
**Audit type:** First-pass EU AI Act compliance assessment  
**Prepared for:** Head of Product  
**Scope:** Week 5 project audit based on the repository README and runtime code structure.  
**Caveat:** This is a consulting-level compliance assessment, not legal advice, not a conformity assessment, and not a certification.

---

## 1. System brief

Job Search Automation is a Python and Streamlit application that helps a job applicant prepare job applications in a controlled human-in-the-loop workflow. The system takes a candidate profile, a CV, optional supporting documents, and a job URL, then helps transform that information into structured application material.

The application can extract candidate information from an uploaded CV, store reviewed identity/contact/profile information, extract structured job-offer data from a public job URL, resolve an application URL, inspect the application page, identify required documents and form fields, generate application materials, and prepare a reviewed fill plan for browser-assisted form completion.

The main inputs are personal candidate data, uploaded documents, job URLs, public job descriptions, application-page HTML snapshots, and manually reviewed profile preferences such as target roles, locations, employment type, seniority, salary expectations, availability, and work authorization. Some inputs are personal data. Some may be sensitive or high-impact in practice, especially gender, nationality, disability-related fields, consent fields, salary, work authorization, and application answers.

The main outputs are normalized job listings, application requirements, application summaries, cover letter drafts, CV tailoring notes, recruiter-message drafts, form-answer drafts, upload checklists, missing-information lists, application fill plans, and tracker records. The system does not currently make an employer-side recruitment decision. It does not rank applicants for an employer, reject candidates, or decide access to employment. It supports the applicant in preparing materials.

Human review is central to the design. Candidate data is reviewed, extracted job data is reviewed, requirements are reviewed, package materials are editable, sensitive or user-decision fields are blocked or require explicit values, and Browser Use receives only a reviewed fill plan. The browser agent is instructed not to submit the application and to stop with the page ready for manual inspection.

The system was built by the project developer as a custom application. In a production scenario, the provider would be whoever places this application into service under their name. The deployer would usually be the person or organization using it for job-application preparation. OpenAI is an upstream GPAI/model provider for the LLM calls. Browser Use, Playwright, Streamlit, LangGraph, and related libraries are technical components or frameworks, not the main regulatory provider of the downstream job-search product.

---

## 2. Risk tier classification

| Question | Answer |
|---|---|
| Does this system fall under any prohibited category under Article 5? | No. The system does not manipulate users, exploit vulnerable groups, perform social scoring, perform biometric identification, infer workplace emotions, or perform prohibited biometric categorisation. |
| Does this system operate in any Annex III high-risk area? | It touches the employment context, but not in the relevant employer-side way. It supports the applicant. It does not decide, rank, screen, or evaluate candidates for an employer. |
| If Annex III: does it significantly influence decisions in that area, or is it narrow/preparatory? | It is preparatory/supportive from the applicant side. It may influence how the applicant presents themselves, but it does not significantly influence an employer’s hiring decision in the regulatory sense unless the system is repurposed by employers or recruiters. |
| Does this system interact with end users or generate content requiring disclosure under Article 50? | Yes, potentially. It generates application text and uses AI-assisted workflows. Users should be clearly informed when AI is used, and generated materials should remain identifiable as AI-assisted drafts in the product workflow. |
| First-pass risk tier | Limited risk / transparency-relevant. If kept as a private local tool, it may be closer to minimal risk, but a production deployment should treat transparency controls as required. |
| One-sentence justification | The system is not prohibited and not high-risk as built because it supports candidate-side application preparation rather than employer-side recruitment decisions, but it generates AI-assisted application content and therefore requires clear transparency and review controls. |

### Ambiguity

The classification changes if the product is repurposed. If an employer, recruiter, staffing agency, or HR department uses the same system to rank, screen, reject, or compare job candidates, the classification could move into high-risk employment AI. If the browser agent is changed to submit applications autonomously, the legal and operational risk also increases, even if the AI Act category may still not become high-risk.

---

## 3. Role map

| Role | Entity | Key AI Act obligations |
|---|---|---|
| Provider | The developer or organization that places Job Search Automation into service under its own name. For this lab, assume the project team is the provider. | Define intended use, document system capabilities and limits, provide user information, implement transparency controls, maintain appropriate technical documentation, and avoid prohibited or high-risk repurposing without reassessment. |
| Deployer | The user or organization using the system to prepare applications. For private individual use, AI Act deployer obligations may be limited or not apply. For a career agency or professional use, the organization using it would be the deployer. | Use the system within intended limits, review outputs before use, avoid automated submission without review, handle personal data lawfully, and maintain appropriate records if used professionally. |
| GPAI / model provider | OpenAI, when OpenAI models are used through the API. | GPAI obligations sit upstream: model documentation, copyright/transparency duties, and systemic-risk obligations where applicable. The downstream application provider cannot pass all product-level responsibility to the model provider. |
| Tooling / automation framework | Browser Use, Playwright, Streamlit, LangGraph, requests, BeautifulSoup, Pydantic. | These are supporting tools. They do not remove responsibility from the downstream application provider or deployer. Browser automation creates operational and privacy controls that the provider/deployer must manage. |
| Affected third parties | Employers, recruiters, ATS platforms, and application-page operators receiving materials or interacting with automated browser activity. | They are not deployers of this system, but their terms of service, privacy notices, and application-process rules may create separate obligations or constraints. |

---

## 4. High-risk obligation checklist

This system is **not classified as high-risk** in its current design, so the 11 high-risk provider-obligation checklist is not completed as applicable.

| High-risk provider obligation | Status for this project |
|---|---|
| Risk management system | Not required as high-risk obligation; lightweight risk register still recommended. |
| Data and data governance | Not required as high-risk obligation; still relevant for GDPR and output quality. |
| Technical documentation | Not required as high-risk obligation; project documentation should still describe intended use and limits. |
| Record-keeping and logging | Not required as high-risk obligation; logs are still useful for traceability and debugging. |
| Transparency and user information | Relevant because AI-generated materials and AI-assisted actions are central to the product. |
| Human oversight | Not required as high-risk obligation, but already a core safety control and should be preserved. |
| Accuracy, robustness, cybersecurity | Not required as high-risk obligation, but needed for safe handling of candidate data and generated outputs. |
| Conformity assessment | Not applicable unless future use becomes high-risk. |
| EU declaration of conformity / CE marking | Not applicable unless future use becomes high-risk. |
| Registration | Not applicable unless future use becomes high-risk. |
| Post-market monitoring | Not applicable as high-risk obligation; issue tracking and incident logging still recommended. |

---

## 5. Transparency obligations and current design

| Transparency issue | Current state | Assessment |
|---|---|---|
| User knows AI is used | UI labels several actions as AI-assisted, such as generating packages, discovering requirements, and using Browser Use apply assistance. | Mostly met. The user-facing UI is not hiding AI use. |
| Generated content is reviewable | Application packages are editable. Artifacts can be manually changed. Missing-information and quality findings are surfaced. | Mostly met. This is one of the strongest design controls. |
| AI outputs are labelled in exports | Generated Markdown/PDF/exported artifacts may not carry a durable “AI-assisted draft” marker or metadata. | Partial. Add export-level disclosure or metadata. |
| Browser agent limits are visible | The browser agent is built around reviewed fill plans and is instructed not to submit. | Mostly met, but should be reinforced with an explicit pre-launch confirmation screen. |
| Sensitive/user-decision fields | Several sensitive categories are blocked or require user review. | Partial. The classifier should be extended and tested against more real application forms. |

---

## 6. Gap analysis and remediation plan

### Gap 1 — Export-level AI disclosure

**Obligation / issue:** Article 50-style transparency and user information.  
**Current state:** The UI makes AI use visible, but generated exports such as cover letters, form answers, or Markdown packages may not preserve a durable AI-assisted marker.  
**Required state:** Users should clearly know which materials were AI-generated or AI-assisted, and exported artifacts should not lose that context.  
**Remediation:** Add metadata to generated packages and exports: generation source, model/profile, timestamp, reviewed status, and “AI-assisted draft reviewed by user” marker. For user-facing exports, decide whether visible disclosure is needed or whether internal metadata is sufficient.  
**Escalation needed:** Yes — legal review for the exact Article 50 disclosure/marking requirement in production.

---

### Gap 2 — Personal data governance

**Obligation / issue:** GDPR and general privacy governance.  
**Current state:** The system stores candidate identity data, CV-derived information, optional documents, salary expectations, nationality, gender, work authorization, and application answers in local JSON/files.  
**Required state:** A production version needs a clear data map, purpose limitation, retention policy, deletion process, access controls, and privacy notice.  
**Remediation:** Add a privacy/data-handling document, delete/export controls, retention defaults, local encryption recommendation, and a “clear all runtime data” function. For hosted use, add authentication, access control, and DPA/vendor documentation.  
**Escalation needed:** Yes — Data Protection Officer or privacy lawyer if deployed beyond local personal use.

---

### Gap 3 — Third-party API and GPAI dependency

**Obligation / issue:** Provider/deployer boundary and upstream model dependency.  
**Current state:** OpenAI is used for CV extraction, job extraction, requirements discovery, package generation, and field mapping. The app records workflow traces, but the product documentation should state what data is sent to model providers.  
**Required state:** Users should know which workflows send personal data or job data to third-party AI APIs.  
**Remediation:** Add an “AI data flow” section to the product README/UI: workflow name, data sent, provider, retention assumptions, purpose, and user control. Add a non-AI/manual mode where possible.  
**Escalation needed:** Yes — privacy/vendor review for production use.

---

### Gap 4 — Browser automation and external site rules

**Obligation / issue:** Operational compliance, website terms, unauthorized automation risk, and user agency.  
**Current state:** Browser Use receives a reviewed fill plan and is instructed not to submit, but it interacts with external application pages.  
**Required state:** The user should explicitly confirm that browser assistance is allowed for the target site and that they remain responsible for final review and submission.  
**Remediation:** Add a pre-run confirmation checklist: “I reviewed the fill plan,” “I accept using browser assistance on this site,” “Do not submit,” “Stop before final submit,” and “I will inspect the page manually.” Keep logs of the run result.  
**Escalation needed:** Possibly — legal review if deployed commercially or used at scale.

---

### Gap 5 — Incomplete approval state

**Obligation / issue:** Human oversight and traceability.  
**Current state:** The application has review steps for requirements and fill plans, and package editing exists, but the README still lists explicit package approval and ready-to-apply workflow as planned rather than complete.  
**Required state:** Before browser assistance, all generated application materials should have an explicit approval state, not merely “draft” or edited.  
**Remediation:** Add a package approval gate: `draft -> reviewed -> approved -> ready_to_apply`. Browser assistance should be blocked unless the package and fill plan are both approved/reviewed and source fingerprints are fresh.  
**Escalation needed:** No, unless the approval gate is used to satisfy a contractual/legal control.

---

### Gap 6 — Source evidence for generated claims

**Obligation / issue:** Accuracy, traceability, and hallucination control.  
**Current state:** The system uses structured outputs, low temperature for extraction, evidence snapshots, workflow traces, and quality checks. However, generated application claims may still contain unsupported or overstated statements.  
**Required state:** Claims in generated materials should be traceable to candidate profile, experience units, job requirements, or reviewed user input.  
**Remediation:** Require each generated artifact to include machine-readable source references for key claims. Add a review warning for unsupported claims. Expand tests for hallucinated skills, false credentials, inflated experience, and unsupported salary/work-authorization statements.  
**Escalation needed:** No for implementation; legal review only if product claims become regulated or contractual.

---

### Gap 7 — Sensitive field classifier coverage

**Obligation / issue:** User decision boundaries and special-category/personal data risk.  
**Current state:** The app blocks or flags several sensitive/user-decision fields such as consent, privacy, referral, internal employee status, and disability.  
**Required state:** The classifier should consistently cover consent, disability, health, criminal record, union membership, visa/work authorization, salary, start date, relocation, demographic questions, equal-opportunity monitoring, and optional marketing/data-sharing choices.  
**Remediation:** Centralize sensitive-field taxonomy in one module, add multilingual patterns, add tests using real German/English ATS field labels, and require manual review for all matches.  
**Escalation needed:** Possibly — DPO/legal input for sensitive-data categories and jurisdiction-specific employment questions.

---

## 7. Recommended next steps

1. **Keep the classification as limited-risk/transparency-relevant** for the current applicant-side product.
2. **Add explicit export-level AI disclosure/metadata** for generated packages.
3. **Add a privacy/data-flow notice** covering OpenAI uploads/calls, local storage, optional documents, Browser Use logs, and deletion.
4. **Finish the package approval gate** before browser assistance.
5. **Add a browser-assistance pre-run confirmation checklist**.
6. **Strengthen source traceability** for generated claims.
7. **Create a role/reclassification warning**: if used by employers for candidate screening/ranking, reassess as potentially high-risk.

---

## 8. Compliance memo to Head of Product

**To:** Head of Product  
**Subject:** First-pass EU AI Act audit of Job Search Automation

Job Search Automation is not high-risk under the EU AI Act in its current design because it supports the applicant’s own application preparation rather than an employer’s recruitment or candidate-selection decision. It does, however, generate AI-assisted application materials and uses AI-assisted browser workflows, so the product should be treated as transparency-relevant and should preserve strong human review controls.

The likely provider is the organization or developer placing the application into service under its own name. The likely deployer is the user or organization using it to prepare applications. OpenAI is an upstream GPAI/model provider for the LLM calls, while Browser Use and Playwright are automation/tooling components.

The strongest existing controls are the human-in-the-loop design, structured JSON storage, reviewed requirements, editable application packages, blocked sensitive fields, reviewed fill plans, source freshness checks, and the rule that Browser Use should stop before final submission. These controls should be preserved.

The main gaps are: first, generated exports do not appear to carry durable AI-assisted metadata or disclosure; second, the project needs a clearer privacy and data-flow notice for CV uploads, optional documents, OpenAI API calls, local storage, and browser logs; third, the package approval state should be completed before browser assistance is allowed.

Recommended next steps are to add AI-generated-content metadata to exports, document all personal-data flows, implement a package approval gate, add a browser-assistance confirmation checklist, and expand tests for unsupported claims and sensitive application fields. Legal/privacy review is recommended before commercial deployment, especially if the tool is hosted, used by a career agency, or connected to external job boards at scale.

This memo is not a legal opinion, not a conformity assessment, and not a certification. It is a first-pass product compliance review for design and remediation planning.

---

## 9. Reinforce section

### Components that are easy to minimize

The browser-assistance feature is the component most likely to be underestimated. Even though the system stops before final submission, it still interacts with third-party application pages and may fill personal data into live forms. That creates privacy, terms-of-service, logging, and user-agency issues.

The OpenAI API boundary is also easy to minimize. CVs, candidate data, job data, application requirements, and generated package content may be sent to an external model provider. That needs a clear user-facing data-flow explanation in any production version.

### Design decision that creates compliance burden

The decision to include Browser Use apply assistance creates the largest compliance burden. A simpler product that only generates reviewed application materials would be easier to classify and govern. The Browser Use path is still defensible because it is gated by a reviewed fill plan and stops before submission, but it needs stronger confirmation, logging, and privacy controls.

---

## 10. Stretch artifact — Transparency and human-review notice

### Draft notice for the product UI

**AI-assisted application preparation**

This tool uses AI to help extract job information, inspect application requirements, draft application materials, and map reviewed candidate information to application form fields.

AI-generated outputs may be incomplete, inaccurate, outdated, or unsuitable for a specific employer. You must review and approve all generated text, field answers, document uploads, and browser actions before using them.

The tool does not make employment decisions, does not decide whether you should apply, and does not submit applications automatically. Browser assistance may fill only reviewed fields from the approved fill plan and must stop before final submission.

Some workflows may send candidate data, CV content, job descriptions, application-page information, and generated drafts to an external AI model provider. Do not upload documents or enter data unless you are allowed to use them for this purpose.

Before using browser assistance, confirm that:

- the candidate profile is correct;
- the application package has been reviewed;
- the fill plan has been reviewed;
- sensitive or consent fields have been checked manually;
- the target application page permits this kind of assistance;
- final submission will be done only after manual inspection.

---

## 11. Final classification statement

**Final first-pass classification:** Limited risk / transparency-relevant, not high-risk as currently designed.

The system does not perform employer-side recruitment screening or candidate ranking. It supports the applicant’s preparation workflow. The main compliance work is therefore transparency, human review, personal-data governance, browser-assistance controls, and reclassification warnings if the system is ever repurposed for employer-side hiring decisions.
