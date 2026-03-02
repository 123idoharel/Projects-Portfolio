# Smart Parking Guidance System

## Overview
The Smart Parking Guidance System is a decision-support application that simulates real-time parking allocation and navigation inside a multi-floor parking facility.

The system models the parking environment as a weighted graph and provides intelligent parking recommendations based on distance, congestion, and user preferences.

This project demonstrates system design, graph algorithms, simulation, and interactive visualization.

---

## Key Features

- Graph-based modeling of multi-floor parking layouts  
- Real-time parking allocation based on availability and demand  
- Route optimization using Dijkstra’s algorithm  
- Dynamic scoring based on:
  - Distance to target (entrance / exit / elevator)
  - Current occupancy and load
  - User preference
- Simulation of vehicle arrivals and parking occupancy
- Interactive visualization for:
  - Operator monitoring
  - User navigation

---

## System Architecture

The system is designed with a modular architecture:

- **Offline layer**
  - Layout loading and preprocessing
  - Graph construction
  - Distance calculations

- **Runtime layer**
  - Real-time occupancy simulation
  - Parking assignment logic
  - Route generation

- **Visualization layer**
  - Interactive dashboards using Streamlit
  - Separate views for operators and drivers

---

## Technologies

- Python
- Streamlit
- Graph Algorithms
- JSON-based configuration
- JavaScript (Web interface extension)

---

## Algorithms and Concepts

- Dijkstra shortest path
- Graph modeling of physical environments
- Real-time decision logic
- Simulation systems
- Separation of offline/online computation
- Modular system architecture


---

## Project Goals

This project was developed to demonstrate:

- End-to-end system development
- Algorithmic problem solving
- Real-time simulation
- Interactive user interface design
- Software architecture and modular design

---
