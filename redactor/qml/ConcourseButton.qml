import QtQuick
import QtQuick.Effects
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: control
    property string text: ""
    property string variant: "secondary"
    property bool compact: false
    signal clicked()

    implicitWidth: label.implicitWidth + (compact ? 22 : 30)
    implicitHeight: compact ? 32 : 36
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.38
    scale: pointer.pressed ? 0.985 : 1
    Behavior on scale { NumberAnimation { duration: 80 } }

    readonly property bool primary: variant === "primary"
    readonly property bool danger: variant === "danger"
    readonly property bool ghost: variant === "ghost"
    readonly property bool hovered: pointer.containsMouse && enabled

    Rectangle {
        id: background
        anchors.fill: parent
        radius: Theme.radiusButton
        color: control.primary
               ? (control.hovered ? "#FFC24D" : Theme.amber)
               : control.danger
                 ? (control.hovered ? "#2A1114" : "#171214")
                 : control.ghost
                   ? (control.hovered ? "#22262A" : "transparent")
                   : (control.hovered ? "#2A2E33" : Theme.panelRaised)
        border.width: control.ghost ? 0 : 1
        border.color: control.danger
                      ? Theme.red
                      : control.primary ? "#FFD37A" : "#3B4046"
        Behavior on color { ColorAnimation { duration: 110 } }
    }

    MultiEffect {
        anchors.fill: background
        source: background
        shadowEnabled: true
        shadowColor: control.primary ? Theme.amber : "#000000"
        shadowOpacity: control.primary ? (control.hovered ? 0.55 : 0.34) : 0.42
        shadowBlur: control.primary ? 0.95 : 0.55
        shadowVerticalOffset: control.primary ? 3 : 2
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 1
        height: 1
        radius: 1
        color: "#FFFFFF"
        opacity: control.primary ? 0.38 : 0.12
        visible: !control.ghost
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: Theme.radiusButton + 2
        color: "transparent"
        border.color: Theme.amber
        border.width: 1
        opacity: 0.85
        visible: control.activeFocus
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: control.text
        color: control.primary ? Theme.ink : Theme.white
        font.family: Backend.displayFont
        font.pixelSize: control.compact ? 10 : 11
        font.letterSpacing: 1.1
        font.weight: Font.DemiBold
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        enabled: control.enabled
        cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: control.clicked()
    }

    Keys.onReturnPressed: if (control.enabled) control.clicked()
    Keys.onSpacePressed: if (control.enabled) control.clicked()
}
