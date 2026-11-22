import QtQuick
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: control
    objectName: "methodToggle"
    property string method: "Pixelate"
    signal selected(string method)

    implicitWidth: 150
    implicitHeight: 26
    opacity: enabled ? 1 : 0.4

    Rectangle {
        anchors.fill: parent
        radius: 5
        color: "#0F1114"
        border.width: 1
        border.color: "#2A2D31"
    }

    Row {
        id: segments
        anchors.fill: parent
        anchors.margins: 2
        spacing: 2

        Rectangle {
            width: (segments.width - 2) / 2
            height: segments.height
            radius: 3
            color: control.method === "Pixelate" ? Theme.amber
                   : pixelHover.containsMouse ? "#1D2024" : "transparent"

            Text {
                anchors.centerIn: parent
                text: "PIXELATE"
                color: control.method === "Pixelate" ? Theme.ink : Theme.steelLight
                font.family: Backend.displayFont
                font.pixelSize: 8
                font.letterSpacing: 0.6
            }

            MouseArea {
                id: pixelHover
                anchors.fill: parent
                hoverEnabled: true
                enabled: control.enabled
                cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: control.selected("Pixelate")
            }
        }

        Rectangle {
            width: (segments.width - 2) / 2
            height: segments.height
            radius: 3
            color: control.method === "Solid black" ? Theme.amber
                   : solidHover.containsMouse ? "#1D2024" : "transparent"

            Text {
                anchors.centerIn: parent
                text: "SOLID"
                color: control.method === "Solid black" ? Theme.ink : Theme.steelLight
                font.family: Backend.displayFont
                font.pixelSize: 8
                font.letterSpacing: 0.6
            }

            MouseArea {
                id: solidHover
                anchors.fill: parent
                hoverEnabled: true
                enabled: control.enabled
                cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: control.selected("Solid black")
            }
        }
    }
}
