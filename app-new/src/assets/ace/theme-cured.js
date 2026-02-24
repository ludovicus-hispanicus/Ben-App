// Custom ACE theme for CuReD cuneiform transliteration
ace.define("ace/theme/cured", ["require", "exports", "module", "ace/lib/dom"], function(require, exports, module) {
  "use strict";

  exports.isDark = false;
  exports.cssClass = "ace-cured";
  exports.cssText = `
.ace-cured {
  background-color: #f8f8f8;
  color: #333;
  font-family: 'Noto Sans Mono', 'Courier New', Courier, monospace;
}

.ace-cured .ace_gutter {
  background: #f0f0f0;
  color: #999;
}

.ace-cured .ace_gutter-active-line {
  background-color: #e8e8e8;
}

.ace-cured .ace_cursor {
  color: #333;
}

.ace-cured .ace_marker-layer .ace_selection {
  background: rgba(66, 133, 244, 0.3);
}

.ace-cured .ace_marker-layer .ace_active-line {
  background: rgba(0, 0, 0, 0.04);
}

/* Bracket highlighting */
.ace-cured .ace_bracket.ace_square {
  color: #c62828 !important;
}

.ace-cured .ace_bracket.ace_paren {
  color: #7b1fa2 !important;
}

.ace-cured .ace_bracket.ace_angle {
  color: #1565c0 !important;
}

.ace-cured .ace_bracket.ace_curly {
  color: #2e7d32 !important;
}

.ace-cured .ace_bracket.ace_half {
  color: #e65100 !important;
}

/* Markup formatting */
.ace-cured .ace_markup.ace_bold {
  color: #666;
}

.ace-cured .ace_markup.ace_bold.ace_text {
  font-weight: bold;
  color: #333;
}

.ace-cured .ace_markup.ace_italic {
  color: #666;
}

.ace-cured .ace_markup.ace_italic.ace_text {
  font-style: italic;
  color: #333;
}

.ace-cured .ace_markup.ace_sup {
  color: #888;
}

.ace-cured .ace_markup.ace_sup.ace_text {
  color: #333;
  font-size: 0.8em;
  vertical-align: super;
}

.ace-cured .ace_markup.ace_sub {
  color: #888;
}

.ace-cured .ace_markup.ace_sub.ace_text {
  color: #333;
  font-size: 0.8em;
  vertical-align: sub;
}

.ace-cured .ace_markup.ace_br {
  color: #888;
  background: rgba(0,0,0,0.05);
  border-radius: 2px;
}
`;

  var dom = require("../lib/dom");
  dom.importCssString(exports.cssText, exports.cssClass, false);
});

// Dark theme variant
ace.define("ace/theme/cured_dark", ["require", "exports", "module", "ace/lib/dom"], function(require, exports, module) {
  "use strict";

  exports.isDark = true;
  exports.cssClass = "ace-cured-dark";
  exports.cssText = `
.ace-cured-dark {
  background-color: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Noto Sans Mono', 'Courier New', Courier, monospace;
}

.ace-cured-dark .ace_gutter {
  background: #2d2d2d;
  color: #858585;
}

.ace-cured-dark .ace_gutter-active-line {
  background-color: #3c3c3c;
}

.ace-cured-dark .ace_cursor {
  color: #fff;
}

.ace-cured-dark .ace_marker-layer .ace_selection {
  background: rgba(66, 133, 244, 0.4);
}

.ace-cured-dark .ace_marker-layer .ace_active-line {
  background: rgba(255, 255, 255, 0.05);
}

/* Bracket highlighting - dark mode */
.ace-cured-dark .ace_bracket.ace_square {
  color: #ef5350 !important;
}

.ace-cured-dark .ace_bracket.ace_paren {
  color: #ce93d8 !important;
}

.ace-cured-dark .ace_bracket.ace_angle {
  color: #64b5f6 !important;
}

.ace-cured-dark .ace_bracket.ace_curly {
  color: #81c784 !important;
}

.ace-cured-dark .ace_bracket.ace_half {
  color: #ffb74d !important;
}

/* Markup formatting - dark mode */
.ace-cured-dark .ace_markup.ace_bold {
  color: #888;
}

.ace-cured-dark .ace_markup.ace_bold.ace_text {
  font-weight: bold;
  color: #d4d4d4;
}

.ace-cured-dark .ace_markup.ace_italic {
  color: #888;
}

.ace-cured-dark .ace_markup.ace_italic.ace_text {
  font-style: italic;
  color: #d4d4d4;
}

.ace-cured-dark .ace_markup.ace_sup {
  color: #666;
}

.ace-cured-dark .ace_markup.ace_sup.ace_text {
  color: #d4d4d4;
  font-size: 0.8em;
  vertical-align: super;
}

.ace-cured-dark .ace_markup.ace_sub {
  color: #666;
}

.ace-cured-dark .ace_markup.ace_sub.ace_text {
  color: #d4d4d4;
  font-size: 0.8em;
  vertical-align: sub;
}

.ace-cured-dark .ace_markup.ace_br {
  color: #666;
  background: rgba(255,255,255,0.05);
  border-radius: 2px;
}
`;

  var dom = require("../lib/dom");
  dom.importCssString(exports.cssText, exports.cssClass, false);
});
