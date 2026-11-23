import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import Redactor 1.0

Item {
    id: viewer
    property int hoveredBox: -1
    property int keyboardBox: -1
    readonly property string captureTitle: Backend.captureMode === "area" ? "SCAN AREA"
                                          : Backend.captureMode === "anchor" ? "ANCHOR MATCH"
                                          : Backend.captureMode === "learn" ? "LEARN PATTERN" : ""
    readonly property string captureInstruction: Backend.captureMode === "area"
                                                 ? "Drag a tight box around the text."
                                                 : Backend.captureMode === "anchor"
                                                   ? "Drag around a stable cue near the boxes."
                                                   : Backend.captureMode === "learn"
                                                     ? "Drag around the text to block."
                                                     : ""

    Connections {
        target: Backend
        function onImageChanged() { viewer.hoveredBox = -1; viewer.keyboardBox = -1 }
        function onReviewChanged() {
            if (viewer.keyboardBox >= Backend.totalBoxes)
                viewer.keyboardBox = Backend.totalBoxes - 1
        }
    }

    function stepBox(delta) {
        if (Backend.totalBoxes === 0)
            return
        if (keyboardBox < 0)
            keyboardBox = 0
        else
            keyboardBox = (keyboardBox + delta + Backend.totalBoxes) % Backend.totalBoxes
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.shellTop }
            GradientStop { position: 1.0; color: Theme.shellBottom }
        }
    }

    RowLayout {
        id: caption
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 22
        anchors.rightMargin: 24
        anchors.topMargin: 15
        height: 26
        spacing: 10
        visible: Backend.hasImage

        Text {
            Layout.fillWidth: true
            text: Backend.imageName
            elide: Text.ElideMiddle
            color: Theme.white
            font.family: Theme.bodyFont
            font.pixelSize: 11
        }

        Text {
            text: Backend.imageSizeText
            color: Theme.steelLight
            font.family: Theme.displayFont
            font.pixelSize: 9
            font.letterSpacing: 0.7
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: Theme.hairline
        }

        Text {
            text: "METHOD"
            color: Theme.mutedText
            font.family: Theme.displayFont
            font.pixelSize: 9
            font.letterSpacing: 0.8
        }

        MethodToggle {
            Layout.preferredHeight: 26
            method: Backend.redactionMethod
            enabled: !Backend.busy
            onSelected: function(method) {
                Backend.setRedactionMethod(method)
            }
        }

        ConcourseButton {
            Layout.preferredHeight: 26
            text: "RULE TAGS"
            compact: true
            variant: Backend.showRules ? "primary" : "secondary"
            tip: "Show which rule flagged each box"
            onClicked: Backend.setShowRules(!Backend.showRules)
        }

        Text {
            id: zoomText
            text: Math.round(Backend.viewScale * 100) + "%"
            color: Theme.white
            font.family: Theme.displayFont
            font.pixelSize: 10
            font.letterSpacing: 0.6
            Accessible.role: Accessible.StaticText
            Accessible.name: "Display scale " + text
            ToolTip.visible: zoomPointer.containsMouse
            ToolTip.delay: 500
            ToolTip.timeout: 5000
            ToolTip.text: "Scroll or Ctrl+= / Ctrl+- to zoom. Right-drag or Shift+arrows to pan. Ctrl+0 fits."

            MouseArea {
                id: zoomPointer
                anchors.fill: parent
                anchors.margins: -4
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: Theme.hairline
            visible: Backend.confirmed
        }

        ConcourseButton {
            Layout.preferredHeight: 26
            text: "REVISE"
            compact: true
            visible: Backend.confirmed
            tip: "Return to editing the boxes"
            onClicked: Backend.editBoxes()
        }

        ConcourseButton {
            Layout.preferredHeight: 26
            text: "COPY IMAGE"
            compact: true
            visible: Backend.confirmed
            tip: "Copy the redacted image to the clipboard (Ctrl+C)"
            enabled: !Backend.busy
            onClicked: Backend.copyRedacted()
        }
    }

    Item {
        id: frame
        anchors.fill: parent
        anchors.margins: 20
        anchors.topMargin: Backend.hasImage ? 54 : 20

        Rectangle {
            id: cardBackground
            anchors.fill: parent
            radius: 6
            color: Theme.inset
            border.width: 1
            border.color: Theme.shadow
        }

        MultiEffect {
            anchors.fill: cardBackground
            source: cardBackground
            shadowEnabled: true
            shadowColor: Theme.shadow
            shadowOpacity: 0.6
            shadowBlur: 0.85
            shadowVerticalOffset: 9
        }

        Rectangle {
            anchors.fill: parent
            radius: 6
            color: "transparent"
            border.width: 1
            border.color: Theme.buttonBorder
            opacity: 0.45
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 2
            height: 1
            color: Theme.highlight
            opacity: 0.06
        }

        Item {
            id: stage
            objectName: "stage"
            anchors.fill: parent
            anchors.margins: 6
            clip: true
            activeFocusOnTab: true
            Accessible.role: Accessible.Pane
            Accessible.name: "Screenshot review area"
            Accessible.description: "Arrow keys move between boxes, Space includes or excludes, Delete removes, Shift with arrows pans, Ctrl+Enter confirms."

            onWidthChanged: Backend.setViewSize(width, height)
            onHeightChanged: Backend.setViewSize(width, height)
            Component.onCompleted: Backend.setViewSize(width, height)
            onActiveFocusChanged: {
                if (activeFocus && keyboardBox < 0 && Backend.totalBoxes > 0)
                    keyboardBox = 0
            }

            Keys.onLeftPressed: function(event) {
                if (event.modifiers & Qt.ShiftModifier)
                    Backend.panStep(60, 0)
                else
                    stepBox(-1)
            }
            Keys.onUpPressed: function(event) {
                if (event.modifiers & Qt.ShiftModifier)
                    Backend.panStep(0, 60)
                else
                    stepBox(-1)
            }
            Keys.onRightPressed: function(event) {
                if (event.modifiers & Qt.ShiftModifier)
                    Backend.panStep(-60, 0)
                else
                    stepBox(1)
            }
            Keys.onDownPressed: function(event) {
                if (event.modifiers & Qt.ShiftModifier)
                    Backend.panStep(0, -60)
                else
                    stepBox(1)
            }
            Keys.onSpacePressed: {
                if (keyboardBox >= 0) {
                    Backend.toggleBox(keyboardBox)
                    event.accepted = true
                }
            }
            Keys.onDeletePressed: {
                if (keyboardBox >= 0) {
                    var removed = keyboardBox
                    Backend.removeBox(removed)
                    viewer.keyboardBox = Math.min(removed, Backend.totalBoxes - 1)
                    event.accepted = true
                }
            }

            Image {
                id: screenshot
                z: 0
                visible: Backend.hasImage
                x: Backend.viewOffsetX
                y: Backend.viewOffsetY
                width: Math.max(1, Backend.imageWidth * Backend.viewScale)
                height: Math.max(1, Backend.imageHeight * Backend.viewScale)
                source: Backend.hasImage ? "image://redactor/view/" + Backend.imageRevision : ""
                fillMode: Image.Stretch
                smooth: true
                mipmap: true
                cache: false
                asynchronous: false
            }

            MouseArea {
                id: interaction
                z: 1
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Backend.panning ? Qt.ClosedHandCursor : Qt.CrossCursor

                onPressed: function(mouse) {
                    stage.forceActiveFocus()
                    if (mouse.button === Qt.RightButton) {
                        Backend.beginPan(mouse.x, mouse.y)
                    } else {
                        Backend.press(mouse.x, mouse.y)
                    }
                }

                onPositionChanged: function(mouse) {
                    if (mouse.buttons & Qt.RightButton) {
                        Backend.movePan(mouse.x, mouse.y)
                    } else if (mouse.buttons & Qt.LeftButton) {
                        Backend.move(mouse.x, mouse.y)
                    }
                }

                onReleased: function(mouse) {
                    if (mouse.button === Qt.RightButton) {
                        Backend.endPan()
                    } else {
                        Backend.release(mouse.x, mouse.y)
                    }
                }

                onWheel: function(wheel) {
                    Backend.zoomAt(wheel.x, wheel.y, wheel.angleDelta.y)
                }
            }

            Repeater {
                id: boxRepeater
                model: Backend.boxes
                onCountChanged: viewer.hoveredBox = -1

                delegate: Item {
                    id: box
                    property var boxData: modelData
                    z: 2
                    x: boxData.x1 * Backend.viewScale + Backend.viewOffsetX
                    y: boxData.y1 * Backend.viewScale + Backend.viewOffsetY
                    width: Math.max(1, (boxData.x2 - boxData.x1) * Backend.viewScale)
                    height: Math.max(1, (boxData.y2 - boxData.y1) * Backend.viewScale)
                    visible: Backend.hasImage && !Backend.confirmed

                    HoverHandler {
                        onHoveredChanged: {
                            if (hovered)
                                viewer.hoveredBox = index
                            else if (viewer.hoveredBox === index)
                                viewer.hoveredBox = -1
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: -3
                        radius: 2
                        color: "transparent"
                        border.width: 4
                        border.color: box.boxData.selected ? Theme.amber : Theme.red
                        opacity: box.boxData.selected ? 0.24 : 0.16
                    }

                    Rectangle {
                        anchors.fill: parent
                        radius: 1
                        color: box.boxData.selected ? Theme.amberFill : Theme.redFill
                        border.width: 2
                        border.color: box.boxData.selected ? Theme.amber : Theme.red
                    }

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: -6
                        radius: 2
                        color: "transparent"
                        border.width: 2
                        border.color: Theme.white
                        visible: stage.activeFocus && viewer.keyboardBox === index
                    }

                    Rectangle {
                        id: ruleTag
                        z: 5
                        visible: Backend.showRules && (viewer.hoveredBox !== -1
                                 ? viewer.hoveredBox === index
                                 : (box.boxData.selected && Backend.selectedCount === 1))
                        width: Math.min(Math.max(80, ruleText.implicitWidth + 12), stage.width - 8)
                        height: 19
                        radius: 3
                        color: Theme.panelRaised
                        border.width: 1
                        border.color: Theme.amber
                        x: Math.max(4 - box.x, Math.min(stage.width - box.x - width - 4, 0))
                        y: box.y - height - 4 < 4 ? 4 : -height - 4

                        Text {
                            id: ruleText
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 6
                            anchors.rightMargin: 6
                            text: box.boxData.ruleLabel
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: Theme.amber
                            font.family: Theme.displayFont
                            font.pixelSize: 9
                            font.letterSpacing: 0.5
                        }
                    }

                    Item {
                        id: removeHandle
                        z: 10
                        width: 16
                        height: 16
                        x: Math.max(-box.x + 2, Math.min(stage.width - box.x - 18, box.width + 2))
                        y: Math.max(-box.y + 2, Math.min(stage.height - box.y - 18, -8))

                        Rectangle {
                            anchors.fill: parent
                            radius: 3
                            color: Theme.fieldFace
                            border.width: 1
                            border.color: Theme.steelLight
                        }

                        Rectangle {
                            width: 8
                            height: 1.5
                            radius: 0.75
                            color: Theme.white
                            anchors.centerIn: parent
                            rotation: 45
                        }

                        Rectangle {
                            width: 8
                            height: 1.5
                            radius: 0.75
                            color: Theme.white
                            anchors.centerIn: parent
                            rotation: -45
                        }

                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -4
                            acceptedButtons: Qt.LeftButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Backend.removeBox(index)
                        }
                    }
                }
            }

            Rectangle {
                z: 8
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 8
                width: keyHint.implicitWidth + 16
                height: 22
                radius: 4
                color: Theme.panel
                border.width: 1
                border.color: Theme.buttonBorder
                visible: stage.activeFocus && Backend.totalBoxes > 0 && !Backend.confirmed
                         && Backend.captureMode === "none" && !Backend.busy

                Text {
                    id: keyHint
                    anchors.centerIn: parent
                    text: "ARROWS MOVE · SPACE TOGGLE · DEL REMOVE · SHIFT PAN · CTRL+= ZOOM"
                    color: Theme.steelLight
                    font.family: Theme.displayFont
                    font.pixelSize: 9
                    font.letterSpacing: 0.6
                }
            }

            Rectangle {
                z: 9
                anchors.fill: parent
                color: "transparent"
                border.width: 1
                border.color: Theme.amber
                opacity: 0.7
                visible: stage.activeFocus
            }

            Rectangle {
                z: 3
                visible: Backend.dragActive
                         && Backend.dragWidth > 0
                         && Backend.dragHeight > 0
                x: Backend.dragX
                y: Backend.dragY
                width: Backend.dragWidth
                height: Backend.dragHeight
                color: Theme.amberFill
                radius: 2

                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        var ctx = getContext("2d");
                        ctx.reset();
                        var x = 2;
                        var y = 2;
                        var w = width - 4;
                        var h = height - 4;
                        if (w <= 0 || h <= 0)
                            return;
                        ctx.strokeStyle = Theme.scrim;
                        ctx.lineWidth = 4;
                        ctx.setLineDash([]);
                        ctx.strokeRect(x, y, w, h);
                        ctx.strokeStyle = Theme.amber;
                        ctx.lineWidth = 2;
                        ctx.setLineDash([8, 5]);
                        ctx.strokeRect(x, y, w, h);
                    }
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                }

                Repeater {
                    model: [[0, 0], [1, 0], [0, 1], [1, 1]]

                    delegate: Rectangle {
                        required property var modelData
                        width: 9
                        height: 9
                        visible: parent.width > 18 && parent.height > 18
                        x: modelData[0] ? parent.width - width : 0
                        y: modelData[1] ? parent.height - height : 0
                        color: Theme.amber
                        border.width: 1
                        border.color: Theme.scrim
                    }
                }
            }

            Item {
                z: 4
                anchors.fill: parent
                visible: !Backend.hasImage

                Column {
                    anchors.centerIn: parent
                    width: Math.min(stage.width - 100, 540)
                    spacing: 14

                    Text {
                        width: parent.width
                        text: "NO SCREENSHOT"
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.white
                        font.family: Theme.displayFont
                        font.pixelSize: 34
                        font.letterSpacing: 4
                        font.weight: Font.DemiBold
                    }

                    Item {
                        width: parent.width
                        height: 2

                        Rectangle {
                            anchors.centerIn: parent
                            width: 54
                            height: 2
                            color: Theme.amber
                        }
                    }

                    Text {
                        width: parent.width
                        text: "Open a screenshot to scan for identifiers, review every box, "
                              + "and export a safe copy. Everything runs on this machine."
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        color: Theme.steelLight
                        font.family: Theme.bodyFont
                        font.pixelSize: 13
                        lineHeight: 1.25
                    }

                    Item {
                        width: parent.width
                        height: 38

                        Row {
                            anchors.centerIn: parent
                            spacing: 9

                            ConcourseButton {
                                text: "OPEN IMAGE"
                                variant: "primary"
                                tip: "Open an image file (Ctrl+O)"
                                onClicked: Backend.openImage()
                            }

                            ConcourseButton {
                                text: "OPEN FOLDER"
                                tip: "Open every image in a folder (Ctrl+Shift+O)"
                                onClicked: Backend.openFolder()
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "CTRL+O OPEN · CTRL+V PASTE · CTRL+F SCAN · CTRL+ENTER CONFIRM"
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.steelLight
                        font.family: Theme.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 0.8
                    }

                    Text {
                        width: parent.width
                        text: "TESSERACT + RAPIDOCR / COORDINATE LOG / PNG COPY"
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.mutedText
                        font.family: Theme.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 1.1
                    }
                }
            }

            Rectangle {
                z: 4
                visible: Backend.hasImage && Backend.captureMode !== "none"
                anchors.fill: parent
                color: "transparent"
                border.width: 2
                border.color: Theme.amber
                opacity: 0.65
            }

            Rectangle {
                id: captureBanner
                z: 7
                visible: Backend.hasImage && Backend.captureMode !== "none"
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.topMargin: 14
                width: Math.min(stage.width - 32, 640)
                height: 58
                radius: 7
                color: Theme.panel
                border.width: 1
                border.color: Theme.amber

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: {}
                }

                Rectangle {
                    width: 3
                    height: parent.height - 18
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    radius: 1.5
                    color: Theme.amber
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 20
                    anchors.rightMargin: 10
                    spacing: 12

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 2

                        Text {
                            text: viewer.captureTitle
                            color: Theme.amber
                            font.family: Theme.displayFont
                            font.pixelSize: 11
                            font.letterSpacing: 1.2
                            font.weight: Font.DemiBold
                        }

                        Text {
                            Layout.fillWidth: true
                            text: viewer.captureInstruction + " Esc cancels."
                            color: Theme.white
                            font.family: Theme.bodyFont
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }

                    ConcourseButton {
                        Layout.alignment: Qt.AlignVCenter
                        Layout.preferredHeight: 30
                        text: "CANCEL"
                        compact: true
                        onClicked: Backend.cancelCapture()
                    }
                }
            }

            Rectangle {
                z: 5
                visible: Backend.busy
                anchors.top: parent.top
                height: 3
                width: 140
                radius: 1.5
                color: Theme.amber
                opacity: 0.9

                NumberAnimation on x {
                    from: -140
                    to: stage.width
                    duration: 1500
                    loops: Animation.Infinite
                    running: Backend.busy
                }
            }

            Rectangle {
                id: busyBanner
                z: 6
                visible: Backend.busy
                anchors.top: parent.top
                anchors.topMargin: 52
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(stage.width - 40, 460)
                height: 64
                radius: 8
                color: Theme.rowSelected
                border.width: 1
                border.color: Theme.amber

                Row {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 10

                    Rectangle {
                        width: 24
                        height: 24
                        radius: 3
                        color: Theme.amber
                        anchors.verticalCenter: parent.verticalCenter

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            height: 1
                            color: Theme.shadow
                            opacity: 0.55
                        }
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 38
                        spacing: 1

                        Text {
                            text: Backend.busyLabel.toUpperCase()
                            color: Theme.white
                            font.family: Theme.displayFont
                            font.pixelSize: 10
                            font.letterSpacing: 1.1
                        }

                        Text {
                            width: parent.width
                            visible: text.length > 0
                            text: Backend.scanStage
                            elide: Text.ElideRight
                            color: Theme.white
                            font.family: Theme.bodyFont
                            font.pixelSize: 11
                        }

                        Text {
                            width: parent.width
                            text: Backend.progressText
                            elide: Text.ElideRight
                            color: Theme.steelLight
                            font.family: Theme.bodyFont
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }
    }

    ErrorBanner {
        width: Math.min(viewer.width - 44, 720)
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 18
    }
}
