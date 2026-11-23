import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme
import Redactor 1.0

SpinBox {
    id: control
    implicitHeight: 34
    implicitWidth: 130
    editable: true

    contentItem: TextInput {
        text: control.textFromValue(control.value, control.locale)
        font.family: Backend.bodyFont
        font.pixelSize: 12
        color: Theme.white
        selectionColor: Theme.amber
        selectedTextColor: Theme.ink
        horizontalAlignment: Qt.AlignLeft
        leftPadding: 10
        rightPadding: 28
        verticalAlignment: TextInput.AlignVCenter
        readOnly: !control.editable
        validator: control.validator
        inputMethodHints: Qt.ImhDigitsOnly
    }

    up.indicator: Rectangle {
        x: control.width - 26
        y: 1
        width: 25
        height: (control.height - 3) / 2
        radius: 3
        color: up.pressed ? "#2A2E33" : "transparent"

        Text {
            anchors.centerIn: parent
            text: "+"
            color: up.pressed ? Theme.amber : Theme.steelLight
            font.family: Backend.displayFont
            font.pixelSize: 12
        }
    }

    down.indicator: Rectangle {
        x: control.width - 26
        y: (control.height + 1) / 2
        width: 25
        height: (control.height - 3) / 2
        radius: 3
        color: down.pressed ? "#2A2E33" : "transparent"

        Text {
            anchors.centerIn: parent
            text: "-"
            color: down.pressed ? Theme.amber : Theme.steelLight
            font.family: Backend.displayFont
            font.pixelSize: 12
        }
    }

    background: Rectangle {
        radius: 6
        color: "#0F1114"
        border.width: 1
        border.color: control.activeFocus ? Theme.amber : "#2A2D31"
    }
}
