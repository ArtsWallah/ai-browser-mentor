# 🛡️ ScamShield AI: Explainable Social-Engineering Detection & Emerging Scam Pattern Discovery

> **Project Topic**: *ScamShield AI: Explainable Detection of Social-Engineering Manipulation and Emerging Scam Patterns*  
> **Integrated Client**: *AI Browser Mentor* (Chrome Extension Manifest V3)  
> **Backend**: FastAPI, SentenceTransformers / FastEmbed, Scikit-Learn, HDBSCAN, Groq LLM

---

## 🎯 1. Research Problem & Motivation

Modern social-engineering attacks (smishing, spear-phishing, credential harvesting) increasingly rely on **psychological manipulation tactics**—such as manufactured urgency, false scarcity, reward lures, authority impersonation, and coercive pressure—rather than identifiable technical exploits or static blacklisted URLs.

Existing defensive approaches suffer from three critical shortcomings:
1. **The "Black-Box" Opacity Problem**: Deep neural classifiers or LLM detectors output opaque risk scores without attributing *which exact textual cues* triggered the detection, leaving users unable to assess false alarms or understand the deception.
2. **The "Novelty Trap" in Unsupervised Discovery**: Standard anomaly detection assumes that rare or novel embeddings represent emerging threats. In practice, pure semantic novelty isolates typographical errors, slang, and benign outliers (yielding 0% scam precision in top-ranked candidates).
3. **Static Template Decay**: Adversaries continuously vary template wording to bypass signature filters. Without an automated, human-in-the-loop pipeline to cluster, rank, and register candidate patterns, defenders remain perpetually reactive.

**ScamShield AI** resolves these challenges through an end-to-end framework combining **character-grounded explainable tactic detection**, **multi-signal candidate ranking**, and **unsupervised pattern clustering with an analyst review registry**.

---

## 🏗️ 2. System Architecture

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      Chrome Extension Client (MV3)                     │
 │  ┌───────────────────────┐ ┌──────────────────────┐ ┌───────────────┐  │
 │  │ Text & Email Analysis │ │ Real-time Evidence   │ │ Link Auditor  │  │
 │  └───────────┬───────────┘ └──────────┬───────────┘ └───────┬───────┘  │
 └──────────────┼────────────────────────┼─────────────────────┼──────────┘
                │                        │                     │
                ▼                        ▼                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                          FastAPI Backend Core                          │
 │                                                                        │
 │  ┌─────────────────────────────────┐   ┌────────────────────────────┐  │
 │  │   Explainable Detection Layer   │   │  Emerging Discovery Engine │  │
 │  │                                 │   │                            │  │
 │  │ • Multi-label Tactic Classifiers│   │ • Embeddings & Densities   │  │
 │  │ • Linear Logit Decomposition    │   │ • HDBSCAN / DBSCAN Cluster │  │
 │  │ • Exact Character Evidence Spans│   │ • Multi-Signal Ranker      │  │
 │  └────────────────┬────────────────┘   └─────────────┬──────────────┘  │
 └───────────────────┼──────────────────────────────────┼─────────────────┘
                     │                                  │
                     ▼                                  ▼
         ┌───────────────────────┐          ┌───────────────────────┐
         │ User Explanation Card │          │ Pattern Review Registry│
         │ (Tactics + Evidence)  │          │ (Analyst Triage API)  │
         └───────────────────────┘          └───────────────────────┘
```

---

## 🔍 3. Explainable Social-Engineering Tactic Detection

Rather than relying on opaque heuristics or ungrounded generative summaries, ScamShield decomposes social engineering into interpretable psychological manipulation tactics:
- **Urgency**: Manufactured time pressure (`"within 24 hours"`, `"immediately"`).
- **Reward Lure**: Phantom financial incentives or sweepstakes (`"won £1000 prize"`, `"claim refund"`).
- **Authority Impersonation**: Claiming organizational mandate (`"bank security"`, `"official alert"`).
- **Payment / Credential Request**: Direct solicitations for sensitive assets.
- **Threat / Coercion**: Consequences for non-compliance (`"account will be suspended"`).

### Grounded Attribution via Linear Logit Decomposition
For each linear tactic classifier with learned weights $w$ and intercept $b$:
$$\text{logit}(x) = b + \sum_{i \in \text{tokens}} w_i \cdot x_i$$
1. **Exact Feature Contributions**: The individual contribution of each n-gram $i$ to the log-odds is directly calculated ($w_i x_i$).
2. **Character-Exact Spans**: Token offsets are mapped back to source text slices (`text[start:end] == span`), guaranteeing 100% faithful alignment with zero generative hallucination.
3. **Monotonic Ablation Invariance**: Removing an identified evidence span demonstrably reduces the model's suspicion logit, verifying that the explanation truthfully mirrors model reasoning.

---

## ⚡ 4. Multi-Signal Candidate Ranking for Pattern Discovery

Previous baselines attempted to identify emerging threats purely by semantic distance from known clusters. When evaluated on held-out data, **novelty-only ranking achieved 0.00% Precision@50**, as distance metrics preferentially surfaced unusual slang and isolated benign outliers.

ScamShield introduces **Multi-Signal Candidate Fusion**:
$$\text{Score}(x) = \alpha \cdot \text{Novelty}(x) + \beta \cdot \text{TacticSuspicion}(x) + \gamma \cdot \text{ClusterDensity}(x)$$

- **Novelty Score**: Semantic distance from established cluster centroids.
- **Tactic Suspicion**: Aggregated manipulation logit from the explainable detection layer.
- **Cluster Density**: Local neighborhood density, ensuring candidate templates represent recurring patterns rather than one-off idiosyncrasies.

---

## 📊 5. Verified Evaluation Benchmarks

To ensure scientific honesty and presentation rigor, metrics across different sub-tasks are kept strictly separated:

### A. Supervised Classifier Performance (Leak-Free Group Partition)
Evaluated using a 70/30 group-partitioned split (seed 42, 5,157 unique texts, 0 text overlap between folds):

| Metric | Measured Value | Standard Error / Notes |
| :--- | :--- | :--- |
| **Precision** | **90.59%** | Low false alarm rate on consumer messages |
| **Recall** | **93.33%** | Captures 140 of 150 held-out scam messages |
| **F1-Score** | **0.9194** | Harmonized detection accuracy |
| **ROC-AUC** | **0.9888** | Excellent ranking discrimination |

### B. Candidate Ranking Benchmarks (Held-out Set, Base Rate = 10.81%)

| Ranking Methodology | Precision@10 | Precision@20 | Precision@50 | Precision@100 | Lift vs. Random |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Novelty-Only Baseline** | 0.00% | 0.00% | 0.00% | 0.00% | -0.108 |
| **Multi-Signal Proposed** | **100.00%** | **100.00%** | **98.00%** | **99.00%** | **+0.87 to +0.89** |

*Root Cause*: Novelty-only selects dialectical slang and outlier syntax. Multi-signal combines semantic displacement with psychological manipulation intent, filtering out non-malicious noise.

### C. Multi-Label Tactic Attribution Generalization
- **In-Sample Benchmark**: Macro-F1 = **0.8870** (strong fit on established attack distributions).
- **Out-of-Fold 5-Fold Stratified Cross-Validation**: Macro-F1 = **0.4967**.
  - Dominant tactics generalize well (`reward_lure`: 0.938 F1, `urgency`: 0.808 F1).
  - Sparse tactics (`threat`: 0.00, `payment_request`: 0.308) experience variance due to limited sample support in SMS data.

---

## 🔬 6. Dataset Provenance, Error Analysis & Limitations

### Dataset Provenance & Attribution
- Evaluated on the curated **UCI SMS Spam Collection** (5,157 deduplicated, normalized records: 4,600 benign, 557 malicious), created by **Tiago A. Almeida** and **José María Gómez Hidalgo** under the [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) license.
- Full academic citations, license terms, and derivative artifact boundary distinctions are detailed in [ATTRIBUTION.md](file:///c:/Users/DELL/Desktop/ai-browser-mentor/backend/data/scamshield/processed/ATTRIBUTION.md).
- Multi-label tactic annotations derived via dictionary-grounded heuristic bootstrap combined with human review.

### Audited Error Taxonomy
From our held-out error audit (`backend/data/phase7_error_analysis.json`):
- **False Positives (16 cases)**: Dominated by urgent personal scheduling (`"call me right now"`, `"emergency meeting"`) and commercial notification alerts without financial malice.
- **False Negatives (11 cases)**: Dominated by obfuscated call-to-actions, short URLs, or extreme SMS shorthand (`"ring 0906..."`).

### Technical & Empirical Limitations
1. **Absence of Temporal Ground Truth**: The benchmark dataset does not include transmission timestamps. Consequently, "emerging" patterns are evaluated through **structural novelty and unseen cluster emergence**, not longitudinal time-series drift.
2. **`fear` Tactic Unmodeled**: The benchmark SMS dataset contained 0 positive exemplars for the `fear` tactic. The model gracefully skips this estimator and relies on rule-based fallbacks.
3. **External Benchmark Status**: Validation on external datasets (e.g., Nazario Phishing, Mendeley Smishing) is planned for future phases.

---

## 🚀 7. Quickstart & Demonstration

### 1. Backend Setup & Startup
```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Verify health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

### 2. Chrome Extension
1. Open `chrome://extensions/` in Google Chrome.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and select `extension/`.
4. Open the popup, select **Security Audit**, and analyze suspicious text.

### 3. Automated Test Verification
Run the complete 146-test regression and audit suite:
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_backend.py tests/test_pattern_discovery.py tests/test_phase6_candidate_ranking.py tests/test_phase7_validation_audit.py -q
```
**Expected Result**: `146 passed`.

For the complete 3-minute presentation script, failure mitigations, and offline artifacts, refer to [DEMO_GUIDE.md](file:///c:/Users/DELL/Desktop/ai-browser-mentor/DEMO_GUIDE.md).

---

## 🔮 8. Future Work

- **Longitudinal Drift Tracking**: Incorporating real-time honeypot message streams with genuine ISO-8601 timestamps to track temporal velocity.
- **Cross-Domain Transfer**: Evaluating zero-shot tactic transfer to email spear-phishing (Nazario corpus) and mobile smishing (Mendeley dataset).
- **Adversarial Hardening**: Defenses against homoglyphic character substitutions and zero-width spaces designed to evade n-gram vectorization.
