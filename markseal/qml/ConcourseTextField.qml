import QtQuick
import QtQuick.Controls
import Redactor 1.0

TextField {
    id: control
    implicitHeight: 34
    leftPadding: 10
    rightPadding: 10
    verticalAlignment: TextInput.AlignVCenter
    color: Theme.white
    placeholderTextColor: Theme.placeholder
    selectionColor: Theme.amber
    selectedTextColor: Theme.ink
    font.family: Theme.bodyFont
    font.pixelSize: 12
    selectByMouse: true

    background: Rectangle {
        radius: 6
        color: Theme.fieldFace
        border.width: 1
        border.color: control.activeFocus ? Theme.amber
                      : control.hovered ? Theme.steelMid : Theme.fieldBorder
        Behavior on border.color { ColorAnimation { duration: 110 } }
    }
}
