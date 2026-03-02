package View;

import algorithms.mazeGenerators.Maze;
import algorithms.mazeGenerators.Position;
import algorithms.search.*;
import javafx.application.Platform;
import javafx.scene.canvas.GraphicsContext;
import javafx.scene.effect.ColorAdjust;
import javafx.scene.canvas.Canvas;
import javafx.scene.paint.Color;
import javafx.scene.image.Image;
import java.util.ArrayList;

// the self designed control to represent the maze
public class MazeRepresentor extends Canvas {

    // holds all the needed info to draw the maze
    private Maze maze;
    private Position player_pos;
    private Image player_img;
    private Image background_img;
    private Image goal_img;
    private Solution solution;
    private boolean show_solution;

    // constructor
    public MazeRepresentor(){

        // allows to handly five the control focus
        this.setFocusTraversable(true);

        // defines listeners in order to draw after size adjustment
        widthProperty().addListener((obs, oldVal, newVal) -> {
            if(newVal.doubleValue() > 0) draw();
        });
        heightProperty().addListener((obs, oldVal, newVal) -> {
            if(newVal.doubleValue() > 0) draw();
        });

    }

    // called after that updating the maze, so updates all the fields and draws.
    public void set_maze_and_player(Maze new_maze){
        this.maze = new_maze;
        this.show_solution = false;
        Position p = maze.getStartPosition();
        this.player_pos = p;
        this.solution = null;
        // approach the GUI thread to draw
        Platform.runLater(() -> {
            draw();
        });

        // get focus back
        Platform.runLater(this::requestFocus);

    }

    // simple methods: updates and re-draw after each update.

    public void set_player_pos(Position new_pos){
        this.player_pos = new_pos;
        draw();
    }

    public void set_player_img(Image new_img){
        this.player_img = new_img;
        draw();
    }

    public void set_goal_img(Image new_img){
        this.goal_img = new_img;
        draw();
    }

    public void set_background_img(Image new_img){
        this.background_img = new_img;
        draw();
    }

    public void set_solution(Solution sol){
        this.solution = sol;
        this.show_solution = true;
        draw();
    }


    // the draw function:
    // first we draw the background image, then for each i,j in the maze we draw a black rectangle if wall.
    // finally we draw the start and goal positions.
    // if we asked to represent the solution we draw it as white dots.
    public void draw() {
        if (maze == null || player_pos == null){
            return;
        }

            GraphicsContext graphic = getGraphicsContext2D();
            graphic.clearRect(0, 0, getWidth(), getHeight());
            if(background_img!=null){
                ColorAdjust brightener = new ColorAdjust();
                brightener.setBrightness(0.2);
                graphic.setEffect(brightener);
                graphic.drawImage(background_img, 0,0,getWidth(),getHeight());
                graphic.setEffect(null);
            }
            for (int i = 0; i < this.maze.getMaze().length; i++) {
                for (int j = 0; j < this.maze.getMaze()[0].length; j++) {
                    if (maze.getMaze()[i][j] == 1) {
                        graphic.setFill(Color.BLACK);
                        graphic.fillRect(j * (getWidth() / maze.getMaze()[0].length), i * (getHeight() / maze.getMaze().length), getWidth() / maze.getMaze().length, getHeight() / maze.getMaze()[0].length);
                    }
                }
            }

            if(show_solution){
                ArrayList<AState> sol = solution.getSolutionPath();
                for(int i=0; i<sol.size();i++){
                    AState s = sol.get(i);
                    Position p = ((MazeState) s).getPosition();
                    graphic.setFill(Color.WHITE);
                    graphic.fillOval(p.getColumnIndex()*(getWidth()/maze.getMaze()[0].length) + 0.15*(getWidth()/maze.getMaze()[0].length),p.getRowIndex()*(getHeight()/maze.getMaze().length) + 0.15*(getHeight()/maze.getMaze().length),(getWidth()/maze.getMaze()[0].length)*0.4,(getHeight()/maze.getMaze().length)*0.4);

                }
            }
        if (player_img != null) {
            graphic.drawImage(player_img, player_pos.getColumnIndex() * (getWidth() / maze.getMaze()[0].length), player_pos.getRowIndex() * (getHeight() / maze.getMaze().length), (getWidth() / maze.getMaze()[0].length), (getHeight() / maze.getMaze().length));
        }
        if (goal_img != null) {
            graphic.drawImage(goal_img, maze.getGoalPosition().getColumnIndex() * (getWidth() / maze.getMaze()[0].length), maze.getGoalPosition().getRowIndex() * (getHeight() / maze.getMaze().length), (getWidth() / maze.getMaze()[0].length), (getHeight() / maze.getMaze().length));
        }



    }



}
