# Dataset Attribution & Provenance Notice

## 1. Upstream Source Dataset: SMS Spam Collection

The file [`uci_sms_clean.csv`](file:///c:/Users/DELL/Desktop/ai-browser-mentor/backend/data/scamshield/processed/uci_sms_clean.csv) is derived from the **SMS Spam Collection v.1**, created by **Tiago A. Almeida** and **José María Gómez Hidalgo**.

- **Repository**: [UCI Machine Learning Repository: SMS Spam Collection](https://archive.ics.uci.edu/dataset/228/sms+spam+collection)
- **Primary Authors**:
  - Tiago A. Almeida (Department of Computer Science, Federal University of São Carlos, UFSCar, Brazil)
  - José María Gómez Hidalgo (R&D Department, Optenet, Spain)
  - Akibo Yamakami (School of Electrical and Computer Engineering, University of Campinas, UNICAMP, Brazil)

### Primary Academic Citations
When utilizing or redistributing text from this benchmark collection, cite the original publications:

1. **DocEng '11**:
   > Almeida, T. A., Gómez Hidalgo, J. M., and Yamakami, A. (2011). *Contributions to the Study of SMS Spam Filtering: New Collection and Results.* In Proceedings of the 2011 ACM Symposium on Document Engineering (DocEng '11), Mountain View, California, USA, pp. 259–262. ACM. DOI: [10.1145/2022402.2022449](https://doi.org/10.1145/2022402.2022449).

2. **ICMLA '12**:
   > Gómez Hidalgo, J. M., Almeida, T. A., and Yamakami, A. (2012). *On the Validity of a New SMS Spam Collection.* In Proceedings of the 11th IEEE International Conference on Machine Learning and Applications (ICMLA '12), Boca Raton, Florida, USA, vol. 2, pp. 240–245. IEEE. DOI: [10.1109/ICMLA.2012.189](https://doi.org/10.1109/ICMLA.2012.189).

---

## 2. Upstream License & Redistribution Conditions

- **License**: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
- **Summary of Terms**:
  - **Attribution**: You must give appropriate credit to the authors (Tiago A. Almeida and José María Gómez Hidalgo), provide a link to the license, and indicate if changes were made.
  - **ShareAlike**: Not required under CC BY 4.0.
  - **No Additional Restrictions**: You may not apply legal terms or technological measures that legally restrict others from doing anything the license permits.

---

## 3. Dataset Preprocessing & Cleaning Notice

In accordance with CC BY 4.0 requirements to indicate modifications, the source corpus was processed for the ScamShield AI evaluation suite as follows:
- **Deduplication**: Exact-duplicate records were consolidated to prevent cross-split data leakage.
- **Normalization**: UTF-8 encoding normalization and whitespace trimming were applied across message texts.
- **Header Structure**: Standardized schema into `id`, `label` (0 for ham, 1 for spam), `message`, and `source` (`UCI_SMS`).

---

## 4. Distinction Regarding Derivative & Project Artifacts

> [!IMPORTANT]
> **Independent Licensing Boundary**:
> Do not assume that every derived dataset, model artifact, or annotation file has the same license as the original upstream dataset.

- **Upstream Message Texts (`uci_sms_clean.csv`)**: Governed by Creative Commons Attribution 4.0 International (CC BY 4.0) with required author citation.
- **Multi-Label Tactic Annotations & Heuristic Dictionaries**: Developed specifically for the ScamShield research project to label social-engineering tactics (`urgency`, `reward_lure`, `credential_request`, etc.). Governed by the repository project license.
- **Trained Model Artifacts (`.pkl`, `.joblib`)**: Compiled feature spaces and weight matrices trained under the ScamShield architecture.
- **Discovered Pattern Registry (`pattern_registry.json`)**: Machine-generated cluster summaries and human analyst review decisions produced during experiment runs.
