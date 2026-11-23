import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: control
    property string text: ""
    property string variant: "secondary"
    property string tip: ""
    property bool compact: false
    property real pressPulse: 0
    signal clicked()

    implicitWidth: label.implicitWidth + (compact ? 22 : 30)
    implicitHeight: compact ? 32 : 36
    activeFocusOnTab: true
    scale: isPressed ? 0.965 : 1
    Accessible.role: Accessible.Button
    Accessible.name: control.text
    Accessible.description: control.tip
    ToolTip.visible: control.hovered && control.tip.length > 0
    ToolTip.delay: 600
    ToolTip.timeout: 5000
    ToolTip.text: control.tip
    Behavior on scale {
        NumberAnimation {
            duration: control.isPressed ? 80 : 160
            easing.type: Easing.OutCubic
        }
    }

    readonly property bool primary: variant === "primary"
    readonly property bool danger: variant === "danger"
    readonly property bool ghost: variant === "ghost"
    readonly property bool hovered: pointer.containsMouse && enabled
    readonly property bool isPressed: pointer.pressed && enabled

    function activate() {
        if (!enabled)
            return
        pressPulse = 1
        pressRelease.restart()
        clicked()
    }

    Rectangle {
        id: background
        anchors.fill: parent
        radius: Theme.radiusButton
        color: !control.enabled
               ? "#191C1F"
               : control.isPressed
               ? (control.primary ? "#E6A000"
                  : control.danger ? "#351318"
                  : control.ghost ? "#2A2E33" : "#15181B")
               : control.primary
                 ? (control.hovered ? "#FFC24D" : Theme.amber)
                 : control.danger
                   ? (control.hovered ? "#2A1114" : "#171214")
                   : control.ghost
                     ? (control.hovered ? "#22262A" : "transparent")
                     : (control.hovered ? "#2A2E33" : Theme.panelRaised)
        border.width: control.ghost && !control.isPressed ? 0 : 1
        border.color: !control.enabled
                      ? "#2A2D31"
                      : control.isPressed
                      ? (control.danger ? "#E04A5A" : control.primary ? "#FFE2A6" : Theme.amber)
                      : control.danger
                        ? Theme.red
                        : control.primary ? "#FFD37A" : "#3B4046"
        Behavior on color { ColorAnimation { duration: 110 } }
    }

    MultiEffect {
        anchors.fill: background
        source: background
        shadowEnabled: control.enabled
        shadowColor: control.primary ? Theme.amber : "#000000"
        shadowOpacity: control.isPressed
                       ? (control.primary ? 0.2 : 0.26)
                       : control.primary ? (control.hovered ? 0.55 : 0.34) : 0.42
        shadowBlur: control.isPressed ? 0.4 : (control.primary ? 0.95 : 0.55)
        shadowVerticalOffset: control.isPressed ? 1 : (control.primary ? 3 : 2)
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 1
        height: 1
        radius: 1
        color: "#FFFFFF"
        opacity: control.isPressed
                 ? (control.primary ? 0.22 : 0.06)
                 : (control.primary ? 0.38 : 0.12)
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

    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: Theme.radiusButton + 2
        color: "transparent"
        border.width: 1
        border.color: control.danger ? Theme.red : control.primary ? "#FFE2A6" : Theme.amber
        opacity: control.pressPulse * 0.5
        scale: 1 + (1 - control.pressPulse) * 0.025
        visible: control.pressPulse > 0.001
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: control.text
        color: !control.enabled
               ? Theme.mutedText
               : control.primary ? Theme.ink : Theme.white
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
        onClicked: {
            control.forceActiveFocus()
            control.activate()
        }
    }

    Keys.onReturnPressed: control.activate()
    Keys.onSpacePressed: control.activate()

    NumberAnimation {
        id: pressRelease
        target: control
        property: "pressPulse"
        from: 1
        to: 0
        duration: 240
        easing.type: Easing.OutCubic
    }
}
