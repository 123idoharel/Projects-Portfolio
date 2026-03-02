package View;

import Server.Configurations;
import ViewModel.MyViewModel;
import algorithms.mazeGenerators.Maze;
import algorithms.mazeGenerators.MyMazeGenerator;
import javafx.application.Platform;
import javafx.beans.binding.Bindings;
import javafx.scene.control.Alert;
import javafx.scene.control.Label;
import javafx.scene.image.Image;
import javafx.scene.image.ImageView;
import javafx.scene.input.KeyEvent;
import javafx.scene.input.MouseEvent;
import javafx.scene.input.ScrollEvent;
import javafx.animation.PauseTransition;


import javafx.scene.media.Media;
import javafx.scene.media.MediaPlayer;
import javafx.util.Duration;

import javafx.fxml.FXML;
import javafx.scene.control.TextField;
import javafx.scene.layout.StackPane;
import javafx.stage.FileChooser;
import javafx.stage.Stage;

import java.io.File;

public class MyViewController implements IView{
    // holds fields for the GUI controls
    @FXML
    public MazeRepresentor mr;
    @FXML
    private TextField rowsText;
    @FXML
    private TextField colsText;
    @FXML
    private StackPane mazeStackPane;
    @FXML
    private Label goalStatusLabel;
    @FXML
    private ImageView start_image;

    // also needed fields - includes approach the viewModel layer.
    public MyViewModel viewModel;

    private MediaPlayer backgroundMusic;

    private MediaPlayer goalPlayer;

    private boolean dragging = false;


    // this function used to connect the layer with the viewModel layer,
    // and also to set the listeners for the key events in the system.
    // we defined properties for those events in viewModel layer and here we set the listeners.
    public void setViewModel(MyViewModel viewModel) {
        this.viewModel = viewModel;
        viewModel.set_view(this);

        // creates a default maze just for the system start - don't even show it to user.
        // helps us in terms of prevent nulls in start.
        Maze defaultic = new MyMazeGenerator().generate(10,10);
        viewModel.maze_property.set(defaultic);
        viewModel.player_position_property.set(defaultic.getStartPosition());


        // listeners define

        // listener to maze_property: listens to a change in the system's maze.
        // we defined that when the maze changes we update the property, so the listener gets that.

        viewModel.maze_property.addListener((obs, oldVal, newVal) -> {
            if (newVal != null) {
                // approach the MazeRepresentor to draw the new maze (and update inner fields)
                mr.set_maze_and_player(newVal);
            }
            // starts a new play of background music for the new maze
            if (backgroundMusic != null) {
                backgroundMusic.stop();
                backgroundMusic.seek(Duration.ZERO);
                backgroundMusic.play();
            }
            // we return the focus to the MazeRepresentor so key press will be noted.
            mr.requestFocus();
        });

        // when there was only a player movement noted we ask the MazeRepresentor to re-draw with updated position.
        viewModel.player_position_property.addListener((obs, oldVal, newVal) -> {
            if (newVal != null) {
                mr.set_player_pos(newVal);
            }
        });

        //when user requested to see the solution, we update and ask the MR to update his field and re-draw with solution.
        viewModel.solution_property.addListener((obs, oldVal, newVal) -> {
            if (newVal != null) {
                mr.set_solution(newVal);
            }
        });

        // when the user reached the goal position -we:
        // 1. pause the background music and play the goal music. 2. tells him he solved. 3. generate a new 100X100 maze, and notify the user.
        viewModel.reached_goal_property.addListener((obs, oldVal, newVal) -> {
            // if reached
            if(newVal){
                // stop music
                if (backgroundMusic != null) {
                    backgroundMusic.stop();
                }
                // play goal music
                String goalSoundPath = getClass().getResource("/sounds/goal_sound2.mp3").toExternalForm();
                Media goalReachedSound = new Media(goalSoundPath);
                MediaPlayer tempPlayer = new MediaPlayer(goalReachedSound);
                tempPlayer.setVolume(1.0);
                tempPlayer.play();
                // represent a success
                goalStatusLabel.setText("Maze Completed! Hala madrid!");
                goalStatusLabel.setVisible(true);
                // remove the success representation and the music after 4 seconds - generates new maze.
                PauseTransition delay = new PauseTransition(Duration.seconds(4));
                delay.setOnFinished(event -> {
                    goalStatusLabel.setVisible(false);
                    tempPlayer.stop();
                    tempPlayer.dispose();
                });
                delay.play();

                // the alert:
                show_alert(Alert.AlertType.INFORMATION, "success", "reached goal. updates default 100X100 new maze");
                viewModel.generateMaze(100, 100);
                viewModel.reached_goal_property.set(false);
                Platform.runLater(() -> {
                    // return the focus to the MazeRepresentor
                    mr.requestFocus();
                });
            }


        });
    }


    @FXML
    public void initialize() {
        // automatically runs at start. sets a basic size for the MazeRepresentor.
        mr.setWidth(600);
        mr.setHeight(600);

        // set binding to resize the MR according to panel size change
        mr.widthProperty().bind(Bindings.max(400, mazeStackPane.widthProperty()));
        mr.heightProperty().bind(Bindings.max(400, mazeStackPane.heightProperty()));

        // load the images and set them in the MazeRepresentor, so the draw function will know them + start background image.

        Image player_img = new Image(getClass().getResource("/images/player2.png").toExternalForm());
        mr.set_player_img(player_img);
        Image back_img = new Image(getClass().getResource("/images/background.png").toExternalForm());
        mr.set_background_img(back_img);
        Image goal_img = new Image(getClass().getResource("/images/goal2.png").toExternalForm());
        mr.set_goal_img(goal_img);
        Image first_image = new Image(getClass().getResource("/images/background.png").toExternalForm());
        start_image.setImage(first_image);

        // set a welcome sentence
        goalStatusLabel.setText("Welcome to the Real Madrid Maze!");
        goalStatusLabel.setVisible(true);

        // play the background music infinite
        String musicPath = getClass().getResource("/sounds/reg_sound.mp3").toExternalForm();
        Media media = new Media(musicPath);
        backgroundMusic = new MediaPlayer(media);
        backgroundMusic.setCycleCount(MediaPlayer.INDEFINITE);
        backgroundMusic.play();

        // sets the goal media - still don't start playing.
        String goalSoundPath = getClass().getResource("/sounds/goal_sound.mp3").toExternalForm();
        Media goalReachedSound = new Media(goalSoundPath);
        goalPlayer = new MediaPlayer(goalReachedSound);
        goalPlayer.setVolume(1.0);

    }

    // when user presses 'generate' button
    public void clicked_generate_maze(){
        try {
            // hide welcome sentence and picture
            goalStatusLabel.setVisible(false);
            start_image.setVisible(false);

            // take the requested sizes
            int rows = Integer.parseInt(rowsText.getText());
            int cols = Integer.parseInt(colsText.getText());
            // send to the viewModel to handle the generate (calls the model, updates properties, etc..).
            viewModel.generateMaze(rows, cols);
        } catch (Exception e) {
            show_alert(Alert.AlertType.ERROR, "error","please enter int size and generate");
        }
        // return focus to MazeRepresentor
        Platform.runLater(() -> mr.requestFocus());
    }

    // for press on solve button
    public void clicked_solve(){
        // send to the viewModel to handle, and return focus to MR
        viewModel.show_solution();
        Platform.runLater(() -> mr.requestFocus());
    }

    // clicked key press - move to viewModel to handle
    public void handle_key_press(KeyEvent keyEvent) {
        if (viewModel != null){
            viewModel.move_player(keyEvent.getCode());
        }
    }

    // dragged the mouse - we check it by release that came after dragging and not only press.
    // check with the boolean who tells.
    public void handle_mouse_release(MouseEvent mouseEvent) {
        if(dragging){
            viewModel.move_player_to(mouseEvent, mr.getWidth(), mr.getHeight());
        }
        dragging = false;
    }

    // if only pressed - mark dragging as false.
    public void handle_mouse_pressed(MouseEvent mouseEvent) {
        dragging = false;
    }

    // scroll - it's only a matter of view so we handle it here - update the scales with logical limit
    public void handle_scroll(ScrollEvent scrollEvent) {
        if (scrollEvent.isControlDown()) {
            if (scrollEvent.getDeltaY() > 0) {
                if ((mr.getScaleX() <= 3.0 && mr.getScaleY() <= 3.0)) {
                    mr.setScaleY(mr.getScaleY() * 1.1);
                    mr.setScaleX(mr.getScaleX() * 1.1);
                }
            } else {
                if (mr.getScaleX() >= 0.3 && mr.getScaleY() >= 0.3) {
                    mr.setScaleY(mr.getScaleY() * 0.9);
                    mr.setScaleX(mr.getScaleX() * 0.9);
                }
            }
        }
    }

    // dragged - marked dragging true
    public void handle_mouse_dragged(MouseEvent mouseEvent) {
        dragging = true;
    }

    // clicked 'new' - means generate new maze but didn't give sizes. default - 100X100.
    public void clicked_new_at_menu(){
        goalStatusLabel.setVisible(false);
        start_image.setVisible(false);
        viewModel.generateMaze(100,100);
        Platform.runLater(() -> mr.requestFocus());
    }

    // save and load - opens the option to choose how to save or which maze to load as described in tirgul.

    public void clicked_save_at_menu(){
        FileChooser fc = new FileChooser();
        fc.setTitle("save");
        fc.getExtensionFilters().add(new FileChooser.ExtensionFilter("only maze files",".maze"));
        File chosen_file = fc.showSaveDialog(new Stage());
        if(chosen_file!=null){
            viewModel.save(chosen_file);
        }
        else{
            show_alert(Alert.AlertType.ERROR, "error", "invalid file chosen");
        }
        // return focus
        Platform.runLater(() -> mr.requestFocus());
    }
    public void clicked_load_at_menu(){
        FileChooser fc = new FileChooser();
        fc.setTitle("load");
        fc.getExtensionFilters().add(new FileChooser.ExtensionFilter("only maze files",".maze"));
        File chosen_file = fc.showOpenDialog(new Stage());
        if(chosen_file!=null){
            viewModel.load(chosen_file);
        }
        else{
            show_alert(Alert.AlertType.ERROR, "error", "invalid file chosen");
        }
        // return focus
        Platform.runLater(() -> mr.requestFocus());
    }

    // simple methods:

    public void clicked_help_on_menu(){
        show_alert(Alert.AlertType.INFORMATION, "help","actions: press numPad/drag mouse for movement.\nscroll for Zoom.\nblue dots mark solution path");
        Platform.runLater(() -> mr.requestFocus());
    }

    public void clicked_exit_on_menu(){
        System.exit(0);
    }

    public void clicked_about_on_menu(){
        show_alert(Alert.AlertType.INFORMATION, "about","This game developed by Ido Harel and Sagi Horowitz.\nIt uses DepthFirstSearch algorithm to generate mazes. \nIt enables several algorithms to solve the maze, as:\n BreadthFirstSearch\n BestFirstSearch\nDepthFirstSearch.\n default: BreadthFirstSearch. ");
        Platform.runLater(() -> mr.requestFocus());
    }

    public void clicked_properties_on_menu(){
       String s = "";
       s = s + "Current configuration: \nThreadsNum: " + Configurations.instance().getThreadsNum() + "\nSearchingAlgorithm: " + Configurations.instance().getAlgorithm() + "\nGenerating type: " + Configurations.instance().getMazeGenerateType();
        show_alert(Alert.AlertType.INFORMATION, "Properties",s );
        Platform.runLater(() -> mr.requestFocus());
    }

    // inner help function to manage alert
    @Override
    public void show_alert(Alert.AlertType type, String title, String message) {
        Alert alert = new Alert(type);
        alert.setTitle(title);
        alert.setContentText(message);
        alert.showAndWait();
    }


}

