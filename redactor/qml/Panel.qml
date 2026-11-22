import QtQuick
import QtQuick.Effects
import "Theme.js" as Theme

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
        border.color: panel.inset ? "#050506" : "#34393F"
    }

    MultiEffect {
        anchors.fill: face
        source: face
        shadowEnabled: !panel.inset
        shadowColor: "#000000"
        shadowOpacity: 0.42
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
        color: "#FFFFFF"
        opacity: panel.inset ? 0.02 : 0.07
    }
}
