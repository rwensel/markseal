import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import "Theme.js" as Theme
import Redactor 1.0

Item {
    id: viewer

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#14171A" }
            GradientStop { position: 1.0; color: "#0B0C0E" }
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
            font.family: Backend.bodyFont
            font.pixelSize: 11
        }

        Text {
            text: Backend.imageSizeText
            color: Theme.steelLight
            font.family: Backend.displayFont
            font.pixelSize: 9
            font.letterSpacing: 0.7
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: "#34393F"
        }

        Text {
            text: "SCROLL ZOOM / RIGHT-DRAG PAN"
            visible: caption.width > 620
            color: Theme.mutedText
            font.family: Backend.displayFont
            font.pixelSize: 8
            font.letterSpacing: 0.7
        }

        Text {
            text: Backend.zoomPercent + "%"
            color: Theme.white
            font.family: Backend.displayFont
            font.pixelSize: 10
            font.letterSpacing: 0.6
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
            border.color: "#050506"
        }

        MultiEffect {
            anchors.fill: cardBackground
            source: cardBackground
            shadowEnabled: true
            shadowColor: "#000000"
            shadowOpacity: 0.6
            shadowBlur: 0.85
            shadowVerticalOffset: 9
        }

        Rectangle {
            anchors.fill: parent
            radius: 6
            color: "transparent"
            border.width: 1
            border.color: "#3B4046"
            opacity: 0.45
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 2
            height: 1
            color: "#FFFFFF"
            opacity: 0.06
        }

        Item {
            id: stage
            anchors.fill: parent
            anchors.margins: 6
            clip: true

            onWidthChanged: Backend.setViewSize(width, height)
            onHeightChanged: Backend.setViewSize(width, height)
            Component.onCompleted: Backend.setViewSize(width, height)

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
                model: Backend.boxes

                delegate: Item {
                    id: box
                    property var boxData: modelData
                    z: 2
                    x: boxData.x1 * Backend.viewScale + Backend.viewOffsetX
                    y: boxData.y1 * Backend.viewScale + Backend.viewOffsetY
                    width: Math.max(1, (boxData.x2 - boxData.x1) * Backend.viewScale)
                    height: Math.max(1, (boxData.y2 - boxData.y1) * Backend.viewScale)
                    visible: Backend.hasImage && !Backend.confirmed

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
                        color: box.boxData.selected ? "#0CFFB000" : "#14B00020"
                        border.width: 2
                        border.color: box.boxData.selected ? Theme.amber : Theme.red
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
                            color: "#181A1D"
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
                            acceptedButtons: Qt.LeftButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Backend.removeBox(index)
                        }
                    }
                }
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
                color: "#12FFFFFF"
                border.width: 1
                border.color: Theme.white
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
                        font.family: Backend.displayFont
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
                        font.family: Backend.bodyFont
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
                                onClicked: Backend.openImage()
                            }

                            ConcourseButton {
                                text: "OPEN FOLDER"
                                onClicked: Backend.openFolder()
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "TESSERACT + RAPIDOCR / COORDINATE LOG / PNG COPY"
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.mutedText
                        font.family: Backend.displayFont
                        font.pixelSize: 9
                        font.letterSpacing: 1.1
                    }
                }
            }

            Rectangle {
                z: 5
                visible: Backend.hasImage && Backend.captureMode !== "none"
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.margins: 12
                height: 22
                radius: 4
                width: Math.min(stage.width - 24, hintText.implicitWidth + 18)
                color: "#8C0B0D10"

                Text {
                    id: hintText
                    anchors.centerIn: parent
                    width: parent.width - 14
                    text: Backend.captureMode === "area"
                          ? "AREA SCAN / DRAG AROUND TEXT / ESC CANCELS"
                          : Backend.captureMode === "anchor"
                            ? "ANCHOR MATCH / DRAG AROUND A STABLE CUE / ESC CANCELS"
                            : "SCROLL ZOOM / RIGHT-DRAG PAN / CLICK TOGGLE / DRAG TO ADD"
                    elide: Text.ElideRight
                    color: Backend.captureMode !== "none" ? Theme.amber : Theme.steelLight
                    font.family: Backend.displayFont
                    font.pixelSize: 9
                    font.letterSpacing: 0.7
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
                z: 6
                visible: Backend.busy
                anchors.top: parent.top
                anchors.topMargin: 52
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(stage.width - 40, 420)
                height: 46
                radius: 8
                color: "#E61D2024"
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
                            color: "#000000"
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
                            font.family: Backend.displayFont
                            font.pixelSize: 10
                            font.letterSpacing: 1.1
                        }

                        Text {
                            width: parent.width
                            text: Backend.progressText
                            elide: Text.ElideRight
                            color: Theme.steelLight
                            font.family: Backend.bodyFont
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }
    }
}
