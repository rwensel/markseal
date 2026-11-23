import QtQuick
import QtQuick.Window
import Redactor 1.0

Window {
    id: overlay
    visible: false
    visibility: Window.FullScreen
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "#66000000"

    property real startX: 0
    property real startY: 0
    property real endX: 0
    property real endY: 0
    property bool dragging: false

    function open() {
        startX = 0
        startY = 0
        endX = 0
        endY = 0
        dragging = false
        visible = true
    }

    function commit() {
        dragging = false
        var left = Math.min(startX, endX)
        var top = Math.min(startY, endY)
        var right = Math.max(startX, endX)
        var bottom = Math.max(startY, endY)
        visible = false
        if (right - left < 4 || bottom - top < 4)
            return
        region.x = Math.round(left)
        region.y = Math.round(top)
        region.w = Math.round(right - left)
        region.h = Math.round(bottom - top)
        grabTimer.restart()
    }

    QtObject {
        id: region
        property int x: 0
        property int y: 0
        property int w: 0
        property int h: 0
    }

    Timer {
        id: grabTimer
        interval: 90
        repeat: false
        onTriggered: Backend.captureRegion(region.x, region.y, region.w, region.h)
    }

    Shortcut {
        sequence: "Escape"
        onActivated: overlay.visible = false
    }

    Rectangle {
        anchors.fill: parent
        color: "#66000000"
    }

    Rectangle {
        visible: overlay.dragging
        x: Math.min(overlay.startX, overlay.endX)
        y: Math.min(overlay.startY, overlay.endY)
        width: Math.abs(overlay.endX - overlay.startX)
        height: Math.abs(overlay.endY - overlay.startY)
        color: "transparent"
        border.width: 2
        border.color: Theme.amber
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.CrossCursor
        onPressed: function(mouse) {
            overlay.startX = mouse.x
            overlay.startY = mouse.y
            overlay.endX = mouse.x
            overlay.endY = mouse.y
            overlay.dragging = true
        }
        onPositionChanged: function(mouse) {
            if (overlay.dragging) {
                overlay.endX = mouse.x
                overlay.endY = mouse.y
            }
        }
        onReleased: function(mouse) {
            overlay.endX = mouse.x
            overlay.endY = mouse.y
            overlay.commit()
        }
    }
}
