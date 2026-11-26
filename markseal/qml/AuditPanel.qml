import QtQuick
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: root
    objectName: "auditPanel"
    visible: false
    z: 45
    focus: visible

    function open() {
        Backend.batch.prepareAudit()
        visible = true
        forceActiveFocus()
    }

    function close() {
        visible = false
    }

    function statusLabel(item) {
        if (item.issue)
            return "ISSUE"
        if (item.outside_pixels_unchanged === false)
            return "REVIEW"
        return "CLEAN"
    }

    function statusColor(item) {
        if (item.issue || item.outside_pixels_unchanged === false)
            return Theme.dangerText
        return Theme.amber
    }

    function detailText(item) {
        var parts = []
        if (item.logged_boxes !== undefined)
            parts.push(item.logged_boxes + (item.logged_boxes === 1 ? " box" : " boxes"))
        if (item.wide_boxes > 0)
            parts.push(item.wide_boxes + (item.wide_boxes === 1 ? " wide box" : " wide boxes"))
        if (item.masked_percent !== undefined)
            parts.push(item.masked_percent + "% masked")
        return parts.join(" · ")
    }

    function ocrText(item) {
        if (!item.ocr_candidates)
            return ""
        var original = item.ocr_candidates
        var exported = item.export_ocr_candidates
        var text = "OCR original: " + original.covered + " covered / "
                   + original.partial + " partial / " + original.uncovered + " uncovered"
        if (exported)
            text += " · exported: " + exported.covered + " readable"
        return text
    }

    readonly property real auditRatio: Backend.batch.progressMax > 0
                                        ? Math.min(1, Backend.batch.progressValue
                                                   / Backend.batch.progressMax)
                                        : 0

    Keys.onEscapePressed: root.close()

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
        width: Math.min(parent.width - 120, 900)
        height: Math.min(parent.height - 56, 700)

        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                ColumnLayout {
                    spacing: 1

                    Text {
                        text: "AUDIT EXPORTS"
                        color: Theme.white
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.scaleFont(24)
                        font.letterSpacing: 2.4
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: "LOCAL CHECK / ORIGINALS + EXPORTS"
                        color: Theme.steelLight
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.scaleFont(9)
                        font.letterSpacing: 1.2
                    }
                }

                Item { Layout.fillWidth: true }

                ConcourseButton {
                    text: "CLOSE"
                    compact: true
                    variant: "ghost"
                    tip: "Close the audit panel (Esc)"
                    onClicked: root.close()
                }
            }

            HintText {
                Layout.fillWidth: true
                text: "Compare exported PNGs with their originals and coordinate logs. The audit runs locally and reports review candidates, not proof."
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                FieldLabel {
                    Layout.preferredWidth: 72
                    text: "ORIGINALS"
                }

                ConcourseTextField {
                    Layout.fillWidth: true
                    readOnly: true
                    text: Backend.batch.auditOriginals
                    placeholderText: "Choose the folder with original images"
                }

                ConcourseButton {
                    text: "CHOOSE"
                    compact: true
                    enabled: !Backend.batch.busy && !Backend.batch.auditRunning
                    tip: "Choose the originals folder"
                    onClicked: Backend.batch.chooseAuditOriginals()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                FieldLabel {
                    Layout.preferredWidth: 72
                    text: "EXPORTS"
                }

                ConcourseTextField {
                    Layout.fillWidth: true
                    readOnly: true
                    text: Backend.batch.auditExports
                    placeholderText: "Choose the folder with exported PNGs"
                }

                ConcourseButton {
                    text: "CHOOSE"
                    compact: true
                    enabled: !Backend.batch.busy && !Backend.batch.auditRunning
                    tip: "Choose the export folder"
                    onClicked: Backend.batch.chooseAuditExports()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 3
                spacing: 26

                ToggleRow {
                    label: "OCR verification"
                    checked: Backend.batch.auditRunOcr
                    enabled: !Backend.batch.busy && !Backend.batch.auditRunning
                    onToggled: function(next) { Backend.batch.setAuditRunOcr(next) }
                }

                ToggleRow {
                    label: "Use saved blocked patterns"
                    checked: Backend.batch.auditUsePatterns
                    enabled: Backend.batch.auditRunOcr && !Backend.batch.busy
                              && !Backend.batch.auditRunning
                    onToggled: function(next) { Backend.batch.setAuditUsePatterns(next) }
                }

                Item { Layout.fillWidth: true }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 9

                ConcourseButton {
                    text: "RUN LOCAL AUDIT"
                    variant: "primary"
                    compact: true
                    enabled: !Backend.batch.busy && !Backend.batch.auditRunning
                             && Backend.batch.auditOriginals.length > 0
                             && Backend.batch.auditExports.length > 0
                    tip: "Audit every PNG in the selected export folder"
                    onClicked: Backend.batch.startAudit()
                }

                ConcourseButton {
                    text: "CANCEL"
                    compact: true
                    variant: "danger"
                    visible: Backend.batch.auditRunning
                    enabled: Backend.batch.canCancel
                    tip: "Stop queued audit work"
                    onClicked: Backend.batch.cancelAudit()
                }

                ConcourseButton {
                    text: "SAVE REPORT"
                    compact: true
                    visible: Backend.batch.auditHasRun
                             && Backend.batch.auditResults.length > 0
                             && !Backend.batch.auditRunning
                    tip: "Save the audit result as JSON"
                    onClicked: Backend.batch.saveAuditReport()
                }

                Item { Layout.fillWidth: true }

                Text {
                    Layout.maximumWidth: Math.round(frame.width * 0.45)
                    text: Backend.batch.auditSummary
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: Theme.steelLight
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.scaleFont(10)
                    font.letterSpacing: 0.7
                    visible: Backend.batch.auditSummary.length > 0
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                visible: Backend.batch.auditRunning

                RowLayout {
                    Layout.fillWidth: true

                    Text {
                        Layout.fillWidth: true
                        text: Backend.batch.progressText
                        color: Theme.steelLight
                        font.family: Theme.bodyFont
                        font.pixelSize: Theme.scaleFont(10)
                    }

                    Text {
                        text: Backend.batch.progressCurrent
                        color: Theme.mutedText
                        font.family: Theme.bodyFont
                        font.pixelSize: Theme.scaleFont(10)
                        elide: Text.ElideMiddle
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 4
                    radius: 1
                    color: Theme.inset

                    Rectangle {
                        width: parent.width * root.auditRatio
                        height: parent.height
                        radius: 1
                        color: Theme.amber
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 110

                ListView {
                    id: resultsList
                    objectName: "auditResults"
                    anchors.fill: parent
                    clip: true
                    spacing: 6
                    model: Backend.batch.auditResults
                    boundsBehavior: Flickable.StopAtBounds
                    activeFocusOnTab: true
                    Accessible.role: Accessible.List
                    Accessible.name: "Audit results"

                    delegate: Rectangle {
                        id: row
                        required property var modelData

                        width: resultsList.width - 8
                        height: resultBody.implicitHeight + 18
                        radius: Theme.radiusCard
                        color: Theme.fieldFace
                        border.width: 1
                        border.color: modelData.issue ? Theme.dangerBorder : Theme.hairline

                        ColumnLayout {
                            id: resultBody
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 9
                            spacing: 3

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: row.modelData.export
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                    color: Theme.white
                                    font.family: Theme.displayFont
                                    font.pixelSize: Theme.scaleFont(12)
                                    font.letterSpacing: 0.4
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    text: root.statusLabel(row.modelData)
                                    color: root.statusColor(row.modelData)
                                    font.family: Theme.displayFont
                                    font.pixelSize: Theme.scaleFont(9 * Theme.labelScale)
                                    font.letterSpacing: Theme.labelTracking
                                    font.weight: Font.DemiBold
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: row.modelData.issue !== null
                                text: row.modelData.issue || ""
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                color: Theme.dangerText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.detailText(row.modelData)
                                color: Theme.steelLight
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: root.ocrText(row.modelData).length > 0
                                text: root.ocrText(row.modelData)
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }

                Column {
                    anchors.centerIn: parent
                    width: frame.width - 180
                    spacing: 7
                    visible: !Backend.batch.auditHasRun && !Backend.batch.auditRunning

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 42
                        height: 2
                        color: Theme.amber
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "NO AUDIT YET"
                        color: Theme.white
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.scaleFont(17)
                        font.letterSpacing: 1.6
                        font.weight: Font.DemiBold
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "Choose the original folder and the folder with exported PNGs. The check covers missing logs, pixels outside the logged boxes, and wide masks."
                        color: Theme.steelLight
                        font.family: Theme.bodyFont
                        font.pixelSize: Theme.scaleFont(11)
                    }
                }

                Text {
                    anchors.centerIn: parent
                    width: frame.width - 180
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "No exported PNGs were found in this folder."
                    color: Theme.steelLight
                    font.family: Theme.bodyFont
                    font.pixelSize: Theme.scaleFont(11)
                    visible: Backend.batch.auditHasRun
                             && Backend.batch.auditResults.length === 0
                             && !Backend.batch.auditRunning
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: "Review candidates, not proof. OCR and saved patterns stay local."
                    color: Theme.mutedText
                    font.family: Theme.bodyFont
                    font.pixelSize: Theme.scaleFont(10)
                    wrapMode: Text.WordWrap
                }

                Text {
                    visible: Backend.batch.auditHasRun
                    text: Backend.batch.auditRunning ? "AUDITING LOCALLY" : "AUDIT COMPLETE"
                    color: Backend.batch.auditRunning ? Theme.amber : Theme.steelLight
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.scaleFont(9 * Theme.labelScale)
                    font.letterSpacing: Theme.labelTracking
                }
            }
        }
    }
}
