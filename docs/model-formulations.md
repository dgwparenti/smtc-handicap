# Three Bayesian Handicap Model Formulations

## Context

The current model (`cresta_handicap.stan`) is a hierarchical Normal with **single shared observation noise** `sigma_obs = 1.94s` for all 378 riders. Handicaps are derived from posterior mean ability differences. This works — Bayesian handicaps are tighter than committee ones in ~60-80% of races — but three limitations hurt the spread:

1. **All riders treated as equally consistent** — a metronome veteran and a volatile beginner share the same sigma
2. **Falls discarded entirely** — `_query_valid_times` filters `is_fall = 0`, losing ~15-20% of runs and all information about crash-prone riders
3. **Split times unused** — 62% of records have 4 intermediate checkpoints, but only `finish_time` enters the model

Below are three formulations that address these limitations, ordered from easiest to hardest.

---

## Current Model (Baseline Reference)

```
mu[n] = alpha[j] + eta[s] + beta_trend[j] * season_num[s] + gamma[r] + is_sl[j] * beta_improve * run_seq[n]
y[n] ~ Normal(mu[n], sigma_obs)

alpha[j]      ~ N(mu_pop, sigma_pop)      // rider ability
eta[s]        ~ N(0, sigma_season)         // global season effect
beta_trend[j] ~ N(beta_trend_mu, sigma_trend)  // per-rider career trend
gamma[r]      ~ N(0, sigma_race)           // race-type effect
```

**Handicap**: `h[j] = E[alpha[j] + beta_trend[j] * season_num[s]] - same for scratch rider`

---

## Formulation A: Heteroscedastic (Per-Rider Consistency)

### Key Insight
Replace the single `sigma_obs` with per-rider `sigma[j]`. Then derive handicaps from a **competitive quantile** (e.g., 20th percentile = "good day") rather than the mean. This penalizes volatile riders whose occasional fast runs are subsidized by mean-based handicaps.

### Generative Model

Everything unchanged except observation noise:

```
// NEW: per-rider observation noise (log-normal hierarchy)
mu_log_sigma     ~ Normal(log(2.0), 0.5)       // population center ~2s
sigma_log_sigma  ~ Half-Normal(0, 0.5)          // spread in consistency
log_sigma_raw[j] ~ Normal(0, 1)                 // non-centered
sigma_rider[j]   = exp(mu_log_sigma + sigma_log_sigma * log_sigma_raw[j])

// Likelihood (the ONLY change from current model)
y[n] ~ Normal(mu[n], sigma_rider[rider[n]])
```

**Total new parameters**: J + 2 (380 params). Everything else identical.

### Handicap Derivation

For a 3-run handicap race, the p-th quantile of rider j's aggregate time is:

```
Q_3[j] = 3 * mu[j] + sqrt(3) * sigma_rider[j] * Phi_inv(p)
```

Setting p = 0.20 (the rider's "good day" — 80% of their runs are slower):

```
h[j] = (mu[j] - mu[scratch]) + (sqrt(3)/3) * (sigma_rider[j] - sigma_rider[scratch]) * Phi_inv(0.20)
```

The second term is **negative** when the rider is more volatile than scratch (sigma_rider[j] > sigma_rider[scratch]), meaning volatile riders get LESS handicap because their good days are disproportionately fast.

**Intuition**: A consistent rider (sigma = 0.8s) racing against a volatile one (sigma = 3.0s) with identical means: the volatile rider's 20th percentile is 2.5s faster than the consistent rider's. Mean-based handicaps miss this entirely.

### Why It Improves Spread
- Directly models the mechanism that causes net-time blowouts: volatile riders occasionally producing outlier-fast aggregates
- Consistent riders get slightly larger handicaps (their good day is close to their mean), volatile riders get smaller ones
- Expected tightening: **10-20%** in net-time range among top finishers

### Practical Notes
- **Data changes**: None. Same data block as current model.
- **Stan changes**: ~20 lines added to current `.stan` file
- **Compute cost**: ~10-20% longer (J extra parameters, but well-identified)
- **LOO-comparable**: Yes — identical data, can directly compare `elpd_loo`
- **Sparse riders**: With only 3 runs, `sigma_rider[j]` shrinks to population mean via partial pooling — quantile handicap ≈ mean handicap. This is correct behavior.
- **Quantile choice**: p=0.20 is a reasonable default; sensitivity analysis recommended (p=0.10 to p=0.35)

---

## Formulation B: Hurdle Model (Fall Probability)

### Key Insight
Model each run as a two-stage process: (1) does the rider finish? (2) if yes, how fast? Currently, a rider who finishes 90% at 55s and one who finishes 70% at 55s get identical handicaps. But in a 3-run race, the 70%-finisher has only a 34% chance of completing all 3 runs (0.7^3). Falls carry information about rider risk that mean-time-only handicaps ignore.

### Generative Model

**Stage 1 — Finish probability** (Bernoulli, all runs including falls):

```
mu_logit_p     ~ Normal(2.0, 1.0)            // ~88% baseline finish rate
sigma_logit_p  ~ Half-Normal(0, 1.5)         // between-rider spread
logit_p_raw[j] ~ Normal(0, 1)                // non-centered
logit_p_base[j] = mu_logit_p + sigma_logit_p * logit_p_raw[j]

// Per-observation finish probability
logit(p[n]) = logit_p_base[rider[n]]
              + delta_season * season_num[season[n]]    // experience reduces falls
              + is_sl[rider[n]] * delta_sl               // SL riders fall more

z[n] ~ Bernoulli(p[n])     // z=1 finish, z=0 fall
```

**Stage 2 — Finish time** (conditional on z=1, same as current model):

```
y[n] | z[n]=1 ~ Normal(mu[n], sigma_obs)     // unchanged
```

**New parameters**: J + 4 (logit_p_raw[J], mu_logit_p, sigma_logit_p, delta_season, delta_sl)

### Data Requirements

`data_prep.py` must change to provide two observation arrays:

```python
# N_all: ALL runs (finishes + falls)
rider_all[N_all], season_all[N_all], finished[N_all]  # 0/1

# N_finish: only finished runs (same as current N)
rider[N_finish], season[N_finish], ..., y[N_finish]    # same as before
```

The query changes from `AND tr.is_fall = 0` to including all records, with a `finished` indicator.

### Handicap Derivation

The handicap has two components:

```
h[j] = (mu[j] - mu[scratch])                          // speed component (same as now)
       + rho * log(p_finish[scratch] / p_finish[j])    // fall risk premium
```

**rho** is a calibration parameter (not fitted — set by the committee). It converts the fall probability ratio into equivalent seconds. A natural calibration:

- If a rider's P(complete 3 runs) = p^3, and a fall in any run means effectively +infinity time for that run
- The "expected cost" of one fall = the expected time lost, amortized
- A rider with p=0.70 vs scratch at p=0.95: `log(0.95/0.70) = 0.305`
- With rho=5.0: they get 1.5s extra handicap per run, reflecting their fall risk

### Why It Improves Spread
- **Information recovery**: ~15-20% more data points now inform the model
- **Better alpha[j] estimation**: Riders who fall often but finish fast when they don't are correctly identified as "fast but dangerous"
- **Risk-adjusted fairness**: A rider who completes all 3 runs in a race has already beaten the odds if they're fall-prone — the handicap should account for this luck
- Expected tightening: **5-15%**, strongest in mixed-experience fields

### Practical Notes
- **Data changes**: Moderate — extend `_query_valid_times` to include falls, add `finished` flag
- **Stan changes**: New file `cresta_handicap_hurdle.stan` (or parameterized variant)
- **Compute cost**: ~20-30% longer (Bernoulli likelihood is cheap, but N_all > N_finish)
- **LOO-comparable**: Only for the time-model component (same N_finish). The fall model adds information but can't be directly compared via LOO with the current model.
- **Policy decision**: rho is a knob the committee turns. Some may object to penalizing fall risk at all ("handicaps should only reflect speed"). This is a feature, not a bug — it makes the policy explicit.

### Fall Location Extension (Optional)
With fall_location data (S, TH, JS, CH, BA, ST), the finish probability could be decomposed by track section:
```
// Section-specific hazard (logistic)
logit(p_section[n,k]) = logit_p_base[j] + lambda_section[k]
P(finish) = prod_k P(pass section k)
```
This uses the Cresta's known danger points (Shuttlecock, Battledore) but adds complexity. Recommended as a v2 extension.

---

## Formulation C: Sectional (Split-Based) Model

### Key Insight
Decompose each run into 5 track sections using intermediate split times. Model per-rider ability at each section. This captures that some riders dominate the straights but lose time in corners (or vice versa). The current model treats finish time as monolithic, washing out section-specific patterns.

### Track Sections (TOP start)

| Section k | From → To | Approx. Duration | Fall Locations |
|-----------|-----------|-------------------|----------------|
| 1 | Start → Junction | ~16s | S (Straight), TH (Top House) |
| 2 | Junction → Rise | ~10s | JS (Junctions), CH (Churchyard) |
| 3 | Rise → Stream | ~8s | BA (Battledore/Bank) |
| 4 | Stream → Bulpetts | ~7s | ST (Stream) |
| 5 | Bulpetts → Finish | ~16s | (rare) |

Section times derived from splits: `t[1] = split_junction`, `t[k] = split[k] - split[k-1]`, `t[5] = finish_time - split_bulpetts`.

### Generative Model

```
// Per-section population means and spreads
mu_section[k]        ~ Normal(prior_section_mu[k], 5.0)    for k = 1..5
sigma_pop_section[k] ~ Half-Normal(0, 3)                   for k = 1..5
sigma_section[k]     ~ Half-Normal(0, 2)                   for k = 1..5

// Per-rider, per-section abilities (non-centered)
alpha_section_raw[j,k] ~ Normal(0, 1)
alpha_section[j,k]     = mu_section[k] + sigma_pop_section[k] * alpha_section_raw[j,k]

// Shared effects distributed proportionally across sections
section_frac[k] = mu_section[k] / sum(mu_section)

// Section-level expected time
t[n,k] = alpha_section[rider[n], k]
         + eta[season[n]] * section_frac[k]
         + beta_trend[rider[n]] * season_num[season[n]] * section_frac[k]
         + gamma[race_type[n]] * section_frac[k]
         + is_sl[rider[n]] * beta_improve * run_seq[n] * section_frac[k]
```

**Two likelihood components** (handling the 62/38 split/no-split data mix):

```
// Records WITH splits (62%): 5 independent section observations per run
y_section[n,k] ~ Normal(t[n,k], sigma_section[k])     for k = 1..5

// Records with ONLY total time (38%): summed prediction
y_total[n] ~ Normal(sum_k(t[n,k]), sqrt(sum_k(sigma_section[k]^2)))
```

### Handicap Derivation

```
predicted_total[j] = sum_k(alpha_section[j,k] + eta[S] * frac[k] + beta_trend[j] * sn * frac[k])
h[j] = predicted_total[j] - predicted_total[scratch]
```

Same structure as current, but now each rider's predicted total is a sum of 5 section-level estimates, each informed by section-specific data. The committee additionally gets a **section breakdown**:

```
h_section[j,k] = alpha_section[j,k] - alpha_section[scratch,k]
// "Rider X loses 2.3s to scratch at Junction-Rise but gains 0.8s at Bulpetts-Finish"
```

### Why It Improves Spread
- **5x more information** per split-available record (5 section obs vs 1 total)
- **Section-specific patterns**: Riders who are fast overall but have a weak section are better estimated. Their weakness is modeled rather than averaged away.
- **Diagnostic value**: Committee sees WHERE handicap comes from, enabling targeted coaching
- Expected tightening: **15-30%**, biggest gains for riders with asymmetric section profiles

### Practical Notes
- **Data changes**: Major — `data_prep.py` must extract section times from splits, handle missing splits, validate `t[k] > 0`
- **Stan changes**: New model file with `matrix[J, K]` rider-section abilities
- **Parameters**: J x K + 3K + existing = ~2,270 (vs 800 current). **3-5x longer** fit time.
- **Missing data**: 38% of records lack splits → contribute only total-time information. If split availability correlates with season (JSONs more recent), potential bias.
- **Identifiability**: For riders with ONLY total-time records, section abilities not individually identified — shrunk to population mean by partial pooling. Only their sum is constrained.
- **Data quality**: Section times from `split[k] - split[k-1]` can be noisy or negative if timing equipment glitches. Need per-section outlier filtering.

---

## Comparison

| | A: Heteroscedastic | B: Hurdle (Falls) | C: Sectional |
|---|---|---|---|
| **Core change** | Per-rider sigma + quantile handicap | Joint finish-prob + time | Per-section rider abilities |
| **New params** | ~380 | ~382 | ~2,270 |
| **Data prep changes** | None | Moderate | Major |
| **Fit time delta** | +10-20% | +20-30% | +200-400% |
| **LOO-comparable** | Yes (same data) | Partial | Partial |
| **Expected tightening** | 10-20% | 5-15% | 15-30% |
| **Implementation effort** | 1-2 days | 2-3 days | 5-7 days |
| **Committee value** | Consistency metrics | Safety profiles | Section breakdown |
| **Risk** | Low | Medium | High |

## Recommended Path

1. **Start with A** — zero data prep changes, directly LOO-comparable, validates whether per-rider consistency matters. If sigma_log_sigma posterior is concentrated near zero, riders really are equally consistent and A doesn't help.

2. **Then B** — requires data prep work but is modular (fall model can be fit separately first). Introduces the policy question about fall-risk handicapping.

3. **A + B combined** — heteroscedastic hurdle model (per-rider sigma AND per-rider fall probability). This is the natural synthesis and likely the best single-model approach.

4. **C as research** — highest potential but highest risk. Only worth pursuing after confirming split data quality and establishing that A+B leaves meaningful room for improvement.
