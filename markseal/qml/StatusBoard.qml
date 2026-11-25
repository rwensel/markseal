import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: board

    readonly property bool hasImage: Backend.review.hasImage
    readonly property bool hasBoxes: Backend.review.totalBoxes > 0
    readonly property string stateValue: !hasImage ? "EMPTY"
                                                : Backend.review.confirmed ? "APPLIED"
                                                : hasBoxes ? "PENDING" : "READY"
    readonly property string stateDescription: !hasImage
                                                ? "No screenshot is open."
                                                : Backend.review.confirmed
                                                ? "Boxes are applied to the preview."
                                                : hasBoxes
                                                ? "Boxes exist but are not confirmed. Press Confirm to apply them."
                                                : "A screenshot is open. Scan it or drag a box."

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.boardTop }
            GradientStop { position: 1.0; color: Theme.boardBottom }
        }
    }

    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 1
        color: Theme.buttonBorder
        opacity: 0.5
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 16
        spacing: 12

        Rectangle {
            width: 7
            height: 7
            radius: 1
            color: Backend.batch.busy ? Theme.amber : Theme.steelMid
        }

        Text {
            Layout.fillWidth: true
            text: Backend.statusText
            elide: Text.ElideRight
            color: Theme.steelLight
            font.family: Theme.bodyFont
            font.pixelSize: 12
            Accessible.role: Accessible.StaticText
            Accessible.name: Backend.statusText
        }

        FlipTile {
            value: String(Backend.review.selectedCount)
            label: "SELECTED"
            accent: Theme.amber
        }

        FlipTile {
            value: String(Backend.review.excludedCount)
            label: "EXCLUDED"
            accent: Theme.red
        }

        FlipTile {
            value: String(Backend.review.totalBoxes)
            label: "TOTAL"
            accent: Theme.steelLight
        }

        FlipTile {
            id: stateTile
            value: board.stateValue
            label: "STATE"
            accent: !board.hasImage || (board.hasBoxes && !Backend.review.confirmed)
                    ? Theme.steelMid
                    : Backend.review.confirmed ? Theme.amber : Theme.steelLight
            Accessible.description: board.stateDescription

            HoverHandler { id: stateHover }
            ToolTip.visible: stateHover.hovered
            ToolTip.delay: 500
            ToolTip.text: board.stateDescription
        }
    }
}
