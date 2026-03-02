package ViewModel;

import Model.IModel;
import View.IView;
import algorithms.mazeGenerators.Maze;
import algorithms.mazeGenerators.Position;
import algorithms.search.BreadthFirstSearch;
import algorithms.search.SearchableMaze;
import algorithms.search.Solution;
import javafx.application.Platform;
import javafx.beans.property.BooleanProperty;
import javafx.beans.property.ObjectProperty;
import javafx.beans.property.SimpleBooleanProperty;
import javafx.beans.property.SimpleObjectProperty;
import javafx.scene.control.Alert;
import javafx.scene.input.KeyCode;
import javafx.scene.input.MouseEvent;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;

public class MyViewModel {

    //the ViewModel layer holds the model and view layers and can approach them.
    private IModel model;
    private IView view;

    // also holds properties (which enables listeners) for main events (like maze change or player movement etc..).
    public ObjectProperty<Maze> maze_property = new SimpleObjectProperty<>();
    public ObjectProperty<Position> player_position_property = new SimpleObjectProperty<>();
    public ObjectProperty<Solution> solution_property = new SimpleObjectProperty<>();
    public BooleanProperty reached_goal_property = new SimpleBooleanProperty(false);


    public void set_model(IModel model) {
        // first, we connect the layer to the model.
        this.model = model;

        // updates the model's function that will run when a maze is generated (after generated)
        // 'maze' is the generated Maze.
        // the function: updates the properties for the changes in the maze and the position fields.
        this.model.setOnMazeGenerated(maze -> {
            if (maze == null) {
                return;
            }
            try {
                // wait for UI thread because affects graphics
                Platform.runLater(() -> {
                    //we want to update the property. it causes a call for 'equal' function - so here we validate
                    // that not the current or the new maze are null.
                    Maze currentMaze = maze_property.get();
                    if (maze != null && (currentMaze == null || !maze.equals(currentMaze))) {
                        // updates that we have a new maze - updates the property and the listener will know.
                        maze_property.set(maze);
                    }

                    // after the maze update we update the player position property. also check not null.
                    Position pos = maze.getStartPosition();
                    Position current = player_position_property.get();
                    if (pos != null && (current == null || !pos.equals(current))) {
                        player_position_property.set(pos);
                    }
                });
            } catch (Exception e) {
               view.show_alert(Alert.AlertType.ERROR,"Error processing maze: " ,"retry");
                e.printStackTrace();
            }
        });
    }
    public void set_view(IView view){
        this.view = view;
    }

// check valid sizes and send to the model to generate. (will update the property from inside)
    public void generateMaze(int rows, int cols){
        if(rows < 1 || cols < 1){
            view.show_alert(Alert.AlertType.ERROR, "size problem", "too small size - re-enter and generate");
            return;
        }
        model.generateMaze(rows,cols);

    }

    // when user request to represent the solution.
    //ask the model to solve (updates the model's field inside) - and updates the property.
    public void show_solution(){
        if(model.get_maze() == null){
            view.show_alert(Alert.AlertType.ERROR, "error", "maze doesn't exists");
            return;
        }
        model.solveMaze();
        Solution sol = model.get_solution();
        if(sol == null){
            view.show_alert(Alert.AlertType.ERROR, "can't solve", "there is no solution");
            return;
        }
        Solution newSol = model.get_solution();
        Solution oldSol = solution_property.get();
        if (newSol != null && (oldSol == null || !newSol.equals(oldSol))) {
            solution_property.set(newSol);
        }
    }

    // gets the pressed key and decides the new position by it.
    // we check that we can move to the cell in terms of movement rules and walls,
    // ask the model to move the player and then update the property.

    public void move_player(KeyCode key) {
        Position current = model.get_player_position();
        int row = current.getRowIndex();
        int col = current.getColumnIndex();

        switch (key) {
            case NUMPAD8:
                row--;
                break;
            case NUMPAD2:
                row++;
                break;
            case NUMPAD4:
                col--;
                break;
            case NUMPAD6:
                col++;
                break;
            case NUMPAD7:
                row--;
                col--;
                break;
            case NUMPAD9:
                row--;
                col++;
                break;
            case NUMPAD1:
                row++;
                col--;
                break;
            case NUMPAD3:
                row++;
                col++;
                break;
            default:
                return;
        }

        Position new_position = new Position(row, col);

        if (!model.can_move_to(new_position)){
            view.show_alert(Alert.AlertType.ERROR, "move problem", "can't move to requested position. try again");
            return;
        }
        model.move_player_to(new_position);
        Position newPos = model.get_player_position();
        Position oldPos = player_position_property.get();
        if (newPos != null && (oldPos == null || !newPos.equals(oldPos))) {
            player_position_property.set(newPos);
        }

        // if reached the goal: update the property.
        if(model.reached_goal()){
            reached_goal_property.set(true);
        }

    }

    // this is the function that's being called after mouse drag.
    // here we must make sure that there is a valid path to the new position.
    // we calculate the new position, check, and updates the model and the property.
    public void move_player_to(MouseEvent event, double width, double height){
        Maze maze = model.get_maze();
        int rows = maze.getMaze().length;
        int cols = maze.getMaze()[0].length;

        // calculate new position
        int col = (int)((event.getX()) / (width / cols));
        int row = (int)((event.getY()) / (height / rows));
        Position move_to = new Position(row,col);

        // creates the ExtraSearchableMaze which is a wrapper designed to let us know if there is a valid path in the maze
        // between 2 positions which are not the random start and goal.
        ExtraSearchableMaze sm = new ExtraSearchableMaze(maze,model.get_player_position(),new Position(row,col));
        BreadthFirstSearch bfs = new BreadthFirstSearch();
        Solution sol = bfs.solve(sm);

        // check if there is a solution and the movement is valid by rules and walls (could give up but extra ensure)
        if (!(sol!=null && model.can_move_to(move_to))){
            view.show_alert(Alert.AlertType.ERROR, "move problem", "can't move to requested position. try again");
            return;
        }
        // update the model and then the property (ensures not null)
        model.move_player_to(move_to);
        Position oldPos = player_position_property.get();
        if (move_to != null && (oldPos == null || !move_to.equals(oldPos))) {
            player_position_property.set(move_to);
        }        if(model.reached_goal()){
            reached_goal_property.set(true);
        }
    }

    // call the model for save
    public void save(File file){
        try {
            model.save(file);
        } catch (Exception e){
            view.show_alert(Alert.AlertType.ERROR, "error","couldn't save");
        }
    }

    // call the model for load and then updates the maze and the property
    public void load(File file){
        try{
            model.load(file);
            Maze loadedMaze = model.get_maze();
            Maze oldMaze = maze_property.get();
            if (loadedMaze != null && (oldMaze == null || !loadedMaze.equals(oldMaze))) {
                maze_property.set(loadedMaze);
            }
        }
        catch (Exception e){
            view.show_alert(Alert.AlertType.ERROR, "error","couldn't load");
        }
    }

}
