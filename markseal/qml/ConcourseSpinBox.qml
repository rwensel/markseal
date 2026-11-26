import QtQuick
import QtQuick.Controls
import Redactor 1.0

SpinBox {
    id: control
    implicitHeight: 34
    implicitWidth: 130
    editable: true

    contentItem: TextInput {
        text: control.textFromValue(control.value, control.locale)
        font.family: Theme.bodyFont
        font.pixelSize: Theme.scaleFont(12)
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
        color: up.pressed ? Theme.buttonFaceHover : "transparent"

        Text {
            anchors.centerIn: parent
            text: "+"
            color: up.pressed ? Theme.amber : Theme.steelLight
            font.family: Theme.displayFont
            font.pixelSize: Theme.scaleFont(12)
        }
    }

    down.indicator: Rectangle {
        x: control.width - 26
        y: (control.height + 1) / 2
        width: 25
        height: (control.height - 3) / 2
        radius: 3
        color: down.pressed ? Theme.buttonFaceHover : "transparent"

        Text {
            anchors.centerIn: parent
            text: "-"
            color: down.pressed ? Theme.amber : Theme.steelLight
            font.family: Theme.displayFont
            font.pixelSize: Theme.scaleFont(12)
        }
    }

    background: Rectangle {
        radius: 6
        color: Theme.fieldFace
        border.width: 1
        border.color: control.activeFocus ? Theme.amber : Theme.fieldBorder
    }
}
