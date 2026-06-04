# GDPR Audit 

## 1. Data Processing Brief

`job_search_automation` is a Python application for a controlled human-in-the-loop job application workflow. The core flow is: candidate profile plus job position produces a validated application package. The system stores structured candidate data, ingests job URLs, normalizes job listings, compares the candidate profile against jobs, generates tailored application material, and tracks application status.

The system processes personal data about the job applicant/candidate. This includes CV-derived identity and contact data, professional history, education, skills, languages, certifications, projects, references, target roles, target locations, salary expectations, work authorization, source documents, optional supporting documents, generated cover letters, form answers, recruiter messages, and application tracker notes. The system may also process job-board data such as company names, job URLs, apply URLs, requirements, form fields, and application-page snapshots.

Data comes mainly from the candidate/user directly, uploaded CV or supporting documents, manually entered job preferences, job URLs, extracted job descriptions, and application pages. Some data is sent to the OpenAI API for structured extraction, job normalization, requirements extraction, field mapping, and application package generation. Uploaded files may also be sent to OpenAI for downstream extraction.

Data is stored locally in JSON files under `data/`, `data/runtime/`, and derived Markdown exports under `outputs/`. Runtime data and candidate profile files are excluded from Git by `.gitignore`, which reduces accidental public exposure. Processing location is partly local, but OpenAI API processing may involve non-EU infrastructure unless the provider contract and region settings prove otherwise.

The system assists decisions affecting the candidate, especially job suitability assessment, match scoring, strategy generation, and application preparation. It does not appear to autonomously submit final applications. Human review and approval are core design principles.

Important scope note: if this is used only by the candidate for personal job-search management, GDPR controller obligations may be limited by the personal/household context. If offered to clients, other users, or candidates as a service, GDPR applies fully.

---

## 2. Personal Data Inventory

| Data category | Source | Purpose(s) | Retention period | Crosses EU border? |
|---|---|---|---|---|
| Candidate identity and contact data: name, email, phone, address, city, country, nationality, LinkedIn/GitHub/portfolio URLs | User CV upload or manual profile entry | Build candidate profile; pre-fill application material; generate form answers | Unknown; currently local JSON until user deletes | Yes / possible if sent to OpenAI for CV extraction or field mapping |
| Gender value | Extracted from CV/salutation or manual entry | Candidate identity normalization and application form support | Unknown; should be minimized and only stored if needed | Yes / possible if included in LLM calls |
| CV-derived professional data: work experience, education, skills, languages, certifications, projects, references | CV upload and optional documents | Generate application packages; match candidate to job; answer screening questions | Unknown; local JSON until deleted | Yes / possible if sent to OpenAI |
| Candidate preferences: roles, locations, remote preference, employment type, seniority, availability, salary range, work authorization | User manual input | Job matching, filtering, application strategy | Unknown; local JSON until deleted | Yes / possible if included in LLM calls |
| Optional supporting documents and file metadata | User uploads | Evidence extraction; document checklist; application upload planning | Unknown; should be tied to application need | Yes / possible if uploaded or parsed via provider |
| Job listings: title, company, source URL, apply URL, description, requirements, salary, location, dynamic fields | Job URL, extracted job page, manual input | Normalize jobs; compare with candidate; generate applications | Unknown; stored per job workspace | Usually no personal data unless job pages include contact names; page content may be sent to OpenAI |
| Application-page snapshots: forms, controls, visible text excerpts, raw HTML excerpts, embedded JSON summaries | Apply URL inspection | Discover application requirements and form fields | Unknown; should be short-lived or minimized | Possibly, if interpreted via LLM API |
| Match analysis: match score, matched/missing skills, weak points, strategy | Generated from candidate profile and job listing | Help user prioritize and tailor applications | Unknown; stored per job/tracker | Possibly if generated through LLM or shared with vendor |
| Application package: cover letters, CV tailoring notes, recruiter messages, form answers, summaries | Generated from candidate data and job requirements | Prepare application materials | Unknown; stored as JSON and Markdown export | Yes / possible if generated through OpenAI |
| Tracker data: job status, notes, generated package path, application state | User/system workflow | Track applications and workflow state | Unknown; local JSON until deleted | Usually no unless synced or sent to vendor |

Purpose limitation flag: CV and profile data collected to support a specific job application may be reused across many job applications, match scoring, and generated form answers. That is expected in this project, but the purpose should be stated clearly in the privacy notice if the tool is used beyond private self-use.

---

## 3. Role Map

| Entity | Role | Processing activity | DPA in place? |
|---|---|---|---|
| Candidate/user using the app privately | Possibly outside GDPR controller obligations for personal use | Provides own CV/profile/job preferences and reviews outputs | N/A for purely personal use |
| Project owner / app operator if offered as a service | Controller, or processor if operating for a client | Determines why candidate data is collected and how the workflow uses it | TBD |
| Client company, if deploying this for users/candidates | Controller | Determines purpose: job-search support, application generation, tracker management | Required with processors |
| Developer/team maintaining the system | Processor if handling candidate data for a client; controller if deciding purposes independently | Development, support, data handling, debugging | Required if processing client/user data |
| OpenAI API provider | Processor / sub-processor depending on contract chain | Structured extraction, file upload, LLM generation, field mapping | Required before production use |
| Browser Use / Playwright local browser flow | Usually part of the local processing environment, not necessarily separate controller | Assisted filling/upload planning through local browser | TBD depending on vendor/runtime use |
| GitHub repository | Not intended processor for runtime personal data | Source code hosting; should not contain candidate data | Candidate data excluded by `.gitignore`; no DPA needed for runtime data if no personal data is committed |
| Other cloud/vendor services | Processor or sub-processor | Hosting, analytics, logging, storage, if added later | Required if personal data is processed |

International transfer note: OpenAI processing may involve data leaving the EEA unless the applicable contract, region, and data-processing terms confirm otherwise. A production deployment should document SCCs, adequacy mechanism, EU-US Data Privacy Framework certification where applicable, and transfer risk assessment.

---

## 4. Lawful Basis Assessment

| Purpose | Proposed lawful basis | One-line justification | Flag for legal review? |
|---|---|---|---|
| Store candidate profile and CV-derived professional data | Contract, or consent if user-directed self-service | The data is necessary to provide the job-application workflow requested by the user | Yes, if commercial deployment |
| Extract structured data from CV and supporting documents | Contract | Extraction is necessary to transform user-provided documents into application material | Yes, especially if documents include sensitive data |
| Generate tailored application material | Contract | Cover letters, form answers, and recruiter messages are the core service output | Low / medium |
| Future candidate/job match analysis and scoring | Contract or legitimate interests | Disabled in the current known-job workflow; reassess transparency and profiling controls before enabling suitability analysis | Yes |
| Store tracker status and notes | Contract | Tracking application state is part of the requested service | Low |
| Send personal data to OpenAI API | Contract + processor arrangement | Provider processing is necessary for AI-assisted functions, but requires DPA and transfer safeguards | Yes |
| Reuse profile data across many jobs | Contract, with clear purpose statement | Reuse is expected by the user if the tool is explicitly for repeated applications | Medium |
| Improve the product using user data | TBD — legal review | This is a separate purpose from generating applications and should not be assumed | Yes |
| Logs/debugging containing personal data | Legitimate interests | Security and debugging may be legitimate, but logs must be minimized and time-limited | Yes |

### Legitimate Interests Assessment — logs/debugging

| Test | Answer |
|---|---|
| Legitimate interest | Maintain security, diagnose failures, and ensure reliable operation. |
| Necessity | Only minimal technical logs should be used; full CVs, generated letters, or raw profile data should not be logged unless strictly necessary. |
| Balancing test | Candidate privacy risk is high if logs contain personal job-search data. Logging must be minimized, access-controlled, and time-limited. |

---

## 5. Risk and Rights Analysis

### 5.1 Special-category data — Article 9

Special-category data is not a required functional input, but it may appear in uploaded CVs, references, optional documents, free-text notes, or application answers. Possible examples include disability, health information, nationality/ethnicity inferences, trade union references, political activities, or religious information. The system should avoid extracting or storing such data unless strictly necessary and legally justified. Sensitive form fields such as disability or consent-related fields should remain blocked until explicit user review.

### 5.2 Automated decision-making — Article 22

The system creates match scores, weak-point analysis, and application strategy, but it does not appear to make final decisions about the candidate. The main affected person is the candidate/user, and the system is advisory. Article 22 risk would increase if the system automatically applied, rejected jobs, ranked opportunities without human review, or made recommendations used by an employer or recruiter. Current human-in-the-loop design lowers the risk, but the UI should clearly show that scores are advisory.

### 5.3 DPIA trigger

A DPIA is likely required for a production deployment. Relevant EDPB criteria include profiling or scoring, use of innovative technology, potentially large-scale processing if many users are onboarded, matching/combining datasets, possible special-category data in uploaded documents, and cross-border processing through LLM providers. For private self-use, a full DPIA may not be legally required, but the same analysis is useful as an engineering control.

### 5.4 Data subject rights friction

The most difficult rights are access, erasure, rectification, and objection to profiling. Access requires the system to list what candidate data, generated artifacts, API traces, and tracker entries exist. Erasure requires deletion of local JSON, outputs, uploads, and any provider-side retained data where applicable. Rectification is operationally important because wrong CV extraction can propagate into cover letters, form answers, and match scores. The current design supports editable review, but it does not yet prove a complete rights workflow or deletion workflow.

---

## 6. Law Stacking Check

| Law | Applies? | Reason |
|---|---|---|
| GDPR | Yes, if used beyond purely personal self-use | The system processes identifiable candidate data, CVs, generated application material, and profile-based scoring. |
| AI Act | Likely limited/minimal risk for private candidate-assistance use; could change if deployed for recruitment decisions | The system assists the candidate, not an employer. It does not decide employment access. If repurposed by employers to screen candidates, high-risk employment AI issues would arise. |
| ePrivacy | Usually no / maybe | The repo does not show cookie-based tracking. ePrivacy may apply if hosted as a web app with non-essential cookies, tracking pixels, or communications-content monitoring. |
| Data Act | Usually N/A | No connected product or IoT-generated data is central. Cloud switching may become relevant only for a hosted commercial service. |

---

## 7. Client Recommendation Memo

**To:** Data Protection Officer / Legal Counsel  
**Subject:** GDPR first-pass assessment of `job_search_automation`

### Bottom line

**Proceed with conditions.** The project can continue as a controlled candidate-assistance tool, but it should not be deployed for real users until data protection documentation, processor contracts, transfer controls, retention rules, and subject-rights workflows are in place.

The system processes substantial candidate personal data: CV-derived identity and contact fields, work history, education, skills, salary expectations, work authorization, uploaded documents, generated cover letters, form answers, tracker notes, and match scores. This data is stored locally in JSON and may be sent to OpenAI for structured extraction, file processing, job analysis, field mapping, and application package generation.

The first action is to document the processing model before production use. The project needs a privacy notice, data inventory, retention schedule, records of processing activities, and clear separation between private self-use and client/user-facing deployment. The privacy notice must explain that the system uses AI to extract, transform, score, and generate application material from candidate data.

The second action is to complete vendor and transfer controls. OpenAI or any other LLM/cloud provider must be covered by a DPA, and international transfers must be documented through SCCs, adequacy, or another valid mechanism. No candidate CVs or application documents should be sent to a provider without that contract position being verified.

The third action is to implement operational rights handling. The system should support deletion, export/access, correction of extracted data, and objection or opt-out from profiling-style match scoring. The existing human-review design is positive, but rights handling must be explicit rather than assumed.

Residual risks remain. Uploaded documents may contain special-category data not expected by the system. Generated outputs may contain inaccurate or misleading claims if extraction is wrong. Provider-side retention and cross-border processing remain compliance risks unless contractually controlled.

This memo is not a legal opinion, DPIA, or certification. Legal counsel should review the final deployment model before relying on this assessment.

---

## 8. Accountability Test

| Document / evidence | Exists? | Gap |
|---|---|---|
| Data inventory | Partial | This audit creates a first version, but the live app should maintain one. |
| Records of processing activities | No / Unknown | Required for production or client-facing deployment. |
| Privacy notice | No / Unknown | Needed before real users provide CVs or profile data. |
| DPA with OpenAI / LLM provider | Unknown | Must be confirmed before processing real user data. |
| International transfer mechanism | Unknown | Needs SCCs/adequacy/DPF verification depending on provider setup. |
| LIA | No / Unknown | Needed for logging, product improvement, or other non-core purposes. |
| DPIA | No | Recommended for production because profiling, LLM processing, documents, and transfer risks combine. |
| Retention schedule | No / partial | `.gitignore` protects local runtime data from Git, but deletion periods are not defined. |
| Subject rights workflow | No / partial | Editable data exists, but access/export/delete workflow is not documented as GDPR process. |
| Security/access control documentation | Partial | Local storage and `.gitignore` help, but access control, encryption, and incident response are not documented. |
| Vendor list/subprocessor list | No / Unknown | Needed if deployed to users/clients. |

Accountability conclusion: the project has good engineering controls around human review and local data separation, but current documentation would not be enough to demonstrate full GDPR compliance to a regulator for production use.

---

## 9. Reinforce

### 9.1 Regulator Documentation List

| Documentation item | Exists? | Notes |
|---|---|---|
| DPA | Unknown | Required with OpenAI and any hosting/logging provider. |
| LIA | No | Needed for logs, analytics, or product improvement uses. |
| DPIA | No | Recommended before deployment. |
| Privacy notice | No / Unknown | Must explain AI extraction, generation, scoring, storage, providers, retention, and rights. |
| Retention schedule | No | Define deletion for CVs, uploaded documents, outputs, logs, job workspaces, and tracker data. |
| Records of processing activities | No | Needed for organizational accountability. |
| Security documentation | Partial | `.gitignore` excludes sensitive runtime files, but access control/encryption is not documented. |
| Data subject rights workflow | No | Must support access, correction, deletion, and objection. |
| Transfer mechanism | Unknown | Must be documented for OpenAI/non-EU processing. |
| Vendor/subprocessor list | No / Unknown | Required for production deployment. |

### 9.2 Legal-review Preparation — OpenAI Processing of CV Data

| Question | Information to prepare |
|---|---|
| What data is sent? | CV text, identity/contact fields, work history, education, skills, preferences, application answers, and uploaded documents where file extraction is used. |
| Who provided it? | Candidate/user directly. |
| Original purpose | Generate and manage job application materials. |
| New purpose | AI extraction, normalization, scoring, field mapping, and package generation. |
| Is consent available? | Possible, but contract may be more appropriate for core service delivery. Consent may be needed for optional processing. |
| Is legitimate interests plausible? | Possibly for security/logging, weak for unrelated product improvement. |
| Does Article 9 apply? | Possible if CVs or documents contain health, disability, union, political, religious, or ethnic-origin data. |
| Does data cross EU border? | Unknown until provider region/contract is confirmed. |
| What counsel needs | Deployment model, user type, provider DPA, retention terms, API data-use policy, transfer mechanism, and whether data is used for product improvement. |

---

## 10. Data Protection by Design Checklist

Highest-risk processing activity: sending CV/profile/application data to an LLM provider for extraction, analysis, field mapping, and generated application material.

| Design principle | Current state of system | Pass / Fail / Unknown | Required change |
|---|---|---|---|
| Data minimisation | The app sends structured data needed for AI workflows, but exact prompt payload minimisation is not proven for all workflows. | Unknown | Review each LLM call and send only fields necessary for that task. |
| Purpose binding | The project has clear workflow purposes, but technical restriction against unrelated reuse is not fully documented. | Partial | Add policy and code boundaries preventing product-improvement reuse without separate lawful basis. |
| Access controls | Local files are stored on the user's machine; role-based access is not relevant for private use but needed for hosted use. | Unknown | Add authentication, authorization, and least-privilege access if deployed as a service. |
| Retention enforcement | Runtime data is excluded from Git, but automated deletion/anonymisation is not documented. | Fail / Unknown | Add deletion controls and retention schedule for CVs, outputs, logs, and provider files. |
| Subject rights workflow | Data is editable, but formal access/export/delete workflow is not documented. | Partial | Add export/delete functions and rights-handling procedure. |
| Incident response | `.gitignore` reduces accidental disclosure, but breach process is not documented. | Unknown | Add incident response plan and 72-hour breach notification procedure for production use. |
