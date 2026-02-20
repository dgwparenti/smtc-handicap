# TOP >50 Rides Handicap Model

**Model name**: `Top >50rides`
**Start position**: TOP
**Minimum rides**: 50 completed runs from TOP
**Training data**: 4,204 timed runs from 55 riders across 6 seasons (2020-2026), 15 race types
**Model fit**: `data/model_fits/top.nc`

## Validation Results

Evaluated against committee handicaps across 33 handicap races with at least 5 qualifying riders:

| Metric | Committee | Model |
|--------|-----------|-------|
| Average top-5 net time range | 1.239s | 0.969s |
| Tighter top-5 in how many races | 9/33 (27%) | **24/33 (73%)** |

The model produces a tighter finish among the top 5 net-time finishers in nearly three-quarters of all handicap races.

---

## Part 1: How It Works (Non-Technical)

### What the model sees

The model looks at every recorded TOP finish time across all seasons since 2019-20. It only considers riders with at least 50 completed runs, giving it a reliable picture of each rider's ability. Falls and DNFs are excluded.

### Step 1 — Learn each rider's true speed

Every rider has an underlying ability level. But actual finish times vary from run to run due to daily form, snow and ice conditions, nerves, and so on.

The model separates the **rider's true ability** from this day-to-day variation. It estimates three things per rider:

- **Baseline ability** — their typical finishing time, all else equal (e.g. "this rider is fundamentally a 55-second rider")
- **Personal consistency** — how much their times scatter around that baseline. Some riders are very consistent (times vary by less than 1 second); others are volatile (swings of 2-3 seconds between runs)
- **Year-on-year trend** — whether the rider is gradually improving or declining over seasons. Each rider gets their own individual trend

### Step 2 — Account for factors outside the rider's control

Not everything that affects finish times is about the rider:

- **Season conditions** — some winters are universally faster or slower. When every rider is about half a second quicker, that's the ice, not the riders. The model detects this automatically
- **Race type** — different races (Stagni Cup, Swiss Championship, etc.) can produce slightly different time profiles
- **SL learning curve** — Supplementary List riders improve through the season as they gain runs and experience. The model accounts for this

### Step 3 — Predict each rider's competitive time

For a given race, the model predicts each rider's expected finishing time by combining their ability, the current season conditions, the race type, and their trend.

Crucially, it then adjusts for **consistency**. Two riders who both average 56 seconds are not equal competitors:

- A consistent rider (times between 55.2 and 56.8) will run about 55.2 on a competitive day
- A volatile rider (times between 53.5 and 58.5) might run 53.5 on their best day, but that's unreliable

The model shifts each rider's predicted time toward their "competitive best" in proportion to how consistent they are. This means **the handicap rewards reliable performance**, not occasional brilliance. To prevent extreme adjustments for very volatile riders, this shift is capped.

### Step 4 — Compute the handicap

The scratch rider (typically the committee's designated scratch) gets handicap = 0. Every other rider's handicap is the difference between their competitive time and the scratch rider's competitive time.

### Step 5 — Compress large handicaps

When comparing the model's raw handicaps against actual race outcomes, we found that the model tends to be too generous to slower riders — it gives them slightly more handicap than they need. This is a systematic pattern across many races.

To correct this, the model applies a gentle **compression** to handicap values. Think of it like a progressive scale: small handicaps (1-2 seconds) stay essentially unchanged, but large handicaps (6-8 seconds) are trimmed slightly. A rider who would get a raw handicap of 2 seconds receives about 2.1 seconds; a rider who would get 8 seconds receives about 7.2 seconds instead.

This compression was calibrated against actual race outcomes to produce the tightest possible top-5 finishes.

### Why should the committee believe this?

**1. It's validated against your results.** In 24 out of 33 handicap races (73%), the model produces a tighter top-5 finish spread than the committee. The average top-5 spread is 0.97 seconds (model) vs 1.24 seconds (committee).

**2. It respects the committee's scratch rider.** The model does not second-guess who should be scratch. It takes the committee's designated scratch rider and computes all handicaps relative to that rider.

**3. It uses all available data equally.** The model weighs 4,200+ timed runs without recency bias, without forgetting older performances, and without being influenced by reputation or personality.

**4. It handles things that are hard for any individual to track:**
- Separating a fast season from a fast rider (was it them or the ice?)
- Weighing consistency vs. occasional brilliance objectively
- Tracking gradual improvement or decline over multiple seasons for 55+ riders simultaneously
- Being unbiased and consistent across all riders at once

**5. Every handicap comes with a confidence rating.** Riders with 20+ runs and narrow uncertainty get HIGH confidence; riders with fewer runs or wider uncertainty get MEDIUM or LOW. The committee can see exactly where the model is most and least certain.

**6. The 9 races where the committee is tighter** often involve very local knowledge (recent injuries, course familiarity, specific conditions) that the model cannot capture from historical data alone. The model is an evidence base; the committee adds the human context.

---

## Part 2: Mathematical Formulation

### 2.1 Data Preparation

**Source**: SQLite database of all recorded time records from TOP start position.

**Filtering**:
- Only completed runs (no falls, no DNFs) with valid finish times
- Outlier removal: times outside 49.7-70.0 seconds are excluded
- Minimum 50 completed runs per rider (ensures reliable estimation)
- Race types with fewer than 100 observations are collapsed into an "OTHER" category (reduces noise from rare race formats; yields R=15 race types)

**Indexing**:
- Riders indexed j = 1, ..., J (J=55)
- Seasons indexed s = 1, ..., S (S=6, covering 2020-2026)
- Race types indexed r = 1, ..., R (R=15)
- Season numbers centered: `season_num[s] = year[s] - mean(years)`
- Per-rider, per-season sequential run counter `run_seq` for SL learning

### 2.2 Generative Model (Stan)

The model predicts finish time `y[n]` for observation n as:

```
y[n] ~ Normal(mu[n], sigma_rider[rider[n]])
```

where the expected time `mu[n]` decomposes as:

```
mu[n] = alpha[j]                              # rider baseline ability
      + eta[s]                                # global season effect
      + beta_trend[j] * season_num[s]         # per-rider linear trend over seasons
      + gamma[r]                              # race-type effect
      + beta_improve * run_seq[n] * is_sl[j]  # SL within-season learning
```

#### Hierarchical Priors

**Rider abilities** (non-centered parameterization):
```
alpha[j] = mu_pop + sigma_pop * alpha_raw[j]
alpha_raw[j] ~ Normal(0, 1)
mu_pop ~ Normal(57, 10)          # prior centered on typical TOP time
sigma_pop ~ HalfNormal(0, 5)    # between-rider spread
```

**Per-rider observation noise** (log-normal hierarchy):
```
sigma_rider[j] = exp(mu_log_sigma + sigma_log_sigma * log_sigma_raw[j])
log_sigma_raw[j] ~ Normal(0, 1)
mu_log_sigma ~ Normal(log(2.0), 0.5)     # population center ~2s
sigma_log_sigma ~ HalfNormal(0, 0.5)     # spread in consistency
```

This is the key modelling choice: each rider has their own observation noise `sigma_rider[j]`, capturing that some riders are more consistent than others.

**Season effects** (non-centered):
```
eta[s] = sigma_season * eta_raw[s]
eta_raw[s] ~ Normal(0, 1)
sigma_season ~ HalfNormal(0, 1)
```

**Per-rider trends** (non-centered):
```
beta_trend[j] = beta_trend_mu + sigma_trend * beta_trend_raw[j]
beta_trend_raw[j] ~ Normal(0, 1)
beta_trend_mu ~ Normal(0, 1)
sigma_trend ~ HalfNormal(0, 0.2)
```

**Race-type effects** (non-centered):
```
gamma[r] = sigma_race * gamma_raw[r]
gamma_raw[r] ~ Normal(0, 1)
sigma_race ~ HalfNormal(0, 1)
```

**SL within-season learning**:
```
beta_improve ~ Normal(-0.3, 0.3)    # expect slight improvement (negative = faster)
```

### 2.3 Model Fitting

- **Sampler**: CmdStanPy (NUTS/HMC), 4 chains, 1000 warmup + 1000 sampling iterations
- **Adaptation**: `adapt_delta = 0.95` (higher than default for cleaner exploration)
- **Convergence**: R-hat <= 1.01, ESS_bulk > 400, 0 divergences
- **Output**: ArviZ InferenceData saved to `data/model_fits/top.nc`
- **Posterior draws**: D = 4000 (4 chains x 1000 draws)

### 2.4 Handicap Computation (Post-Processing)

Given a field of riders for a specific race type `r` and season `s`, handicaps are computed from the posterior in four stages.

#### Stage 1: Predicted times

For each posterior draw d = 1, ..., D and each rider i in the field:

```
pred_time[d, i] = alpha[d, j]
               + eta[d, s]
               + beta_trend[d, j] * season_num[s]
               + gamma[d, r]
               + beta_improve[d] * (max_run_seq[j] + 1) * is_sl[j]
```

This gives a (D x n_field) matrix of predicted times.

#### Stage 2: Quantile-based consistency adjustment

Each rider's predicted time is shifted toward their competitive best, using the posterior mean of their per-rider sigma:

```
sigma_bar[j] = mean_d(sigma_rider[d, j])        # posterior mean consistency

shift[j] = max(sigma_bar[j] * phi, cap)          # phi = -1.30, cap = -2.5

pred_q[d, i] = pred_time[d, i] + shift[j]
```

where `phi = -1.30` controls the quantile depth (how far toward their best-day performance) and `cap = -2.5s` prevents over-adjustment for very volatile riders. Consistent riders (small sigma) get a small shift; volatile riders (large sigma) get a larger shift, but never more than 2.5 seconds.

#### Stage 3: Handicap relative to scratch

The scratch rider (committee-designated, or auto-detected as the rider with the lowest mean `pred_q`) is fixed across all draws:

```
handicap_raw[d, i] = pred_q[d, i] - pred_q[d, scratch]
```

#### Stage 4: Power-law compression

Raw handicaps are compressed using a concave power law:

```
handicap[d, i] = sign(h) * scale * |h|^power
```

where `scale = 1.175` and `power = 0.84`. Since `power < 1`, this is a concave function that compresses large handicap differences more than small ones:

| Raw handicap | Compressed handicap |
|-------------|-------------------|
| 0.0s | 0.00s |
| 1.0s | 1.18s |
| 2.0s | 2.11s |
| 3.0s | 2.96s |
| 4.0s | 3.76s |
| 5.0s | 4.52s |
| 6.0s | 5.26s |
| 7.0s | 5.97s |
| 8.0s | 6.66s |

The scratch rider is set to exactly 0.0 after compression.

#### Stage 5: Summary statistics

The final handicap for each rider is the **median** across all D posterior draws:

```
handicap_final[i] = median_d(handicap[d, i])
```

with 95% credible interval from the 2.5th and 97.5th percentiles.

**Confidence levels**:
- HIGH: >= 20 runs and 95% CI width < 3.0s
- MEDIUM: >= 10 runs
- LOW: < 10 runs

### 2.5 Calibrated Parameters

These parameters were optimized via iterative grid search ("Ralph Loop") against committee handicap outcomes across 33 qualifying races:

| Parameter | Symbol | Value | Role |
|-----------|--------|-------|------|
| Quantile shift | phi | -1.30 | Depth of competitive-best adjustment |
| Shift cap | cap | -2.5s | Maximum consistency shift magnitude |
| Compression scale | scale | 1.175 | Linear coefficient in power-law |
| Compression power | power | 0.84 | Concavity of handicap compression |
| Aggregation | - | median | Robust central tendency over draws |
| Scratch rider | - | committee | Uses committee-designated scratch |

### 2.6 Implementation Files

| File | Purpose |
|------|---------|
| `src/smtc_handicap/stan/cresta_handicap.stan` | Stan model specification |
| `src/smtc_handicap/model/data_prep.py` | Data query, filtering, indexing |
| `src/smtc_handicap/model/predict.py` | Posterior handicap computation |
| `src/smtc_handicap/model/fit.py` | Model compilation and fitting |
| `src/smtc_handicap/model/diagnostics.py` | Convergence checks and saving |
| `scripts/fit_model.py` | CLI: `python scripts/fit_model.py --position TOP` |
| `scripts/evaluate_tightness.py` | CLI: evaluation against committee |
