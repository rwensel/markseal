import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: toolbar
    implicitHeight: 70
    signal settingsClicked()

    Rectangle {
        id: bar
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#1C1F23" }
            GradientStop { position: 1.0; color: "#121417" }
        }
    }

    MultiEffect {
        anchors.fill: bar
        source: bar
        shadowEnabled: true
        shadowColor: "#000000"
        shadowOpacity: 0.5
        shadowBlur: 0.7
        shadowVerticalOffset: 7
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: "#000000"
        opacity: 0.8
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 1
        height: 1
        color: "#464B51"
        opacity: 0.55
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 7

        RowLayout {
            spacing: 10
            Layout.preferredWidth: 232

            Rectangle {
                width: 46
                height: 46
                radius: 8
                color: Theme.panelRaised
                border.width: 1
                border.color: "#3B4046"

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 8
                    radius: 4
                    color: Theme.amber

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        height: 1
                        color: "#000000"
                        opacity: 0.5
                    }
                }
            }

            Column {
                spacing: 0

                Text {
                    text: "OFFLINE REDACTOR"
                    color: Theme.white
                    font.family: Backend.displayFont
                    font.pixelSize: 15
                    font.letterSpacing: 1.5
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "SCREENSHOT / LOCAL ONLY"
                    color: Theme.steelLight
                    font.family: Backend.displayFont
                    font.pixelSize: 9
                    font.letterSpacing: 1.2
                }
            }
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 30
            color: "#34393F"
        }

        ConcourseButton {
            text: "OPEN IMAGE"
            compact: true
            enabled: !Backend.busy
            onClicked: Backend.openImage()
        }

        ConcourseButton {
            text: "OPEN FOLDER"
            compact: true
            enabled: !Backend.busy
            onClicked: Backend.openFolder()
        }

        ConcourseButton {
            text: "SCAN"
            compact: true
            enabled: Backend.hasImage && !Backend.busy
            onClicked: Backend.find()
        }

        ConcourseButton {
            text: "SCAN AREA"
            compact: true
            enabled: Backend.hasImage && !Backend.busy
            onClicked: Backend.beginScanArea()
        }

        ConcourseButton {
            text: "UNDO"
            compact: true
            enabled: Backend.hasImage && Backend.totalBoxes > 0
            onClicked: Backend.undo()
        }

        ConcourseButton {
            text: "EDIT"
            compact: true
            enabled: Backend.hasImage && Backend.confirmed
            onClicked: Backend.editBoxes()
        }

        ConcourseButton {
            text: "CLEAR"
            compact: true
            enabled: Backend.hasImage && Backend.totalBoxes > 0
            onClicked: Backend.clearBoxes()
        }

        Item { Layout.fillWidth: true }

        ConcourseButton {
            text: "CONFIRM"
            compact: true
            enabled: Backend.hasImage && !Backend.busy
            onClicked: Backend.confirmSelection()
        }

        ConcourseButton {
            text: "SAVE"
            variant: "primary"
            compact: true
            enabled: Backend.hasImage && !Backend.busy
            onClicked: Backend.save()
        }

        ConcourseButton {
            text: "SETTINGS"
            variant: "ghost"
            compact: true
            onClicked: Backend.requestSettings()
        }
    }
}
