package ViewModel;

import algorithms.mazeGenerators.Maze;
import algorithms.mazeGenerators.Position;
import algorithms.search.AState;
import algorithms.search.MazeState;
import algorithms.search.SearchableMaze;

// a wrapper class for searchableMaze. used to determine given a start and goal positions and a maze if there's a path from the position to the goal.
// we create an object and solve it, when the solver asks for the start and end positions he gets the positions we entered and
// not the one that were chosen randomly. then we know if a solution exists between ur positions.
public class ExtraSearchableMaze extends SearchableMaze {

    private Maze maze;
    private Position start;
    private Position finish;

    public ExtraSearchableMaze(Maze maze, Position s1, Position s2){
        super(maze);
        this.start = s1;
        this.finish = s2;
    }

    // must implement ISearchable functions
    @Override
    public AState getStartState() {
        return new MazeState(start);
    }

    @Override
    public AState getGoalState() {
        return new MazeState(finish);
    }

}
