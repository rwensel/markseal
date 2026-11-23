import QtQuick
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: board

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
            value: Backend.review.confirmed ? "APPLIED" : "PENDING"
            label: "STATE"
            accent: Backend.review.confirmed ? Theme.amber : Theme.steelMid
        }
    }
}
