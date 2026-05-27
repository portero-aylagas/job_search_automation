# GDPR Audit Pack - Javier Portero

## Scenario

**AI ranking system for internal promotions in a regional retail chain**

---

## 1. Fact Pattern

The client is a regional retail chain that wants to use AI to standardize internal promotion decisions after inconsistent performance from newly promoted assistant managers. The system would process employee profiles, sales numbers, absence records, customer complaints, disciplinary notes, training completion, manager comments, and short recorded interview answers.

The AI would score employees and deprioritize candidates considered unreliable, low-performing, or unlikely to handle pressure in leadership roles. HR managers would approve the final list, but they would normally start from the AI ranking and override it only with a documented reason. Affected people are employees applying for promotion, leadership training, or higher-responsibility shifts. Data subjects are assumed to be in the EU/EEA. Vendor location is unknown, so transfers must be checked. Because the system affects career progression, this is a high-risk employment AI case.

---

## 2. Audit Worksheet

## Section A — Data Map

| Field | Your answer |
|---|---|
| Categories of personal data | Employee identity, role, store, sales performance, absence records, customer complaints, disciplinary notes, training completion, manager comments, interview recordings/transcripts, AI scores, rankings, override logs. |
| Sources | HR system, POS/sales systems, absence system, complaint system, disciplinary records, learning platform, manager reviews, promotion interviews, AI logs. |
| Purpose 1 | Normal internal promotion and leadership-training selection. |
| Lawful basis for purpose 1 | Contract or legitimate interests. Final basis should be confirmed by legal review. |
| Purpose 2 | AI scoring, ranking, and deprioritization of candidates. |
| Lawful basis for purpose 2 | TBD — legal review. Legitimate interests may work only if a documented LIA passes purpose, necessity, and balancing. Consent is weak in employment. |
| Purpose 3 | Audit the system for bias, accuracy, consistency, complaints, and human overrides. |
| Lawful basis for purpose 3 | Legitimate interests or legal obligation, depending on local employment and AI governance requirements. |
| Retention period | HR records should follow the HR retention schedule. AI input datasets should be limited to the promotion cycle unless longer retention is justified. Interview recordings should be deleted or reduced to transcripts when no longer needed. Scores and override logs should be kept only for the appeal, dispute, or compliance period. |
| Recipients and sub-processors | HR, promotion panel, relevant managers, DPO/legal/compliance, AI vendor, cloud provider, transcription provider, analytics/logging vendor, consultant if accessing personal data. |
| International transfers | Unknown until vendor stack is confirmed. If a US or other non-EU vendor processes employee data, SCCs or another valid mechanism plus transfer-risk assessment are needed. |
| DPA requirement | A DPA is required with every processor handling employee data. |

---

## Section B — Risk and Rights

### 1. Are special-category data present or inferable?

Possibly. Absence records may reveal health, disability, pregnancy, or care responsibilities. Interview recordings may reveal disability, accent, or emotional state. Manager comments and disciplinary notes may also contain sensitive details. These fields should be excluded unless clearly necessary and legally justified.

### 2. Is there automated decision-making with legal or similarly significant effects?

Yes, there is serious Article 22 risk. Promotion affects career progression, pay, responsibility, and employment prospects. HR approval is not enough if managers mostly follow the AI ranking. Human review must be real: independent assessment, easy override, documented reasoning, and a challenge route.

### 3. Is a DPIA required?

Yes. The system scores employees, combines HR datasets, uses AI in employment decisions, affects career opportunities, and may process sensitive inferences. DPIA triggers include scoring, significant effects, vulnerable data subjects, data matching, innovative technology, and possible systematic monitoring.

### 4. What data subject friction points are likely?

Access, rectification, objection, explanation, and contestation. Employees may ask what data was used, why they ranked lower, and how to correct inaccurate comments, complaints, or disciplinary records.

### 5. What is the controller / processor split?

The retail chain is the controller. The AI vendor is a processor if it acts under the retailer's instructions. Cloud, transcription, and analytics providers may be processors or sub-processors. The consultant is likely a processor if handling employee data.

### 6. Is a DPA needed?

Yes. The DPA should cover instructions, confidentiality, security, subprocessors, audit rights, deletion or return of data, data subject request support, DPIA assistance, breach reporting, and transfer safeguards.

---

## Section C — Law Stacking

| Law | Applies? | Reason |
|---|---|---|
| GDPR | Yes | Identifiable employee data is processed and converted into derived scores. |
| AI Act | Yes, high-risk | The system is used in employment to evaluate workers and affect promotion opportunities. It adds risk management, data governance, logging, transparency, human oversight, accuracy, robustness, and documentation obligations. |
| ePrivacy | Usually secondary | It may apply if the interview platform or employee portal uses non-essential cookies, fingerprinting, or communications monitoring. |
| Data Act | Usually not applicable | No connected product or IoT-generated data is central to the scenario. |
| Digital Omnibus | Pending only | GDPR/ePrivacy/Data Act changes should not be relied on until adopted and in force. |

---

## 3. Client Recommendation Memo

**To:** Regional Retail Chain — HR, Legal, and IT  
**Subject:** GDPR and EU data-law assessment of AI promotion ranking system

### Bottom line

**Go with conditions.** The project should not launch in its current form because automatic deprioritization of employees creates high GDPR and AI Act risk. It may proceed only after a DPIA, lawful-basis review, genuine human review, employee challenge process, and vendor controls.

### Recommendation

The proposed system processes extensive employee data and creates reliability and leadership-readiness scores that directly affect promotion opportunities. This is high-risk employment processing, not ordinary HR administration. Absence records, disciplinary notes, complaints, manager comments, and interview recordings may be subjective, outdated, inaccurate, or capable of revealing sensitive information.

The first action is to complete a DPIA before go-live. It should assess necessity, proportionality, bias, data minimisation, accuracy, human review, employee transparency, appeal routes, and vendor security. High-risk fields such as absence records, disciplinary notes, and manager comments should be excluded unless the company proves they are necessary and proportionate.

The second action is to define the lawful basis per purpose. Normal promotion administration may rely on contract or legitimate interests, but AI scoring and deprioritization need separate legal review. Consent should not be the main basis because employees are not in an equal bargaining position. If special-category data is used or inferred, an Article 9 condition is required.

The third action is to redesign the HR workflow. HR managers must not rubber-stamp the AI ranking. They need access to the evidence behind the score, freedom to override, and a clear process for employees to request explanation, correction, and human reconsideration.

Residual risks remain. The model may reproduce historic bias from manager comments, complaints, or disciplinary records. Employees may challenge the system as opaque or unfair. If a non-EU vendor is used, transfer and vendor-control risks must be contractually managed.

---

## 4. Peer Review Rubric

| Criterion | Score 1–3 | Comment |
|---|---:|---|
| Clear bottom-line recommendation | 3 | The memo clearly recommends “Go with conditions” and explains that deployment should only proceed after DPIA, governance, human oversight, and transfer safeguards. |
| Lawful basis selection is justified | 2 | Legitimate interests is identified, and the need for a balancing test is mentioned. However, the answer could be stronger by separating lawful basis per purpose instead of using one broad basis for all purposes. AI scoring and automatic deprioritization should probably remain “TBD — legal review” until the LIA is completed. |
| Top actions are specific and sequenced | 3 | The top actions are clear: complete DPIA, redesign human review, and execute DPAs / transfer safeguards. The sequence is practical and fits the risk profile. |
| Residual risks are named honestly | 3 | The memo correctly names remaining risks: discrimination from inferred behavioural scores, employee trust issues, and likely regulator scrutiny. |
| Law stacking is addressed (AI Act / ePrivacy) | 3 | GDPR, AI Act, ePrivacy, and Data Act are all addressed. The AI Act high-risk classification is correctly flagged, and ePrivacy/Data Act are reasonably treated as secondary or likely not applicable. |

### Client-style response

We accept the recommendation to proceed only with conditions. The strongest concern is the current HR workflow, because requiring managers to justify overrides makes the AI ranking the default decision path and weakens the claim of meaningful human review. Before deployment, we would ask the consultant to redesign that section so HR assessment is genuinely independent and the AI output is only one input among several.

---

## 5. Optional DPIA Outline

| DPIA section | Key points |
|---|---|
| Description of processing | HR, performance, absence, complaint, disciplinary, training, manager-comment, and interview data are combined to produce promotion scores and rankings. |
| Necessity and proportionality | The business goal is valid, but each field must be justified. Lower-risk options include structured human scoring and AI used only for consistency checks. |
| Main risks | Inaccurate records, subjective comments, historic bias, indirect health/disability discrimination, weak human review, poor explainability, excessive retention, and vendor-transfer risk. |
| Mitigations | Minimise data, exclude sensitive fields where possible, require human-led decisions, provide transparency and challenge routes, run bias testing, log outputs and overrides, sign DPAs, define retention limits, and secure transfers. |

---

## 6. DPA Clause to Check

The DPA with the AI vendor should prohibit the vendor from using employee data for its own model training or product improvement unless the retailer gives explicit written authorisation and a separate lawful basis is documented.

---

## 7. UK GDPR Note

If UK employees are included, the same core analysis applies under UK GDPR. The recommendation remains **go with conditions**.

---

## 8. Mini Data Protection by Design Checklist

Highest-risk processing activity: AI scoring and deprioritization of employees for promotion decisions.

| Control | Status | Reason |
|---|---|---|
| Data minimisation | Fail / Unknown | The system uses broad HR data, including absence records, disciplinary notes, complaints, and manager comments. Each field must be justified before use. |
| Purpose binding | Unknown | It is not clear whether the data is technically restricted to promotion assessment only or could be reused for other HR analytics. |
| Access controls | Unknown | HR and relevant managers need access, but access rights must be role-based and limited to people involved in the promotion process. |
| Retention enforcement | Unknown | The proposal does not confirm automated deletion or anonymisation of interview recordings, AI scores, or audit logs. |
| Subject rights workflow | Unknown | The company must be able to handle access, correction, objection, and contestation requests within the GDPR deadline. |
| Incident response | Unknown | The proposal does not show whether there is a documented breach detection and notification process within 72 hours. |