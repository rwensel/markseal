import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls
import Redactor 1.0

Window {
    id: settings
    property Window parentWindow: null
    width: 790
    height: 680
    minimumWidth: 700
    minimumHeight: 600
    modality: Qt.ApplicationModal
    flags: Qt.Dialog
    transientParent: parentWindow
    color: Theme.bg
    title: "Settings - MarkSeal"
    visible: false

    property string tab: "engine"
    readonly property bool immediateTab: tab === "watched" || tab === "blocked"
    property string errorText: ""
    property bool showDiagnostics: false
    property var selectedCategories: []
    property string sensitivityValue: "Share a screenshot"
    property int confidenceValue: 50
    property bool allTextValue: false
    property bool enhancedValue: false
    property bool colorValue: false
    property string methodValue: "Pixelate"
    property string outputValue: ""
    property string templateValue: ""
    property bool includeLogValue: true
    property int parallelValue: 1

    function openSettings() {
        Backend.settings.clearThemePreview()
        selectedCategories = Backend.settings.categories.slice(0)
        sensitivityValue = Backend.settings.sensitivity
        confidenceValue = Backend.settings.confidence
        allTextValue = Backend.settings.allText
        enhancedValue = Backend.settings.enhancedOcr
        colorValue = Backend.settings.colorOcr
        methodValue = Backend.settings.redactionMethod
        outputValue = Backend.settings.outputDirectory
        templateValue = Backend.settings.filenameTemplate
        includeLogValue = Backend.settings.includeLog
        parallelValue = Backend.settings.parallelImages
        tab = "engine"
        showDiagnostics = false
        errorText = ""
        sensitivityCombo.currentIndex = Math.max(0, sensitivityCombo.find(sensitivityValue))
        methodCombo.currentIndex = Math.max(0, methodCombo.find(methodValue))
        outputField.text = outputValue
        templateField.text = templateValue
        confidenceSpin.value = confidenceValue
        parallelSpin.value = parallelValue
        visible = true
        raise()
        requestActivate()
    }

    function tryApply() {
        var typedConfidence = parseInt(confidenceSpin.contentItem.text)
        if (!isNaN(typedConfidence)) {
            confidenceValue = Math.max(0, Math.min(100, typedConfidence))
        }
        var typedParallel = parseInt(parallelSpin.contentItem.text)
        if (!isNaN(typedParallel)) {
            parallelValue = Math.max(1, Math.min(Backend.settings.parallelLimit, typedParallel))
        }
        var error = Backend.settings.applySettings(
            sensitivityValue, confidenceValue, allTextValue, enhancedValue, colorValue,
            selectedCategories, methodValue,
            outputValue, templateValue, includeLogValue, parallelValue,
            Backend.settings.previewTheme
        )
        if (error.length > 0) {
            errorText = error
            return false
        }
        errorText = ""
        return true
    }

    function closeSettings() {
        Backend.settings.clearThemePreview()
        visible = false
    }

    onClosing: function(close) {
        close.accepted = false
        closeSettings()
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.settingsTop }
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
                font.family: Theme.displayFont
                font.pixelSize: Theme.scaleFont(24)
                font.letterSpacing: 2.4
                font.weight: Font.DemiBold
            }

            Text {
                text: "LOCAL DETECTION / REDACTION / OUTPUT"
                color: Theme.steelLight
                font.family: Theme.displayFont
                font.pixelSize: Theme.scaleFont(9)
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
                    text: "OCR"
                    active: settings.tab === "engine"
                    onClicked: settings.tab = "engine"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "PATTERNS"
                    active: settings.tab === "patterns"
                    onClicked: settings.tab = "patterns"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "REDACTION"
                    active: settings.tab === "redaction"
                    onClicked: settings.tab = "redaction"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "OUTPUT"
                    active: settings.tab === "output"
                    onClicked: settings.tab = "output"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "WATCHED FOLDERS"
                    active: settings.tab === "watched"
                    onClicked: settings.tab = "watched"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "BLOCKED PATTERNS"
                    active: settings.tab === "blocked"
                    onClicked: settings.tab = "blocked"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "APPEARANCE"
                    active: settings.tab === "appearance"
                    onClicked: settings.tab = "appearance"
                }

                RailTab {
                    Layout.fillWidth: true
                    text: "UPDATES"
                    active: settings.tab === "updates"
                    onClicked: settings.tab = "updates"
                }

                Item { Layout.fillHeight: true }

                Text {
                    Layout.fillWidth: true
                    text: "NO NETWORK UNLESS UPDATES ARE ON"
                    wrapMode: Text.WordWrap
                    color: Theme.steelMid
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.scaleFont(9)
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
                    currentIndex: settings.tab === "engine" ? 0
                                  : settings.tab === "patterns" ? 1
                                  : settings.tab === "redaction" ? 2
                                  : settings.tab === "output" ? 3
                                  : settings.tab === "watched" ? 4
                                  : settings.tab === "blocked" ? 5
                                  : settings.tab === "appearance" ? 6 : 7

                    Flickable {
                        id: engineFlick
                        clip: true
                        contentWidth: width
                        contentHeight: enginePage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            visible: engineFlick.contentHeight > engineFlick.height
                            background: Item {}
                            contentItem: Rectangle {
                                implicitWidth: 4
                                radius: 2
                                color: Theme.steelMid
                                opacity: 0.6
                            }
                        }

                        ColumnLayout {
                            id: enginePage
                            width: parent.width
                            spacing: 10

                            FieldLabel { text: "MIN OCR CONFIDENCE (0-100)" }

                            ConcourseSpinBox {
                                id: confidenceSpin
                                Layout.preferredWidth: 130
                                from: 0
                                to: 100
                                onValueModified: settings.confidenceValue = value
                            }

                            FieldLabel { text: "PARALLEL IMAGE JOBS (1-" + Backend.settings.parallelLimit + ")" }

                            ConcourseSpinBox {
                                id: parallelSpin
                                Layout.preferredWidth: 130
                                from: 1
                                to: Backend.settings.parallelLimit
                                onValueModified: settings.parallelValue = value
                            }

                            HintText {
                                Layout.fillWidth: true
                                text: "Higher values process multiple images at once in folder scans, copying, matching, and export. "
                                      + "Local OCR can use significant CPU and memory. RapidOCR keeps a local engine per active worker."
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

                            HintText {
                                Layout.fillWidth: true
                                Layout.topMargin: 4
                                text: "Detection changes apply on the next scan."
                            }
                        }
                    }

                    Flickable {
                        id: patternsFlick
                        clip: true
                        contentWidth: width
                        contentHeight: patternsPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            visible: patternsFlick.contentHeight > patternsFlick.height
                            background: Item {}
                            contentItem: Rectangle {
                                implicitWidth: 4
                                radius: 2
                                color: Theme.steelMid
                                opacity: 0.6
                            }
                        }

                        ColumnLayout {
                            id: patternsPage
                            width: parent.width
                            spacing: 10

                            FieldLabel { text: "DETECTION PRESET" }

                            ConcourseComboBox {
                                id: sensitivityCombo
                                Layout.fillWidth: true
                                model: Backend.settings.presetNames
                                onActivated: {
                                    settings.sensitivityValue = currentText
                                    if (currentText !== "Custom") {
                                        var preset = Backend.settings.presetCategories[currentText]
                                        if (preset) {
                                            settings.selectedCategories = preset.slice(0)
                                        }
                                    }
                                }

                                Connections {
                                    target: settings
                                    function onSensitivityValueChanged() {
                                        sensitivityCombo.currentIndex = Math.max(
                                            0, sensitivityCombo.find(settings.sensitivityValue))
                                    }
                                }
                            }

                            HintText {
                                Layout.fillWidth: true
                                text: settings.sensitivityValue === "Custom"
                                      ? "Custom uses the categories you selected below. "
                                        + "Toggling a category switches the preset to Custom."
                                      : (Backend.settings.presetDescriptions[settings.sensitivityValue] || "")
                            }

                            FieldLabel {
                                Layout.topMargin: 4
                                text: "DETECTION PATTERNS"
                            }

                            HintText {
                                Layout.fillWidth: true
                                text: "Personal names and addresses use a bundled local model. "
                                      + "Dates of birth and license/ID numbers are read from "
                                      + "field labels."
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: categoriesGrid.implicitHeight + 22
                                radius: 6
                                color: Theme.fieldFace
                                border.width: 1
                                border.color: Theme.fieldBorder

                                GridLayout {
                                    id: categoriesGrid
                                    anchors.fill: parent
                                    anchors.margins: 11
                                    columns: 2
                                    columnSpacing: 12
                                    rowSpacing: 3

                                    Repeater {
                                        model: Backend.settings.categoryNames

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

                            HintText {
                                Layout.fillWidth: true
                                Layout.topMargin: 4
                                text: "Custom expressions are managed under Blocked patterns."
                            }
                        }
                    }

                    Flickable {
                        id: redactionFlick
                        clip: true
                        contentWidth: width
                        contentHeight: redactionPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            visible: redactionFlick.contentHeight > redactionFlick.height
                            background: Item {}
                            contentItem: Rectangle {
                                implicitWidth: 4
                                radius: 2
                                color: Theme.steelMid
                                opacity: 0.6
                            }
                        }

                        ColumnLayout {
                            id: redactionPage
                            width: parent.width
                            spacing: 10

                            FieldLabel { text: "REDACTION METHOD" }

                            ConcourseComboBox {
                                id: methodCombo
                                Layout.fillWidth: true
                                model: Backend.settings.methodNames
                                onActivated: settings.methodValue = currentText
                            }

                            Panel {
                                Layout.fillWidth: true
                                Layout.topMargin: 4
                                implicitHeight: 88
                                fillColor: Theme.fieldFace
                                inset: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 3

                                    Text {
                                        text: "PIXELATE"
                                        color: Theme.amber
                                        font.family: Theme.displayFont
                                        font.pixelSize: Theme.scaleFont(10)
                                        font.letterSpacing: 1
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Coarse mosaic blocks cover the selected pixels. Fast, but text can remain recognizable or recoverable."
                                        wrapMode: Text.WordWrap
                                        color: Theme.steelLight
                                        font.family: Theme.bodyFont
                                        font.pixelSize: Theme.scaleFont(11)
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                implicitHeight: 88
                                fillColor: Theme.fieldFace
                                inset: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 3

                                    Text {
                                        text: "SOLID BLACK"
                                        color: Theme.dangerText
                                        font.family: Theme.displayFont
                                        font.pixelSize: Theme.scaleFont(10)
                                        font.letterSpacing: 1
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Opaque black removes image detail inside the selected boxes. Recommended for highly sensitive material."
                                        wrapMode: Text.WordWrap
                                        color: Theme.steelLight
                                        font.family: Theme.bodyFont
                                        font.pixelSize: Theme.scaleFont(11)
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                implicitHeight: 88
                                fillColor: Theme.fieldFace
                                inset: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 3

                                    Text {
                                        text: "BLUR"
                                        color: Theme.amber
                                        font.family: Theme.displayFont
                                        font.pixelSize: Theme.scaleFont(10)
                                        font.letterSpacing: 1
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Gaussian blur softens the selected area. Fast, but blurred text can sometimes be recovered — prefer solid black for highly sensitive material."
                                        wrapMode: Text.WordWrap
                                        color: Theme.steelLight
                                        font.family: Theme.bodyFont
                                        font.pixelSize: Theme.scaleFont(11)
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                implicitHeight: 88
                                fillColor: Theme.fieldFace
                                inset: true

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 3

                                    Text {
                                        text: "ERASE"
                                        color: Theme.dangerText
                                        font.family: Theme.displayFont
                                        font.pixelSize: Theme.scaleFont(10)
                                        font.letterSpacing: 1
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Replaces the selected area with nearby background pixels. Looks seamless; check the result before sharing."
                                        wrapMode: Text.WordWrap
                                        color: Theme.steelLight
                                        font.family: Theme.bodyFont
                                        font.pixelSize: Theme.scaleFont(11)
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
                        id: outputFlick
                        clip: true
                        contentWidth: width
                        contentHeight: outputPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            visible: outputFlick.contentHeight > outputFlick.height
                            background: Item {}
                            contentItem: Rectangle {
                                implicitWidth: 4
                                radius: 2
                                color: Theme.steelMid
                                opacity: 0.6
                            }
                        }

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
                                        var directory = Backend.settings.chooseOutputFolder()
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

                            ConcourseButton {
                                Layout.topMargin: 8
                                text: settings.showDiagnostics ? "HIDE PERFORMANCE LOGS" : "PERFORMANCE LOGS"
                                variant: "secondary"
                                compact: true
                                tip: "Show the local timing logs used for troubleshooting"
                                onClicked: settings.showDiagnostics = !settings.showDiagnostics
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: settings.showDiagnostics
                                spacing: 8

                                Text {
                                    Layout.fillWidth: true
                                    text: "Each run records elapsed time, gaps between images, per-pass timings, counts, and error types. "
                                          + "Traces omit filenames, paths, OCR text, and blocked-pattern expressions."
                                    wrapMode: Text.WordWrap
                                    color: Theme.steelLight
                                    font.family: Theme.bodyFont
                                    font.pixelSize: Theme.scaleFont(11)
                                    lineHeight: 1.2
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: 40
                                    radius: 6
                                    color: Theme.fieldFace
                                    border.width: 1
                                    border.color: Theme.fieldBorder

                                    Text {
                                        anchors.fill: parent
                                        anchors.leftMargin: 11
                                        anchors.rightMargin: 11
                                        text: Backend.settings.performanceLogsDirectory()
                                        elide: Text.ElideMiddle
                                        verticalAlignment: Text.AlignVCenter
                                        color: Theme.steelLight
                                        font.family: Theme.bodyFont
                                        font.pixelSize: Theme.scaleFont(11)
                                    }
                                }

                                ConcourseButton {
                                    text: "OPEN PERFORMANCE LOGS FOLDER"
                                    compact: true
                                    onClicked: Backend.settings.openPerformanceLogs()
                                }

                                HintText {
                                    Layout.fillWidth: true
                                    text: "Coordinate logs still contain source filenames. Inspect them before sharing. "
                                          + "This application does not download or install OCR."
                                }
                            }
                        }
                    }

                    Flickable {
                        id: watchedFlick
                        clip: true
                        contentWidth: width
                        contentHeight: watchedPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            visible: watchedFlick.contentHeight > watchedFlick.height
                            background: Item {}
                            contentItem: Rectangle {
                                implicitWidth: 4
                                radius: 2
                                color: Theme.steelMid
                                opacity: 0.6
                            }
                        }

                        ColumnLayout {
                            id: watchedPage
                            width: parent.width
                            spacing: 10

                            Text {
                                Layout.fillWidth: true
                                text: "MarkSeal watches these folders while it runs. Automatic watches "
                                      + "redact and export new images without review; every file stays "
                                      + "in the inbox with its coordinate log. Include subfolders to cover "
                                      + "a tree; images already there are recorded, not processed."
                                wrapMode: Text.WordWrap
                                color: Theme.steelLight
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(12)
                                lineHeight: 1.25
                            }

                            Text {
                                Layout.fillWidth: true
                                text: "CHANGES ON THIS PAGE SAVE IMMEDIATELY. CLOSE WHEN DONE."
                                wrapMode: Text.WordWrap
                                color: Theme.amber
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.scaleFont(9)
                                font.letterSpacing: 0.8
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 9

                                ConcourseButton {
                                    text: "ADD FOLDER"
                                    variant: "primary"
                                    onClicked: Backend.watches.chooseFolder()
                                }

                                Item { Layout.fillWidth: true }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: Backend.watches.watchRows.length === 0
                                text: "No watched folders. Add a folder to collect screenshots here."
                                wrapMode: Text.WordWrap
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(11)
                            }

                            Repeater {
                                model: Backend.watches.watchRows

                                delegate: Rectangle {
                                    required property var modelData

                                    Layout.fillWidth: true
                                    implicitHeight: watchBody.implicitHeight + 20
                                    radius: Theme.radiusCard
                                    color: Theme.fieldFace
                                    border.width: 1
                                    border.color: Theme.hairline

                                    ColumnLayout {
                                        id: watchBody
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 10
                                        spacing: 4

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8

                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.name
                                                textFormat: Text.PlainText
                                                elide: Text.ElideRight
                                                color: Theme.white
                                                font.family: Theme.displayFont
                                                font.pixelSize: Theme.scaleFont(12)
                                                font.letterSpacing: 0.4
                                                font.weight: Font.DemiBold
                                            }

                                            ConcourseComboBox {
                                                Layout.preferredWidth: 130
                                                model: ["MANUAL", "AUTO"]
                                                currentIndex: modelData.policy === "AUTO" ? 1 : 0
                                                onActivated: Backend.watches.setPolicy(
                                                    modelData.path, currentText.toLowerCase())
                                            }

                                            ConcourseButton {
                                                text: "REMOVE"
                                                compact: true
                                                variant: "danger"
                                                tip: "Stop watching this folder"
                                                onClicked: Backend.watches.removeWatch(
                                                    modelData.path)
                                            }
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.path
                                            textFormat: Text.PlainText
                                            elide: Text.ElideMiddle
                                            color: Theme.mutedText
                                            font.family: Theme.bodyFont
                                            font.pixelSize: Theme.scaleFont(10)
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 6

                                            Text {
                                                text: "OUTPUT"
                                                color: Theme.steelLight
                                                font.family: Theme.displayFont
                                                font.pixelSize: Theme.scaleFont(9)
                                                font.letterSpacing: 1.1
                                            }

                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.output
                                                textFormat: Text.PlainText
                                                elide: Text.ElideMiddle
                                                color: Theme.steelLight
                                                font.family: Theme.bodyFont
                                                font.pixelSize: Theme.scaleFont(10)
                                            }
                                        }

                                        ToggleRow {
                                            Layout.fillWidth: true
                                            label: "Include subfolders"
                                            checked: modelData.recursive
                                            onToggled: function(next) {
                                                Backend.watches.setRecursive(
                                                    modelData.path, next)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Flickable {
                        id: blockedFlick
                        clip: true
                        contentWidth: width
                        contentHeight: blockedPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            visible: blockedFlick.contentHeight > blockedFlick.height
                            background: Item {}
                            contentItem: Rectangle {
                                implicitWidth: 4
                                radius: 2
                                color: Theme.steelMid
                                opacity: 0.6
                            }
                        }

                        ColumnLayout {
                            id: blockedPage
                            width: parent.width
                            spacing: 10

                            FieldLabel { text: "LEARN A BLOCKED PATTERN" }

                            Text {
                                Layout.fillWidth: true
                                text: "Open an image, then select a scan area to read its text. "
                                      + "The app generates a regular expression with fixed-text or detected value-type matching for you to review and save."
                                wrapMode: Text.WordWrap
                                color: Theme.steelLight
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(12)
                                lineHeight: 1.25
                            }

                            Text {
                                Layout.fillWidth: true
                                text: "CHANGES ON THIS PAGE SAVE IMMEDIATELY. CLOSE WHEN DONE."
                                wrapMode: Text.WordWrap
                                color: Theme.amber
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.scaleFont(9)
                                font.letterSpacing: 0.8
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 9

                                ConcourseButton {
                                    text: "LEARN FROM SCAN AREA"
                                    variant: "primary"
                                    enabled: Backend.review.hasImage && !Backend.batch.busy
                                    onClicked: {
                                        if (settings.tryApply()) {
                                            settings.visible = false
                                            Backend.review.beginLearnPattern()
                                        }
                                    }
                                }

                                ConcourseButton {
                                    text: "ADD PATTERN"
                                    onClicked: Backend.settings.addBlockedPatternManually()
                                }

                                Item { Layout.fillWidth: true }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: Backend.review.hasImage
                                      ? "The settings window closes; drag around the text in the viewer. Manual patterns can be added any time."
                                      : "Open an image to learn from a scan area, or add a pattern manually."
                                wrapMode: Text.WordWrap
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }

                            FieldLabel {
                                Layout.topMargin: 6
                                text: "BLOCKED PATTERNS"
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: Backend.settings.blockedPatterns.length === 0
                                text: "No blocked patterns yet. Learn one from a scan area or add an expression manually."
                                wrapMode: Text.WordWrap
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(11)
                            }

                            Repeater {
                                model: Backend.settings.blockedPatterns

                                delegate: Rectangle {
                                    required property var modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    implicitHeight: card.implicitHeight + 20
                                    radius: 6
                                    color: Theme.fieldFace
                                    border.width: 1
                                    border.color: modelData.enabled ? Theme.buttonBorder : Theme.hairline
                                    opacity: modelData.enabled ? 1 : 0.72

                                    ColumnLayout {
                                        id: card
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 10
                                        spacing: 5

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8

                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.text.length > 0
                                                      ? modelData.text : "Manual pattern"
                                                textFormat: Text.PlainText
                                                elide: Text.ElideRight
                                                color: Theme.white
                                                font.family: Theme.bodyFont
                                                font.pixelSize: Theme.scaleFont(11)
                                                font.weight: Font.DemiBold
                                            }

                                            ToggleRow {
                                                label: "ENABLED"
                                                checked: modelData.enabled
                                                onToggled: function(next) {
                                                    Backend.settings.setBlockedPatternEnabled(index, next)
                                                }
                                            }

                                            ConcourseButton {
                                                text: "EDIT"
                                                compact: true
                                                onClicked: Backend.settings.renameBlockedPattern(index)
                                            }

                                            ConcourseButton {
                                                text: "REMOVE"
                                                compact: true
                                                variant: "danger"
                                                onClicked: Backend.settings.removeBlockedPattern(index)
                                            }
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.pattern
                                            textFormat: Text.PlainText
                                            wrapMode: Text.WrapAnywhere
                                            color: Theme.steelLight
                                            font.family: Theme.bodyFont
                                            font.pixelSize: Theme.scaleFont(10)
                                        }
                                    }
                                }
                            }

                            HintText {
                                Layout.fillWidth: true
                                Layout.topMargin: 4
                                text: "Patterns are matched case-insensitively in addition to the selected detection categories. "
                                      + "Disable one to keep it without blocking it."
                            }
                        }
                    }

                    Flickable {
                        id: appearanceFlick
                        clip: true
                        contentWidth: width
                        contentHeight: appearancePage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: appearancePage
                            width: appearanceFlick.width
                            spacing: 12

                            FieldLabel {
                                text: "APPEARANCE"
                            }

                            Text {
                                Layout.fillWidth: true
                                text: "Pick a world for the whole shell. The window updates as you click; "
                                      + "Apply keeps it, Cancel or Escape restores the saved theme."
                                wrapMode: Text.WordWrap
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(11)
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: Backend.settings.systemHighContrast
                                text: "WINDOWS HIGH CONTRAST IS ON. THE SYSTEM PALETTE OVERRIDES THESE THEME CHOICES."
                                wrapMode: Text.WordWrap
                                color: Theme.amber
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.scaleFont(9)
                                font.letterSpacing: 0.8
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                visible: !Backend.settings.systemHighContrast
                                columns: 2
                                rowSpacing: 10
                                columnSpacing: 10

                                Repeater {
                                    model: Backend.settings.themeChoices

                                    ThemeCard {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        themeId: modelData.id
                                        name: modelData.name
                                        tagline: modelData.tagline
                                        swatches: modelData.swatches
                                        selected: modelData.id === Backend.settings.previewTheme
                                        onClicked: Backend.settings.previewThemeById(modelData.id)
                                    }
                                }
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    Flickable {
                        id: updatesFlick
                        clip: true
                        contentWidth: width
                        contentHeight: updatesPage.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ColumnLayout {
                            id: updatesPage
                            width: updatesFlick.width
                            spacing: 10

                            FieldLabel { text: "BUILD" }

                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 66
                                radius: Theme.radiusCard
                                color: Theme.panelRaised
                                border.width: 1
                                border.color: Theme.hairline

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    spacing: 16

                                    ColumnLayout {
                                        spacing: 2

                                        Text {
                                            text: "MARKSEAL"
                                            color: Theme.steelLight
                                            font.family: Theme.displayFont
                                            font.pixelSize: Theme.scaleFont(9)
                                            font.letterSpacing: 1.2
                                        }

                                        Text {
                                            text: "Version " + Backend.updates.currentVersion
                                                  + (Backend.settings.betaChannel ? "  ·  Beta" : "")
                                            color: Theme.white
                                            font.family: Theme.displayFont
                                            font.pixelSize: Theme.scaleFont(15)
                                            font.letterSpacing: 0.8
                                        }
                                    }

                                    Item { Layout.fillWidth: true }

                                    ColumnLayout {
                                        spacing: 2

                                        Text {
                                            text: "PLATFORM"
                                            color: Theme.steelLight
                                            font.family: Theme.displayFont
                                            font.pixelSize: Theme.scaleFont(9)
                                            font.letterSpacing: 1.2
                                        }

                                        Text {
                                            text: Backend.updates.platform
                                            color: Theme.white
                                            font.family: Theme.bodyFont
                                            font.pixelSize: Theme.scaleFont(12)
                                        }
                                    }
                                }
                            }

                            ConcourseButton {
                                Layout.preferredHeight: 30
                                text: "THIRD-PARTY LICENSES"
                                compact: true
                                onClicked: licensesPanel.visible = true
                            }

                            FieldLabel { text: "UPDATES" }

                            Text {
                                Layout.fillWidth: true
                                text: "Off by default. When enabled, the app fetches a public release manifest and shows the notes. "
                                      + "It sends no data about you or your screenshots."
                                wrapMode: Text.WordWrap
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(11)
                            }

                            ToggleRow {
                                Layout.fillWidth: true
                                label: "Check for updates"
                                checked: Backend.settings.checkForUpdates
                                onToggled: function(next) { Backend.settings.setCheckForUpdates(next) }
                            }

                            ToggleRow {
                                Layout.fillWidth: true
                                label: "Download updates automatically"
                                checked: Backend.settings.downloadAutomatically
                                onToggled: function(next) { Backend.settings.setDownloadAutomatically(next) }
                            }

                            ToggleRow {
                                Layout.fillWidth: true
                                label: "Beta channel"
                                checked: Backend.settings.betaChannel
                                onToggled: function(next) { Backend.settings.setBetaChannel(next) }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: "Beta builds are pre-release and may be less stable. "
                                      + "Switching back to stable will not downgrade until a stable release catches up."
                                wrapMode: Text.WordWrap
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(11)
                            }

                            ConcourseButton {
                                Layout.preferredHeight: 32
                                text: "CHECK NOW"
                                compact: true
                                enabled: Backend.settings.checkForUpdates && !Backend.updates.busy
                                onClicked: Backend.updates.check()
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: !Backend.settings.checkForUpdates
                                text: "Turn on Check for updates to run a manual check."
                                wrapMode: Text.WordWrap
                                color: Theme.mutedText
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: Backend.updates.status.length > 0
                                text: Backend.updates.status
                                wrapMode: Text.WordWrap
                                color: Theme.steelLight
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }

                            Item { Layout.fillHeight: true }
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
                color: Theme.dangerText
                font.family: Theme.bodyFont
                font.pixelSize: Theme.scaleFont(11)
            }

            Item { Layout.fillWidth: true; visible: settings.errorText.length === 0 }

            ConcourseButton {
                text: settings.immediateTab ? "CLOSE" : "CANCEL"
                onClicked: settings.closeSettings()
            }

            ConcourseButton {
                text: "APPLY"
                visible: !settings.immediateTab
                variant: "primary"
                onClicked: {
                    if (settings.tryApply()) {
                        settings.closeSettings()
                    }
                }
            }
        }
    }

    Rectangle {
        id: licensesPanel
            objectName: "licensesPanel"
            anchors.fill: parent
            visible: false
            color: Qt.rgba(0.04, 0.04, 0.05, 0.72)
            z: 100

            MouseArea {
                anchors.fill: parent
                onClicked: licensesPanel.visible = false
            }

            Rectangle {
                anchors.centerIn: parent
                width: Math.min(parent.width - 80, 720)
                height: parent.height - 100
                radius: Theme.radiusPanel
                color: Theme.panelRaised
                border.width: 1
                border.color: Theme.hairline

                MouseArea { anchors.fill: parent }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text: "THIRD-PARTY LICENSES"
                            color: Theme.white
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.scaleFont(11)
                            font.letterSpacing: 1.0
                        }

                        Item { Layout.fillWidth: true }

                        ConcourseButton {
                            text: "CLOSE"
                            compact: true
                            onClicked: licensesPanel.visible = false
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Flickable {
                            id: licensesView
                            anchors.fill: parent
                            clip: true
                            contentWidth: width
                            contentHeight: licensesText.implicitHeight

                            Text {
                                id: licensesText
                                width: licensesView.width - 8
                                text: Backend.settings.thirdPartyNotices
                                wrapMode: Text.WordWrap
                                color: Theme.steelLight
                                font.family: Theme.bodyFont
                                font.pixelSize: Theme.scaleFont(10)
                            }
                        }

                        Rectangle {
                            visible: licensesView.contentHeight > licensesView.height
                            width: 3
                            height: Math.max(24, licensesView.visibleArea.heightRatio * licensesView.height)
                            radius: 1.5
                            color: Theme.steelMid
                            opacity: 0.7
                            x: licensesView.width - 5
                            y: licensesView.visibleArea.yPosition * licensesView.height
                        }
                    }

                    ConcourseButton {
                        Layout.preferredHeight: 30
                        text: "OPEN FULL NOTICES"
                        compact: true
                        onClicked: Backend.settings.openThirdPartyNotices()
                    }
                }
            }
        }
}
