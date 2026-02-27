# Jailbreak — Category Logic

![Jailbreak category flowchart](category-jailbreak-chart.png)

Detects attempts to override safety, ignore instructions, reveal system prompt, or obtain restricted content under a “benign” pretext. Uses **LLM classification** plus **deterministic heuristics** for pretext + privilege escalation.

---

## Main flow: `check_jailbreak`

```mermaid
flowchart TD
    A[prompt] --> B[LLM classification]
    B --> C[Heuristic: pretext illegal how-to]
    B --> D[Heuristic: privileged role]
    C --> E[Merge heuristic flags into LLM result]
    D --> E
    E --> F[Adjust score by flags]
    F --> G[CategoryResult]
```

---

## Heuristic: Pretextual illegal/how-to — `_heuristic_pretextual_illegal_howto_flags`

Detects: “screenplay / fiction / curiosity / research” + procedural (“step by step”, “how to”) + **illegal or harmful topic** (bomb, drugs, hack, fraud, etc.). Avoids flagging pure writing-craft questions.

```mermaid
flowchart TD
    P[prompt] --> PR[Pretext marker?]
    PR -->|No| NONE[no flags]
    PR -->|Yes| PROC[Procedural marker?]
    PROC -->|No| NONE
    PROC -->|Yes| WRITE[“how to write” only?]
    WRITE -->|Yes, no other procedural| NONE
    WRITE -->|No| ILL[Illegal/harmful topic?]
    ILL -->|No| NONE
    ILL -->|Yes| FLAG["benign_pretext_for_harmful_howto"]
```

**Pretext examples:** screenplay, fiction, roleplay, hypothetically, for research, for education, artistic project.  
**Procedural:** step by step, walk me through, detailed instructions, how to, recipe, blueprint.  
**Illegal/harmful:** bomb, explosive, drugs, hack, phishing, malware, steal, fraud, fake id, etc.

---

## Heuristic: Privileged role — `_heuristic_privileged_role_flags`

Detects: model cast as **admin/root** + **resource** (users, accounts, database, logs, delete data).

```mermaid
flowchart LR
    P[prompt] --> R[Role markers]
    P --> M[Resource markers]
    R --> BOTH{Both present?}
    M --> BOTH
    BOTH -->|Yes| FLAG["privilege_escalation_admin_role"]
    BOTH -->|No| NONE[no flags]
```

**Role:** “you are system administrator”, “you are root”, “you have admin privileges”, etc.  
**Resource:** user, account, database, log, deactivated, delete user data, etc.

---

## Score adjustment: `_adjust_jailbreak_score`

- **No flags** → score = **0**.
- **Any flags** → score at least **40** (medium).
- **High flags** → score = max(score, **70**).

```mermaid
flowchart TD
    RAW[raw score + flags] --> NF{flags empty?}
    NF -->|Yes| ZERO[score = 0]
    NF -->|No| HIGH{High flag?}
    HIGH -->|Yes| H[score ≥ 70]
    HIGH -->|No| M[score ≥ 40]
    H --> OUT[CategoryResult]
    M --> OUT
    ZERO --> OUT
```

**High flags:** `bypass_safety`, `disable_safety`, `ignore_instructions`, `system_override`, `reveal_system_prompt`, `prompt_injection`.

---

## High vs medium — what’s the distinction?

| Tier | Score | Distinction | Examples |
|------|--------|-------------|----------|
| **High** | ≥ 70 | **Explicit safety-bypass or system override** — user is directly asking the model to ignore rules, reveal internals, or act as if unconstrained. | Ignore instructions, disable safety, bypass safety, reveal system prompt, system override, prompt injection |
| **Medium** | ≥ 40 | **Indirect or contextual jailbreak** — restricted content under a pretext, or privilege escalation, without literal “ignore instructions.” | Benign pretext for harmful how-to (e.g. screenplay + step-by-step + illegal topic), privilege escalation (admin/root + user/database access) |

**Rule of thumb:** High = “do not follow your rules / show me your prompt”; medium = “get restricted content by framing or role.”
