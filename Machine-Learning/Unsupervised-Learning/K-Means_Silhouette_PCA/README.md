# Ex2 – Unsupervised Learning  
## Customer Segmentation using K-Means & PCA

### Overview

This project focuses on the practical implementation of **unsupervised learning techniques** for customer segmentation.

The objective of the assignment was to apply clustering and dimensionality reduction methods in order to discover hidden structures in customer behavioral data and extract meaningful patterns without labeled targets.

The project demonstrates the full unsupervised learning workflow:  
data preprocessing, clustering, dimensionality reduction, evaluation, and interpretation.

---

## Project Objectives

- Load and preprocess real-world tabular data
- Perform exploratory data analysis (EDA)
- Apply K-Means clustering
- Evaluate cluster quality using quantitative metrics
- Perform dimensionality reduction using PCA
- Analyze the impact of dimensionality reduction on clustering performance
- Derive business-oriented insights from clustering results

---

## Methodology

### Data Preparation
- Handling missing values (median imputation)
- Feature scaling using MinMaxScaler
- Categorical feature encoding (One-Hot Encoding)
- Removal of non-informative columns

### Clustering
- K-Means applied on selected features
- K-Means applied on the full feature space
- Optimal number of clusters determined using:
  - Elbow Method (inertia)
  - Silhouette Score

### Dimensionality Reduction
- Principal Component Analysis (PCA) with 2 components
- Variance explained analysis
- Visualization in reduced feature space

### PCA + KMeans
- Clustering on reduced-dimensional data
- Comparison of clustering quality before and after PCA
- Evaluation based on silhouette scores and visual separation

---

## Technologies Used

- Python  
- Pandas  
- NumPy  
- Matplotlib  
- Scikit-learn  
  - KMeans  
  - MinMaxScaler  
  - PCA  
  - silhouette_score  

---

## Skills Demonstrated

- End-to-end unsupervised learning pipeline
- Data preprocessing and feature engineering
- Cluster validation and model evaluation
- Dimensionality reduction techniques
- Analytical reasoning and interpretation of model results
- Business insight extraction from unlabeled data

---

## How to Run

1. Install dependencies:
