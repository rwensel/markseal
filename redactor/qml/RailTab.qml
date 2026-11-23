import QtQuick
import Redactor 1.0

Item {
    id: tab
    property string text: ""
    property bool active: false
    signal clicked()

    implicitHeight: 38
    implicitWidth: 168
    activeFocusOnTab: true
    Accessible.role: Accessible.PageTab
    Accessible.name: tab.text
    Accessible.selected: tab.active
    scale: pointer.pressed ? 0.985 : 1
    Behavior on scale { NumberAnimation { duration: 90 } }

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: pointer.pressed
               ? (tab.active ? Theme.tabActiveFace : Theme.tabActiveFace)
               : tab.active ? Theme.panelRaised
               : (pointer.containsMouse ? Theme.tabHover : "transparent")
        border.width: tab.active || pointer.pressed ? 1 : 0
        border.color: pointer.pressed ? Theme.amber : Theme.tabBorder
        Behavior on color { ColorAnimation { duration: 100 } }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 3
        height: 18
        radius: 1.5
        color: Theme.amber
        visible: tab.active
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        text: tab.text
        color: tab.active ? Theme.white : Theme.steelLight
        font.family: Theme.displayFont
        font.pixelSize: 11
        font.letterSpacing: 1.1
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            tab.forceActiveFocus()
            tab.clicked()
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: 8
        color: "transparent"
        border.color: Theme.amber
        border.width: 1
        opacity: 0.8
        visible: tab.activeFocus
    }

    Keys.onReturnPressed: tab.clicked()
    Keys.onSpacePressed: tab.clicked()
}
