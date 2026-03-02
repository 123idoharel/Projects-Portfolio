package Model;

import Client.*;
import IO.MyDecompressorInputStream;
import algorithms.mazeGenerators.Maze;
import algorithms.mazeGenerators.MyMazeGenerator;
import algorithms.mazeGenerators.Position;
import algorithms.search.AState;
import algorithms.search.Solution;
import javafx.application.Platform;
import javafx.scene.control.Alert;

import java.io.*;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.ArrayList;

// the model layer - manages all the logic.
public class MyModel implements IModel {

    // keeps the current maze, player current position, solution(generates only if requested),
    // and boolean value to know if the user solved thr maze.
    private Maze maze;
    private Position player_position;
    private Solution solution;
    private boolean reached_goal;

    // this saves a function that will run when the maze is generated.
    // note: its not a function to generate maze, but a function that will run every time we generate a maze,
    // after we generate.
    private java.util.function.Consumer<Maze> onMazeGenerated;
// we set it when we connect the layer to ViewModel layer.
    public void setOnMazeGenerated(java.util.function.Consumer<Maze> consumer) {
        this.onMazeGenerated = consumer;
    }

    // when we need to generate a maze - the model generates by sending the size to the server.
    @Override
    public void generateMaze(int rows, int cols) {
            try {
                MyModel self = this;
                Client client = new Client(InetAddress.getLocalHost(), 5400, new IClientStrategy() {
                    @Override
                    public void clientStrategy(InputStream inFromServer, OutputStream outToServer) {
                        try {
                            ObjectOutputStream toServer = new ObjectOutputStream(outToServer);
                            ObjectInputStream fromServer = new ObjectInputStream(inFromServer);
                            toServer.flush();
                            int[] mazeDimensions = new int[]{rows, cols};
                            toServer.writeObject(mazeDimensions); //send maze dimensions to server
                            toServer.flush();
                            byte[] compressedMaze = (byte[]) fromServer.readObject(); //read generated maze (compressed with MyCompressor) from server
                            InputStream is = new MyDecompressorInputStream(new ByteArrayInputStream(compressedMaze));
                            byte[] decompressedMaze = new byte[rows * cols  + 100]; //allocating byte[] for the decompressed maze -
                            is.read(decompressedMaze); //Fill decompressedMaze with bytes
                            Maze maze1 = new Maze(decompressedMaze);

                            // after we generated the maze - we update the fields.
                            self.maze = maze1;
                            self.player_position = maze1.getStartPosition();
                            self.solution = null;

                            // we use Platform.runLater because of the onMazeGenerated function -
                            // which affects the graphics. therefore we need to wait the UI thread.
                            Platform.runLater(() -> {

                                // the function as defined changes properties and therefore graphics
                                if (onMazeGenerated != null)
                                    onMazeGenerated.accept(maze1);
                            });
                        } catch (Exception e) {
                            e.printStackTrace();
                        }
                    }
                });
                client.communicateWithServer();
            } catch (UnknownHostException e) {
                e.printStackTrace();
            }
        }

    // when we need to solve a maze - the model generates by sending request to the server.
    @Override
    public void solveMaze() {
        try {
            MyModel self = this;
            Client client = new Client(InetAddress.getLocalHost(), 5401, new IClientStrategy() {
                @Override
                public void clientStrategy(InputStream inFromServer, OutputStream outToServer) {
                    try {
                        ObjectOutputStream toServer = new ObjectOutputStream(outToServer);
                        ObjectInputStream fromServer = new ObjectInputStream(inFromServer);
                        toServer.flush();
                        //send maze to server
                        toServer.writeObject(self.maze);
                        toServer.flush();
                        // get solution
                        Solution mazeSolution = (Solution) fromServer.readObject(); //read generated maze (compressed with MyCompressor) from server
                        self.solution = mazeSolution;
                    } catch (Exception e) {
                        e.printStackTrace();
                    }
                }
            });
            client.communicateWithServer();
        } catch (UnknownHostException e) {
            e.printStackTrace();
        }
    }

    // simple methods:

    @Override
    public Maze get_maze() {
        return this.maze;
    }

    public void set_maze(Maze maze){
        this.maze = maze;
        this.player_position = maze.getStartPosition();
        this.reached_goal = reached_goal();
        this.solution = null;
    }


    @Override
    public Solution get_solution() {
        return this.solution;
    }

    @Override
    public Position get_player_position() {
        return this.player_position;
    }

    // checks if player can move to the requested position in terms of availability and movement rules.
    @Override
    public boolean can_move_to(Position newPosition) {
        if(newPosition.getRowIndex()>=0 && newPosition.getRowIndex() < this.maze.getMaze().length && newPosition.getColumnIndex() >= 0 && newPosition.getColumnIndex()<this.maze.getMaze()[0].length &&  (maze.getMaze()[newPosition.getRowIndex()][newPosition.getColumnIndex()] == 0)){
            return true;
        }
        else{
            return false;
        }
    }

    // moves the player (called after checks)
    @Override
    public void move_player_to(Position newPosition) {
        if (this.maze == null)
            return;
        this.player_position = newPosition;
    }

    @Override
    public boolean reached_goal() {
        return this.player_position.equals(this.maze.getGoalPosition());
    }


    //save and load uses the maze coding as bytes array.
    public void save(File file) throws IOException{
        byte[] as_bytes = this.maze.toByteArray();
        try(FileOutputStream out = new FileOutputStream(file)){
            out.write(as_bytes);
        }
    }

    public void load(File file) throws IOException {
        try (FileInputStream in = new FileInputStream(file)) {
            byte[] as_bytes = in.readAllBytes();
            Maze res = new Maze(as_bytes);
            this.set_maze(res);
        }
    }



}
