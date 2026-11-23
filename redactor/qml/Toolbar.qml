import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: toolbar
    implicitHeight: 70
    signal settingsClicked()

    readonly property bool wide: width >= 1240
    readonly property bool canScan: Backend.hasImage && !Backend.busy && !Backend.confirmed
    readonly property bool canConfirm: Backend.hasImage && !Backend.busy && !Backend.confirmed

    Shortcut {
        sequence: "Alt+M"
        enabled: !toolbar.wide
        onActivated: overflow.popup(moreButton, moreButton.width - overflow.width,
                                    moreButton.height + 6)
    }

    Rectangle {
        id: bar
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.toolbarTop }
            GradientStop { position: 1.0; color: Theme.toolbarBottom }
        }
    }

    MultiEffect {
        anchors.fill: bar
        source: bar
        shadowEnabled: true
        shadowColor: Theme.shadow
        shadowOpacity: 0.5
        shadowBlur: 0.7
        shadowVerticalOffset: 7
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Theme.shadow
        opacity: 0.8
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 1
        height: 1
        color: Theme.toolbarEdge
        opacity: 0.55
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 7

        RowLayout {
            spacing: 10
            Layout.preferredWidth: 232

            Rectangle {
                width: 46
                height: 46
                radius: 8
                color: Theme.panelRaised
                border.width: 1
                border.color: Theme.buttonBorder

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 8
                    radius: 4
                    color: Theme.amber

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        height: 1
                        color: Theme.shadow
                        opacity: 0.5
                    }
                }
            }

            Column {
                spacing: 0

                Text {
                    text: "OFFLINE REDACTOR"
                    color: Theme.white
                    font.family: Theme.displayFont
                    font.pixelSize: 15
                    font.letterSpacing: 1.5
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "SCREENSHOT / LOCAL ONLY"
                    color: Theme.steelLight
                    font.family: Theme.displayFont
                    font.pixelSize: 9
                    font.letterSpacing: 1.2
                }
            }
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 30
            color: Theme.toolbarDivider
        }

        ConcourseButton {
            text: "OPEN IMAGE"
            compact: true
            tip: "Open an image file (Ctrl+O)"
            enabled: !Backend.busy
            onClicked: Backend.openImage()
        }

        ConcourseButton {
            text: "OPEN FOLDER"
            compact: true
            tip: "Open every image in a folder (Ctrl+Shift+O)"
            enabled: !Backend.busy
            onClicked: Backend.openFolder()
        }

        ConcourseButton {
            text: "PASTE"
            compact: true
            tip: "Paste an image from the clipboard (Ctrl+V)"
            visible: toolbar.wide
            enabled: !Backend.busy
            onClicked: Backend.pasteImage()
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 30
            color: Theme.toolbarDivider
        }

        ConcourseButton {
            text: "SCAN IMAGE"
            compact: true
            variant: toolbar.canScan && Backend.totalBoxes === 0 ? "primary" : "secondary"
            tip: "Find identifiers in this image (Ctrl+F)"
            enabled: toolbar.canScan
            onClicked: Backend.find()
        }

        ConcourseButton {
            text: "SCAN REGION"
            compact: true
            tip: "Drag around one area to scan just that text"
            visible: toolbar.wide
            enabled: toolbar.canScan
            onClicked: Backend.beginScanArea()
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 30
            color: Theme.toolbarDivider
        }

        ConcourseButton {
            text: "UNDO"
            compact: true
            tip: "Undo the last box (Ctrl+Z)"
            enabled: Backend.hasImage && Backend.totalBoxes > 0
            onClicked: Backend.undo()
        }

        ConcourseButton {
            text: "CLEAR"
            compact: true
            tip: "Remove every box from this image"
            visible: toolbar.wide
            enabled: Backend.hasImage && Backend.totalBoxes > 0
            onClicked: Backend.clearBoxes()
        }

        ConcourseButton {
            id: moreButton
            text: "MORE"
            compact: true
            tip: overflow.visible ? "" : "More actions (Alt+M)"
            visible: !toolbar.wide
            onClicked: overflow.popup(moreButton, moreButton.width - overflow.width,
                                      moreButton.height + 6)
        }

        Item { Layout.fillWidth: true }

        ConcourseButton {
            text: Backend.confirmLabel
            compact: true
            variant: toolbar.canConfirm && Backend.totalBoxes > 0 ? "primary" : "secondary"
            tip: Backend.confirmLabel.indexOf(" ") > 0
                 ? "Apply the boxes to every selected image"
                 : "Apply the selected boxes (Ctrl+Enter)"
            enabled: toolbar.canConfirm
            onClicked: Backend.confirmSelection()
        }

        ConcourseButton {
            text: "SAVE"
            compact: true
            variant: Backend.confirmed ? "primary" : "secondary"
            tip: "Save the confirmed PNG copy and coordinate log (Ctrl+S)"
            enabled: Backend.hasImage && !Backend.busy && Backend.confirmed
            onClicked: Backend.save()
        }

        ConcourseButton {
            text: "SETTINGS"
            variant: "ghost"
            compact: true
            tip: "Detection, redaction, and output preferences"
            onClicked: Backend.requestSettings()
        }
    }

    Menu {
        id: overflow
        width: 218

        background: Rectangle {
            color: Theme.panel
            radius: 8
            border.width: 1
            border.color: Theme.hairline
        }

        MenuAction {
            text: "Paste image  (Ctrl+V)"
            onTriggered: Backend.pasteImage()
        }
        MenuAction {
            text: "Scan a region"
            enabled: toolbar.canScan && !Backend.busy
            onTriggered: Backend.beginScanArea()
        }
        MenuAction {
            text: "Clear all boxes"
            enabled: Backend.hasImage && Backend.totalBoxes > 0 && !Backend.busy
            onTriggered: Backend.clearBoxes()
        }
    }
}
