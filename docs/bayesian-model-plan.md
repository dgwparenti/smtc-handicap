# Bayesian Handicapping Model — Design & Implementation Plan

## 1. Executive Summary

This document describes the design of a Bayesian hierarchical model for predicting rider finish times on the Cresta Run, and how those predictions are converted into handicaps. The model is written in **Stan** (a probabilistic programming language) and called from Python via **CmdStanPy**.

**Core idea**: A handicap is not simply the difference between a rider's average time and the fastest rider's. It must predict what time a rider is *likely to produce in a specific race*, given:

1. **Season form** — how the rider is performing *this* season relative to their career baseline.
2. **Race context** — whether the upcoming race is one where riders historically push hard (e.g., a prestigious cup) or a more casual event (e.g., practice).

The model learns these components from historical data, quantifies uncertainty, and produces a posterior predictive distribution for each rider's time in a given race. The handicap follows directly from these predictions.

---

## 2. Why Bayesian? Why Stan?

A junior data scientist should understand *why* we chose this approach rather than simpler alternatives.

### Why not just use averages?

| Approach | Problem |
|----------|---------|
| Use rider's season average | Ignores that some races are faster (riders push harder). A rider whose average is 56s might run 54s in the Brabazon Trophy. |
| Use rider's best time | Overly optimistic. A rider who ran 52s once but usually runs 56s will get too large a handicap. |
| Use rider's last N races | Doesn't account for race type. Practice times ≠ race times. |
| Committee judgment | Subjective, inconsistent, time-consuming. |

### Why Bayesian?

1. **Uncertainty quantification**: We get a full distribution, not a point estimate. For a rider with only 3 runs this season, the model naturally expresses more uncertainty than for a rider with 30 runs. The committee can see this and exercise more caution for uncertain handicaps.

2. **Hierarchical shrinkage**: New riders or riders with few observations get "pulled" toward the population average, preventing wild handicaps from small samples. As data accumulates, their estimates converge to their true ability.

3. **Principled handling of multiple data sources**: Practice runs, race runs, different seasons — the model gives each its proper weight without ad hoc rules.

4. **Separation of effects**: The model cleanly decomposes an observed time into *rider ability* + *season form* + *race context* + *noise*. This decomposition is exactly what handicapping requires.

### Why Stan?

- Stan's Hamiltonian Monte Carlo (HMC) sampler is the gold standard for hierarchical models. It handles correlated posteriors and high-dimensional parameter spaces better than simpler MCMC methods.
- Stan's compiler catches modelling errors before sampling.
- Stan models are self-documenting: the model block is a direct translation of the mathematical specification.
- CmdStanPy provides a clean Python interface for data prep, model fitting, and posterior extraction.
- Stan is widely used in sports analytics (e.g., FiveThirtyEight's NBA model, cycling power models) and has a mature ecosystem.

---

## 3. Model Architecture

### 3.1 Scope and Separation

We fit **two independent models**: one for **TOP** starts and one for **JUNCTION** starts. These are different courses with different time scales (~51–80s for TOP, ~44–55s for JUNCTION), so they should not share parameters.

Everything below applies to *one* model (say, TOP). The JUNCTION model has the same structure with its own fitted parameters.

### 3.2 Hierarchical Structure

The model has four levels, from most general to most specific:

```
Population
  └── Rider (baseline ability)
        └── Season × Rider (current form)
              └── Observation (individual run time)
```

Cross-cutting these levels, we have a **race-type effect** that captures how much faster or slower a specific race is compared to the overall average.

### 3.3 Mathematical Specification

**Notation**:
- $j = 1, \ldots, J$ — riders
- $s = 1, \ldots, S$ — seasons
- $r = 1, \ldots, R$ — race types (e.g., "Stagni Cup", "Brabazon Trophy", "Practice", etc.)
- $n = 1, \ldots, N$ — individual observations (run times)
- $y_n$ — observed finish time for observation $n$

**Population level** (hyperpriors):

$$\mu_{\text{pop}} \sim \text{Normal}(57, 10)$$
$$\sigma_{\text{pop}} \sim \text{Half-Normal}(5)$$

These express vague prior knowledge: TOP times average around 57 seconds with substantial variation across riders. For JUNCTION, set the prior mean to ~48s.

**Rider level** (baseline ability):

$$\alpha_j \sim \text{Normal}(\mu_{\text{pop}}, \sigma_{\text{pop}}) \quad \text{for } j = 1, \ldots, J$$

$\alpha_j$ is rider $j$'s long-run average ability. The hierarchical prior means that a rider with sparse data gets shrunk toward the population mean — this is a feature, not a bug.

**Rider consistency** (run-to-run variability):

$$\sigma_j \sim \text{Half-Normal}(3) \quad \text{for } j = 1, \ldots, J$$

Each rider has their own noise level. A consistent rider has small $\sigma_j$; an erratic rider has large $\sigma_j$. This is important for handicapping: two riders with the same expected time but different consistency represent different risks.

**Season form** (rider × season interaction):

$$\sigma_{\text{season}} \sim \text{Half-Normal}(2)$$
$$\delta_{s,j} \sim \text{Normal}(0, \sigma_{\text{season}}) \quad \text{for all } s, j$$

$\delta_{s,j}$ captures rider $j$'s deviation from their career baseline *in season $s$*. A positive value means the rider is slower than usual; a negative value means they are in better form. The shared $\sigma_{\text{season}}$ controls how much season-to-season variation is typical across all riders.

**Race-type effect**:

$$\sigma_{\text{race}} \sim \text{Half-Normal}(1.5)$$
$$\gamma_r \sim \text{Normal}(0, \sigma_{\text{race}}) \quad \text{for } r = 1, \ldots, R$$

$\gamma_r$ is the systematic effect of race type $r$. For a prestigious cup where everyone pushes hard, $\gamma_r$ will be negative (faster times). For practice, $\gamma_r$ will be positive (slower, more relaxed runs). This directly addresses the question: *"will the rider push hard in this race?"*

**SL (Supplementary List) rider improvement**:

For SL riders — less experienced riders who are actively improving — we add a within-season trend:

$$\beta_{\text{improve}} \sim \text{Normal}(-0.3, 0.2)$$

$$\text{For SL rider } j: \quad \text{trend}_{n} = \beta_{\text{improve}} \times \text{run\_seq}_{n}$$

where $\text{run\_seq}_{n}$ is the sequential run number for that rider *within the current season* (1st run, 2nd run, ..., $k$th run). The negative prior on $\beta_{\text{improve}}$ reflects the expectation that SL riders generally get faster over a season. For non-SL riders, this term is zero.

**Observation model** (likelihood):

$$y_n \sim \text{Normal}(\mu_n, \sigma_{j[n]})$$

where:

$$\mu_n = \alpha_{j[n]} + \delta_{s[n], j[n]} + \gamma_{r[n]} + \mathbb{1}[\text{SL}_{j[n]}] \cdot \beta_{\text{improve}} \cdot \text{run\_seq}_{n}$$

In words: the expected time for observation $n$ is the rider's baseline ability, plus their season form adjustment, plus the race-type effect, plus (for SL riders only) an improvement trend.

### 3.4 Diagram

```
                    ┌─────────────────────┐
                    │   Population Prior   │
                    │  μ_pop  ~  N(57, 10) │
                    │  σ_pop  ~  HN(5)     │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │   Rider Ability αⱼ   │
                    │  αⱼ ~ N(μ_pop, σ_pop)│
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼─────┐  ┌─────▼─────┐  ┌──────▼──────────┐
    │Season Form δₛⱼ│  │Race γᵣ    │  │SL Improvement β │
    │ ~ N(0, σ_seas) │  │ ~ N(0,σ_r)│  │ ~ N(-0.3, 0.2)  │
    └────────┬──────┘  └─────┬─────┘  └──────┬──────────┘
             │               │               │
             └───────────────┼───────────────┘
                             │
                   ┌─────────▼───────────┐
                   │  Expected Time μₙ   │
                   │= αⱼ + δₛⱼ + γᵣ + …  │
                   └─────────┬───────────┘
                             │
                   ┌─────────▼───────────┐
                   │  Observed Time yₙ   │
                   │ ~ N(μₙ, σⱼ)         │
                   └─────────────────────┘
```

---

## 4. Stan Model Code

Below is the full Stan program. Save this as `models/cresta_handicap.stan`.

```stan
// =============================================================================
// Cresta Run Handicap Model
// Hierarchical Bayesian model for predicting rider finish times.
//
// Separate models are fitted for TOP and JUNCTION start positions.
// =============================================================================

data {
  int<lower=1> N;                    // Total number of observed run times
  int<lower=1> J;                    // Number of unique riders
  int<lower=1> S;                    // Number of seasons
  int<lower=1> R;                    // Number of race types

  array[N] int<lower=1, upper=J> rider;      // Rider index for each observation
  array[N] int<lower=1, upper=S> season;     // Season index for each observation
  array[N] int<lower=1, upper=R> race_type;  // Race-type index for each observation

  vector[N] y;                       // Observed finish times (seconds)

  // SL rider data
  array[J] int<lower=0, upper=1> is_sl;  // 1 if rider is SL, 0 otherwise
  vector[N] run_seq;                      // Sequential run number within season for this rider
                                          // (1, 2, 3, ... counting from season start)

  // Prior configuration (passed from Python so TOP/JUNCTION can differ)
  real prior_mu_pop;       // Prior mean for population mean (57 for TOP, 48 for JUNCTION)
  real prior_sigma_mu_pop; // Prior sd for population mean (10)
}

parameters {
  // --- Population level ---
  real mu_pop;                        // Population mean finish time
  real<lower=0> sigma_pop;            // Between-rider spread in ability

  // --- Rider level (non-centered parameterization for efficiency) ---
  vector[J] alpha_raw;               // Standardized rider abilities
  vector<lower=0>[J] sigma_rider;    // Per-rider run-to-run consistency

  // --- Season form ---
  real<lower=0> sigma_season;         // How much riders vary season to season
  matrix[S, J] delta_raw;            // Standardized season × rider deviations

  // --- Race-type effect ---
  real<lower=0> sigma_race;           // How much race types vary
  vector[R] gamma_raw;               // Standardized race-type effects

  // --- SL improvement ---
  real beta_improve;                  // Mean improvement rate (seconds per run, expect < 0)
}

transformed parameters {
  // Rider baseline abilities (non-centered → centered)
  vector[J] alpha = mu_pop + sigma_pop * alpha_raw;

  // Season × rider form deviations
  matrix[S, J] delta;
  for (s in 1:S)
    for (j in 1:J)
      delta[s, j] = sigma_season * delta_raw[s, j];

  // Race-type effects
  vector[R] gamma = sigma_race * gamma_raw;

  // Expected time for each observation
  vector[N] mu;
  for (n in 1:N) {
    mu[n] = alpha[rider[n]]
            + delta[season[n], rider[n]]
            + gamma[race_type[n]];

    // SL improvement trend (only active for SL riders)
    if (is_sl[rider[n]] == 1) {
      mu[n] += beta_improve * run_seq[n];
    }
  }
}

model {
  // --- Hyperpriors ---
  mu_pop ~ normal(prior_mu_pop, prior_sigma_mu_pop);
  sigma_pop ~ normal(0, 5);       // half-normal via constraint
  sigma_season ~ normal(0, 2);
  sigma_race ~ normal(0, 1.5);

  // --- Rider level ---
  alpha_raw ~ std_normal();        // implies alpha ~ N(mu_pop, sigma_pop)
  sigma_rider ~ normal(0, 3);     // half-normal via constraint

  // --- Season form ---
  to_vector(delta_raw) ~ std_normal();  // implies delta ~ N(0, sigma_season)

  // --- Race-type effects ---
  gamma_raw ~ std_normal();        // implies gamma ~ N(0, sigma_race)

  // --- SL improvement ---
  beta_improve ~ normal(-0.3, 0.2);

  // --- Likelihood ---
  y ~ normal(mu, sigma_rider[rider]);
}

generated quantities {
  // Posterior predictive checks: simulate new data from the model
  vector[N] y_rep;
  for (n in 1:N)
    y_rep[n] = normal_rng(mu[n], sigma_rider[rider[n]]);

  // Log-likelihood for LOO-CV model comparison
  vector[N] log_lik;
  for (n in 1:N)
    log_lik[n] = normal_lpdf(y[n] | mu[n], sigma_rider[rider[n]]);
}
```

### 4.1 Key Design Decisions Explained

| Decision | Rationale |
|----------|-----------|
| **Non-centered parameterization** (`alpha_raw`, `delta_raw`, `gamma_raw`) | Standard technique for hierarchical models. Stan's HMC sampler struggles with centered parameterizations when the data is sparse; non-centered avoids "funnel" geometries in the posterior. Always use this for hierarchical random effects. |
| **Per-rider `sigma_rider`** | Riders vary in consistency. A rider who always runs ~56±0.5s is very different from one who runs 54–60s. The handicap committee should see this. It also improves model fit. |
| **Shared `sigma_season`** | We assume season-to-season variation is similar across riders. This pools information and is especially helpful for riders with data in only 1–2 seasons. |
| **Race-type as categorical** | Named races (Stagni Cup, Brabazon, etc.) and practice are discrete categories. Treating them as random effects pools information across race types while allowing each to have its own shift. |
| **Single `beta_improve` for all SL riders** | With limited SL data, estimating per-rider improvement rates would be noisy. A shared improvement rate is more stable. If the data grows large enough, this could become per-rider. |
| **`generated quantities` block** | `y_rep` enables posterior predictive checks (plot simulated data vs real data to spot model misfit). `log_lik` enables LOO-CV for model comparison if we later try alternative specifications. |
| **Priors passed as data** | Allows the same `.stan` file to serve both TOP and JUNCTION models by passing different `prior_mu_pop` values (57 vs 48). Avoids code duplication. |

---

## 5. Handling Falls and Missing Data

### Falls

When a rider falls (e.g., `Fall(S)`), the recorded time is **not a valid finish time**. Options:

1. **Exclude falls entirely** (recommended for MVP). Falls are a separate process (technique failure, not speed), and including partial times would bias the model.
2. **Model as censored data** (future extension). We know the rider *would have* finished in at least $y_{\text{fall}}$ seconds, so we could use a censored likelihood: $y_n > y_{\text{fall}}$. This is straightforward in Stan but adds complexity.

**For MVP: exclude all fall observations.** Track fall *rate* per rider as a separate metric for the committee (a rider who falls 30% of the time is a higher risk regardless of their expected time).

### Practice vs. Race

Practice runs and race runs are both valid observations, but riders typically push less in practice. This is captured naturally by the race-type effect $\gamma_r$: practice will get a positive $\gamma$ (slower), competitive races will get a negative $\gamma$ (faster). No special handling needed — just assign practice a race-type index.

---

## 6. From Predictions to Handicaps

### 6.1 Predicting Expected Time

To predict rider $j$'s expected time in race type $r$ during the current season $s^*$:

$$\hat{y}_j = \hat{\alpha}_j + \hat{\delta}_{s^*, j} + \hat{\gamma}_r + \mathbb{1}[\text{SL}_j] \cdot \hat{\beta}_{\text{improve}} \cdot k_j$$

where $k_j$ is the rider's projected run count by the time of the race, and all hat-quantities are posterior means (or medians).

In practice, we draw from the full posterior to get a **distribution** of predicted times, not just a point estimate.

### 6.2 Calculating the Handicap

Given a field of riders $\{j_1, j_2, \ldots, j_M\}$ entered in a race:

1. For each posterior draw $d = 1, \ldots, D$:
   - Compute $\hat{y}_j^{(d)}$ for each rider $j$ in the field.
   - Identify the scratch rider: $j^* = \arg\min_j \hat{y}_j^{(d)}$
   - Compute handicaps: $h_j^{(d)} = \hat{y}_j^{(d)} - \hat{y}_{j^*}^{(d)}$
2. Take the **posterior mean** (or median) of $h_j^{(d)}$ across all draws as the recommended handicap.
3. Report the **95% credible interval** for the handicap as a measure of confidence.

```python
# Pseudocode for handicap calculation
def calculate_handicaps(posterior_samples, field_rider_ids, race_type_idx, current_season_idx):
    """
    posterior_samples: dict with keys 'alpha', 'delta', 'gamma', 'beta_improve', etc.
                       Each value has shape (num_draws, ...)
    field_rider_ids: list of rider indices in the field
    race_type_idx: index of the upcoming race type
    current_season_idx: index of the current season
    """
    num_draws = posterior_samples['alpha'].shape[0]

    # Predicted times: shape (num_draws, num_riders_in_field)
    pred_times = np.zeros((num_draws, len(field_rider_ids)))
    for i, j in enumerate(field_rider_ids):
        pred_times[:, i] = (
            posterior_samples['alpha'][:, j]
            + posterior_samples['delta'][:, current_season_idx, j]
            + posterior_samples['gamma'][:, race_type_idx]
        )
        # Add SL improvement if applicable
        # ...

    # Handicap = rider's time minus fastest rider's time (per draw)
    scratch_times = pred_times.min(axis=1, keepdims=True)  # (num_draws, 1)
    handicaps = pred_times - scratch_times                  # (num_draws, num_riders)

    # Summarize
    handicap_mean = handicaps.mean(axis=0)
    handicap_lo = np.percentile(handicaps, 2.5, axis=0)
    handicap_hi = np.percentile(handicaps, 97.5, axis=0)

    return handicap_mean, handicap_lo, handicap_hi
```

### 6.3 Rounding and Committee Output

- Round handicaps to the nearest **0.25 seconds** (or whatever granularity the committee uses).
- Report alongside:
  - Number of runs in the current season (data richness).
  - Rider consistency ($\sigma_j$ posterior mean).
  - Confidence level: **HIGH** (>20 runs, tight CI), **MEDIUM** (10–20 runs), **LOW** (<10 runs or wide CI).

---

## 7. Data Preparation (Python → Stan)

### 7.1 Required Input Data

The Python wrapper must prepare the following before calling Stan:

| Stan variable | Source | Notes |
|---------------|--------|-------|
| `N` | Count of rows | Exclude falls, DNFs |
| `J` | Count of unique riders | In the filtered dataset |
| `S` | Count of seasons | e.g., 5 if 2021–2025 |
| `R` | Count of distinct race types | See mapping below |
| `rider[N]` | Integer rider index 1..J | Build a mapping `rider_id → integer` |
| `season[N]` | Integer season index 1..S | e.g., 2021→1, 2022→2, ... |
| `race_type[N]` | Integer race-type index 1..R | See mapping below |
| `y[N]` | Finish times in seconds | Floats |
| `is_sl[J]` | SL flag per rider | 0 or 1 |
| `run_seq[N]` | Sequential run number within-season per rider | 1, 2, 3, ... |
| `prior_mu_pop` | 57 for TOP, 48 for JUNCTION | Passed as data |
| `prior_sigma_mu_pop` | 10 | Vague prior |

### 7.2 Race-Type Mapping

Build a mapping from race names to race-type indices. Group by the *name* of the event, not the date. For example:

```python
race_type_map = {
    "PRACTICE":          1,
    "THE STAGNI CUP":    2,
    "THE BRABAZON TROPHY": 3,
    "THE CECIL ROSS CUP": 4,
    # ... one entry per distinct named race across all seasons
}
```

Practice should always be its own race type. If there are one-off races with very few observations, consider grouping them into an "OTHER" category so the model has enough data to estimate their effect.

### 7.3 Data Filtering

Before passing data to Stan:

1. **Exclude falls and DNFs** — these are not valid finish times.
2. **Exclude obvious outliers** — a time of 200s for a TOP run likely indicates a near-fall or walking down. Apply a reasonable cutoff (e.g., > 3× median for that start position).
3. **Separate TOP and JUNCTION** — fit two independent models.
4. **Ensure index contiguity** — rider indices must be 1..J with no gaps. Re-index after filtering.

---

## 8. Implementation Steps

This section tells you, step-by-step, what to build and in what order.

### Step 1: Install Dependencies

Add to `pyproject.toml`:
```toml
dependencies = [
    # ... existing deps ...
    "cmdstanpy>=1.2",
    "numpy",
    "pandas",
    "arviz",       # posterior diagnostics & plotting
]
```

Then install CmdStan (the Stan compiler) via:
```bash
python -m cmdstanpy.install_cmdstan
```

### Step 2: Create Project Structure

```
src/smtc_handicap/
├── models/
│   └── cresta_handicap.stan      # The Stan model file (Section 4 above)
├── model/
│   ├── __init__.py
│   ├── data_prep.py              # Prepare Python data → Stan input dict
│   ├── fit.py                    # Compile & fit the Stan model
│   ├── predict.py                # Extract posteriors, compute handicaps
│   └── diagnostics.py            # Convergence checks, posterior predictive checks
```

### Step 3: Implement `data_prep.py`

This module queries the SQLite database and produces the Stan input dictionary. Key functions:

- `build_stan_data(db_path, start_position, seasons=None) -> dict`:
  - Query all valid (non-fall, non-DNF) finish times for the given start position.
  - Build rider/season/race-type index mappings.
  - Compute `run_seq` for each observation.
  - Return a dict ready to pass to `CmdStanModel.sample()`.

- `get_rider_index_map(df) -> dict[str, int]`: Map rider_id to 1-based integer.

- `get_race_type_map(df) -> dict[str, int]`: Map race name to 1-based integer.

### Step 4: Implement `fit.py`

```python
from cmdstanpy import CmdStanModel

def compile_model(stan_file: str = "src/smtc_handicap/models/cresta_handicap.stan"):
    """Compile the Stan model. Only needs to happen once (or when .stan changes)."""
    model = CmdStanModel(stan_file=stan_file)
    return model

def fit_model(model: CmdStanModel, stan_data: dict, chains=4, iter_warmup=1000, iter_sampling=2000):
    """Run MCMC sampling. Returns a CmdStanMCMC object."""
    fit = model.sample(
        data=stan_data,
        chains=chains,
        iter_warmup=iter_warmup,
        iter_sampling=iter_sampling,
        adapt_delta=0.9,        # Increase if you get divergent transitions
        max_treedepth=12,       # Increase if you hit max treedepth warnings
    )
    return fit
```

### Step 5: Implement `diagnostics.py`

After fitting, you **must** check convergence before trusting results:

1. **R-hat** (potential scale reduction): Should be < 1.01 for all parameters. Use `fit.summary()` from CmdStanPy.
2. **Effective sample size (ESS)**: Should be > 400 for key parameters. If low, increase `iter_sampling`.
3. **Divergent transitions**: Should be 0. If > 0, increase `adapt_delta` (e.g., 0.95 or 0.99). If still present, the model may be misspecified.
4. **Posterior predictive checks**: Use `y_rep` from `generated quantities` to plot simulated data vs actual data. Use `arviz.plot_ppc()`.
5. **LOO-CV**: Use `arviz.loo()` with `log_lik` to check model fit and compare alternative specifications.

```python
import arviz as az

def check_diagnostics(fit):
    """Run standard convergence checks."""
    idata = az.from_cmdstanpy(fit)

    # Check R-hat and ESS
    summary = az.summary(idata, var_names=["mu_pop", "sigma_pop", "sigma_season", "sigma_race", "beta_improve"])
    print(summary)

    # Check divergences
    divergences = idata.sample_stats["diverging"].sum().item()
    print(f"Divergent transitions: {divergences}")

    # LOO-CV
    loo = az.loo(idata, var_name="log_lik")
    print(loo)

    return idata
```

### Step 6: Implement `predict.py`

Extract posterior samples and compute handicaps (see Section 6.2 pseudocode above).

Key functions:
- `get_posterior_samples(fit) -> dict`: Extract alpha, delta, gamma, beta_improve as numpy arrays.
- `predict_time(posterior, rider_idx, season_idx, race_type_idx) -> np.array`: Posterior predictive distribution for a rider's time.
- `calculate_handicaps(posterior, field, race_type_idx, season_idx) -> pd.DataFrame`: Compute handicaps for all riders in a field.

### Step 7: Write Tests

- **Unit tests for data_prep**: Check index mappings, run_seq calculation, fall exclusion.
- **Smoke test for Stan model**: Fit on a small synthetic dataset (5 riders, 2 seasons, 50 observations). Verify convergence and that recovered parameters are close to true values.
- **Integration test**: End-to-end from DB query to handicap output.

### Step 8: Validate Against Historical Committee Handicaps

- For past handicap races where committee handicaps are recorded, compare model-suggested handicaps to actual handicaps.
- Compute correlation and mean absolute error.
- Run backtest: simulate the handicap race outcome using model handicaps and check if parity improves (i.e., net times are closer together).

---

## 9. Validation Strategy

### 9.1 Prior Predictive Check (Before Fitting)

Before fitting to real data, sample from the priors only (set `N=0` or use a separate Stan program) and check that the implied distribution of finish times is plausible. For TOP, prior-predictive times should cover roughly 48–75 seconds. If the priors generate absurd values (e.g., negative times or 200+ seconds), adjust.

### 9.2 Posterior Predictive Check (After Fitting)

Use `y_rep` to generate simulated datasets from the fitted model. Compare:
- Distribution of simulated times vs actual times (histogram overlay).
- Per-rider simulated means and SDs vs actual means and SDs.
- If the model is well-calibrated, the real data should look like a plausible draw from the posterior predictive.

### 9.3 Cross-Validation

Use **leave-one-season-out** cross-validation:
- Fit on seasons 2021–2024, predict 2025 handicaps.
- Compare predicted handicaps to actual committee handicaps for 2025.
- Check if model handicaps would have produced more competitive race outcomes.

### 9.4 Sensitivity Analysis

Vary key priors and check that results are robust:
- Change `prior_mu_pop` by ±5 seconds.
- Change `prior_sigma_mu_pop` from 10 to 5 or 20.
- Halve and double `sigma_season`, `sigma_race` prior scales.
- If results change substantially with prior changes, the data may be insufficient and the committee should be warned.

---

## 10. Reporting Output

The final output for the committee should be a table like:

| Rider | Runs (Season) | Expected Time | Consistency (σ) | Suggested H'Cap | 95% CI | Confidence |
|-------|--------------|---------------|-----------------|----------------|--------|------------|
| F.J.A. Hitz | 42 | 53.2s | 0.8s | Scr | — | HIGH |
| C.E. Wallace | 28 | 56.4s | 1.2s | 3.20 | [2.5, 3.9] | HIGH |
| B.A.P. Bracher | 8 | 58.1s | 2.1s | 4.90 | [3.1, 6.8] | MEDIUM |
| New SL Rider | 4 | 62.3s | 3.5s | 9.10 | [5.2, 13.0] | LOW |

The wide CI for the SL rider tells the committee "we're not sure — use judgment here". The tight CI for Hitz says "we're confident, this rider is very consistent."

---

## 11. Incremental Model Updates

### Overview

The orchestrator (`src/smtc_handicap/orchestrator.py`, see `docs/implementation-plan-incremental-update.md`) triggers model refits automatically after new data is ingested. The model module exposes a single entry point for this:

### `refit_from_db(db_path, output_dir=None) -> dict`

```python
def refit_from_db(db_path: Path, output_dir: Path | None = None) -> dict:
    """Full refit of TOP + JUNCTION models from all DB data.
    Skips a model if < 20 observations for that start position."""
    for position in ("TOP", "JUNCTION"):
        stan_data = build_stan_data(db_path, start_position=position)
        if stan_data["N"] < 20:
            continue
        model = compile_model()
        fit = fit_model(model, stan_data)
        # Save results + run diagnostics
```

### How the Orchestrator Triggers Refits

1. `orchestrator.run_incremental()` calls `pipeline.ingest_new_pdfs()` and checks how many new records were inserted.
2. If new data was ingested **and** `refit_model=True` (the default), it calls `refit_from_db(db_path)`.
3. The refit uses **all** data in the DB (not just new data) — Stan fits the full hierarchical model from scratch. This ensures posterior estimates are globally consistent.
4. Each refit takes ~5–10 seconds per start position. The orchestrator logs timing and diagnostic summaries.
5. If `--no-refit` is passed via CLI, or no new data was ingested, the refit step is skipped.

### Design Rationale

- **Full refit, not incremental update**: Hierarchical Bayesian models do not support incremental posterior updates in a principled way. Re-running MCMC on the full dataset is the correct approach and is fast enough (<20s total) for the expected data volume (~2000–5000 observations).
- **Minimum observation threshold**: Models are skipped if fewer than 20 observations exist for a start position, avoiding degenerate fits early in a season.
- **Output**: Posteriors are saved to `data/model_output/` (configurable via `output_dir`). The orchestrator returns a summary dict including fit diagnostics.

---

## 12. Future Extensions (Post-MVP)

These are not needed for the first version but are natural next steps:

1. **Time-varying rider ability**: Replace the static $\alpha_j$ with a random walk $\alpha_{j,t}$ that drifts over seasons. This would capture long-term improvement or decline.

2. **Split-time sub-model**: Model each split section (Junction, Rise, Stream, Bulpetts) separately. This could reveal *where* a rider gains or loses time and produce more granular predictions.

3. **Censored fall model**: Treat falls as right-censored observations to extract partial information about rider speed.

4. **Condition effects**: If weather/ice condition data becomes available, add a condition covariate to explain race-day variation beyond the race-type effect.

5. **Per-rider improvement rates for SL**: With enough data, replace the shared `beta_improve` with per-rider improvement rates using another hierarchical level.

6. **Student-t likelihood**: Replace the Normal likelihood with a Student-t to be more robust to occasional outlier runs (e.g., a rider who stops mid-run).

---

## 13. Summary for Quick Reference

| Component | What it captures | Why it matters for handicapping |
|-----------|-----------------|--------------------------------|
| $\alpha_j$ (rider ability) | Long-run average speed | Core of the handicap: faster riders get less |
| $\delta_{s,j}$ (season form) | Current season fitness | A rider in bad form this year shouldn't get last year's handicap |
| $\gamma_r$ (race-type effect) | How competitive the race is | Riders push harder in cups; practice times aren't race times |
| $\sigma_j$ (consistency) | Run-to-run variability | Tells the committee how reliable the prediction is |
| $\beta_{\text{improve}}$ (SL trend) | Learning curve for new riders | SL riders improve rapidly; the model tracks this |

**The handicap formula**: For a given race, predict each rider's expected time using all components above. The handicap is the difference between each rider's predicted time and the fastest rider's predicted time. Uncertainty is quantified via the full posterior distribution.
