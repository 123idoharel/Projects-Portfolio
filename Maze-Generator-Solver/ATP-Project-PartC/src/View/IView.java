package View;

import javafx.scene.control.Alert;

public interface IView {
    public void show_alert(Alert.AlertType type, String title, String message);
}
