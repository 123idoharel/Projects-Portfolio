package View;

import Model.MyModel;
import ViewModel.MyViewModel;
import javafx.application.Application;
import javafx.fxml.FXMLLoader;
import javafx.scene.Scene;
import javafx.scene.layout.BorderPane;
import javafx.stage.Stage;
import Server.*;

// must  extend Application
public class Main extends Application {

    // must implement start
    @Override
    public void start(Stage stage) throws Exception {
        // we launch our servers for solve and generate
        startServers();

        // load the fxml
        FXMLLoader fxmlLoader = new FXMLLoader(getClass().getResource("/View/MyView.fxml"));
        BorderPane root = fxmlLoader.load();
        // get an object of the defined controller
        MyViewController controller = fxmlLoader.getController();
        // create model and modelview objects
        MyModel model = new MyModel();
        MyViewModel viewModel = new MyViewModel();
        // connect the viewmodel layer to the model
        viewModel.set_model(model);
        // connect the viewmodel and the view layers
        controller.setViewModel(viewModel);

        Scene scene = new Scene(root);
        scene.getStylesheets().add(getClass().getResource("/Styles/style.css").toExternalForm());
        stage.setScene(scene);
        stage.setTitle("Maze Game");
        stage.setResizable(true);
        stage.show();
    }

    // start both servers and their own threads, so when called they will already be ready.
    private static void startServers() {
        new Thread(() -> {
            try {
                Server generateServer = new Server(5400, 1000, new ServerStrategyGenerateMaze());
                generateServer.start();
            } catch (Exception e) {
                e.printStackTrace();
            }
        }).start();

        new Thread(() -> {
            try {
                Server solveServer = new Server(5401, 1000, new ServerStrategySolveSearchProblem());
                solveServer.start();
            } catch (Exception e) {
                e.printStackTrace();
            }
        }).start();
    }

    public static void main(String[] args) {
        launch(args);
    }
}



