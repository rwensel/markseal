import QtQuick
import QtQuick.Controls
import Redactor 1.0

MenuItem {
    id: control
    implicitHeight: 36

    contentItem: Text {
        leftPadding: 12
        text: control.text
        font.family: Theme.bodyFont
        font.pixelSize: 12
        color: control.enabled ? Theme.white : Theme.mutedText
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: 5
        color: control.highlighted && control.enabled ? Theme.rowActive : "transparent"
    }
}
