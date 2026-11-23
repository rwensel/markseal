import QtQuick
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: card
    property string themeId: ""
    property string name: ""
    property string tagline: ""
    property var swatches: ({})
    property bool selected: false
    signal clicked()

    implicitHeight: body.implicitHeight + 28
    activeFocusOnTab: true
    Accessible.role: Accessible.RadioButton
    Accessible.name: card.name
    Accessible.description: card.tagline
    Accessible.checked: card.selected

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: card.selected ? Theme.rowActive
                              : pointer.containsMouse ? Theme.fieldHover : Theme.fieldFace
        border.width: card.selected ? 2 : 1
        border.color: card.selected ? Theme.amber
                                    : card.activeFocus ? Theme.focusRing : Theme.hairline
    }

    ColumnLayout {
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 4

        Text {
            Layout.fillWidth: true
            text: card.name
            color: Theme.white
            elide: Text.ElideRight
            font.family: Theme.displayFont
            font.pixelSize: 12 * Theme.labelScale
            font.letterSpacing: Theme.labelTracking
            font.weight: Font.DemiBold
        }

        Text {
            Layout.fillWidth: true
            text: card.tagline
            color: Theme.mutedText
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            font.family: Theme.bodyFont
            font.pixelSize: 10
        }

        Row {
            spacing: 4

            Repeater {
                model: ["bg", "surface", "accent", "white", "muted"]

                delegate: Rectangle {
                    required property string modelData
                    width: 20
                    height: 14
                    radius: 3
                    color: card.swatches && card.swatches[modelData] ? card.swatches[modelData]
                                                                     : "transparent"
                    border.width: 1
                    border.color: Theme.hairline
                }
            }
        }
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            card.forceActiveFocus()
            card.clicked()
        }
    }

    Keys.onReturnPressed: card.clicked()
    Keys.onSpacePressed: card.clicked()
}
