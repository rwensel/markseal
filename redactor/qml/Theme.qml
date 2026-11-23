pragma Singleton
import QtQuick
import Redactor 1.0

QtObject {
    id: theme
    readonly property var t: Backend.palette.tokens

    readonly property color bg: t.bg
    readonly property color panel: t.panel
    readonly property color panelRaised: t.panelRaised
    readonly property color inset: t.inset
    readonly property color steel: t.steel
    readonly property color steelMid: t.steelMid
    readonly property color steelLight: t.steelLight
    readonly property color hairline: t.hairline
    readonly property color amber: t.amber
    readonly property color amberHover: t.amberHover
    readonly property color amberPressed: t.amberPressed
    readonly property color amberBorder: t.amberBorder
    readonly property color amberFill: t.amberFill
    readonly property color accentGlow: t.accentGlow
    readonly property color accentSoft: t.accentSoft
    readonly property color red: t.red
    readonly property color redFill: t.redFill
    readonly property color redBorder: t.redBorder
    readonly property color dangerText: t.dangerText
    readonly property color dangerFace: t.dangerFace
    readonly property color dangerBorder: t.dangerBorder
    readonly property color white: t.white
    readonly property color ink: t.ink
    readonly property color mutedText: t.mutedText
    readonly property color tile: t.tile
    readonly property color tileTop: t.tileTop
    readonly property color tileHingeDark: t.tileHingeDark
    readonly property color tileHingeLight: t.tileHingeLight
    readonly property color shellTop: t.shellTop
    readonly property color shellBottom: t.shellBottom
    readonly property color viewerTop: t.viewerTop
    readonly property color viewerBottom: t.viewerBottom
    readonly property color toolbarTop: t.toolbarTop
    readonly property color toolbarBottom: t.toolbarBottom
    readonly property color sidebarTop: t.sidebarTop
    readonly property color sidebarBottom: t.sidebarBottom
    readonly property color settingsTop: t.settingsTop
    readonly property color settingsBottom: t.settingsBottom
    readonly property color toolbarDivider: t.toolbarDivider
    readonly property color toolbarEdge: t.toolbarEdge
    readonly property color insetBorder: t.insetBorder
    readonly property color boardTop: t.boardTop
    readonly property color boardBottom: t.boardBottom
    readonly property color rowActive: t.rowActive
    readonly property color rowSelected: t.rowSelected
    readonly property color rowHover: t.rowHover
    readonly property color buttonFace: t.buttonFace
    readonly property color buttonFaceHover: t.buttonFaceHover
    readonly property color buttonFacePressed: t.buttonFacePressed
    readonly property color buttonBorder: t.buttonBorder
    readonly property color buttonBorderHover: t.buttonBorderHover
    readonly property color ghostHover: t.ghostHover
    readonly property color disabledFace: t.disabledFace
    readonly property color disabledText: t.disabledText
    readonly property color focusRing: t.focusRing
    readonly property color fieldFace: t.fieldFace
    readonly property color fieldBorder: t.fieldBorder
    readonly property color fieldHover: t.fieldHover
    readonly property color placeholder: t.placeholder
    readonly property color tabFace: t.tabFace
    readonly property color tabHover: t.tabHover
    readonly property color tabActiveFace: t.tabActiveFace
    readonly property color tabBorder: t.tabBorder
    readonly property color bannerFace: t.bannerFace
    readonly property color bannerBorder: t.bannerBorder
    readonly property color scrim: t.scrim
    readonly property color dropBorder: t.dropBorder
    readonly property color shadow: t.shadow
    readonly property color highlight: t.highlight

    readonly property string displayFont: t.displayFont
    readonly property string bodyFont: t.bodyFont
    readonly property real labelTracking: t.labelTracking
    readonly property real labelScale: t.labelScale

    readonly property real radiusShell: 12
    readonly property real radiusPanel: 10
    readonly property real radiusButton: 8
    readonly property real radiusCard: 4
}
