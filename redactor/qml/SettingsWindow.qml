import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls
import "Theme.js" as Theme
import Redactor 1.0

Window {
    id: settings
    property Window parentWindow: null
    width: 790
    height: 680
    minimumWidth: 700
    minimumHeight: 560
    modality: Qt.ApplicationModal
    flags: Qt.Dialog
    transientParent: parentWindow
    color: Theme.bg
    title: "Settings - Offline Screenshot Redactor"
    visible: false

    property string tab: "detection"
    property string errorText: ""
    property var selectedCategories: []
    property string sensitivityValue: "Focused"
    property int confidenceValue: 50
    property bool allTextValue: false
    property bool enhancedValue: false
    property bool colorValue: false
    property string engineValue: "Tesseract"
    property string patternValue: ""
    property string methodValue: "Pixelate"
    property string outputValue: ""
    property string templateValue: ""
    property bool includeLogValue: true
    property int parallelValue: 1

    function openSettings() {
        selectedCategories = Backend.categories.slice(0)
        sensitivityValue = Backend.sensitivity
        confidenceValue = Backend.confidence
        allTextValue = Backend.allText
        enhancedValue = Backend.enhancedOcr
        colorValue = Backend.colorOcr
        engineValue = Backend.ocrEngine
        patternValue = Backend.customPattern
        methodValue = Backend.redactionMethod
        outputValue = Backend.outputDirectory
        templateValue = Backend.filenameTemplate
        includeLogValue = Backend.includeLog
        parallelValue = Backend.parallelImages
        tab = "detection"
        errorText = ""
        engineCombo.currentIndex = Math.max(0, engineCombo.find(engineValue))
        sensitivityCombo.currentIndex = Math.max(0, sensitivityCombo.find(sensitivityValue))
        methodCombo.currentIndex = Math.max(0, methodCombo.find(methodValue))
        patternField.text = patternValue
        outputField.text = outputValue
        templateField.text = templateValue
        confidenceSpin.value = confidenceValue
        parallelSpin.value = parallelValue
        visible = true
        raise()
    }

    function tryApply() {
        var typedConfidence = parseInt(confidenceSpin.contentItem.text)
        if (!isNaN(typedConfidence)) {
            confidenceValue = Math.max(0, Math.min(100, typedConfidence))
        }
        var typedParallel = parseInt(parallelSpin.contentItem.text)
        if (!isNaN(typedParallel)) {
            parallelValue = Math.max(1, Math.min(Backend.parallelLimit, typedParallel))
        }
        var error = Backend.applySettings(
            sensitivityValue, confidenceValue, allTextValue, enhancedValue, colorValue,
            engineValue, patternValue, selectedCategories, methodValue,
            outputValue, templateValue, includeLogValue, parallelValue
        )
        if (error.length > 0) {
            errorText = error
            return false
        }
        errorText = ""
        return true
    }

    function closeSettings() {
        visible = false
    }

    onClosing: function(close) {
        close.accepted = false
        if (tryApply()) {
            visible = false
        }
    }

    Shortcut {
        sequence: "Escape"
        onActivated: settings.closeSettings()
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#121417" }
            GradientStop { position: 1.0; color: Theme.bg }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1

            Text {
                text: "SETTINGS"
                color: Theme.white
                font.family: Backend.displayFont
                font.pixelSize: 24
                font.letterSpacing: 2.4
                font.weight: Font.DemiBold
            }

            Text {
                text: "LOCAL DETECTION / REDACTION / OUTPUT"
                color: Theme.steelLight
                font.family: Backend.displayFont
                font.pixelSize: 9
                font.letterSpacing: 1.2
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            ColumnLayout {
                Layout.preferredWidth: 166
                Layout.minimumWidth: 166
                Layout.maximumWidth: 166
                Layout.fillWidth: false
                Layout.fillHeight: true
                spacing: 6

                RailTab {
                    Layout.fillWidth: true
                    text: "DETECTION"
                    active: settings.tab === "detection"
                    onClicked: settings.tab = "detection"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "REDACTION"
                    active: settings.tab === "redaction"
                    onClicked: settings.tab = "redaction"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "FOLDER OUTPUT"
                    active: settings.tab === "output"
                    onClicked: settings.tab = "output"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "DIAGNOSTICS"
                    active: settings.tab === "diagnostics"
                    onClicked: settings.tab = "diagnostics"
                }

                Item { Layout.fillHeight: true }

                Text {
                    Layout.fillWidth: true
                    text: "NO NETWORK CALLS"
                    color: Theme.steelMid
                    font.family: Backend.displayFont
                    font.pixelSize: 9
                    font.letterSpacing: 1.1
                }
            }

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 420
                Layout.preferredWidth: 560

                StackLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    currentIndex: settings.tab === "detection" ? 0
                                  : settings.tab === "redaction" ? 1
                                  : settings.tab === "output" ? 2 : 3

                    Flickable {
                        clip: true
                        contentWidth: width
                        contentHeight: detectionPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            background: Item {}
                            contentItem: Rectangle {
                                implicitWidth: 4
                                radius: 2
                                color: Theme.steelMid
                                opacity: 0.6
                            }
                        }

                        ColumnLayout {
                            id: detectionPage
                            width: parent.width
                            spacing: 10

                            FieldLabel { text: "OCR ENGINE" }

                            ConcourseComboBox {
                                id: engineCombo
                                Layout.fillWidth: true
                                model: Backend.engineNames
                                onActivated: settings.engineValue = currentText
                            }

                            FieldLabel { text: "SENSITIVITY" }

                            ConcourseComboBox {
                                id: sensitivityCombo
                                Layout.fillWidth: true
                                model: Backend.presetNames
                                onActivated: {
                                    settings.sensitivityValue = currentText
                                    if (currentText !== "Custom") {
                                        var preset = Backend.presetCategories[currentText]
                                        if (preset) {
                                            settings.selectedCategories = preset.slice(0)
                                        }
                                    }
                                }
                            }

                            FieldLabel { text: "MIN OCR CONFIDENCE (0-100)" }

                            ConcourseSpinBox {
                                id: confidenceSpin
                                Layout.preferredWidth: 130
                                from: 0
                                to: 100
                                onValueModified: settings.confidenceValue = value
                            }

                            FieldLabel { text: "PARALLEL IMAGE JOBS (1-" + Backend.parallelLimit + ")" }

                            ConcourseSpinBox {
                                id: parallelSpin
                                Layout.preferredWidth: 130
                                from: 1
                                to: Backend.parallelLimit
                                onValueModified: settings.parallelValue = value
                            }

                            HintText {
                                Layout.fillWidth: true
                                text: "Higher values process multiple images at once in folder scans, copying, matching, and export. "
                                      + "Local OCR can use significant CPU and memory. RapidOCR scans stay serialized."
                            }

                            ToggleRow {
                                Layout.fillWidth: true
                                label: "Enhanced OCR (slower, useful for screen photos)"
                                checked: settings.enhancedValue
                                onToggled: function(next) { settings.enhancedValue = next }
                            }

                            ToggleRow {
                                Layout.fillWidth: true
                                label: "Color-assisted OCR (slower, helps colored text)"
                                checked: settings.colorValue
                                onToggled: function(next) { settings.colorValue = next }
                            }

                            ToggleRow {
                                Layout.fillWidth: true
                                label: "Suggest all detected text (bypasses patterns)"
                                checked: settings.allTextValue
                                onToggled: function(next) { settings.allTextValue = next }
                            }

                            FieldLabel {
                                Layout.topMargin: 4
                                text: "DETECTION PATTERNS"
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: categoriesGrid.implicitHeight + 22
                                radius: 6
                                color: "#101214"
                                border.width: 1
                                border.color: "#2A2D31"

                                GridLayout {
                                    id: categoriesGrid
                                    anchors.fill: parent
                                    anchors.margins: 11
                                    columns: 2
                                    columnSpacing: 12
                                    rowSpacing: 3

                                    Repeater {
                                        model: Backend.categoryNames

                                        delegate: ToggleRow {
                                            required property string modelData
                                            Layout.fillWidth: true
                                            label: modelData
                                            checked: settings.selectedCategories.indexOf(modelData) >= 0
                                            onToggled: function(next) {
                                                var update = settings.selectedCategories.slice(0)
                                                var position = update.indexOf(modelData)
                                                if (next && position < 0) {
                                                    update.push(modelData)
                                                } else if (!next && position >= 0) {
                                                    update.splice(position, 1)
                                                }
                                                settings.selectedCategories = update
                                                settings.sensitivityValue = "Custom"
                                            }
                                        }
                                    }
                                }
                            }

                            FieldLabel {
                                Layout.topMargin: 4
                                text: "CUSTOM REGULAR EXPRESSION"
                            }

                            ConcourseTextField {
                                id: patternField
                                Layout.fillWidth: true
                                placeholderText: "Optional Python regular expression"
                                onTextEdited: settings.patternValue = text
                            }

                            HintText {
                                Layout.fillWidth: true
                                text: "Detection changes apply on the next scan. The custom pattern runs alongside the enabled categories."
                            }
                        }
                    }

                    Flickable {
                        clip: true
                        contentWidth: width
                        contentHeight: redactionPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: redactionPage
                            width: parent.width
                            spacing: 10

                            FieldLabel { text: "REDACTION METHOD" }

                            ConcourseComboBox {
                                id: methodCombo
                                Layout.fillWidth: true
                                model: Backend.methodNames
                                onActivated: settings.methodValue = currentText
                            }

                            Panel {
                                Layout.fillWidth: true
                                Layout.topMargin: 4
                                implicitHeight: 88
                                fillColor: "#101214"
                                inset: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 3

                                    Text {
                                        text: "PIXELATE"
                                        color: Theme.amber
                                        font.family: Backend.displayFont
                                        font.pixelSize: 10
                                        font.letterSpacing: 1
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Coarse mosaic blocks cover the selected pixels. Fast, but text can remain recognizable or recoverable."
                                        wrapMode: Text.WordWrap
                                        color: Theme.steelLight
                                        font.family: Backend.bodyFont
                                        font.pixelSize: 11
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                implicitHeight: 88
                                fillColor: "#101214"
                                inset: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 3

                                    Text {
                                        text: "SOLID BLACK"
                                        color: Theme.red
                                        font.family: Backend.displayFont
                                        font.pixelSize: 10
                                        font.letterSpacing: 1
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Opaque black removes image detail inside the selected boxes. Recommended for highly sensitive material."
                                        wrapMode: Text.WordWrap
                                        color: Theme.steelLight
                                        font.family: Backend.bodyFont
                                        font.pixelSize: 11
                                    }
                                }
                            }

                            HintText {
                                Layout.fillWidth: true
                                Layout.topMargin: 4
                                text: "The method applies across the folder and is remembered across restarts. Changing it returns images to review before export."
                            }
                        }
                    }

                    Flickable {
                        clip: true
                        contentWidth: width
                        contentHeight: outputPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: outputPage
                            width: parent.width
                            spacing: 8

                            FieldLabel { text: "OUTPUT FOLDER" }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 7

                                ConcourseTextField {
                                    id: outputField
                                    Layout.fillWidth: true
                                    placeholderText: "Source folder / redacted"
                                    onTextEdited: settings.outputValue = text
                                }

                                ConcourseButton {
                                    text: "BROWSE"
                                    compact: true
                                    onClicked: {
                                        var directory = Backend.chooseOutputFolder()
                                        if (directory.length > 0) {
                                            settings.outputValue = directory
                                            outputField.text = directory
                                        }
                                    }
                                }
                            }

                            HintText {
                                Layout.fillWidth: true
                                text: "Leave blank to save in the source folder's redacted subfolder."
                            }

                            FieldLabel {
                                Layout.topMargin: 6
                                text: "FILENAME TEMPLATE"
                            }

                            ConcourseTextField {
                                id: templateField
                                Layout.fillWidth: true
                                placeholderText: "{stem}_redacted"
                                onTextEdited: settings.templateValue = text
                            }

                            HintText {
                                Layout.fillWidth: true
                                text: "{stem} original name / {ext} original extension / {index} folder position. "
                                      + "Example: reviewed_{index:03d} becomes reviewed_001.png."
                            }

                            ToggleRow {
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                label: "Save a coordinate log with each PNG"
                                checked: settings.includeLogValue
                                onToggled: function(next) { settings.includeLogValue = next }
                            }
                        }
                    }

                    Flickable {
                        clip: true
                        contentWidth: width
                        contentHeight: diagnosticsPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: diagnosticsPage
                            width: parent.width
                            spacing: 10

                            FieldLabel { text: "LOCAL PERFORMANCE LOGS" }

                            Text {
                                Layout.fillWidth: true
                                text: "Each run records elapsed time, gaps between images, per-pass timings, counts, and error types. "
                                      + "Traces omit filenames, paths, OCR text, and the custom expression."
                                wrapMode: Text.WordWrap
                                color: Theme.steelLight
                                font.family: Backend.bodyFont
                                font.pixelSize: 12
                                lineHeight: 1.25
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 40
                                radius: 6
                                color: "#101214"
                                border.width: 1
                                border.color: "#2A2D31"

                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 11
                                    anchors.rightMargin: 11
                                    text: Backend.performanceLogsDirectory()
                                    elide: Text.ElideMiddle
                                    verticalAlignment: Text.AlignVCenter
                                    color: Theme.steelLight
                                    font.family: Backend.bodyFont
                                    font.pixelSize: 11
                                }
                            }

                            ConcourseButton {
                                text: "OPEN PERFORMANCE LOGS FOLDER"
                                compact: true
                                onClicked: Backend.openPerformanceLogs()
                            }

                            HintText {
                                Layout.fillWidth: true
                                Layout.topMargin: 8
                                text: "Coordinate logs still contain source filenames. Inspect them before sharing. "
                                      + "This application does not download or install OCR."
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 9

            Text {
                Layout.fillWidth: true
                text: settings.errorText
                visible: text.length > 0
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                color: Theme.red
                font.family: Backend.bodyFont
                font.pixelSize: 11
            }

            Item { Layout.fillWidth: true; visible: settings.errorText.length === 0 }

            ConcourseButton {
                text: "CANCEL"
                onClicked: settings.closeSettings()
            }

            ConcourseButton {
                text: "APPLY"
                variant: "primary"
                onClicked: {
                    if (settings.tryApply()) {
                        settings.closeSettings()
                    }
                }
            }
        }
    }
}
