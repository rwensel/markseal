import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Controls
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: sidebar
    implicitWidth: 336

    Rectangle {
        id: background
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#191C20" }
            GradientStop { position: 1.0; color: "#131518" }
        }
    }

    MultiEffect {
        anchors.fill: background
        source: background
        shadowEnabled: true
        shadowColor: "#000000"
        shadowOpacity: 0.55
        shadowBlur: 0.8
        shadowHorizontalOffset: 7
        shadowVerticalOffset: 0
    }

    Rectangle {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: 1
        color: "#000000"
        opacity: 0.9
    }

    Rectangle {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.rightMargin: 1
        width: 1
        color: "#3B4046"
        opacity: 0.5
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 9

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1

            Text {
                text: "FOLDER CONCOURSE"
                color: Theme.amber
                font.family: Backend.displayFont
                font.pixelSize: 9
                font.letterSpacing: 1.4
            }

            Text {
                Layout.fillWidth: true
                text: Backend.folderName
                elide: Text.ElideMiddle
                color: Theme.white
                font.family: Backend.displayFont
                font.pixelSize: 17
                font.letterSpacing: 0.6
            }

            Text {
                Layout.fillWidth: true
                text: Backend.folderCounts
                elide: Text.ElideRight
                color: Theme.steelLight
                font.family: Backend.bodyFont
                font.pixelSize: 11
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 7
            rowSpacing: 7

            ConcourseButton {
                Layout.fillWidth: true
                text: "SCAN ALL"
                compact: true
                enabled: !Backend.busy
                onClicked: Backend.scanAll()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "SCAN SELECTED"
                compact: true
                enabled: !Backend.busy
                onClicked: Backend.scanSelected()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "RESCAN ALL"
                compact: true
                enabled: !Backend.busy
                onClicked: Backend.rescanAll()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "COPY BOXES"
                compact: true
                enabled: Backend.hasImage && Backend.folderMode && !Backend.busy
                onClicked: Backend.copyBoxesToFolder()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "MATCH ANCHOR"
                compact: true
                enabled: Backend.hasImage && Backend.folderMode && !Backend.busy
                onClicked: Backend.beginAnchorCapture()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "CONFIRM ALL"
                compact: true
                enabled: !Backend.busy
                onClicked: Backend.confirmAll()
            }

            ConcourseButton {
                Layout.fillWidth: true
                Layout.columnSpan: 2
                text: "SAVE REVIEWED IMAGES"
                compact: true
                enabled: !Backend.busy
                onClicked: Backend.saveReviewed()
            }
        }

        Panel {
            Layout.fillWidth: true
            implicitHeight: 160

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 11
                spacing: 5

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Rectangle {
                        width: 6
                        height: 6
                        radius: 1
                        color: Backend.busy ? Theme.amber : Theme.steelMid
                    }

                    Text {
                        text: "JOB STATUS"
                        color: Theme.steelLight
                        font.family: Backend.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 1.2
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: Backend.busy ? "RUNNING" : "IDLE"
                        color: Backend.busy ? Theme.amber : Theme.mutedText
                        font.family: Backend.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 1
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: Backend.progressText
                    elide: Text.ElideRight
                    color: Theme.white
                    font.family: Backend.bodyFont
                    font.pixelSize: 11
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 6
                    radius: 3
                    color: "#0A0B0C"
                    border.width: 1
                    border.color: "#2A2D31"

                    Rectangle {
                        width: parent.width * (Backend.progressMax > 0
                                               ? Math.min(1, Backend.progressValue / Backend.progressMax)
                                               : 0)
                        height: parent.height
                        radius: 3
                        color: Theme.amber
                        Behavior on width { NumberAnimation { duration: 140 } }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: Backend.progressCurrent
                    visible: text.length > 0
                    elide: Text.ElideRight
                    color: Theme.steelLight
                    font.family: Backend.bodyFont
                    font.pixelSize: 10
                }

                Text {
                    Layout.fillWidth: true
                    text: Backend.progressDetail
                    visible: text.length > 0
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    color: Theme.steelLight
                    font.family: Backend.bodyFont
                    font.pixelSize: 10
                }

                Item { Layout.fillHeight: true }

                ConcourseButton {
                    Layout.fillWidth: true
                    text: "CANCEL SCAN"
                    variant: "danger"
                    compact: true
                    enabled: Backend.canCancel
                    onClicked: Backend.cancelScan()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                text: "IMAGES"
                color: Theme.steelLight
                font.family: Backend.displayFont
                font.pixelSize: 9
                font.letterSpacing: 1.2
            }

            Item { Layout.fillWidth: true }

            Text {
                text: "CTRL / SHIFT SELECT"
                color: Theme.mutedText
                font.family: Backend.displayFont
                font.pixelSize: 8
                font.letterSpacing: 0.8
            }
        }

        ListView {
            id: fileList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: Backend.folderModel
            boundsBehavior: Flickable.StopAtBounds
            activeFocusOnTab: true

            Keys.onUpPressed: function(event) {
                var target = Math.max(0, fileList.currentIndex - 1)
                fileList.currentIndex = target
                Backend.selectRow(target, (event.modifiers & Qt.ControlModifier) !== 0,
                                  (event.modifiers & Qt.ShiftModifier) !== 0)
            }

            Keys.onDownPressed: function(event) {
                var target = Math.min(fileList.count - 1, fileList.currentIndex + 1)
                fileList.currentIndex = target
                Backend.selectRow(target, (event.modifiers & Qt.ControlModifier) !== 0,
                                  (event.modifiers & Qt.ShiftModifier) !== 0)
            }

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                background: Item {}
                contentItem: Rectangle {
                    implicitWidth: 4
                    radius: 2
                    color: Theme.steelMid
                    opacity: parent.pressed ? 0.95 : 0.6
                }
            }

            delegate: Rectangle {
                id: row
                width: fileList.width
                height: 48
                radius: 6
                color: model.active ? "#25292E"
                       : model.selected ? "#1D2024"
                       : (pointer.containsMouse ? "#1A1D21" : "transparent")
                border.width: model.selected || model.active ? 1 : 0
                border.color: model.active ? Theme.amber : "#34393F"

                Rectangle {
                    anchors.left: parent.left
                    anchors.leftMargin: 5
                    anchors.verticalCenter: parent.verticalCenter
                    width: 3
                    height: parent.height - 16
                    radius: 1.5
                    color: Theme.amber
                    visible: model.active
                }

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -2
                    spacing: 1

                    Text {
                        width: parent.width
                        text: model.name
                        elide: Text.ElideMiddle
                        color: model.active || model.selected ? Theme.white : Theme.steelLight
                        font.family: Backend.bodyFont
                        font.pixelSize: 12
                    }

                    Text {
                        width: parent.width
                        text: model.jobState === "running"
                              ? Backend.busyLabel.toUpperCase() + "..."
                              : model.jobState === "queued" ? "QUEUED" : model.status
                        elide: Text.ElideRight
                        color: model.jobState !== "" ? Theme.amber
                               : model.hasError || model.partial ? Theme.red
                               : model.saved ? Theme.steelLight
                               : model.reviewed ? Theme.amber
                               : model.scanned ? Theme.white
                               : Theme.mutedText
                        font.family: Backend.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 0.5
                    }
                }

                Rectangle {
                    id: activity
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 14
                    anchors.rightMargin: 10
                    anchors.bottomMargin: 5
                    height: 2
                    radius: 1
                    color: "#1AFFB000"
                    visible: model.jobState !== ""

                    Rectangle {
                        width: 54
                        height: 2
                        radius: 1
                        color: Theme.amber
                        opacity: model.jobState === "queued" ? 0.35 : 1

                        SequentialAnimation on x {
                            running: model.jobState === "running"
                            loops: Animation.Infinite
                            NumberAnimation {
                                from: -54
                                to: activity.width - 54
                                duration: 900
                                easing.type: Easing.InOutQuad
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
                        fileList.forceActiveFocus()
                        fileList.currentIndex = index
                        Backend.selectRow(
                            index,
                            (mouse.modifiers & Qt.ControlModifier) !== 0,
                            (mouse.modifiers & Qt.ShiftModifier) !== 0
                        )
                    }
                }
            }
        }
    }

    Connections {
        target: Backend
        function onScrollRequested(index) {
            fileList.currentIndex = index
            fileList.positionViewAtIndex(index, ListView.Contain)
        }
    }
}
