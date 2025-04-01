# Actor Needs & Scoring System

This document outlines how actor motivations are modeled in the economic simulation. Each actor evaluates their current situation based on the commodities they possess, assigning utility scores based on fulfilling hierarchical needs. Utility includes marginal gains for certain commodities, modeling diminishing returns realistically.

## Scoring Model Overview

Actors score their status each turn based on a clear hierarchy of needs. The total score is the sum of scores across all needs, including marginal utilities where applicable.

---

## 1. Basic Needs

Actors have strong penalties for unmet basic needs, driving essential economic behavior.

### 1.1 Food

- **Baseline need:** Must consume at least 1 food per day.
- **Penalty if unmet:** `-25` points.
- **Marginal Utility:**  
  Each additional unit of food provides diminishing marginal utility, calculated as:
  
  \[
  \text{Utility}_{food}(qty) = 15 \times (1 - e^{-1.0 \times qty})
  \]

| Food Quantity | Utility (rounded) |
|---------------|-------------------|
| 0             | -25 (penalty)     |
| 1             | 9                 |
| 2             | 13                |
| 3             | 14                |
| 4+            | ~15 (maxed out)   |

### 1.2 Shelter (Housing)

- **Baseline need:** At least one house (non-transportable facility).
- **Penalty if unmet:** `-25` points.
- **Marginal Utility:** None. Additional houses provide no utility.

| Houses | Utility |
|--------|---------|
| 0      | -25     |
| 1+     | +15     |

### 1.3 Clothing

- **Baseline need:** At least 1 set of clothing.
- **Penalty if unmet:** `-15` points.
- **Marginal Utility:**  
  Provides diminishing marginal utility up to a maximum of 10 sets:

\[
\text{Utility}_{clothing}(qty) = 10 \times (1 - e^{-0.3 \times qty})
\]

| Clothing Sets | Utility (rounded) |
|---------------|-------------------|
| 0             | -15 (penalty)     |
| 1             | 3                 |
| 2             | 5                 |
| 5             | 8                 |
| 10+           | ~10 (maxed out)   |

---

## 2. Safety Needs

Safety needs encourage actors to establish financial and practical security.

### 2.1 Money (Cash Savings)

- **Baseline need:** At least 100 units of currency on hand.
- **Penalty if unmet:** `-10` points.
- **Marginal Utility:**  
  Utility increases up to a maximum of ~300 currency units:

\[
\text{Utility}_{money}(qty) = 12 \times (1 - e^{-0.02 \times qty})
\]

| Money Qty | Utility (rounded) |
|-----------|-------------------|
| 0         | -10 (penalty)     |
| 50        | 6                 |
| 100       | 10                |
| 200       | 12 (near max)     |
| 300+      | ~12 (maxed out)   |

### 2.2 Simple Tools

- **Baseline need:** At least one set of simple tools.
- **Penalty if unmet:** `-10` points.
- **Marginal Utility:**  
  Additional tools provide minor marginal utility up to 3 sets:

\[
\text{Utility}_{tools}(qty) = 8 \times (1 - e^{-1.0 \times qty})
\]

| Tool Sets | Utility (rounded) |
|-----------|-------------------|
| 0         | -10 (penalty)     |
| 1         | 5                 |
| 2         | 7                 |
| 3+        | ~8 (maxed out)    |

---

## 3. Social Needs (Interim Design)

Social needs reflect actors' desire for diverse commodities and comfort items, modeled simply for now:

- **Baseline need:** Possess at least 2 different commodity types (beyond basic/safety commodities).
- **Penalty if unmet:** No penalty (neutral).
- **Marginal Utility:** +3 utility per additional unique commodity type beyond the first, up to a maximum of 5 different types:

| Unique Commodities | Utility |
|--------------------|---------|
| 0-1                | 0       |
| 2                  | 6       |
| 3                  | 9       |
| 4                  | 12      |
| 5+                 | 15      |

*Note: Future iterations can refine this by adding specific luxury commodities.*

---

## Example Full Actor Scoring

Assume the actor currently has:

- Food: 2 units
- Shelter: 1 house
- Clothing: 3 sets
- Money: 150 units
- Simple Tools: 1 set
- Unique extra commodities: 3 types (for social)

The calculation would be:

| Need         | Quantity | Utility Calculation                | Utility |
|--------------|----------|------------------------------------|---------|
| **Food**     | 2 units  | ~13 points                         | +13     |
| **Shelter**  | 1 house  | Fully satisfied                    | +15     |
| **Clothing** | 3 sets   | ~6 points                          | +6      |
| **Money**    | 150      | ~11 points                         | +11     |
| **Tools**    | 1 set    | ~5 points                          | +5      |
| **Social**   | 3 types  | 9 points                           | +9      |
| **TOTAL**    |          |                                    | **+59** |

---

## Marginal Utility Formula (Generalized)

To simplify coding:

```python
import math

def marginal_utility(quantity, max_utility, marginal_rate, penalty_no_supply=0):
    if quantity == 0:
        return penalty_no_supply
    else:
        return max_utility * (1 - math.exp(-marginal_rate * quantity))

# Example (Food calculation)
food_utility = marginal_utility(quantity=2, max_utility=15, marginal_rate=1.0, penalty_no_supply=-25)
```