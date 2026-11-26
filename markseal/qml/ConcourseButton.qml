import QtQuick
import QtQuick.Controls
import QtQuick.Effects
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
        enabled: !Theme.reduceMotion
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
               ? Theme.disabledFace
               : control.isPressed
               ? (control.primary ? Theme.amberPressed
                  : control.danger ? Theme.dangerFace
                  : control.ghost ? Theme.buttonFaceHover : Theme.buttonFacePressed)
               : control.primary
                 ? (control.hovered ? Theme.amberHover : Theme.amber)
                 : control.danger
                   ? (control.hovered ? Qt.lighter(Theme.dangerFace, 1.25) : Theme.dangerFace)
                   : control.ghost
                     ? (control.hovered ? Theme.ghostHover : "transparent")
                     : (control.hovered ? Theme.buttonFaceHover : Theme.panelRaised)
        border.width: control.ghost && !control.isPressed ? 0 : 1
        border.color: !control.enabled
                      ? Theme.fieldBorder
                      : control.isPressed
                      ? (control.danger ? Qt.lighter(Theme.dangerBorder, 1.2)
                         : control.primary ? Qt.lighter(Theme.amberBorder, 1.08) : Theme.amber)
                      : control.danger
                        ? Theme.dangerBorder
                        : control.primary ? Theme.amberBorder : Theme.buttonBorder
        Behavior on color {
            enabled: !Theme.reduceMotion
            ColorAnimation { duration: 110 }
        }
    }

    MultiEffect {
        anchors.fill: background
        source: background
        shadowEnabled: control.enabled
        shadowColor: control.primary ? Theme.amber : Theme.shadow
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
        color: Theme.highlight
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
        border.color: control.danger ? Theme.dangerBorder
                                      : control.primary ? Qt.lighter(Theme.amberBorder, 1.08)
                                                        : Theme.amber
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
        font.family: Theme.displayFont
        font.pixelSize: Theme.scaleFont((control.compact ? 10 : 11) * Theme.labelScale)
        font.letterSpacing: Theme.labelTracking
        font.weight: Font.DemiBold
    }

    MouseArea {
        id: touchMargin
        anchors.fill: parent
        anchors.topMargin: -6
        anchors.bottomMargin: -6
        enabled: control.enabled
        onClicked: {
            control.forceActiveFocus()
            control.activate()
        }
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
        duration: Theme.reduceMotion ? 0 : 240
        easing.type: Easing.OutCubic
    }
}
