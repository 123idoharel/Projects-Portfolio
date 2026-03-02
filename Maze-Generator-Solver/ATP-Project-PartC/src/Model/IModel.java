package Model;

import algorithms.mazeGenerators.Maze;
import algorithms.mazeGenerators.Position;
import algorithms.search.Solution;

import java.io.File;
import java.io.IOException;
import java.util.function.Consumer;

// interface will be implemented by the model. contains all the function the model must support.
public interface IModel {
    public void generateMaze(int rows, int cols);
    public void solveMaze();

    public Maze get_maze();

    public Solution get_solution();

    public Position get_player_position();

    public boolean can_move_to(Position newPosition);

    public void move_player_to(Position newPosition);

    public boolean reached_goal();

    public void set_maze(Maze maze);

    public void save(File file) throws IOException;

    public void load(File file) throws IOException;

    public void setOnMazeGenerated(Consumer<Maze> consumer);

}
