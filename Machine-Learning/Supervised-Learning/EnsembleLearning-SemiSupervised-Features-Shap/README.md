# ML Project 3 – Theory, Ensemble Learning, Semi-Supervised Learning & Feature Engineering

## Overview
This project contains three main parts that combine **machine learning theory**, **supervised learning with ensembles**, **semi-supervised learning**, and a complete workflow of **feature generation/selection + explainability**.

The work demonstrates end-to-end ML skills: simulation, reasoning/proof, preprocessing, model training, evaluation, feature engineering, and interpretability.

---

# Part 1 — Condorcet’s Jury Theorem (Monte Carlo + Proof)

## Goal
Study how majority voting behaves when each voter has probability \( p>0.5 \) to be correct:
- Empirically estimate the probability that a jury majority is correct using **Monte-Carlo simulations**
- Prove that as jury size grows \( n\to\infty \), majority correctness tends to 1 using the **Law of Large Numbers**

## Skills demonstrated
- Probabilistic modeling 
- Simulation & estimation
- Visualization and interpretation

---

# Part 2 — AdaBoost + Semi-Supervised Learning (CIFAR-10)

## Goal
Train an ensemble model on a **small labeled subset** and explore how to leverage additional **unlabeled data** to improve performance.

Dataset: **CIFAR-10** (10 classes, 32×32 RGB images)

## Workflow
### 1) EDA (Exploratory Data Analysis)
- Printed dataset statistics (sizes, shapes, class count)
- Visualized a sample image per class
- Analyzed:
  - class distribution (balance)
  - pixel intensity distribution
  - RGB channel behavior

### 2) Baseline Supervised Model
- Preprocessed images by flattening to feature vectors and normalizing pixels to [0,1]
- Trained **AdaBoostClassifier** with a small decision tree as weak learner
- Evaluated accuracy on the test set

### 3) Semi-Supervised Improvement (Pseudo-Labeling)
- Predicted class probabilities on unlabeled data
- Selected the most confident predictions (top-confidence samples)
- Added pseudo-labeled samples to training set
- Retrained AdaBoost with the same strength and compared performance

## Skills demonstrated
- Ensemble learning (AdaBoost)
- Practical preprocessing of image data
- Semi-supervised idea: pseudo-labeling
- Evaluation and analysis of improvement limits

---

# Part 3 — Feature Engineering, Feature Selection & Explainability 

## Goal
Build a predictive model for wine quality while practicing:
- Feature generation
- Feature transformations (engineering)
- Feature selection (multiple methods)
- Model evaluation
- Explainability (global + local) using SHAP

Dataset: **UCI Wine Quality** (physicochemical tests → quality score)

## Workflow
### 1) Preprocessing + EDA
- Loaded dataset from UCI repository
- Produced statistics and plots:
  - target distribution
  - feature distributions
  - correlation heatmap
  - feature-to-target correlations
- Standardized features before linear modeling and selection

### 2) Feature Generation (new meaningful features)
Examples:
- alcohol-to-sugar ratio
- total acidity index
- sulfur balance (free/total)

### 3) Feature Engineering (transformations)
Examples:
- log transform for skewed sulfur dioxide
- polynomial term (alcohol²)
- interaction feature (alcohol × sulphates)

### 4) Feature Selection
Compared two methods:
- **RFE** (Recursive Feature Elimination)
- **Lasso** (sparse linear selection)

Used selected features (union/strong overlap) to build a compact model.

### 5) Modeling + Evaluation
- Trained a **Linear Regression** model
- Reported standard regression metrics (MAE / MSE / R²)

### 6) Explainability (SHAP)
- **Global explanation:** top contributing features across all samples
- **Local explanation:** explained two specific predictions (high vs low) using waterfall plots


# Tech Stack
- Python, NumPy, Pandas
- Matplotlib (and Seaborn for correlation heatmap)
- Scikit-learn: AdaBoost, Decision Trees, preprocessing, metrics, RFE, Lasso, Linear Regression
- Keras datasets: MNIST / CIFAR-10
- SHAP (explainability)
- ucimlrepo (Wine Quality fetch)
bash
pip install numpy pandas matplotlib seaborn scikit-learn shap tensorflow keras ucimlrepo
