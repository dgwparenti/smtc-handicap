// =============================================================================
// Cresta Run Handicap Model
// Hierarchical Bayesian model for predicting rider finish times.
//
// Separate models are fitted for TOP and JUNCTION start positions.
// Uses a single shared observation noise sigma_obs rather than per-rider
// sigma_rider to keep the parameter space tractable with sparse data.
// Per-rider consistency is computed post-hoc from residuals.
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
  real prior_mu_pop;            // Prior mean for population mean (57 for TOP, 48 for JUNCTION)
  real prior_sigma_mu_pop;      // Prior sd for population mean (10)
  real<lower=0> prior_sigma_season_sd;  // Prior sd for sigma_season (2 normally, 0.01 when S=1)
}

parameters {
  // --- Population level ---
  real mu_pop;                              // Population mean finish time
  real<lower=0, upper=20> sigma_pop;        // Between-rider spread in ability

  // --- Rider level (non-centered parameterization for efficiency) ---
  vector[J] alpha_raw;                      // Standardized rider abilities

  // --- Shared observation noise ---
  real<lower=0, upper=15> sigma_obs;        // Shared run-to-run variability

  // --- Season form ---
  real<lower=0, upper=10> sigma_season;     // How much riders vary season to season
  matrix[S, J] delta_raw;                   // Standardized season x rider deviations

  // --- Race-type effect ---
  real<lower=0, upper=10> sigma_race;       // How much race types vary
  vector[R] gamma_raw;                      // Standardized race-type effects

  // --- SL improvement ---
  real beta_improve;                        // Mean improvement rate (seconds per run, expect < 0)
}

transformed parameters {
  // Rider baseline abilities (non-centered -> centered)
  vector[J] alpha = mu_pop + sigma_pop * alpha_raw;

  // Season x rider form deviations
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
  sigma_season ~ normal(0, prior_sigma_season_sd);
  sigma_race ~ normal(0, 1.5);

  // --- Observation noise ---
  sigma_obs ~ normal(0, 3);       // half-normal via constraint

  // --- Rider level ---
  alpha_raw ~ std_normal();        // implies alpha ~ N(mu_pop, sigma_pop)

  // --- Season form ---
  to_vector(delta_raw) ~ std_normal();  // implies delta ~ N(0, sigma_season)

  // --- Race-type effects ---
  gamma_raw ~ std_normal();        // implies gamma ~ N(0, sigma_race)

  // --- SL improvement ---
  beta_improve ~ normal(-0.3, 0.2);

  // --- Likelihood ---
  y ~ normal(mu, sigma_obs);
}

generated quantities {
  // Posterior predictive checks: simulate new data from the model
  vector[N] y_rep;
  for (n in 1:N)
    y_rep[n] = normal_rng(mu[n], sigma_obs);

  // Log-likelihood for LOO-CV model comparison
  vector[N] log_lik;
  for (n in 1:N)
    log_lik[n] = normal_lpdf(y[n] | mu[n], sigma_obs);
}
