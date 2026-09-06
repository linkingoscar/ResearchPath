# R engine map

| File | Public role | Called by |
|---|---|---|
| `run_analysis.R` | Frozen PROCESS/path/SEM ModelSpec → ResultBundle | `app.services.r_engine` |
| `run_empirical_analysis.R` | Questionnaire methods plus latent longitudinal-panel, diary/ESM, multilevel MI and Monte Carlo planning evidence | `app.services.empirical_analysis` |
| `worker.R` | Resident task host for approved R entrypoints | `app.services.r_workers` |
| `lib/*.R` | Focused estimators, bootstrap, EFA/CFA/validity, runtime and resource helpers | Sourced by the public entrypoints |
| `r_sem_helpers.R` | lavaan fit, parameter and latent reliability helpers | `lib/sem_analysis.R` |

The three `run_*.R` files and `worker.R` are command entrypoints, not reusable libraries. New estimators belong in focused helper modules sourced by an entrypoint. Statistical formulas stay in the R engine rather than React or FastAPI routes. An executable capability must satisfy the Python result contract.

Current module boundaries:

- `run_analysis.R`: IO/progress, data preparation, equation compilation, path estimators, bootstrap and SEM result assembly;
- `run_empirical_analysis.R`: descriptive/factorability, EFA, CFA, validity, group comparison, hierarchical regression, longitudinal panel and diary multilevel orchestration;
- `run_advanced_analysis.R`: experimental, multilevel, imputation, power and advanced measurement requests;
- `longitudinal_*.R` and `diary_*.R`: panel and intensive-longitudinal estimators, diagnostics and method-specific power.

Keep module changes local and run the nearest NumPy, lavaan or boundary tests for the affected estimator.
