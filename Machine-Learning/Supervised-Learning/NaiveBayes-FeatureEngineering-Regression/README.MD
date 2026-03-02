# Machine Learning Project  
## Naive Bayes Classification & FeatureEngineering & Regression

## Overview

This project combines two supervised machine learning tasks:

1. **Handwritten Digit Classification (MNIST)** using a generative model  
2. **Virality Score Prediction** (0–100) using a full regression pipeline developed for a private Kaggle competition  

The work demonstrates end-to-end ML capabilities including data preprocessing, model training, evaluation, hyperparameter tuning, and model explainability.

---

# Project Objectives

- Apply supervised learning techniques for classification and regression
- Perform structured preprocessing
- Engineer meaningful features from raw metadata and text
- Evaluate model performance using appropriate metrics (MSE, etc)
- Improve model generalization through hyperparameter tuning
- Interpret model behavior using SHAP explainability tools

---

# Part 1 – MNIST Digit Classification

### Goal
Classify handwritten digits (0–9) from grayscale images.

### Approach
- Dataset loaded via Keras (MNIST)
- Images flattened into 784-dimensional vectors
- Bernoulli Naive Bayes classifier applied
- Pixel values binarized for compatibility with Bernoulli assumptions

### Evaluation
- Confusion matrix analysis
- Accuracy computation
- Visualization of learned class representations
- Generation of synthetic digit samples using learned distributions

### Concepts Demonstrated
- Generative modeling
- Conditional probability modeling
- Multi-class classification
- Model evaluation via confusion matrix

---

# Part 2 – Virality Score Prediction (Kaggle)

### Goal
Predict the virality score of short-form videos based on metadata, categorical features, timestamps, and text.

### Approach

#### 1. Exploratory Data Analysis (EDA)
- Missing value analysis
- Linear and non-linear pattern detection
- Interaction analysis between features
- Temporal and behavioral trend discovery

#### 2. Feature Engineering
- Missing value imputation
- One-hot encoding for categorical features
- Cyclic encoding (sin/cos) for temporal features
- Behavioral features (upload frequency per user)
- Custom binary indicators (extreme follower effect)
- Text vectorization using TF-IDF
- Topic modeling using NMF for compact semantic representation

#### 3. Model
- DecisionTreeRegressor
- Hyperparameter tuning via RandomizedSearchCV
- Cross-validation for generalization control

#### 4. Evaluation
- Mean Squared Error (MSE)
- Mean Absolute Error (MAE)
- R² score
- Private Kaggle leaderboard ranking

#### 5. Explainability
- SHAP analysis
- Global feature importance
- Feature interaction insights
- Instance-level prediction explanation

---

# Technologies Used

- Python
- Pandas
- NumPy
- Scikit-learn
- TensorFlow / Keras
- Matplotlib
- SciPy
- SHAP
- TF-IDF (text vectorization)
- NMF (topic modeling)

---

# Skills Demonstrated

- Supervised classification and regression
- Structured preprocessing of heterogeneous data
- Feature engineering for real-world ML problems
- Handling missing and sparse data
- Hyperparameter optimization
- Model evaluation and validation
- Model interpretability and explainability
- Kaggle competition workflow

pip install numpy pandas matplotlib scikit-learn tensorflow keras scipy shap
