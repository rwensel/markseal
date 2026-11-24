import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import Redactor 1.0

Window {
    id: root
    width: 1360
    height: 860
    minimumWidth: 1080
    minimumHeight: 680
    visible: true
    color: Theme.bg
    title: Backend.review.imageName.length > 0
           ? Backend.review.imageName + " - MarkSeal"
           : "MarkSeal"

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.shellTop }
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
            onCaptureClicked: captureRegion.open()
        }

        UpdateBanner {
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            Layout.topMargin: 6
            Layout.bottomMargin: visible ? 8 : 0
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Sidebar {
                Layout.preferredWidth: 336
                Layout.fillHeight: true
                visible: Backend.folder.folderMode
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

    CaptureRegion {
        id: captureRegion
    }

    DropArea {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            visible: parent.containsDrag
            color: Theme.scrim

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
                    font.family: Theme.displayFont
                    font.pixelSize: 30
                    font.letterSpacing: 3
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "PNG / JPEG / BMP / TIFF / FOLDER"
                    color: Theme.steelLight
                    font.family: Theme.displayFont
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
        target: Backend.settings
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
        sequence: "Ctrl+Shift+C"
        onActivated: captureRegion.open()
    }

    Shortcut {
        sequence: "PageUp"
        onActivated: Backend.review.previousPdfPage()
    }

    Shortcut {
        sequence: "PageDown"
        onActivated: Backend.review.nextPdfPage()
    }

    Shortcut {
        sequence: "Ctrl+C"
        onActivated: Backend.review.copyRedacted()
    }

    Shortcut {
        sequence: "Ctrl+F"
        onActivated: Backend.review.find()
    }

    Shortcut {
        sequence: "Ctrl+="
        onActivated: Backend.review.zoomStep(1)
    }

    Shortcut {
        sequence: "Ctrl+Shift+="
        onActivated: Backend.review.zoomStep(1)
    }

    Shortcut {
        sequence: "Ctrl+-"
        onActivated: Backend.review.zoomStep(-1)
    }

    Shortcut {
        sequence: "Ctrl+0"
        onActivated: Backend.review.zoomFit()
    }

    Shortcut {
        sequence: "Ctrl+A"
        onActivated: Backend.review.selectAllBoxes()
    }

    Shortcut {
        sequence: "Ctrl+Shift+A"
        onActivated: Backend.review.selectNoBoxes()
    }

    Shortcut {
        sequence: "Ctrl+Z"
        onActivated: Backend.review.undo()
    }

    Shortcut {
        sequence: "Ctrl+Shift+Z"
        onActivated: Backend.review.redo()
    }

    Shortcut {
        sequence: "Ctrl+Y"
        onActivated: Backend.review.redo()
    }

    Shortcut {
        sequence: "Ctrl+Return"
        onActivated: Backend.review.confirmSelection()
    }

    Shortcut {
        sequence: "Ctrl+S"
        onActivated: Backend.review.save()
    }

    Shortcut {
        sequence: "Escape"
        context: Qt.ApplicationShortcut
        onActivated: {
            if (captureRegion.visible)
                captureRegion.visible = false
            else if (settingsWindow.visible)
                settingsWindow.closeSettings()
            else
                Backend.review.cancelCapture()
        }
    }
}
