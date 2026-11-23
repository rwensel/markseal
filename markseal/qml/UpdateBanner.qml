import QtQuick
import QtQuick.Layouts
import Redactor 1.0

Rectangle {
    id: banner
    visible: Backend.updates.hasUpdate
    implicitHeight: visible ? (banner.showNotes ? 150 : 46) : 0
    color: Theme.panelRaised
    radius: 6
    border.width: 1
    border.color: Theme.amber

    property bool showNotes: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 9
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "UPDATE " + (Backend.updates.updateInfo.version || "") + " AVAILABLE"
                color: Theme.white
                font.family: Theme.displayFont
                font.pixelSize: 11
                font.letterSpacing: 1.0
            }

            ConcourseButton {
                text: "NOTES"
                compact: true
                onClicked: banner.showNotes = !banner.showNotes
            }

            ConcourseButton {
                text: "UPDATE"
                compact: true
                enabled: !Backend.updates.busy
                onClicked: Backend.updates.install()
            }

            ConcourseButton {
                text: "LATER"
                compact: true
                onClicked: Backend.updates.dismiss()
            }
        }

        Text {
            Layout.fillWidth: true
            visible: banner.showNotes
            text: Backend.updates.updateInfo.notes || ""
            wrapMode: Text.WordWrap
            maximumLineCount: 6
            elide: Text.ElideRight
            color: Theme.steelLight
            font.family: Theme.bodyFont
            font.pixelSize: 10
        }

        Text {
            Layout.fillWidth: true
            visible: Backend.updates.errorText.length > 0
            text: Backend.updates.errorText
            wrapMode: Text.WordWrap
            color: Theme.dangerText
            font.family: Theme.bodyFont
            font.pixelSize: 10
        }
    }
}
