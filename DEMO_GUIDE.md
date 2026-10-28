# ScamShield AI — Project Demonstration Guide

**Project Topic**: *ScamShield AI: Explainable Detection of Social-Engineering Manipulation and Emerging Scam Patterns*  
**Date**: October 2026  
**Target Environment**: Windows (PowerShell), Python 3.10+, Chrome Extension (Manifest V3)

---

## 1. Quick Startup Checklist (Under 60 Seconds)

### Step 1: Start the FastAPI Backend
Open PowerShell and navigate to the project backend directory:
```powershell
cd c:\Users\DELL\Desktop\ai-browser-mentor\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
> **Verification**: Open [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) in your browser.  
> Expected Response: `{"status":"ok","groq_configured":true,"scamshield_configured":true}`.

### Step 2: Load / Reload the Chrome Extension
1. Open Google Chrome and go to `chrome://extensions/`.
2. Ensure **Developer mode** toggle (top right) is **ON**.
3. If not loaded: Click **Load unpacked** and select `c:\Users\DELL\Desktop\ai-browser-mentor\extension`.
4. If already loaded: Click the **reload (circular arrow)** button on the *AI Browser Mentor* card.
5. Pin the extension to your Chrome toolbar.
6. Open the extension popup: verify that the status indicator displays **Connected** (green pill).

---

## 2. Live Demonstration Flow (3-Minute Script)

### Demo Part A: Explainable Scam & Manipulation Detection (60s)
1. **Scenario**: Analyzing a high-risk social engineering message in real-time.
2. In the Extension Popup, switch to the **Security Audit** tab (or call the `/scamshield/analyze-text` API directly).
3. Paste this safe demonstration message:
   ```text
   URGENT: Your account has been flagged for suspicious activity and will be suspended within 24 hours. Call 08001234 immediately to verify your identity and claim your refund.
   ```
4. Click **Analyze Text**.
5. **Expected Output & Interpretation**:
   - **Risk Level / Suspicion Score**: High / > 0.85.
   - **Detected Tactics**:
     - `urgency`: Flags temporal coercion (`"URGENT"`, `"immediately"`, `"within 24 hours"`).
     - `reward_lure`: Flags incentive bait (`"claim your refund"`).
   - **Evidence Spans**: Character-exact substrings highlighting exactly which words triggered the prediction (`span[start:end] == token`).
   - **Model Transparency**: Linear logit decomposition showing model feature contribution and limitations note.
6. **Negative Control (Benign Message)**:
   ```text
   Hi John, could you review the meeting agenda for tomorrow afternoon? Let me know if you have any feedback.
   ```
   - **Result**: Suspicion ~ 0.00, No manipulative tactics flagged.

---

### Demo Part B: Multi-Signal Candidate Ranking & Emerging Pattern Discovery (90s)
Demonstrate the research contribution: discovering uncatalogued scam templates without relying solely on semantic novelty.

#### Live Command
In a PowerShell terminal inside `backend/`:
```powershell
.\.venv\Scripts\python.exe scamshield_discovery_pipeline.py --max-samples 100 --min-cluster-size 3
```
*Note*: If demonstrating on a live projector where you want instantaneous response without waiting for embedding compute, see the **Fallback Demo** in Section 6 below.

#### Inspecting the Human-Review Pattern Registry
1. Open [http://127.0.0.1:8000/scamshield/discovery/patterns](http://127.0.0.1:8000/scamshield/discovery/patterns) in Chrome.
2. Observe the returned JSON:
   - `total_registered`: 430 patterns catalogued.
   - `pending_review`: Patterns flagged by multi-signal ranking requiring analyst sign-off.
   - `categories`: Breakdown by tactic combination (`urgency + reward_lure`, `impersonation`, etc.).
3. Showcase Analyst Review Action via PowerShell:
   ```powershell
   curl.exe -X POST "http://127.0.0.1:8000/scamshield/discovery/review" `
     -H "Content-Type: application/json" `
     -d '{"pattern_id": "PATTERN-2026-0001", "action": "accept", "reviewed_by": "evaluator", "assigned_tactics": ["urgency", "reward_lure"], "notes": "Verified emerging smishing template."}'
   ```
   Returns updated status: `"accepted"`.

---

## 3. Explaining Tactic Evidence, Logit Contributions & Limitations

When presenting the explainability mechanism to evaluators, highlight:
1. **Linear Logit Decomposition**:
   - For any detected tactic, the probability is derived from $P = \sigma(w^T x + b)$.
   - Each TF-IDF feature contributes $w_i x_i$ to the log-odds.
   - We extract the top-contributing tokens and map them back to character offsets `[start, end]` in the raw user string.
2. **Ablation Invariance**:
   - Removing the highlighted evidence span strictly decreases the tactic score, confirming that the explanation directly reflects model decision logic.
3. **Transparent Limitations (Research Honesty)**:
   - **`fear` tactic model**: Disclose that `fear` had 0 positive training samples in the baseline dataset and is currently unmodeled; the system falls back to heuristic keyword cues.
   - **Domain limitation**: Evaluated on SMS communication; complex multi-turn dialog or adversarial character obfuscation (leetspeak) requires additional normalizers.

---

## 4. Verified Evaluation Benchmarks (Cheat Sheet for Questions)

Keep metrics rigorously separated during your presentation:

| Metric Category | Target / Task | Verified Result | Evaluation Split / Protocol |
| :--- | :--- | :--- | :--- |
| **Supervised Classifier** | Phishing / Spam Classification | **Precision: 90.6%, Recall: 93.3%, F1: 0.919, ROC-AUC: 0.989** | Leak-free GroupKFold (70/30 split, seed 42, 0 group overlap) |
| **Multi-Signal Ranking** | Top Candidate Identification | **P@10: 100%, P@20: 100%, P@50: 98.0%, P@100: 99.0%** | Held-out 1,548 samples (Lift vs. random = +0.87 to +0.89) |
| **Novelty-Only Baseline** | Top Candidate Identification | **P@10: 0.0%, P@50: 0.0%** | Novelty alone selects outliers/typos, failing spam triage |
| **Tactic Detection (In-Sample)** | Multi-label Tactic Attribution | **Macro-F1: 0.8870** | Saved model evaluation on known patterns |
| **Tactic Detection (Out-of-Fold)** | Generalization on Held-out Tactics | **Macro-F1: 0.4967** | 5-Fold Stratified CV (`reward_lure`: 0.938, rare classes sparse) |

### Important Research Caveats:
- **No Temporal Emergence Claim**: Because the benchmark dataset (UCI SMS) lacks timestamps, emergence is evaluated via *structural novelty* and *unseen cluster density*, not time-series drift.
- **External Dataset Benchmark**: External validation on live phishing feeds (Nazario / Mendeley Smishing) is scheduled as post-demonstration work.

---

## 5. Troubleshooting & Failsafes

| Failure Symptom | Cause | Immediate Fix |
| :--- | :--- | :--- |
| **Backend connection refused (red pill)** | Uvicorn server is not running | Run `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| **Extension popup blank or unresponsive** | Chrome background worker asleep | Go to `chrome://extensions/`, click circular **Reload** icon on ScamShield card |
| **Port 8000 already in use** | A dangling Python process holds port 8000 | In PowerShell: `Get-Process python \| Stop-Process -Force` then restart uvicorn |
| **`scamshield_configured: false` on `/health`** | Model path missing in `.env` | Ensure `backend/.env` has `SCAMSHIELD_MODEL_PATH=C:/Users/DELL/Desktop/ScamShield-AI/models/tfidf_multilabel_baseline.joblib` |
| **Content script cannot extract webpage text** | Restricted chrome page (e.g. `chrome://`) | Navigate to any standard HTTP/HTTPS page or use the Extension's direct text input |

---

## 6. Offline Fallback Demonstration (Zero-Latency Guarantee)

If the presentation venue lacks internet access or live execution is constrained:

1. **Saved Discovery Artifact**: Open `backend/data/discovery_results.json`.
   - Point out the cluster assignments, silhouette scores, and multi-signal ranks generated during the audited evaluation.
2. **Phase 7 Error Analysis Artifact**: Open `backend/data/phase7_error_analysis.json`.
   - Highlights 16 False Positives and 11 False Negatives with detailed root-cause taxonomy (e.g., informal abbreviations, boundary ambiguity).
3. **Execute the Full Automated Test Suite**:
   ```powershell
   cd c:\Users\DELL\Desktop\ai-browser-mentor\backend
   .\.venv\Scripts\python.exe -m pytest tests/test_backend.py tests/test_pattern_discovery.py tests/test_phase6_candidate_ranking.py tests/test_phase7_validation_audit.py -q
   ```
   **Output**: `146 passed` in under 15 seconds. This provides definitive, live proof of system stability and validity.
