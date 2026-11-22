import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme
import Redactor 1.0

ComboBox {
    id: control
    implicitHeight: 34
    implicitWidth: 160
    font.family: Backend.bodyFont
    font.pixelSize: 12
    hoverEnabled: true

    background: Rectangle {
        radius: 6
        color: "#0F1114"
        border.width: 1
        border.color: control.activeFocus ? Theme.amber
                      : control.hovered ? Theme.steelMid : "#2A2D31"
        Behavior on border.color { ColorAnimation { duration: 110 } }
    }

    contentItem: Text {
        leftPadding: 10
        rightPadding: 26
        text: control.displayText
        font.family: Backend.bodyFont
        font.pixelSize: 12
        color: Theme.white
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: control.width - 19
        y: (control.height - height) / 2
        text: "v"
        font.family: Backend.displayFont
        font.pixelSize: 11
        color: Theme.steelLight
    }

    delegate: ItemDelegate {
        id: item
        width: control.width
        height: 30
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            leftPadding: 10
            text: modelData
            font.family: Backend.bodyFont
            font.pixelSize: 12
            color: item.highlighted ? Theme.ink : Theme.white
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 4
            color: item.highlighted ? Theme.amber : "transparent"
        }
    }

    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
        padding: 4

        background: Rectangle {
            color: "#181B1F"
            radius: 8
            border.width: 1
            border.color: Theme.hairline
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
        }

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 90 }
        }
    }
}
