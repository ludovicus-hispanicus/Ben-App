import { AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter, Input, NgZone, OnChanges, OnDestroy, OnInit, Output, SimpleChanges, ViewChild } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Subscription } from 'rxjs';
import { Index, Letter, LetterHover } from 'src/app/models/letter';

import { AtfConverterService } from 'src/app/services/atf-converter.service';
import { ReplacementMappingsService, ReplacementMapping } from 'src/app/services/replacement-mappings.service';
import { ValidationError } from 'src/app/services/ebl.service';

// Import ACE editor
import * as ace from 'ace-builds';

// Import ACE extensions
import 'ace-builds/src-noconflict/ext-searchbox';

// Configure ACE base path for workers
ace.config.set('basePath', 'assets/ace');
ace.config.set('modePath', 'assets/ace');
ace.config.set('themePath', 'assets/ace');

@Component({
  selector: 'text-editor',
  templateUrl: './text-editor.component.html',
  styleUrls: ['./text-editor.component.scss']
})
export class TextEditorComponent implements OnInit, AfterViewInit, OnChanges, OnDestroy {

  @Input() public canEdit: boolean = true;
  @Input() public boxAmount: number = null;
  @Input() public lines: Letter[] = null;

  // Plain text mode (for production/curation - no Letter[] binding)
  @Input() public plainTextMode: boolean = false;
  @Input() public initialText: string = '';
  @Input() public validationErrors: ValidationError[] = [];

  // Live validation status (displayed in editor header)
  @Input() public isValidating: boolean = false;
  @Input() public validationValid: boolean | null = null;
  @Input() public validationParsedLines: number = 0;
  @Input() public validationErrorCount: number = 0;
  @Input() public validationWarningCount: number = 0;
  @Input() public validationSourceLabel: string = '';

  // Disable character normalization (e.g., for translation editor - don't convert á to a₂)
  @Input() public disableNormalization: boolean = false;

  // Hide the validation header (when parent component shows it externally)
  @Input() public hideValidationHeader: boolean = false;

  // Custom preview HTML (e.g., CuRe transliteration readings). Overrides generated preview when set.
  @Input() public customPreviewHtml: string = '';

  // Sign name → cuneiform Unicode map for live conversion in preview
  @Input() public signMap: { [key: string]: string } = null;

  // Cuneiform font family for preview (e.g., 'Assurbanipal', 'Esagil', 'Santakku')
  @Input() public cuneiformFont: string = 'Assurbanipal';

  // Track error markers for column highlighting
  private errorMarkers: number[] = [];

  @Output() lineHover: EventEmitter<LetterHover> = new EventEmitter();
  @Output() lineChanged: EventEmitter<Letter[]> = new EventEmitter();
  @Output() lineDeleted: EventEmitter<number> = new EventEmitter();
  @Output() regexMatchLines: EventEmitter<number[]> = new EventEmitter();
  @Output() textContentChanged: EventEmitter<string> = new EventEmitter();
  @Output() exportRequested: EventEmitter<void> = new EventEmitter();

  @ViewChild('aceEditor', { static: false }) aceEditorRef: ElementRef<HTMLDivElement>;

  public textContent: string = '';
  public lineCount: number = 0;
  public numberStyle: 'plain' | 'prime' | 'alternate' | 'alternate-prime' = 'plain';
  public startNumber: number = 1;
  public viewMode: 'raw' | 'atf' = 'raw';
  public darkMode: boolean = false;


  // Rendered HTML for live preview
  public renderedHtml: SafeHtml = '';

  // Replacement chart (character normalization mappings)
  public newMappingFrom: string = '';
  public newMappingTo: string = '';
  public newMappingCategory: string = 'Custom';
  private mappingsSubscription: Subscription;

  // Right-side properties panel
  public activeRightPanel: 'replacement' | 'normalized' | null = null;
  public rightPanelWidth: number = 300;
  private isPanelResizing: boolean = false;
  private panelResizeMoveHandler: ((e: MouseEvent) => void) | null = null;
  private panelResizeEndHandler: (() => void) | null = null;

  // Editor zoom (font size)
  public editorFontSize: number = 14;
  public readonly minFontSize: number = 8;
  public readonly maxFontSize: number = 32;

  private aceEditor: ace.Ace.Editor = null;
  private suppressUpdate: boolean = false;
  private customModeLoaded: boolean = false;
  private internalLinesUpdate: boolean = false; // Flag to prevent feedback loop from ngOnChanges
  private previewDebounceTimer: any = null;
  private readonly PREVIEW_DEBOUNCE_MS = 300;
  private signMapLookup: { [key: string]: string } = null; // lowercase key → unicode
  private cuneiformStyleEl: HTMLStyleElement = null; // Dynamic <style> in document head

  constructor(
    private atfConverter: AtfConverterService,
    private mappingsService: ReplacementMappingsService,
    private cdr: ChangeDetectorRef,
    private ngZone: NgZone,
    private sanitizer: DomSanitizer
  ) { }

  // Getter for replacement mappings from shared service
  get replacementMappings(): ReplacementMapping[] {
    return this.mappingsService.mappings;
  }

  // --- Public API (called by parent components) ---

  setLines(lines: Letter[]): void {
    this.lines = lines;
    this.lineCount = lines.length;
    this.suppressUpdate = true;
    // Apply silent corrections before setting text (unless normalization is disabled)
    const rawText = lines.map(l => l.letter).join('\n');
    this.textContent = this.disableNormalization ? rawText : this.applySilentCorrections(rawText);
    if (this.aceEditor) {
      this.aceEditor.setValue(this.textContent, -1);
    }
    // Update lines array with corrected text
    this.updateLinesFromText();
    this.updateLivePreview();
    this.suppressUpdate = false;
  }

  // For plain text mode - set content directly
  setText(content: string): void {
    this.suppressUpdate = true;
    this.textContent = content;
    if (this.aceEditor) {
      this.aceEditor.setValue(this.textContent, -1);
    }
    this.updateLivePreview();
    this.suppressUpdate = false;
  }

  // Get current text content
  getText(): string {
    return this.textContent;
  }

  setNewSelectedLine(index: Index): void {
    if (this.aceEditor && index) {
      this.aceEditor.gotoLine(index.row + 1, 0, true);
    }
  }

  hardReset(): void {
    this.lines = [];
    this.lineCount = 0;
    this.suppressUpdate = true;
    this.textContent = '';
    if (this.aceEditor) {
      this.aceEditor.setValue('', -1);
    }
    this.suppressUpdate = false;
  }

  // --- Lifecycle ---

  ngOnInit(): void {
    // In plain text mode (CuReD), use eBL format by default
    if (this.plainTextMode) {
      this.viewMode = 'atf';
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    // Handle initialText changes after component is initialized (e.g., when API data arrives)
    if (changes['initialText'] && this.plainTextMode && this.aceEditor) {
      let newText = changes['initialText'].currentValue || '';
      // Convert to eBL format if in atf mode (plain text mode defaults to eBL)
      // Skip conversion if normalization is disabled (e.g., for translation editor)
      if (this.viewMode === 'atf' && newText && !this.disableNormalization) {
        newText = this.atfConverter.toAtf(newText);
      }
      // Only update if the text actually changed and is different from current content
      if (newText !== this.textContent) {
        this.setText(newText);
      }
    }

    // Handle lines input changes (Letter[] mode)
    if (changes['lines'] && !this.plainTextMode && this.aceEditor) {
      // Skip if this change originated from the editor itself (feedback loop prevention)
      if (this.internalLinesUpdate) {
        this.internalLinesUpdate = false;
        // Don't call setLines — the editor already has the correct content
      } else {
        const newLines = changes['lines'].currentValue as Letter[];
        if (newLines && newLines.length > 0) {
          this.setLines(newLines);
        }
      }
    }

    // Handle validation errors changes
    if (changes['validationErrors'] && this.aceEditor) {
      this.updateValidationAnnotations();
    }

    // Handle custom preview HTML changes
    if (changes['customPreviewHtml']) {
      this.updateLivePreview();
    }

    // Handle sign map changes — build case-insensitive lookup
    if (changes['signMap']) {
      if (this.signMap) {
        this.signMapLookup = {};
        for (const key of Object.keys(this.signMap)) {
          this.signMapLookup[key.toLowerCase()] = this.signMap[key];
        }
      } else {
        this.signMapLookup = null;
      }
      this.updateLivePreview();
    }

    // Handle cuneiform font changes
    if (changes['cuneiformFont']) {
      this.updateCuneiformStyle();
      this.updateLivePreview();
    }
  }

  ngAfterViewInit(): void {
    this.initAceEditor();

    // Subscribe to mappings changes to update preview
    this.mappingsSubscription = this.mappingsService.mappings$.subscribe(() => {
      this.updateLivePreview();
    });
  }

  ngOnDestroy(): void {
    if (this.aceEditor) {
      this.aceEditor.destroy();
      this.aceEditor = null;
    }
    if (this.mappingsSubscription) {
      this.mappingsSubscription.unsubscribe();
    }
    if (this.previewDebounceTimer) {
      clearTimeout(this.previewDebounceTimer);
    }
    if (this.cuneiformStyleEl) {
      this.cuneiformStyleEl.remove();
      this.cuneiformStyleEl = null;
    }
    if (this.panelResizeMoveHandler) {
      document.removeEventListener('mousemove', this.panelResizeMoveHandler);
    }
    if (this.panelResizeEndHandler) {
      document.removeEventListener('mouseup', this.panelResizeEndHandler);
    }
  }

  /** Inject/update a global <style> in document head for cuneiform font and layout */
  private updateCuneiformStyle(): void {
    const font = this.cuneiformFont || 'Assurbanipal';
    const css = `
      .cuneiform-char {
        font-family: '${font}', 'Noto Sans Cuneiform', serif !important;
        font-size: 24px;
        letter-spacing: -1px;
      }
      .cuneiform-line {
        display: flex;
        align-items: baseline;
        gap: 6px;
        margin-bottom: 4px;
      }
      .cuneiform-line .line-num {
        color: #999;
        font-size: 12px;
        min-width: 20px;
        user-select: none;
        flex-shrink: 0;
      }
      .cuneiform-line .line-signs {
        display: inline;
      }
      .unknown-sign {
        color: #999;
        font-style: italic;
        font-size: 12px;
      }
      .dark-mode .cuneiform-char { color: #e0e0e0; }
      .dark-mode .unknown-sign { color: #777; }
    `;

    if (!this.cuneiformStyleEl) {
      this.cuneiformStyleEl = document.createElement('style');
      this.cuneiformStyleEl.setAttribute('data-cuneiform-font', 'true');
      document.head.appendChild(this.cuneiformStyleEl);
    }
    this.cuneiformStyleEl.textContent = css;
  }

  private initAceEditor(): void {
    if (!this.aceEditorRef?.nativeElement) return;

    // Load custom mode and theme
    this.loadCustomMode();
    this.loadCustomTheme();

    // Create ACE editor
    this.aceEditor = ace.edit(this.aceEditorRef.nativeElement, {
      mode: this.getAceMode(),
      theme: this.darkMode ? 'ace/theme/cured_dark' : 'ace/theme/cured',
      fontSize: 14,
      fontFamily: "'Assurbanipal', 'Noto Sans Mono', 'Courier New', Courier, monospace",
      showPrintMargin: false,
      showGutter: true,
      highlightActiveLine: true,
      wrap: true,
      tabSize: 2,
      useSoftTabs: true,
      readOnly: !this.canEdit,
    });

    // Add more space between lines (1.5 = 150% line height)
    this.aceEditor.container.style.lineHeight = '1.5';
    this.aceEditor.renderer.updateFontSize();

    // Set initial content
    if (this.plainTextMode && this.initialText) {
      // Convert to eBL format if in atf mode (plain text mode defaults to eBL)
      // Skip conversion if normalization is disabled (e.g., for translation editor)
      this.textContent = (this.viewMode === 'atf' && !this.disableNormalization)
        ? this.atfConverter.toAtf(this.initialText)
        : this.initialText;
    } else if (!this.plainTextMode && this.lines && this.lines.length > 0) {
      // Letter[] mode — initialize from lines input
      const rawText = this.lines.map(l => l.letter).join('\n');
      this.textContent = this.disableNormalization ? rawText : this.applySilentCorrections(rawText);
      this.lineCount = this.lines.length;
    }
    if (this.textContent) {
      this.aceEditor.setValue(this.textContent, -1);
    }

    // Handle content changes
    this.aceEditor.on('change', () => {
      if (this.suppressUpdate) return;

      this.ngZone.run(() => {
        this.textContent = this.aceEditor.getValue();

        if (this.plainTextMode) {
          // In plain text mode, just emit the content change
          this.textContentChanged.emit(this.textContent);
        } else {
          // In Letter[] mode, update lines and emit
          this.updateLinesFromText();
        }

        this.updateLivePreview();
      });
    });

    // Initial preview update
    this.updateLivePreview();

    // Resize editor after a short delay to ensure container has proper dimensions
    setTimeout(() => {
      if (this.aceEditor) {
        this.aceEditor.resize();
      }
    }, 100);
  }

  private loadCustomMode(): void {
    if (this.customModeLoaded) return;

    // Raw mode highlight rules - only brackets, no markdown
    (ace as any).define("ace/mode/cured_raw_highlight_rules", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text_highlight_rules"], function(require: any, exports: any, module: any) {
      var oop = require("../lib/oop");
      var TextHighlightRules = require("./text_highlight_rules").TextHighlightRules;

      var CuredRawHighlightRules = function() {
        this.$rules = {
          "start": [
            { token: "bracket.square", regex: "\\[" },
            { token: "bracket.square", regex: "\\]" },
            { token: "bracket.paren", regex: "\\(" },
            { token: "bracket.paren", regex: "\\)" },
            { token: "bracket.angle", regex: "<" },
            { token: "bracket.angle", regex: ">" },
            { token: "bracket.curly", regex: "\\{" },
            { token: "bracket.curly", regex: "\\}" },
            { token: "bracket.half", regex: "⸢" },
            { token: "bracket.half", regex: "⸣" },
            { token: "text", regex: "." }
          ]
        };
        this.normalizeRules();
      };

      oop.inherits(CuredRawHighlightRules, TextHighlightRules);
      exports.CuredRawHighlightRules = CuredRawHighlightRules;
    });

    (ace as any).define("ace/mode/cured_raw", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text", "ace/mode/cured_raw_highlight_rules"], function(require: any, exports: any, module: any) {
      var oop = require("../lib/oop");
      var TextMode = require("./text").Mode;
      var CuredRawHighlightRules = require("./cured_raw_highlight_rules").CuredRawHighlightRules;

      var Mode = function() {
        this.HighlightRules = CuredRawHighlightRules;
        this.$behaviour = this.$defaultBehaviour;
      };

      oop.inherits(Mode, TextMode);

      (function() {
        this.lineCommentStart = "";
        this.blockComment = null;
        this.$id = "ace/mode/cured_raw";
      }).call(Mode.prototype);

      exports.Mode = Mode;
    });

    // Norm mode highlight rules - brackets + markdown formatting
    (ace as any).define("ace/mode/cured_norm_highlight_rules", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text_highlight_rules"], function(require: any, exports: any, module: any) {
      var oop = require("../lib/oop");
      var TextHighlightRules = require("./text_highlight_rules").TextHighlightRules;

      var CuredNormHighlightRules = function() {
        this.$rules = {
          "start": [
            { token: "bracket.square", regex: "\\[" },
            { token: "bracket.square", regex: "\\]" },
            { token: "bracket.paren", regex: "\\(" },
            { token: "bracket.paren", regex: "\\)" },
            { token: "bracket.curly", regex: "\\{" },
            { token: "bracket.curly", regex: "\\}" },
            { token: "bracket.half", regex: "⸢" },
            { token: "bracket.half", regex: "⸣" },
            { token: ["markup.bold", "markup.bold.text", "markup.bold"], regex: "(\\*\\*)([^*\\n]+)(\\*\\*)" },
            { token: ["markup.italic", "markup.italic.text", "markup.italic"], regex: "(_)([^_\\n]+)(_)" },
            { token: ["markup.italic", "markup.italic.text", "markup.italic"], regex: "(\\*)([^*\\n]+)(\\*)" },
            { token: ["markup.sup", "markup.sup.text", "markup.sup"], regex: "(<sup>)([^<]+)(</sup>)" },
            { token: ["markup.sub", "markup.sub.text", "markup.sub"], regex: "(<sub>)([^<]+)(</sub>)" },
            { token: "markup.br", regex: "<br>" },
            { token: "text", regex: "." }
          ]
        };
        this.normalizeRules();
      };

      oop.inherits(CuredNormHighlightRules, TextHighlightRules);
      exports.CuredNormHighlightRules = CuredNormHighlightRules;
    });

    (ace as any).define("ace/mode/cured_norm", ["require", "exports", "module", "ace/lib/oop", "ace/mode/text", "ace/mode/cured_norm_highlight_rules"], function(require: any, exports: any, module: any) {
      var oop = require("../lib/oop");
      var TextMode = require("./text").Mode;
      var CuredNormHighlightRules = require("./cured_norm_highlight_rules").CuredNormHighlightRules;

      var Mode = function() {
        this.HighlightRules = CuredNormHighlightRules;
        this.$behaviour = this.$defaultBehaviour;
      };

      oop.inherits(Mode, TextMode);

      (function() {
        this.lineCommentStart = "";
        this.blockComment = null;
        this.$id = "ace/mode/cured_norm";
      }).call(Mode.prototype);

      exports.Mode = Mode;
    });

    this.customModeLoaded = true;
  }

  private loadCustomTheme(): void {
    // Light theme
    (ace as any).define("ace/theme/cured", ["require", "exports", "module", "ace/lib/dom"], function(require: any, exports: any, module: any) {
      exports.isDark = false;
      exports.cssClass = "ace-cured";
      exports.cssText = `
.ace-cured { background-color: #f8f8f8; color: #333; font-family: 'Assurbanipal', 'Noto Sans Mono', 'Courier New', monospace !important; }
.ace-cured .ace_content { font-family: 'Assurbanipal', 'Noto Sans Mono', 'Courier New', monospace !important; }
.ace-cured .ace_gutter { background: #f0f0f0; color: #999; }
.ace-cured .ace_gutter-active-line { background-color: #e8e8e8; }
.ace-cured .ace_cursor { color: #333; }
.ace-cured .ace_marker-layer .ace_selection { background: rgba(66, 133, 244, 0.3); }
.ace-cured .ace_marker-layer .ace_active-line { background: rgba(0, 0, 0, 0.04); }
.ace-cured .ace_bracket.ace_square { color: #c62828 !important; }
.ace-cured .ace_bracket.ace_paren { color: #7b1fa2 !important; }
.ace-cured .ace_bracket.ace_angle { color: #1565c0 !important; }
.ace-cured .ace_bracket.ace_curly { color: #2e7d32 !important; }
.ace-cured .ace_bracket.ace_half { color: #e65100 !important; }
.ace-cured .ace_markup.ace_bold { color: #666; }
.ace-cured .ace_markup.ace_bold.ace_text { font-weight: bold; color: #333; }
.ace-cured .ace_markup.ace_italic { color: #666; }
.ace-cured .ace_markup.ace_italic.ace_text { font-style: italic; color: #333; }
.ace-cured .ace_markup.ace_sup { color: #888; }
.ace-cured .ace_markup.ace_sup.ace_text { color: #333; }
.ace-cured .ace_markup.ace_sub { color: #888; }
.ace-cured .ace_markup.ace_sub.ace_text { color: #333; }
.ace-cured .ace_markup.ace_br { color: #888; background: rgba(0,0,0,0.05); border-radius: 2px; }
`;
      var dom = require("../lib/dom");
      dom.importCssString(exports.cssText, exports.cssClass, false);
    });

    // Dark theme
    (ace as any).define("ace/theme/cured_dark", ["require", "exports", "module", "ace/lib/dom"], function(require: any, exports: any, module: any) {
      exports.isDark = true;
      exports.cssClass = "ace-cured-dark";
      exports.cssText = `
.ace-cured-dark { background-color: #1e1e1e; color: #d4d4d4; font-family: 'Assurbanipal', 'Noto Sans Mono', 'Courier New', monospace !important; }
.ace-cured-dark .ace_content { font-family: 'Assurbanipal', 'Noto Sans Mono', 'Courier New', monospace !important; }
.ace-cured-dark .ace_gutter { background: #2d2d2d; color: #858585; }
.ace-cured-dark .ace_gutter-active-line { background-color: #3c3c3c; }
.ace-cured-dark .ace_cursor { color: #fff; }
.ace-cured-dark .ace_marker-layer .ace_selection { background: rgba(66, 133, 244, 0.4); }
.ace-cured-dark .ace_marker-layer .ace_active-line { background: rgba(255, 255, 255, 0.05); }
.ace-cured-dark .ace_bracket.ace_square { color: #ef5350 !important; }
.ace-cured-dark .ace_bracket.ace_paren { color: #ce93d8 !important; }
.ace-cured-dark .ace_bracket.ace_angle { color: #64b5f6 !important; }
.ace-cured-dark .ace_bracket.ace_curly { color: #81c784 !important; }
.ace-cured-dark .ace_bracket.ace_half { color: #ffb74d !important; }
.ace-cured-dark .ace_markup.ace_bold { color: #888; }
.ace-cured-dark .ace_markup.ace_bold.ace_text { font-weight: bold; color: #d4d4d4; }
.ace-cured-dark .ace_markup.ace_italic { color: #888; }
.ace-cured-dark .ace_markup.ace_italic.ace_text { font-style: italic; color: #d4d4d4; }
.ace-cured-dark .ace_markup.ace_sup { color: #666; }
.ace-cured-dark .ace_markup.ace_sup.ace_text { color: #d4d4d4; }
.ace-cured-dark .ace_markup.ace_sub { color: #666; }
.ace-cured-dark .ace_markup.ace_sub.ace_text { color: #d4d4d4; }
.ace-cured-dark .ace_markup.ace_br { color: #666; background: rgba(255,255,255,0.05); border-radius: 2px; }
`;
      var dom = require("../lib/dom");
      dom.importCssString(exports.cssText, exports.cssClass, false);
    });
  }

  // --- View Mode ---

  private getAceMode(): string {
    return 'ace/mode/cured_raw';
  }

  setViewMode(mode: 'raw' | 'atf'): void {
    if (this.viewMode === mode) return;

    this.suppressUpdate = true;

    if (mode === 'atf') {
      this.textContent = this.atfConverter.toAtf(this.textContent);
    } else {
      // raw mode
      const rawText = this.atfConverter.fromAtf(this.textContent);
      this.textContent = rawText;
      this.updateLinesFromText();
    }

    this.viewMode = mode;

    if (this.aceEditor) {
      this.aceEditor.setValue(this.textContent, -1);
    }

    this.updateLivePreview();
    this.suppressUpdate = false;
  }

  private updateLivePreview(): void {
    if (this.signMapLookup) {
      // Debounced cuneiform preview
      if (this.previewDebounceTimer) {
        clearTimeout(this.previewDebounceTimer);
      }
      this.previewDebounceTimer = setTimeout(() => {
        this.renderedHtml = this.generateCuneiformPreview();
        this.cdr.detectChanges();
      }, this.PREVIEW_DEBOUNCE_MS);
    } else if (this.customPreviewHtml) {
      this.renderedHtml = this.sanitizer.bypassSecurityTrustHtml(this.customPreviewHtml);
    } else {
      this.renderedHtml = this.generateRenderedHtml();
    }
  }

  private generateCuneiformPreview(): SafeHtml {
    if (!this.textContent || !this.signMapLookup) return '';

    // Ensure the global cuneiform font style is injected
    this.updateCuneiformStyle();

    const lines = this.textContent.split('\n');
    let html = '';

    for (let i = 0; i < lines.length; i++) {
      const lineText = lines[i].trim();
      if (!lineText) {
        html += `<div class="cuneiform-line"><span class="line-num">${i + 1}.</span></div>`;
        continue;
      }

      // Split preserving spaces and non-breaking spaces (U+00A0)
      const parts = lineText.split(/([\s\u00A0]+)/);
      const cuneiformSpans = parts.map(part => {
        if (/^[\s\u00A0]+$/.test(part)) {
          // Single regular space → no space (cuneiform had no word separators)
          // Double space or nbsp → preserve count (aesthetic spacing as scribes did)
          const hasNbsp = part.includes('\u00A0');
          const regularSpaces = part.replace(/\u00A0/g, '').length;
          // Count: each nbsp = 1 space, regular spaces only count if 2+ (subtract 1)
          const nbspCount = part.length - regularSpaces;
          const extraRegular = regularSpaces >= 2 ? regularSpaces - 1 : 0;
          const totalSpaces = nbspCount + extraRegular;
          if (totalSpaces > 0) {
            return '&nbsp;'.repeat(totalSpaces);
          }
          return '';
        }

        const token = part;
        // Strip brackets/markers for lookup: [, ], (, ), <, >, {, }, ⸢, ⸣
        const cleaned = token.replace(/[\[\](){}<>⸢⸣?!#*]/g, '');

        // Hyphen-bound signs (e.g. "e-nu-ma") → look up each part, render joined
        if (cleaned.includes('-')) {
          const subParts = cleaned.split('-');
          const chars = subParts.map(p => {
            const u = this.signMapLookup[p.toLowerCase()];
            return u || null;
          });
          if (chars.every(c => c !== null)) {
            return `<span class="cuneiform-char" title="${token}">${chars.join('')}</span>`;
          }
          // Partial match: render found parts as cuneiform, unknown as italic
          return subParts.map(p => {
            const u = this.signMapLookup[p.toLowerCase()];
            if (u) return `<span class="cuneiform-char" title="${p}">${u}</span>`;
            return `<span class="unknown-sign" title="${p}">${this.escapeHtml(p)}</span>`;
          }).join('');
        }

        // Single sign lookup
        const unicode = this.signMapLookup[cleaned.toLowerCase()];
        if (unicode) {
          return `<span class="cuneiform-char" title="${token}">${unicode}</span>`;
        } else {
          return `<span class="unknown-sign" title="${token}">${this.escapeHtml(token)}</span>`;
        }
      }).join('');

      html += `<div class="cuneiform-line"><span class="line-num">${i + 1}.</span><span class="line-signs">${cuneiformSpans}</span></div>`;
    }

    return this.sanitizer.bypassSecurityTrustHtml(html);
  }

  // --- Right Panel Toggle ---

  toggleRightPanel(panel: 'replacement' | 'normalized'): void {
    const wasOpen = this.activeRightPanel === panel;
    this.activeRightPanel = wasOpen ? null : panel;
    // Resize ACE editor after panel opens/closes
    setTimeout(() => {
      if (this.aceEditor) this.aceEditor.resize();
    }, 50);
  }

  startPanelResize(event: MouseEvent): void {
    event.preventDefault();
    this.isPanelResizing = true;
    const startX = event.clientX;
    const startWidth = this.rightPanelWidth;

    this.panelResizeMoveHandler = (e: MouseEvent) => {
      // Dragging left increases width, dragging right decreases
      const delta = startX - e.clientX;
      this.rightPanelWidth = Math.max(180, Math.min(600, startWidth + delta));
    };

    this.panelResizeEndHandler = () => {
      this.isPanelResizing = false;
      document.removeEventListener('mousemove', this.panelResizeMoveHandler);
      document.removeEventListener('mouseup', this.panelResizeEndHandler);
      this.panelResizeMoveHandler = null;
      this.panelResizeEndHandler = null;
      // Resize ACE editor after panel resize
      if (this.aceEditor) this.aceEditor.resize();
    };

    document.addEventListener('mousemove', this.panelResizeMoveHandler);
    document.addEventListener('mouseup', this.panelResizeEndHandler);
  }

  private generateRenderedHtml(): SafeHtml {
    if (!this.textContent) return '';

    // For eBL mode, convert back to raw first for normalization
    let contentToRender = this.textContent;
    if (this.viewMode === 'atf') {
      contentToRender = this.atfConverter.fromAtf(this.textContent);
    }

    let html = this.escapeHtml(contentToRender);

    // Apply enabled mappings from the replacement chart (with HTML escaping)
    for (const mapping of this.replacementMappings) {
      if (!mapping.enabled) continue;

      // Escape the 'from' string for HTML (< → &lt;, > → &gt;)
      const htmlFrom = this.escapeHtml(mapping.from);
      // Escape special regex characters
      const escaped = htmlFrom.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const pattern = new RegExp(escaped, 'g');
      html = html.replace(pattern, mapping.to);
    }

    // Bold **text** - render as bold (must be before italic)
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');

    // Italic _text_ (Nemotron format) - render as italics, REMOVE the underscores
    html = html.replace(/_([^_\n]+)_/g, '<i>$1</i>');

    // Italic *text* (alternative) - render as italics, REMOVE the asterisks
    html = html.replace(/\*([^*\n]+)\*/g, '<i>$1</i>');

    // Superscript <sup>text</sup>
    html = html.replace(/&lt;sup&gt;([^&]+)&lt;\/sup&gt;/g, '<sup>$1</sup>');

    // Subscript <sub>text</sub>
    html = html.replace(/&lt;sub&gt;([^&]+)&lt;\/sub&gt;/g, '<sub>$1</sub>');

    // Line break <br>
    html = html.replace(/&lt;br&gt;/g, '<br>');

    // Bracket highlighting
    html = html.replace(/\[/g, '<span class="hl-square">[</span>');
    html = html.replace(/\]/g, '<span class="hl-square">]</span>');
    html = html.replace(/\(/g, '<span class="hl-paren">(</span>');
    html = html.replace(/\)/g, '<span class="hl-paren">)</span>');
    html = html.replace(/&lt;/g, '<span class="hl-angle">&lt;</span>');
    html = html.replace(/&gt;/g, '<span class="hl-angle">&gt;</span>');
    html = html.replace(/\{/g, '<span class="hl-curly">{</span>');
    html = html.replace(/\}/g, '<span class="hl-curly">}</span>');
    html = html.replace(/⸢/g, '<span class="hl-half">⸢</span>');
    html = html.replace(/⸣/g, '<span class="hl-half">⸣</span>');

    // Convert newlines to <br> for proper display
    html = html.replace(/\n/g, '<br>');

    return this.sanitizer.bypassSecurityTrustHtml(html);
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  /**
   * Apply silent corrections to text (character normalization).
   * These corrections are applied to the actual text, not just the preview.
   * Uses the user-configurable replacement mappings from the shared service.
   */
  private applySilentCorrections(text: string): string {
    return this.mappingsService.applySilentCorrections(text);
  }

  private updateLinesFromText(): void {
    const newLines = this.textContent.split('\n');
    this.lines = newLines.map((t, row) => {
      const letter = new Letter(t);
      letter.index = new Index(row, 0);
      return letter;
    });
    this.lineCount = this.lines.length;
    this.internalLinesUpdate = true; // Prevent ngOnChanges from resetting the editor
    this.lineChanged.emit(this.lines);
  }

  // --- Actions ---

  removeEmptyLines(): void {
    if (this.plainTextMode) {
      // In plain text mode, work directly with textContent
      const lines = this.textContent.split('\n');
      const cleaned = lines.filter(line => line.trim().length > 0);

      this.suppressUpdate = true;
      this.textContent = cleaned.join('\n');
      if (this.aceEditor) {
        this.aceEditor.setValue(this.textContent, -1);
      }
      this.suppressUpdate = false;
      this.textContentChanged.emit(this.textContent);
    } else {
      // In Letter[] mode
      if (!this.lines) return;
      const cleaned = this.lines
        .filter(l => l.letter.trim().length > 0)
        .map((l, row) => {
          const letter = new Letter(l.letter);
          letter.index = new Index(row, 0);
          return letter;
        });
      this.lines = cleaned;
      this.lineCount = cleaned.length;
      this.suppressUpdate = true;
      this.textContent = cleaned.map(l => l.letter).join('\n');
      if (this.aceEditor) {
        this.aceEditor.setValue(this.textContent, -1);
      }
      this.suppressUpdate = false;
      this.lineChanged.emit(this.lines);
    }
  }

  public sectionNumbering: 'continuous' | 'reset' = 'continuous';

  get numberStyleLabel(): string {
    if (this.numberStyle === 'plain') return '1';
    if (this.numberStyle === 'prime') return "1'";
    if (this.numberStyle === 'alternate') return "1/1'";
    return "1'/1";
  }

  toggleNumberStyle(): void {
    if (this.numberStyle === 'plain') this.numberStyle = 'prime';
    else if (this.numberStyle === 'prime') this.numberStyle = 'alternate';
    else if (this.numberStyle === 'alternate') this.numberStyle = 'alternate-prime';
    else this.numberStyle = 'plain';
  }

  toggleSectionNumbering(): void {
    this.sectionNumbering = this.sectionNumbering === 'continuous' ? 'reset' : 'continuous';
  }

  /**
   * Check if a line is an ATF control line (should not be numbered).
   * Control lines start with: # (comment), @ (structure), & (identifier), $ (state)
   */
  private isAtfControlLine(line: string): boolean {
    const trimmed = line.trim();
    return trimmed.startsWith('#') ||
           trimmed.startsWith('@') ||
           trimmed.startsWith('&') ||
           trimmed.startsWith('$') ||
           trimmed === '';
  }

  /**
   * Check if a line is a section marker that resets numbering (@obverse, @reverse, etc.)
   */
  // Sections that reset numbering when in 'reset' mode
  private static readonly RESET_SECTIONS = ['obverse', 'reverse', 'left', 'right', 'seal'];
  // Sections that always continue numbering (never reset)
  private static readonly CONTINUE_SECTIONS = ['bottom', 'top', 'edge', 'column'];

  /** Extract section name from a @ or $ line, returns null if not a section marker */
  private getSectionName(line: string): string | null {
    const trimmed = line.trim().toLowerCase();
    if (!trimmed.startsWith('@') && !trimmed.startsWith('$')) return null;
    const afterPrefix = trimmed.substring(1).trim();
    const allSections = [...TextEditorComponent.RESET_SECTIONS, ...TextEditorComponent.CONTINUE_SECTIONS];
    return allSections.find(s => afterPrefix.startsWith(s)) || null;
  }

  /** Reset sections: obverse, reverse, left, right, seal — reset numbering in 'reset' mode */
  private isSectionResetMarker(line: string): boolean {
    const name = this.getSectionName(line);
    return name !== null && TextEditorComponent.RESET_SECTIONS.includes(name);
  }

  /** Continue sections: bottom, top, edge, column — always continue numbering */
  private isSectionContinueMarker(line: string): boolean {
    const name = this.getSectionName(line);
    return name !== null && TextEditorComponent.CONTINUE_SECTIONS.includes(name);
  }

  private getSectionSuffix(sectionIndex: number): string {
    if (this.numberStyle === 'plain') return '';
    if (this.numberStyle === 'prime') return "'";
    // alternate: even sections = plain, odd sections = prime
    if (this.numberStyle === 'alternate') return sectionIndex % 2 === 0 ? '' : "'";
    // alternate-prime: even sections = prime, odd sections = plain
    return sectionIndex % 2 === 0 ? "'" : '';
  }

  addLineNumbers(): void {
    if (this.plainTextMode) {
      // In plain text mode, work directly with textContent
      const lines = this.textContent.split('\n');
      if (lines.length === 0) return;

      let lineNum = this.startNumber || 1;
      let sectionIndex = -1; // will become 0 on first @ marker
      console.log('[addLineNumbers] numberStyle:', this.numberStyle, 'lines:', lines.length);
      const numbered = lines.map((line, idx) => {
        // Skip control lines (# @ & $) and empty lines
        if (this.isAtfControlLine(line)) {
          // Reset sections (obverse, reverse, left, right, seal): advance section index + optionally reset numbering
          if (this.isSectionResetMarker(line)) {
            sectionIndex++;
            if (this.sectionNumbering === 'reset') {
              lineNum = this.startNumber || 1;
            }
            console.log(`[addLineNumbers] line ${idx}: RESET marker "${line.trim()}", sectionIndex=${sectionIndex}, mode=${this.sectionNumbering}`);
          }
          // Continue sections (bottom, top, edge, column): keep same sectionIndex and numbering
          if (this.isSectionContinueMarker(line)) {
            console.log(`[addLineNumbers] line ${idx}: CONTINUE marker "${line.trim()}", sectionIndex=${sectionIndex} (unchanged)`);
          }
          return line; // Keep as-is, don't number
        }
        // If no section marker seen yet, treat as section 0
        if (sectionIndex < 0) { sectionIndex = 0; }

        const suffix = this.getSectionSuffix(sectionIndex);
        const num = `${lineNum}${suffix}. `;
        if (idx < 5 || suffix) {
          console.log(`[addLineNumbers] line ${idx}: sectionIndex=${sectionIndex}, suffix="${suffix}", num="${num}"`);
        }
        // Remove existing line number if present
        const text = line.replace(/^\d+'?\.\s*/, '');
        lineNum++;
        return num + text;
      });

      this.suppressUpdate = true;
      this.textContent = numbered.join('\n');
      if (this.aceEditor) {
        this.aceEditor.setValue(this.textContent, -1);
      }
      this.suppressUpdate = false;
      this.textContentChanged.emit(this.textContent);
    } else {
      // In Letter[] mode
      if (!this.lines || this.lines.length === 0) return;

      let lineNum = this.startNumber || 1;
      let sectionIndex = -1;
      const numbered = this.lines.map((l, i) => {
        // Skip control lines (# @ & $) and empty lines
        if (this.isAtfControlLine(l.letter)) {
          if (this.isSectionResetMarker(l.letter)) {
            sectionIndex++;
            if (this.sectionNumbering === 'reset') {
              lineNum = this.startNumber || 1;
            }
          }
          // Continue sections: keep same sectionIndex and numbering
          if (this.isSectionContinueMarker(l.letter)) {
            // no-op: inherit parent section's style and numbering
          }
          const letter = new Letter(l.letter);
          letter.index = new Index(i, 0);
          return letter;
        }
        if (sectionIndex < 0) { sectionIndex = 0; }

        const suffix = this.getSectionSuffix(sectionIndex);
        const num = `${lineNum}${suffix}. `;
        // Remove existing line number if present
        const text = l.letter.replace(/^\d+'?\.\s*/, '');
        lineNum++;
        const letter = new Letter(num + text);
        letter.index = new Index(i, 0);
        return letter;
      });
      this.lines = numbered;
      this.lineCount = numbered.length;
      this.suppressUpdate = true;
      this.textContent = numbered.map(l => l.letter).join('\n');
      if (this.aceEditor) {
        this.aceEditor.setValue(this.textContent, -1);
      }
      this.suppressUpdate = false;
      this.lineChanged.emit(this.lines);
    }
  }

  // --- Find & Replace (ACE built-in) ---

  openAceSearch(): void {
    if (this.aceEditor) {
      this.aceEditor.execCommand('replace');
    }
  }

  onKeydown(event: KeyboardEvent): void {
    if ((event.ctrlKey || event.metaKey) && event.key === 'h') {
      event.preventDefault();
      this.openAceSearch();
    }
  }

  // --- Validation ---

  getBadLineMessage(): string | null {
    if (this.boxAmount == null) return 'no bounding boxes';
    if (!this.lines || this.lines.length === 0) return null;
    if (this.boxAmount > this.lines.length) {
      return `${this.boxAmount} boxes and only ${this.lines.length} lines`;
    } else if (this.boxAmount < this.lines.length) {
      return `${this.lines.length} lines and only ${this.boxAmount} boxes`;
    }
    return null;
  }

  /**
   * Update ACE editor annotations based on validation errors.
   * Uses structured ValidationError objects with line, column, and message.
   * Shows error markers in the gutter and highlights the error position.
   */
  private updateValidationAnnotations(): void {
    if (!this.aceEditor) return;

    const session = this.aceEditor.getSession();

    // Clear previous error markers
    this.clearErrorMarkers();

    if (!this.validationErrors || this.validationErrors.length === 0) {
      // Clear all annotations
      session.setAnnotations([]);
      return;
    }

    const annotations: ace.Ace.Annotation[] = [];
    const Range = ace.require('ace/range').Range;

    for (const error of this.validationErrors) {
      // Handle both structured errors (new) and string errors (legacy fallback)
      let lineNum: number;
      let column: number | undefined;
      let message: string;

      if (typeof error === 'string') {
        // Legacy string format: "Line X: message" or "Line X, col Y: message"
        const lineColMatch = (error as string).match(/^Line\s+(\d+)(?:,?\s*col(?:umn)?\s*(\d+))?[:\s]+(.*)$/i);
        if (lineColMatch) {
          lineNum = parseInt(lineColMatch[1], 10);
          column = lineColMatch[2] ? parseInt(lineColMatch[2], 10) : undefined;
          message = lineColMatch[3] || error as string;
        } else {
          lineNum = 1;
          message = error as string;
        }
      } else {
        // Structured error object
        lineNum = error.line;
        column = error.column;
        message = error.message;
      }

      // Add annotation (gutter marker)
      annotations.push({
        row: lineNum - 1, // ACE uses 0-based line numbers
        column: column ? column - 1 : 0, // ACE uses 0-based columns
        text: message,
        type: 'error'
      });

      // Add marker to highlight the error position
      const row = lineNum - 1;
      if (column !== undefined && column > 0) {
        const col = column - 1;
        // Highlight a few characters starting at the error position
        const endCol = Math.min(col + 5, session.getLine(row)?.length || col + 5);
        const range = new Range(row, col, row, endCol);
        const markerId = session.addMarker(range, 'ace_error-column-highlight', 'text', false);
        this.errorMarkers.push(markerId);
      } else {
        // No column — highlight the entire line
        const lineLength = session.getLine(row)?.length || 0;
        if (lineLength > 0) {
          const range = new Range(row, 0, row, lineLength);
          const markerId = session.addMarker(range, 'ace_error-column-highlight', 'text', false);
          this.errorMarkers.push(markerId);
        }
      }
    }

    session.setAnnotations(annotations);
  }

  /**
   * Clear all error column markers from the editor.
   */
  private clearErrorMarkers(): void {
    if (!this.aceEditor) return;

    const session = this.aceEditor.getSession();
    for (const markerId of this.errorMarkers) {
      session.removeMarker(markerId);
    }
    this.errorMarkers = [];
  }

  /**
   * Clear all validation annotations from the editor.
   */
  clearValidationAnnotations(): void {
    if (this.aceEditor) {
      this.aceEditor.getSession().setAnnotations([]);
      this.clearErrorMarkers();
    }
  }

  // --- Theme ---

  toggleDarkMode(): void {
    this.darkMode = !this.darkMode;
    if (this.aceEditor) {
      this.aceEditor.setTheme(this.darkMode ? 'ace/theme/cured_dark' : 'ace/theme/cured');
    }
  }

  // --- Editor Zoom ---

  zoomEditorIn(): void {
    if (this.editorFontSize < this.maxFontSize) {
      this.editorFontSize = Math.min(this.maxFontSize, this.editorFontSize + 2);
      this.applyEditorFontSize();
    }
  }

  zoomEditorOut(): void {
    if (this.editorFontSize > this.minFontSize) {
      this.editorFontSize = Math.max(this.minFontSize, this.editorFontSize - 2);
      this.applyEditorFontSize();
    }
  }

  resetEditorZoom(): void {
    this.editorFontSize = 14;
    this.applyEditorFontSize();
  }

  private applyEditorFontSize(): void {
    if (this.aceEditor) {
      this.aceEditor.setFontSize(this.editorFontSize);
    }
  }

  onEditorWheel(event: WheelEvent): void {
    // Zoom with Ctrl+wheel (standard editor behavior)
    if (event.ctrlKey) {
      event.preventDefault();
      if (event.deltaY < 0) {
        this.zoomEditorIn();
      } else {
        this.zoomEditorOut();
      }
    }
  }

  // --- Replacement Chart ---

  toggleReplacementChart(): void {
    this.toggleRightPanel('replacement');
  }

  get mappingCategories(): string[] {
    return this.mappingsService.getCategories();
  }

  getMappingsByCategory(category: string): ReplacementMapping[] {
    return this.mappingsService.getMappingsByCategory(category);
  }

  toggleMapping(mapping: ReplacementMapping): void {
    this.mappingsService.toggleMapping(mapping);
  }

  toggleCategoryMappings(category: string): void {
    this.mappingsService.toggleCategoryMappings(category);
  }

  addMapping(): void {
    if (!this.newMappingFrom) return;
    this.mappingsService.addMapping(this.newMappingFrom, this.newMappingTo, this.newMappingCategory || 'Custom');
    this.newMappingFrom = '';
    this.newMappingTo = '';
  }

  removeMapping(mapping: ReplacementMapping): void {
    this.mappingsService.removeMapping(mapping);
  }

  resetMappings(): void {
    this.mappingsService.resetToDefaults();
  }
}
