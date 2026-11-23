import QtQuick
import Redactor 1.0

Item {
    id: tile
    property string value: ""
    property string label: ""
    property color accent: Theme.steelLight
    property string displayValue: value
    property string pendingValue: value

    implicitWidth: 78
    implicitHeight: 34
    Accessible.role: Accessible.StaticText
    Accessible.name: tile.label + ": " + tile.displayValue

    onValueChanged: {
        pendingValue = value
        flip.restart()
    }

    Rectangle {
        anchors.fill: parent
        anchors.topMargin: 3
        anchors.leftMargin: 1
        anchors.rightMargin: 1
        radius: 6
        color: Theme.shadow
        opacity: 1
    }

    Rectangle {
        id: face
        anchors.fill: parent
        radius: 6
        color: Theme.tile
        border.width: 1
        border.color: Theme.hairline
        transform: Rotation {
            id: flipRotation
            origin.x: face.width / 2
            origin.y: face.height / 2
            axis { x: 1; y: 0; z: 0 }
            angle: 0
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 1
            height: 1
            radius: 1
            color: Theme.highlight
            opacity: 1
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            height: 1
            color: Theme.tileHingeDark
            opacity: 1
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: 1
            height: 1
            color: Theme.tileHingeLight
            opacity: 1
        }

        Text {
            anchors.top: parent.top
            anchors.topMargin: 1
            anchors.horizontalCenter: parent.horizontalCenter
            text: tile.displayValue
            color: tile.accent
            font.family: Backend.displayFont
            font.pixelSize: 13
            font.letterSpacing: 0.8
            font.weight: Font.DemiBold
        }

        Text {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 2
            anchors.horizontalCenter: parent.horizontalCenter
            text: tile.label
            color: Theme.mutedText
            font.family: Backend.displayFont
            font.pixelSize: 9
            font.letterSpacing: 0.8
        }
    }

    SequentialAnimation {
        id: flip
        NumberAnimation {
            target: flipRotation
            property: "angle"
            to: 90
            duration: 110
            easing.type: Easing.InQuad
        }
        ScriptAction { script: tile.displayValue = tile.pendingValue }
        PropertyAction { target: flipRotation; property: "angle"; value: -90 }
        NumberAnimation {
            target: flipRotation
            property: "angle"
            to: 0
            duration: 150
            easing.type: Easing.OutQuad
        }
    }
}
