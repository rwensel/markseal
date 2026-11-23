import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import "Theme.js" as Theme
import Redactor 1.0

Window {
    id: root
    width: 1360
    height: 860
    minimumWidth: 1080
    minimumHeight: 680
    visible: true
    color: Theme.bg
    title: Backend.imageName.length > 0
           ? Backend.imageName + " - Offline Screenshot Redactor"
           : "Offline Screenshot Redactor"

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#101215" }
            GradientStop { position: 1.0; color: Theme.bg }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Toolbar {
            Layout.fillWidth: true
            Layout.preferredHeight: 70
            onSettingsClicked: settingsWindow.openSettings()
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Sidebar {
                Layout.preferredWidth: 336
                Layout.fillHeight: true
                visible: Backend.folderMode
            }

            Viewer {
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }

        StatusBoard {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
        }
    }

    SettingsWindow {
        id: settingsWindow
        parentWindow: root
    }

    DropArea {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            visible: parent.containsDrag
            color: "#D90B0B0D"

            Rectangle {
                anchors.fill: parent
                anchors.margins: 14
                radius: Theme.radiusShell
                color: "transparent"
                border.width: 2
                border.color: Theme.amber
            }

            Column {
                anchors.centerIn: parent
                spacing: 8

                Text {
                    text: "DROP TO OPEN"
                    color: Theme.white
                    font.family: Backend.displayFont
                    font.pixelSize: 30
                    font.letterSpacing: 3
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "PNG / JPEG / BMP / TIFF / FOLDER"
                    color: Theme.steelLight
                    font.family: Backend.displayFont
                    font.pixelSize: 9
                    font.letterSpacing: 1.2
                }
            }
        }

        onDropped: function(drop) {
            Backend.openDropped(drop.urls)
        }
    }

    Connections {
        target: Backend
        function onSettingsRequested() {
            settingsWindow.openSettings()
        }
    }

    Shortcut {
        sequence: "Ctrl+O"
        onActivated: Backend.openImage()
    }

    Shortcut {
        sequence: "Ctrl+Shift+O"
        onActivated: Backend.openFolder()
    }

    Shortcut {
        sequence: "Ctrl+V"
        onActivated: Backend.pasteImage()
    }

    Shortcut {
        sequence: "Ctrl+C"
        onActivated: Backend.copyRedacted()
    }

    Shortcut {
        sequence: "Ctrl+F"
        onActivated: Backend.find()
    }

    Shortcut {
        sequence: "Ctrl+="
        onActivated: Backend.zoomStep(1)
    }

    Shortcut {
        sequence: "Ctrl+Shift+="
        onActivated: Backend.zoomStep(1)
    }

    Shortcut {
        sequence: "Ctrl+-"
        onActivated: Backend.zoomStep(-1)
    }

    Shortcut {
        sequence: "Ctrl+0"
        onActivated: Backend.zoomFit()
    }

    Shortcut {
        sequence: "Ctrl+A"
        onActivated: Backend.selectAllBoxes()
    }

    Shortcut {
        sequence: "Ctrl+Shift+A"
        onActivated: Backend.selectNoBoxes()
    }

    Shortcut {
        sequence: "Ctrl+Z"
        onActivated: Backend.undo()
    }

    Shortcut {
        sequence: "Ctrl+Return"
        onActivated: Backend.confirmSelection()
    }

    Shortcut {
        sequence: "Ctrl+S"
        onActivated: Backend.save()
    }

    Shortcut {
        sequence: "Escape"
        onActivated: Backend.cancelCapture()
    }
}
