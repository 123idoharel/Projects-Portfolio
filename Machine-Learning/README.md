# Machine Learning Projects Collection  
**Ido Harel**

---

## Overview

This repository contains several machine learning projects, led by **Football_Scouting_ML** — an end-to-end machine learning project for forecasting the future market value and career potential of professional football players.

The repository also includes academic projects covering unsupervised learning, ensemble methods, semi-supervised learning, feature engineering, feature selection, statistical simulations, and model explainability.

---

# Main Project — Football_Scouting_ML

## Project Overview

**Football_Scouting_ML** is an end-to-end machine learning project designed to forecast the future market value of professional football players.

The project combines historical player performance data, market-value records, career progression indicators, and extensive feature engineering to estimate:

- A player’s future career peak market value
- The player’s expected market value over one-to-two-year forecasting horizons
- Pessimistic, expected, and optimistic development scenarios

The goal is to support data-driven scouting by identifying players with strong future growth potential while representing the uncertainty of their possible career development.

---

## Data Collection and Preparation

The project integrates data for approximately **40,000 professional football players**, including:

- Historical performance statistics
- Seasonal and competition-level data
- Player age, position, and career information
- Historical market-value records
- Domestic, continental, and national-team experience

The data preparation process included:

- Cleaning and standardizing records from multiple sources
- Matching players across datasets
- Handling missing values and duplicate records
- Preventing future-data leakage
- Building time-aware training samples
- Creating separate datasets for attackers, midfielders, defenders, and goalkeepers

---

## Exploratory Data Analysis

Extensive exploratory data analysis was performed to examine:

- Market-value distributions
- Player development patterns by age and position
- Relationships between performance and future value
- Historical market-value trajectories
- Missing-data patterns
- Differences between growing, stable, and declining players

The analysis guided the preprocessing, feature engineering, target construction, and modeling decisions.

---

## Feature Engineering

Hundreds of features were generated to represent each player’s current ability and career trajectory, including:

- Current and historical market value
- Market-value growth and decline rates
- Recent performance and career averages
- Playing time and appearance statistics
- Age and career-stage indicators
- Performance trends and consistency
- Competition-level indicators
- Domestic, continental, and international experience
- Historical data-depth and availability indicators
- Interactions between age, performance, and current valuation

Position-specific datasets allowed the models to learn different relationships for attackers, midfielders, defenders, and goalkeepers.

---

## Prediction Targets

The project investigated two main forecasting objectives:

### Future Career Peak

Predicting the maximum market value a player is expected to reach during the remainder of their career.

### One-to-Two-Year Forecasting

Predicting a player’s future market value over shorter forecasting horizons, mainly:

- 12 months
- 24 months

Different target formulations were examined, including absolute future value, relative value growth, and future maximum value within a defined horizon.

---

## Main Modeling Approach

The main modeling pipeline was based on **XGBoost Quantile Regression**.

Instead of producing only a single prediction, separate quantile models were trained to estimate multiple possible future outcomes:

- **Q10 — Pessimistic scenario**
- **Q50 — Expected or median scenario**
- **Q75 — Positive development scenario**
- **Q90 — Optimistic scenario**

This approach provides a range of possible future values and represents the uncertainty associated with player development.

Other models, including **LightGBM, CatBoost, neural networks, and ensemble configurations**, were also tested and compared during the experimentation process.

---

## Growth Classification

An additional classification model was developed to estimate the probability that a player would experience a meaningful increase in market value.

This allowed the system to distinguish between:

- Players with strong growth potential
- Players expected to remain relatively stable
- Players whose value may decline

The growth probability was also used alongside the regression outputs to improve the interpretation of the final predictions.

---

## Model Evaluation

The models were evaluated separately for each player position using:

- Mean Absolute Error
- Mean Squared Error
- Pinball loss
- Spearman rank correlation
- ROC-AUC
- Precision-Recall AUC
- Quantile interval coverage
- Group-based cross-validation
- Temporal backtesting

Time-aware validation was used to ensure that the models were evaluated on future player cohorts and that information from the prediction period was not included during training.

---

## Explainability and Uncertainty

The project includes analysis of:

- The most influential features
- Position-specific prediction patterns
- Model errors
- Predicted versus actual market-value trajectories
- Growth-probability calibration
- Cases of underestimation and overestimation

Quantile predictions and calibration methods were used to provide both a future-value estimate and an uncertainty range around that estimate.

---

## Main Skills Demonstrated

- End-to-end machine learning development
- Multi-source data integration
- Large-scale data preprocessing
- Exploratory data analysis
- Advanced feature engineering
- Time-aware dataset construction
- XGBoost quantile regression
- Classification and regression
- Position-specific modeling
- Model comparison and evaluation
- Temporal backtesting
- Uncertainty estimation
- Explainable machine learning
- Football analytics and data-driven scouting

---

# Additional Academic Machine Learning Projects

## Unsupervised Learning — Clustering and PCA

A customer-segmentation project covering:

- K-Means clustering
- Principal Component Analysis
- Dimensionality reduction
- Elbow and Silhouette evaluation
- Data preprocessing and scaling
- Cluster visualization and interpretation

---

## Condorcet’s Jury Theorem

A theoretical and computational analysis of majority voting using:

- Monte Carlo simulations
- Statistical experiments
- Majority-voting behavior
- The Law of Large Numbers
- Empirical and theoretical convergence analysis

---

## AdaBoost Classification

An ensemble-learning project involving:

- AdaBoost
- Decision-tree weak learners
- Image preprocessing
- Image vectorization
- Training on a limited labeled dataset
- Classification-performance evaluation

---

## Semi-Supervised Learning

A semi-supervised classification experiment using:

- Pseudo-labeling
- Confidence-based sample selection
- Unlabeled training data
- Baseline and extended-model comparison

The project examined when pseudo-labeling improves performance and where the method may introduce errors.

---

## Feature Engineering, Selection and Explainability

A regression project based on the **UCI Wine Quality Dataset**, covering:

- Exploratory data analysis
- Feature transformations
- Polynomial and interaction features
- Recursive Feature Elimination
- Lasso-based feature selection
- Linear regression
- MAE, MSE, and R² evaluation
- Global and local SHAP explanations

---

# Core Machine Learning Competencies

- Supervised learning
- Unsupervised learning
- Ensemble methods
- Semi-supervised learning
- Gradient boosting
- Quantile regression
- Classification and regression
- Dimensionality reduction
- Feature engineering
- Feature selection
- Temporal validation
- Model evaluation
- Statistical simulation
- Uncertainty estimation
- Model explainability

---

# Technologies Used

- Python
- NumPy
- Pandas
- Matplotlib
- Seaborn
- Scikit-learn
- XGBoost
- LightGBM
- CatBoost
- TensorFlow / Keras
- SHAP

---

**Ido Harel**  
Information Systems Engineering Student  
Ben-Gurion University
