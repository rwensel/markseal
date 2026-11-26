import QtQuick
import Redactor 1.0

Item {
    id: control
    objectName: "methodToggle"
    property string method: "Pixelate"
    readonly property var methods: ["Pixelate", "Solid black", "Blur", "Erase"]
    readonly property var labels: ["PIXELATE", "BLACK", "BLUR", "ERASE"]
    signal selected(string method)

    implicitWidth: 236
    implicitHeight: 26
    opacity: enabled ? 1 : 0.4
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: "Redaction method: " + control.method
    Accessible.description: "Press Space to cycle redaction methods"

    function cycle(step) {
        if (!control.enabled)
            return
        var current = Math.max(0, control.methods.indexOf(control.method))
        var next = (current + step + control.methods.length) % control.methods.length
        control.selected(control.methods[next])
    }

    Rectangle {
        anchors.fill: parent
        radius: 5
        color: Theme.fieldFace
        border.width: 1
        border.color: Theme.buttonBorder
    }

    Rectangle {
        z: 3
        anchors.fill: parent
        radius: 5
        color: "transparent"
        border.width: 2
        border.color: Theme.focusRing
        visible: control.activeFocus
    }

    MouseArea {
        id: touchMargin
        anchors.fill: parent
        anchors.topMargin: -9
        anchors.bottomMargin: -9
        enabled: control.enabled
        onClicked: {
            control.forceActiveFocus()
            control.cycle(1)
        }
    }

    Row {
        id: segments
        anchors.fill: parent
        anchors.margins: 2
        spacing: 2

        Repeater {
            model: control.methods.length

            Rectangle {
                required property int index
                width: (segments.width - (control.methods.length - 1) * segments.spacing)
                       / control.methods.length
                height: segments.height
                radius: 3
                color: control.method === control.methods[index]
                       ? (hover.pressed ? Theme.amberPressed : Theme.amber)
                       : hover.containsMouse ? Theme.rowSelected : "transparent"
                Behavior on color {
                    enabled: !Theme.reduceMotion
                    ColorAnimation { duration: 90 }
                }

                Text {
                    anchors.centerIn: parent
                    text: control.labels[index]
                    color: control.method === control.methods[index] ? Theme.ink : Theme.steelLight
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.scaleFont(9 * Theme.labelScale)
                    font.letterSpacing: Theme.labelTracking
                }

                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: control.enabled
                    cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: {
                        control.forceActiveFocus()
                        control.selected(control.methods[index])
                    }
                }
            }
        }
    }

    Keys.onSpacePressed: control.cycle(1)
    Keys.onRightPressed: control.cycle(1)
    Keys.onLeftPressed: control.cycle(-1)
}
