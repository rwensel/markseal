import QtQuick
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: control
    property string label: ""
    property bool checked: false
    signal toggled(bool next)

    implicitHeight: 28
    implicitWidth: row.implicitWidth
    opacity: enabled ? 1 : 0.45
    activeFocusOnTab: true
    Accessible.role: Accessible.CheckBox
    Accessible.name: control.label
    Accessible.checked: control.checked

    function toggle() {
        if (control.enabled)
            control.toggled(!control.checked)
    }

    Row {
        id: row
        anchors.verticalCenter: parent.verticalCenter
        spacing: 9

        Rectangle {
            width: 16
            height: 16
            radius: 3
            color: control.checked ? Theme.amber : "#101214"
            border.width: 1
            border.color: control.checked ? Theme.amber : Theme.steelMid
            Behavior on color { ColorAnimation { duration: 100 } }

            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 2
                color: "transparent"
                border.width: 1
                border.color: "#FFFFFF"
                opacity: control.checked ? 0.22 : 0
            }

            Rectangle {
                width: 3
                height: 7
                radius: 1
                x: 3
                y: 7
                rotation: -42
                color: Theme.ink
                visible: control.checked
            }

            Rectangle {
                width: 3
                height: 11
                radius: 1
                x: 6.5
                y: 3
                rotation: 34
                color: Theme.ink
                visible: control.checked
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: control.label
            color: Theme.white
            font.family: Backend.bodyFont
            font.pixelSize: 12
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: control.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            control.forceActiveFocus()
            control.toggle()
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: 5
        color: "transparent"
        border.width: 1
        border.color: Theme.amber
        opacity: 0.8
        visible: control.activeFocus
    }

    Keys.onSpacePressed: control.toggle()
    Keys.onReturnPressed: control.toggle()
}
