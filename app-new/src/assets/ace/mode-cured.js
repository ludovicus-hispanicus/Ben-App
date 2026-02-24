// Custom ACE mode for CuReD cuneiform transliteration
ace.define("ace/mode/cured_highlight_rules", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text_highlight_rules"], function(require, exports, module) {
  "use strict";

  var oop = require("../lib/oop");
  var TextHighlightRules = require("./text_highlight_rules").TextHighlightRules;

  var CuredHighlightRules = function() {
    this.$rules = {
      "start": [
        // Square brackets - damage/break (red)
        {
          token: "bracket.square",
          regex: /[\[\]]/
        },
        // Parentheses - supplied by context (purple)
        {
          token: "bracket.paren",
          regex: /[()]/
        },
        // Angle brackets - omitted by scribe (blue)
        {
          token: "bracket.angle",
          regex: /[<>]/
        },
        // Curly braces - determinative (green)
        {
          token: "bracket.curly",
          regex: /[{}]/
        },
        // Half brackets - partially damaged (orange)
        {
          token: "bracket.half",
          regex: /[⸢⸣]/
        },
        // Bold notation **text**
        {
          token: ["markup.bold", "markup.bold.text", "markup.bold"],
          regex: /(\*\*)([^*\n]+)(\*\*)/
        },
        // Italic notation _text_ (Nemotron format)
        {
          token: ["markup.italic", "markup.italic.text", "markup.italic"],
          regex: /(_)([^_\n]+)(_)/
        },
        // Italic notation *text* (alternative)
        {
          token: ["markup.italic", "markup.italic.text", "markup.italic"],
          regex: /(\*)([^*\n]+)(\*)/
        },
        // Superscript <sup>text</sup>
        {
          token: ["markup.sup", "markup.sup.text", "markup.sup"],
          regex: /(<sup>)([^<]+)(<\/sup>)/
        },
        // Subscript <sub>text</sub>
        {
          token: ["markup.sub", "markup.sub.text", "markup.sub"],
          regex: /(<sub>)([^<]+)(<\/sub>)/
        },
        // Line break <br>
        {
          token: "markup.br",
          regex: /<br>/
        },
        // Default text
        {
          token: "text",
          regex: /[^\[\](){}<>⸢⸣*_]+/
        }
      ]
    };

    this.normalizeRules();
  };

  oop.inherits(CuredHighlightRules, TextHighlightRules);
  exports.CuredHighlightRules = CuredHighlightRules;
});

ace.define("ace/mode/cured", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text", "ace/mode/cured_highlight_rules"], function(require, exports, module) {
  "use strict";

  var oop = require("../lib/oop");
  var TextMode = require("./text").Mode;
  var CuredHighlightRules = require("./cured_highlight_rules").CuredHighlightRules;

  var Mode = function() {
    this.HighlightRules = CuredHighlightRules;
    this.$behaviour = this.$defaultBehaviour;
  };

  oop.inherits(Mode, TextMode);

  (function() {
    this.lineCommentStart = "";
    this.blockComment = null;
    this.$id = "ace/mode/cured";
  }).call(Mode.prototype);

  exports.Mode = Mode;
});
