import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme
import Redactor 1.0

TextField {
    id: control
    implicitHeight: 34
    leftPadding: 10
    rightPadding: 10
    verticalAlignment: TextInput.AlignVCenter
    color: Theme.white
    placeholderTextColor: "#666C72"
    selectionColor: Theme.amber
    selectedTextColor: Theme.ink
    font.family: Backend.bodyFont
    font.pixelSize: 12
    selectByMouse: true

    background: Rectangle {
        radius: 6
        color: "#0F1114"
        border.width: 1
        border.color: control.activeFocus ? Theme.amber
                      : control.hovered ? Theme.steelMid : "#2A2D31"
        Behavior on border.color { ColorAnimation { duration: 110 } }
    }
}
