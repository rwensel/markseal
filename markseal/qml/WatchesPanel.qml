import QtQuick
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: root
    objectName: "watchesPanel"
    visible: false
    z: 40
    focus: visible

    function open() {
        visible = true
        forceActiveFocus()
    }

    function close() {
        visible = false
    }

    function countText(row) {
        var parts = []
        if (row.new > 0)
            parts.push(row.new + " new")
        if (row.queued > 0)
            parts.push(row.queued + " waiting")
        if (row.needs_review > 0)
            parts.push(row.needs_review + " needs review")
        if (row.existing > 0)
            parts.push(row.existing + " ready")
        if (row.exported > 0)
            parts.push(row.exported + (row.policy === "AUTO" ? " auto-redacted" : " redacted"))
        return parts.length > 0 ? parts.join(" · ") : "Nothing pending"
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim

        MouseArea {
            anchors.fill: parent
            onClicked: root.close()
        }
    }

    Panel {
        id: frame
        anchors.centerIn: parent
        width: Math.min(parent.width - 120, 820)
        height: Math.min(parent.height - 96, 620)

        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Text {
                    text: "INBOX"
                    color: Theme.white
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.scaleFont(24)
                    font.letterSpacing: 2.4
                    font.weight: Font.DemiBold
                }

                Rectangle {
                    readonly property bool hot: Backend.watches.newCount > 0
                    Layout.alignment: Qt.AlignVCenter
                    implicitWidth: newCount.implicitWidth + 16
                    implicitHeight: 22
                    radius: 4
                    color: hot ? Theme.amberFill : Theme.inset
                    border.width: 1
                    border.color: hot ? Theme.amberBorder : Theme.hairline

                    Text {
                        id: newCount
                        anchors.centerIn: parent
                        text: Backend.watches.newCount + " NEW"
                        color: parent.hot ? Theme.amber : Theme.steelLight
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.scaleFont(9 * Theme.labelScale)
                        font.letterSpacing: Theme.labelTracking
                        font.weight: Font.DemiBold
                    }
                }

                Item { Layout.fillWidth: true }

                ConcourseButton {
                    text: "CLOSE"
                    compact: true
                    variant: "ghost"
                    tip: "Close the inbox (Esc)"
                    onClicked: root.close()
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 150

                ListView {
                    id: inboxList
                    objectName: "watchesList"
                    anchors.fill: parent
                    clip: true
                    spacing: 7
                    model: Backend.watches.watchRows
                    boundsBehavior: Flickable.StopAtBounds
                    activeFocusOnTab: true
                    Accessible.role: Accessible.List
                    Accessible.name: "Watched folder inbox"
                    signal openWatch(string path)

                    onOpenWatch: {
                        root.close()
                        Backend.watches.openFolder(path)
                    }

                    delegate: Rectangle {
                        id: row
                        required property var modelData

                        width: inboxList.width - 8
                        height: body.implicitHeight + 22
                        radius: Theme.radiusCard
                        color: pointer.hovered ? Theme.rowHover : Theme.fieldFace
                        border.width: 1
                        border.color: Theme.hairline
                        Accessible.role: Accessible.ListItem
                        Accessible.name: modelData.name + ", " + modelData.policy + ", "
                                        + root.countText(modelData)
                        Accessible.description: modelData.path
                                                + (modelData.error.length > 0
                                                   ? ". Error: " + modelData.error : "")

                        HoverHandler { id: pointer }

                        ColumnLayout {
                            id: body
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 11
                            spacing: 3

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: row.modelData.name
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                    color: Theme.white
                                    font.family: Theme.displayFont
                                    font.pixelSize: Theme.scaleFont(13)
                                    font.letterSpacing: 0.5
                                    font.weight: Font.DemiBold
                                }

                                Rectangle {
                                    Layout.alignment: Qt.AlignVCenter
                                    implicitWidth: policyLabel.implicitWidth + 14
                                    implicitHeight: 18
                                    radius: 3
                                    color: row.modelData.policy === "AUTO" ? Theme.amberFill : Theme.inset
                                    border.width: 1
                                    border.color: row.modelData.policy === "AUTO"
                                                  ? Theme.amberBorder : Theme.hairline

                                    Text {
                                        id: policyLabel
                                        anchors.centerIn: parent
                                        text: row.modelData.policy
                                        color: row.modelData.policy === "AUTO"
                                               ? Theme.amber : Theme.steelLight
                                        font.family: Theme.displayFont
                                        font.pixelSize: Theme.scaleFont(9 * Theme.labelScale)
                                        font.letterSpacing: Theme.labelTracking
                                        font.weight: Font.DemiBold
                                    }
                                }

                                ConcourseButton {
                                    text: "OPEN"
                                    compact: true
                                    tip: "Open this folder in the review board"
                                    onClicked: row.ListView.view.openWatch(row.modelData.path)
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: row.modelData.path
                                textFormat: Text.PlainText
                                elide: Text.ElideMiddle
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.countText(row.modelData)
                                elide: Text.ElideRight
                                color: Theme.steelLight
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(11)
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: row.modelData.error.length > 0
                                text: row.modelData.error
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Theme.dangerText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }

                            Repeater {
                                model: Math.min(5, row.modelData.issues.length)

                                Text {
                                    required property int index

                                    Layout.fillWidth: true
                                    text: row.modelData.issues[index].name + " · "
                                          + row.modelData.issues[index].detail
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                    color: Theme.dangerText
                                    font.family: Theme.bodyFont
                                    font.pixelSize: Theme.scaleFont(10)
                                }
                            }

                            ConcourseButton {
                                Layout.topMargin: 4
                                visible: row.modelData.existing > 0
                                         || row.modelData.needs_review > 0
                                         || row.modelData.queued > 0
                                text: "PROCESS EXISTING ("
                                      + (row.modelData.existing + row.modelData.needs_review
                                         + row.modelData.queued) + ")"
                                compact: true
                                tip: "Requeue the files this watch already has"
                                onClicked: Backend.watches.processExisting(row.modelData.path)
                            }
                        }
                    }
                }

                Rectangle {
                    visible: inboxList.contentHeight > inboxList.height
                    width: 3
                    height: Math.max(24, inboxList.visibleArea.heightRatio * inboxList.height)
                    radius: 1.5
                    color: Theme.steelMid
                    opacity: 0.7
                    x: inboxList.width - 5
                    y: inboxList.visibleArea.yPosition * inboxList.height
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 8
                    visible: inboxList.count === 0

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 42
                        height: 2
                        color: Theme.amber
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "NO WATCHED FOLDERS"
                        color: Theme.white
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.scaleFont(17)
                        font.letterSpacing: 1.6
                        font.weight: Font.DemiBold
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: frame.width - 160
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "Add a folder to collect screenshots here."
                        color: Theme.steelLight
                        font.family: Theme.bodyFont
                        font.pixelSize: Theme.scaleFont(11)
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    id: autoStatus
                    Layout.maximumWidth: Math.round(frame.width * 0.55)
                    Layout.preferredWidth: Math.min(implicitWidth, Layout.maximumWidth)
                    visible: Backend.watches.autoStatus.length > 0
                    text: Backend.watches.autoStatus
                    elide: Text.ElideRight
                    color: Theme.steelLight
                    font.family: Theme.bodyFont
                    font.pixelSize: Theme.scaleFont(11)
                }

                Item { Layout.fillWidth: true }

                ConcourseButton {
                    text: "STOP"
                    compact: true
                    variant: "danger"
                    visible: Backend.watches.autoRunning
                    tip: "Stop automatic processing until you resume it with Process existing or by switching the watch back to AUTO."
                    onClicked: Backend.watches.cancelAuto()
                }

                ConcourseButton {
                    text: "ADD FOLDER"
                    compact: true
                    variant: "primary"
                    tip: "Watch a folder for new screenshots"
                    onClicked: Backend.watches.chooseFolder()
                }
            }
        }
    }
}
