# Harmful / Illegitimate Intent — Category Logic

![Harmful category flowchart](category-harmful-chart.png)

Covers illegal, unethical, deceptive, or dangerous requests. Single category with optional **sub_type**. Uses **LLM classification** plus **deterministic heuristics** for self-harm, dangerous health advice, and extreme weight-loss.

---

## Main flow: `check_harmful`

```mermaid
flowchart TD
    A[prompt] --> B[LLM classification]
    B --> C[Heuristic: self-harm / dangerous health]
    C --> D[Merge flags, sub_type, suggested_rewrite]
    D --> E[Adjust score by flags / sub_type]
    E --> F[CategoryResult]
```

---

## Heuristic: Self-harm & dangerous health — `_heuristic_self_harm_or_dangerous_health_flags`

Returns **flags**, optional **sub_type**, and **suggested_rewrite**; these are merged into the LLM result.

```mermaid
flowchart TD
    P[prompt] --> SH[Self-harm pattern?]
    SH -->|Yes, not benign context| SH_FLAG["self-harm"]
    P --> DH[Dangerous health markers?]
    DH -->|Yes, procedural/tips, not “help someone”| DH_FLAG["dangerous_health_advice"]
    P --> EW[Extreme weight-loss pattern?]
    EW -->|e.g. lose 10+ lbs in ≤7 days| EW_FLAG["dangerous_health_advice"]
    SH_FLAG --> MERGE[Merge into raw]
    DH_FLAG --> MERGE
    EW_FLAG --> MERGE
```

- **Self-harm:** suicide, self-harm, kill myself, etc. Not flagged if **benign context** (prevent, hotline, therapy, support) and no procedural/first-person intent.
- **Dangerous health:** drink bleach, choke challenge, thinspo, purging, extreme calorie/weight loss. “Help someone” context can avoid flag.
- **Extreme weight loss:** e.g. “lose X pounds in Y days” with thresholds (e.g. ≥10 lbs in ≤7 days) → dangerous_health_advice.

---

## Score adjustment: `_adjust_harmful_score`

- **No flags** (and no subtype tokens) → score = **0**.
- **Harmless subtype** (`harmless`, `benign`, `safe`) and **no flags** → score = **0**.
- **Flags** (from LLM or promoted from sub_type) → at least **40**; **high** flags → at least **70**.

```mermaid
flowchart TD
    RAW[raw + flags + sub_type] --> PROMO[If no flags but sub_type: use sub_type as flags]
    PROMO --> NF{flags empty?}
    NF -->|Yes| ZERO[score = 0]
    NF -->|No| HARM{harmless token + no flags?}
    HARM -->|Yes| ZERO
    HARM -->|No| TIER{Flag tier?}
    TIER -->|High| H[score ≥ 70]
    TIER -->|Medium / other| M[score ≥ 40]
    H --> OUT[CategoryResult]
    M --> OUT
    ZERO --> OUT
```

**High flags:** `illegal`, `criminal`, `violence`, `terrorism`, `self-harm`, `murder`.  
**Medium flags:** `impersonation`, `deception`, `fraud`, `harassment`, `dangerous_health_advice`, `eating_disorder`, etc.  
Score is **not** bumped from free-text explanation (to avoid “does not involve illegal intent” false positives).

---

## High vs medium — what’s the distinction?

| Tier | Score | Distinction | Examples |
|------|--------|-------------|----------|
| **High** | ≥ 70 | **Illegal or severe physical/psychological harm** — criminal, violent, or life-threatening. | Illegal, criminal, violence, terrorism, self-harm, murder |
| **Medium** | ≥ 40 | **Unethical, deceptive, or harmful but not necessarily illegal/violent** — fraud, misuse of info, dangerous advice. | Impersonation, deception, fraud, scam, harassment, dangerous_health_advice, eating_disorder, medical privacy violation |

**Rule of thumb:** High = “illegal or life-threatening”; medium = “against policy or harmful, but not necessarily criminal/violent.”
