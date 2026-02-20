// =============================================================================
// Cresta Run Handicap Model (Multi-Season, Heteroscedastic, Student-t)
// Hierarchical Bayesian model for predicting rider finish times.
//
// Separate models are fitted for TOP and JUNCTION start positions.
// Uses per-rider observation noise sigma_rider[J] (log-normal hierarchy)
// instead of a single shared sigma_obs. This captures that some riders
// are more consistent than others, enabling quantile-based handicaps
// that penalize volatile riders.
//
// Student-t likelihood for robustness to outlier times, improving
// alpha[j] estimation for riders with occasional anomalous runs.
//
// Season effects: global eta[S] + per-rider linear trend beta_trend[J].
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
  vector[N] run_seq;                      // Per-season sequential run number for this rider

  // Season trend data
  vector[S] season_num;              // Centered season numbers for trend term

  // Prior configuration (passed from Python so TOP/JUNCTION can differ)
  real prior_mu_pop;            // Prior mean for population mean (57 for TOP, 48 for JUNCTION)
  real prior_sigma_mu_pop;      // Prior sd for population mean (10)
}

parameters {
  // --- Population level ---
  real mu_pop;                              // Population mean finish time
  real<lower=0> sigma_pop;                  // Between-rider spread in ability

  // --- Rider level (non-centered parameterization for efficiency) ---
  vector[J] alpha_raw;                      // Standardized rider abilities

  // --- Per-rider observation noise (log-normal hierarchy) ---
  real mu_log_sigma;                        // Population center for log(sigma_rider)
  real<lower=0> sigma_log_sigma;            // Spread in log(sigma_rider) across riders
  vector[J] log_sigma_raw;                  // Standardized per-rider log-sigmas

  // --- Season effects (global, non-centered) ---
  real<lower=0> sigma_season;               // How much seasons vary (ice/weather)
  vector[S] eta_raw;                        // Standardized season effects

  // --- Per-rider trend over seasons (non-centered) ---
  real beta_trend_mu;                       // Population mean trend (improvement/decline)
  real<lower=0> sigma_trend;                // Between-rider trend spread
  vector[J] beta_trend_raw;                 // Standardized per-rider trends

  // --- Global quadratic season curvature ---
  real beta_quad;                            // Quadratic term for population trend

  // --- Race-type effect (non-centered) ---
  real<lower=0> sigma_race;                 // How much race types vary
  vector[R] gamma_raw;                      // Standardized race-type effects

  // --- SL within-season improvement ---
  real beta_improve;                        // Mean improvement rate (seconds per run, expect < 0)

  // --- Student-t degrees of freedom ---
  real<lower=2> nu;                         // df for heavy-tailed likelihood (>30 ≈ normal)
}

transformed parameters {
  // Rider baseline abilities (non-centered -> centered)
  vector[J] alpha = mu_pop + sigma_pop * alpha_raw;

  // Global season effects
  vector[S] eta = sigma_season * eta_raw;

  // Per-rider linear trends
  vector[J] beta_trend = beta_trend_mu + sigma_trend * beta_trend_raw;

  // Race-type effects
  vector[R] gamma = sigma_race * gamma_raw;

  // Per-rider observation noise (log-normal, non-centered)
  vector<lower=0>[J] sigma_rider;
  for (j in 1:J)
    sigma_rider[j] = exp(mu_log_sigma + sigma_log_sigma * log_sigma_raw[j]);

  // Expected time for each observation
  vector[N] mu;
  for (n in 1:N) {
    mu[n] = alpha[rider[n]]
            + eta[season[n]]
            + beta_trend[rider[n]] * season_num[season[n]]
            + beta_quad * square(season_num[season[n]])
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
  sigma_season ~ normal(0, 3);
  sigma_race ~ normal(0, 2);
  sigma_trend ~ normal(0, 0.5);   // tighter prior to reduce trend extrapolation errors

  // --- Per-rider sigma hyperpriors ---
  mu_log_sigma ~ normal(log(2.0), 0.5);    // population center ~2s
  sigma_log_sigma ~ normal(0, 0.5);         // spread in consistency

  // --- Trend population mean ---
  beta_trend_mu ~ normal(0, 1);   // expect ~0 mean population trend

  // --- Global quadratic curvature ---
  beta_quad ~ normal(0, 0.5);     // weakly informative, expect small

  // --- Rider level ---
  alpha_raw ~ std_normal();        // implies alpha ~ N(mu_pop, sigma_pop)

  // --- Per-rider sigma ---
  log_sigma_raw ~ std_normal();    // implies log(sigma_rider) ~ N(mu_log_sigma, sigma_log_sigma)

  // --- Season effects ---
  eta_raw ~ std_normal();          // implies eta ~ N(0, sigma_season)

  // --- Per-rider trends ---
  beta_trend_raw ~ std_normal();   // implies beta_trend ~ N(beta_trend_mu, sigma_trend)

  // --- Race-type effects ---
  gamma_raw ~ std_normal();        // implies gamma ~ N(0, sigma_race)

  // --- SL improvement ---
  beta_improve ~ normal(-0.3, 0.3);

  // --- Student-t degrees of freedom ---
  nu ~ gamma(2, 0.1);  // prior favors moderate tails (mode ~10)

  // --- Likelihood (Student-t, per-rider noise) ---
  {
    vector[N] sigma_vec;
    for (n in 1:N)
      sigma_vec[n] = sigma_rider[rider[n]];
    y ~ student_t(nu, mu, sigma_vec);
  }
}

generated quantities {
  // Backward-compatible sigma_obs: population center of sigma_rider
  real sigma_obs = exp(mu_log_sigma);

  // Posterior predictive checks
  vector[N] y_rep;
  for (n in 1:N)
    y_rep[n] = student_t_rng(nu, mu[n], sigma_rider[rider[n]]);

  // Log-likelihood for LOO-CV model comparison
  vector[N] log_lik;
  for (n in 1:N)
    log_lik[n] = student_t_lpdf(y[n] | nu, mu[n], sigma_rider[rider[n]]);
}
