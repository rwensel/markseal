import QtQuick
import Redactor 1.0

Item {
    id: control
    objectName: "methodToggle"
    property string method: "Pixelate"
    signal selected(string method)

    implicitWidth: 150
    implicitHeight: 26
    opacity: enabled ? 1 : 0.4
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: "Redaction method: " + control.method
    Accessible.description: "Press Space to switch between pixelate and solid black"

    function toggle() {
        if (control.enabled)
            control.selected(control.method === "Pixelate" ? "Solid black" : "Pixelate")
    }

    Rectangle {
        anchors.fill: parent
        radius: 5
        color: Theme.fieldFace
        border.width: 1
        border.color: Theme.buttonBorder
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
            scale: pixelHover.pressed ? 0.97 : 1
            color: pixelHover.pressed
                   ? (control.method === "Pixelate" ? Theme.amberPressed : Theme.buttonFacePressed)
                   : control.method === "Pixelate" ? Theme.amber
                   : pixelHover.containsMouse ? Theme.rowSelected : "transparent"
            Behavior on color { ColorAnimation { duration: 90 } }
            Behavior on scale { NumberAnimation { duration: 90 } }

            Text {
                anchors.centerIn: parent
                text: "PIXELATE"
                color: control.method === "Pixelate" ? Theme.ink : Theme.steelLight
                font.family: Theme.displayFont
                font.pixelSize: 9 * Theme.labelScale
                font.letterSpacing: Theme.labelTracking
            }

            MouseArea {
                id: pixelHover
                anchors.fill: parent
                hoverEnabled: true
                enabled: control.enabled
                cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: {
                    control.forceActiveFocus()
                    control.selected("Pixelate")
                }
            }
        }

        Rectangle {
            width: (segments.width - 2) / 2
            height: segments.height
            radius: 3
            scale: solidHover.pressed ? 0.97 : 1
            color: solidHover.pressed
                   ? (control.method === "Solid black" ? Theme.amberPressed : Theme.buttonFacePressed)
                   : control.method === "Solid black" ? Theme.amber
                   : solidHover.containsMouse ? Theme.rowSelected : "transparent"
            Behavior on color { ColorAnimation { duration: 90 } }
            Behavior on scale { NumberAnimation { duration: 90 } }

            Text {
                anchors.centerIn: parent
                text: "BLACK"
                color: control.method === "Solid black" ? Theme.ink : Theme.steelLight
                font.family: Theme.displayFont
                font.pixelSize: 9 * Theme.labelScale
                font.letterSpacing: Theme.labelTracking
            }

            MouseArea {
                id: solidHover
                anchors.fill: parent
                hoverEnabled: true
                enabled: control.enabled
                cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: {
                    control.forceActiveFocus()
                    control.selected("Solid black")
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: 6
        color: "transparent"
        border.width: 1
        border.color: Theme.amber
        opacity: 0.85
        visible: control.activeFocus
    }

    Keys.onSpacePressed: control.toggle()
    Keys.onLeftPressed: control.selected("Pixelate")
    Keys.onRightPressed: control.selected("Solid black")
    Keys.onReturnPressed: control.toggle()
}
