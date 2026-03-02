# Maze Generator & Solver (JavaFX + MVVM + Client–Server)

## Overview
An interactive JavaFX application for generating and solving complex mazes.
The project demonstrates end-to-end software engineering: GUI development, MVVM architecture, graph search algorithms, and a client–server design that separates computation services (maze generation & solving) from the UI.

## Key Features
- **Maze generation** based on requested dimensions (Rows/Cols)
- **Maze solving** (shows solution path)
- **Interactive GUI** (JavaFX + FXML)
- **MVVM architecture**:
  - View (FXML + Controller)
  - ViewModel (JavaFX properties + bindings)
  - Model (logic, networking, persistence)
- **Client–Server** computation:
  - Maze generation server (port **5400**)
  - Maze solving server (port **5401**)
- **Player movement** and UI interaction handled from the View layer
- **Save / Load** maze state via menu actions
- **Media support**: background music + goal sound (assets under `/sounds/`)
- **Graphics**: custom maze rendering component (`MazeRepresentor`) with images for player/background/goal

---

## Architecture

### View (UI)
- **FXML:** `MyView.fxml`
- **Controller:** `MyViewController.java`
- Contains UI controls such as:
  - Text fields for rows/cols
  - Buttons: **Generate Maze**, **Show Solution**
  - Menus: New / Save / Load / Properties / Help / About / Exit
- The controller:
  - Handles button/menu clicks
  - Connects to the ViewModel
  - Updates the custom maze renderer (`MazeRepresentor`)
  - Manages focus for keyboard controls and user interaction

### ViewModel
- **File:** `MyViewModel.java`
- Exposes observable JavaFX properties:
  - `maze_property`
  - `player_position_property`
  - `solution_property`
  - `reached_goal_property`
- Acts as the bridge between View events and Model actions.

### Model (Logic + Networking + Persistence)
- **File:** `MyModel.java`
- Responsible for:
  - **Generating a maze** by connecting a local client to the generation server (**localhost:5400**)
  - **Solving a maze** by connecting a local client to the solving server (**localhost:5401**)
  - Decompressing the received maze bytes and building a `Maze` object
  - Saving/Loading maze state (used by menu actions)

### Servers
- Started automatically when the application starts.
- Two servers run on separate threads:
  - **Generate Server:** port `5400` (strategy: Generate Maze)
  - **Solve Server:** port `5401` (strategy: Solve Search Problem)

---

## Entry Point (How the app starts)
**Main class:** `View/Main.java`

This class:
1. Starts both servers (generate & solve)
2. Loads the UI from `MyView.fxml`
3. Creates `MyModel` and `MyViewModel`
4. Connects ViewModel ⇄ Model and Controller ⇄ ViewModel
5. Opens the JavaFX stage (window)

---

## How to Run

### Option 1 — IntelliJ (Recommended)
1. Open the project in IntelliJ
2. Locate and run:
   - `src/main/java/View/Main.java`
3. Click **Run** ▶️ on `Main`

### Option 2 — Maven (If configured)
run JavaFX via Maven.

**Windows:**
```bash
mvnw.cmd javafx:run
