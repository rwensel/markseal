import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: banner
    implicitHeight: 84
    visible: Backend.errorText.length > 0
    z: 20
    activeFocusOnTab: true
    Accessible.role: Accessible.AlertMessage
    Accessible.name: Backend.errorText + ". " + Backend.errorDetail
    Accessible.description: "Error. Tab to Retry, Logs, or Dismiss."

    transform: Translate {
        id: revealShift
        y: banner.visible ? 0 : 6
        Behavior on y {
            enabled: !Theme.reduceMotion
            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
        }
    }

    Connections {
        target: Backend
        function onErrorChanged() {
            if (Backend.errorText.length > 0)
                banner.forceActiveFocus()
        }
    }

    Rectangle {
        id: face
        anchors.fill: parent
        radius: 8
        color: Theme.bannerFace
        border.width: 1
        border.color: Theme.bannerBorder
    }

    MultiEffect {
        anchors.fill: face
        source: face
        shadowEnabled: true
        shadowColor: Theme.shadow
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
                font.family: Theme.displayFont
                font.pixelSize: Theme.scaleFont(10)
                font.letterSpacing: 1.1
            }

            Text {
                Layout.fillWidth: true
                text: Backend.errorDetail
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 2
                elide: Text.ElideRight
                color: Theme.steelLight
                font.family: Theme.bodyFont
                font.pixelSize: Theme.scaleFont(11)
                ToolTip.visible: detailHover.hovered
                ToolTip.delay: 500
                ToolTip.text: Backend.errorDetail

                HoverHandler { id: detailHover }
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
            onClicked: Backend.settings.openPerformanceLogs()
        }

        ConcourseButton {
            text: "DISMISS"
            compact: true
            variant: "ghost"
            onClicked: Backend.dismissError()
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: 10
        color: "transparent"
        border.width: 1
        border.color: Theme.amber
        opacity: 0.85
        visible: banner.activeFocus
    }
}
