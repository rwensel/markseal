import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: banner
    implicitHeight: 84
    visible: Backend.errorText.length > 0
    z: 20

    Rectangle {
        id: face
        anchors.fill: parent
        radius: 8
        color: "#1A1418"
        border.width: 1
        border.color: "#8C1A2E"
    }

    MultiEffect {
        anchors.fill: face
        source: face
        shadowEnabled: true
        shadowColor: "#000000"
        shadowOpacity: 0.55
        shadowBlur: 0.7
        shadowVerticalOffset: 6
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        Rectangle {
            width: 8
            height: 8
            radius: 1
            color: Theme.red
            Layout.alignment: Qt.AlignTop
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            Text {
                Layout.fillWidth: true
                text: Backend.errorText.toUpperCase()
                elide: Text.ElideRight
                color: Theme.white
                font.family: Backend.displayFont
                font.pixelSize: 10
                font.letterSpacing: 1.1
            }

            Text {
                Layout.fillWidth: true
                text: Backend.errorDetail
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                color: Theme.steelLight
                font.family: Backend.bodyFont
                font.pixelSize: 11
            }
        }

        ConcourseButton {
            visible: Backend.errorActionText.length > 0
            text: Backend.errorActionText
            compact: true
            onClicked: Backend.runErrorAction()
        }

        ConcourseButton {
            text: "LOGS"
            compact: true
            variant: "ghost"
            tip: "Open the local performance logs"
            onClicked: Backend.openPerformanceLogs()
        }

        ConcourseButton {
            text: "DISMISS"
            compact: true
            variant: "ghost"
            onClicked: Backend.dismissError()
        }
    }
}
