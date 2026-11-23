import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Controls
import Redactor 1.0

Item {
    id: sidebar
    implicitWidth: 336
    property bool showBatch: false
    readonly property int batchReady: Backend.folder.folderMode
                                      ? 1 + (Backend.review.selectedCount > 0
                                             && Backend.folder.folderImageCount > 1 ? 2 : 0)
                                      : 0

    Rectangle {
        id: background
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.sidebarTop }
            GradientStop { position: 1.0; color: Theme.sidebarBottom }
        }
    }

    MultiEffect {
        anchors.fill: background
        source: background
        shadowEnabled: true
        shadowColor: Theme.shadow
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
        color: Theme.shadow
        opacity: 0.9
    }

    Rectangle {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.rightMargin: 1
        width: 1
        color: Theme.buttonBorder
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
                text: "FOLDER"
                color: Theme.amber
                font.family: Theme.displayFont
                font.pixelSize: 9
                font.letterSpacing: 1.4
            }

            Text {
                Layout.fillWidth: true
                text: Backend.folder.folderName
                elide: Text.ElideMiddle
                color: Theme.white
                font.family: Theme.displayFont
                font.pixelSize: 17
                font.letterSpacing: 0.6
            }

            Text {
                Layout.fillWidth: true
                text: Backend.folder.folderCounts
                elide: Text.ElideRight
                color: Theme.steelLight
                font.family: Theme.bodyFont
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
                tip: "Scan every image in the folder"
                enabled: !Backend.batch.busy
                onClicked: Backend.batch.scanAll()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "SCAN SELECTED"
                compact: true
                tip: "Scan only the highlighted images"
                enabled: !Backend.batch.busy
                onClicked: Backend.batch.scanSelected()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "CONFIRM ALL"
                compact: true
                tip: "Apply the boxes on every scanned image"
                enabled: !Backend.batch.busy
                onClicked: Backend.batch.confirmAll()
            }

            ConcourseButton {
                Layout.fillWidth: true
                text: "SAVE REVIEWED"
                compact: true
                tip: Backend.folder.reviewedCount > 0
                     ? "Export " + Backend.folder.reviewedCount + " confirmed image(s)"
                     : "Confirm at least one image first"
                enabled: !Backend.batch.busy && Backend.folder.reviewedCount > 0
                onClicked: Backend.batch.saveReviewed()
            }

            ConcourseButton {
                Layout.fillWidth: true
                Layout.columnSpan: 2
                text: sidebar.showBatch ? "HIDE BATCH TOOLS"
                      : sidebar.batchReady > 0 ? "BATCH TOOLS · " + sidebar.batchReady
                      : "BATCH TOOLS"
                variant: "secondary"
                compact: true
                tip: sidebar.batchReady > 0
                     ? "Rescan all, copy boxes, and match by anchor; "
                       + sidebar.batchReady + " can run now"
                     : "Rescan all, copy boxes, and match by anchor"
                onClicked: sidebar.showBatch = !sidebar.showBatch
            }

            ConcourseButton {
                Layout.fillWidth: true
                Layout.columnSpan: 2
                visible: sidebar.showBatch
                text: "RESCAN ALL"
                compact: true
                tip: "Run detection again on every image in the folder"
                enabled: !Backend.batch.busy
                onClicked: Backend.batch.rescanAll()
            }

            ConcourseButton {
                Layout.fillWidth: true
                Layout.columnSpan: 2
                visible: sidebar.showBatch
                text: "COPY BOXES TO MATCHING"
                compact: true
                tip: "Copy this image's boxes to every image of the same size"
                enabled: Backend.review.hasImage && Backend.folder.folderImageCount > 1
                         && Backend.review.selectedCount > 0 && !Backend.batch.busy
                onClicked: Backend.batch.copyBoxesToFolder()
            }

            ConcourseButton {
                Layout.fillWidth: true
                Layout.columnSpan: 2
                visible: sidebar.showBatch
                text: "MATCH BY ANCHOR"
                compact: true
                tip: "Place this image's boxes on shifted captures of the same screen"
                enabled: Backend.review.hasImage && Backend.folder.folderImageCount > 1
                         && Backend.review.selectedCount > 0 && !Backend.batch.busy
                onClicked: Backend.review.beginAnchorCapture()
            }
        }

        Panel {
            Layout.fillWidth: true
            implicitHeight: Backend.batch.busy ? 146 : 84

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
                        color: Backend.batch.busy ? Theme.amber : Theme.steelMid
                    }

                    Text {
                        text: "JOB STATUS"
                        color: Theme.steelLight
                        font.family: Theme.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 1.2
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: Backend.batch.busy ? "RUNNING" : "IDLE"
                        color: Backend.batch.busy ? Theme.amber : Theme.mutedText
                        font.family: Theme.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 1
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: Backend.batch.progressText
                    elide: Text.ElideRight
                    color: Theme.white
                    font.family: Theme.bodyFont
                    font.pixelSize: 11
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 6
                    radius: 3
                    color: Theme.inset
                    border.width: 1
                    border.color: Theme.fieldBorder

                    Rectangle {
                        width: parent.width * (Backend.batch.progressMax > 0
                                               ? Math.min(1, Backend.batch.progressValue / Backend.batch.progressMax)
                                               : 0)
                        height: parent.height
                        radius: 3
                        color: Theme.amber
                        Behavior on width { NumberAnimation { duration: 140 } }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: Backend.batch.progressCurrent
                    visible: Backend.batch.busy && text.length > 0
                    elide: Text.ElideRight
                    color: Theme.steelLight
                    font.family: Theme.bodyFont
                    font.pixelSize: 10
                }

                Text {
                    Layout.fillWidth: true
                    text: Backend.batch.progressDetail
                    visible: Backend.batch.busy && text.length > 0
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    color: Theme.steelLight
                    font.family: Theme.bodyFont
                    font.pixelSize: 10
                }

                Item { Layout.fillHeight: true }

                ConcourseButton {
                    Layout.fillWidth: true
                    text: "CANCEL SCAN"
                    variant: "danger"
                    compact: true
                    visible: Backend.batch.canCancel
                    enabled: Backend.batch.canCancel
                    onClicked: Backend.batch.cancelScan()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                text: "IMAGES"
                color: Theme.steelLight
                font.family: Theme.displayFont
                font.pixelSize: 9
                font.letterSpacing: 1.2
            }

            Item { Layout.fillWidth: true }

            Text {
                text: "CTRL / SHIFT SELECT"
                color: Theme.mutedText
                font.family: Theme.displayFont
                font.pixelSize: 9
                font.letterSpacing: 0.7
            }
        }

        ListView {
            id: fileList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150
            clip: true
            spacing: 2
            model: Backend.folder.folderModel
            boundsBehavior: Flickable.StopAtBounds
            activeFocusOnTab: true
            Accessible.role: Accessible.List
            Accessible.name: "Folder images"

            Keys.onUpPressed: function(event) {
                var target = Math.max(0, fileList.currentIndex - 1)
                fileList.currentIndex = target
                Backend.folder.selectRow(target, (event.modifiers & Qt.ControlModifier) !== 0,
                                  (event.modifiers & Qt.ShiftModifier) !== 0)
            }

            Keys.onDownPressed: function(event) {
                var target = Math.min(fileList.count - 1, fileList.currentIndex + 1)
                fileList.currentIndex = target
                Backend.folder.selectRow(target, (event.modifiers & Qt.ControlModifier) !== 0,
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
                width: fileList.width - 10
                height: 48
                radius: 6
                color: model.active ? Theme.rowActive
                       : model.selected ? Theme.rowSelected
                       : (pointer.containsMouse ? Theme.rowHover : "transparent")
                border.width: model.selected || model.active ? 1 : 0
                border.color: model.active ? Theme.amber : Theme.toolbarDivider

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
                        font.family: Theme.bodyFont
                        font.pixelSize: 12
                    }

                    Text {
                        width: parent.width
                        text: model.jobState === "running"
                              ? Backend.batch.busyLabel.toUpperCase() + "..."
                              : model.jobState === "queued" ? "QUEUED" : model.status
                        elide: Text.ElideRight
                        color: model.jobState !== "" ? Theme.amber
                               : model.hasError || model.partial ? Theme.red
                               : model.saved ? Theme.steelLight
                               : model.reviewed ? Theme.amber
                               : model.scanned ? Theme.white
                               : Theme.mutedText
                        font.family: Theme.displayFont
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
                    color: Theme.accentSoft
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
                        Backend.folder.selectRow(
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
        target: Backend.folder
        function onScrollRequested(index) {
            fileList.currentIndex = index
            fileList.positionViewAtIndex(index, ListView.Contain)
        }
    }
}
