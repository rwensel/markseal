import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import Redactor 1.0

Item {
    id: banner
    visible: Backend.updates.hasUpdate
    implicitHeight: visible ? (banner.showNotes ? 186 : 88) : 0

    property bool showNotes: false

    MultiEffect {
        anchors.fill: panel
        source: panel
        shadowEnabled: true
        shadowColor: Theme.shadow
        shadowOpacity: 0.55
        shadowBlur: 0.6
        shadowVerticalOffset: 6
        shadowHorizontalOffset: 0
    }

    Rectangle {
        id: panel
        anchors.fill: parent
        radius: Theme.radiusPanel
        border.width: 1
        border.color: Theme.hairline
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.lighter(Theme.panelRaised, 1.03) }
            GradientStop { position: 1.0; color: Theme.panelRaised }
        }

        Rectangle {
            width: 3
            radius: 1.5
            color: Theme.amber
            opacity: 0.65
            anchors.left: parent.left
            anchors.leftMargin: 1
            anchors.top: parent.top
            anchors.topMargin: 10
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 10
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 10
            anchors.topMargin: 8
            anchors.bottomMargin: 8
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
                    text: Backend.updates.readyToInstall ? "INSTALL"
                        : (Backend.updates.busy ? "WORKING…" : "UPDATE")
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
                visible: Backend.updates.status.length > 0
                text: Backend.updates.status
                color: Theme.steelLight
                font.family: Theme.bodyFont
                font.pixelSize: 10
                elide: Text.ElideRight
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 4
                radius: 2
                color: Theme.hairline
                opacity: Backend.updates.busy || Backend.updates.readyToInstall ? 1 : 0

                Rectangle {
                    width: parent.width * Backend.updates.progress
                    height: parent.height
                    radius: 2
                    color: Theme.amber
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
}
