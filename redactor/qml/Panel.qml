import QtQuick
import QtQuick.Effects

Item {
    id: panel
    property color fillColor: Theme.panel
    property bool inset: false
    property int cornerRadius: Theme.radiusPanel

    Rectangle {
        id: face
        anchors.fill: parent
        radius: panel.cornerRadius
        color: panel.fillColor
        border.width: 1
        border.color: panel.inset ? Theme.shadow : Theme.hairline
    }

    MultiEffect {
        anchors.fill: face
        source: face
        shadowEnabled: !panel.inset
        shadowColor: Theme.shadow
        shadowOpacity: 1
        shadowBlur: 0.65
        shadowVerticalOffset: 5
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
}
