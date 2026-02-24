import { AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter, Input, NgZone, OnDestroy, Output, ViewChild } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { Index, Letter, LetterHover } from 'src/app/models/letter';

import { AtfConverterService } from 'src/app/services/atf-converter.service';
import { CuredService } from 'src/app/services/cured.service';

@Component({
  selector: 'text-editor',
  templateUrl: './text-editor.component.html',
  styleUrls: ['./text-editor.component.scss']
})
export class TextEditorComponent implements AfterViewInit, OnDestroy {

  @Input() public canEdit: boolean = true;
  @Input() public boxAmount: number = null;
  @Input() public lines: Letter[] = null;

  @Output() lineHover: EventEmitter<LetterHover> = new EventEmitter();
  @Output() lineChanged: EventEmitter<Letter[]> = new EventEmitter();
  @Output() lineDeleted: EventEmitter<number> = new EventEmitter();
  @Output() regexMatchLines: EventEmitter<number[]> = new EventEmitter();

  @ViewChild('editor', { static: false }) editorRef: ElementRef<HTMLDivElement>;

  public textContent: string = '';
  public lineCount: number = 0;
  public numberStyle: 'plain' | 'prime' = 'plain';
  public startNumber: number = 1;
  public viewMode: 'raw' | 'norm' | 'atf' = 'raw';
  public darkMode: boolean = false;

  // Normalization (Akkadian post-processing)
  public isNormalizing: boolean = false;
  public normalizeResult: string = null;
  public normalizeCount: number = 0;
  public isNormalized: boolean = false;
  public originalLines: string[] = null;
  public normalizedLines: string[] = null;

  // Find & Replace
  public showFindReplace: boolean = false;
  public findText: string = '';
  public replaceText: string = '';
  public useRegex: boolean = false;
  public caseSensitive: boolean = false;
  public matchCount: number = 0;

  private suppressUpdate: boolean = false;

  constructor(
    private atfConverter: AtfConverterService,
    private curedService: CuredService,
    private sanitizer: DomSanitizer,
    private cdr: ChangeDetectorRef,
    private ngZone: NgZone
  ) { }

  // --- Public API (called by parent CuredComponent) ---

  setLines(lines: Letter[]): void {
    this.lines = lines;
    this.lineCount = lines.length;
    this.suppressUpdate = true;
    this.textContent = lines.map(l => l.letter).join('\n');
    this.renderHighlightedContent();
    this.suppressUpdate = false;
  }

  setNewSelectedLine(index: Index): void {
    // No-op for this approach
  }

  hardReset(): void {
    this.lines = [];
    this.lineCount = 0;
    this.normalizeResult = null;
    this.isNormalizing = false;
    this.isNormalized = false;
    this.originalLines = null;
    this.normalizedLines = null;
    this.suppressUpdate = true;
    this.textContent = '';
    this.renderHighlightedContent();
    this.suppressUpdate = false;
  }

  // --- Lifecycle ---

  ngAfterViewInit(): void {
    // Initial render if there's content
    if (this.textContent) {
      this.renderHighlightedContent();
    }
  }

  ngOnDestroy(): void { }

  // --- View Mode ---

  onViewModeChange(): void {
    if (this.viewMode === 'atf') {
      this.textContent = this.atfConverter.toAtf(this.textContent);
    } else if (this.viewMode === 'norm') {
      // Norm mode just renders markdown formatting, no text conversion needed
    } else {
      // raw mode
      const rawText = this.atfConverter.fromAtf(this.textContent);
      this.textContent = rawText;
      this.refreshLinesFromText();
    }
    this.renderHighlightedContent();
  }

  // --- Contenteditable input handling ---

  onEditorInput(event: Event): void {
    if (this.suppressUpdate) return;

    const editor = this.editorRef?.nativeElement;
    if (!editor) return;

    // Extract plain text from contenteditable (don't re-render during typing)
    const plainText = this.getPlainTextFromEditor(editor);
    this.textContent = plainText;

    // Update lines
    if (this.viewMode === 'atf') {
      const rawText = this.atfConverter.fromAtf(this.textContent);
      this.updateLinesFromText(rawText);
    } else {
      this.updateLinesFromText(this.textContent);
    }

    if (this.findText) {
      this.updateMatchCount();
    }
  }

  onEditorBlur(): void {
    // Apply highlighting when user leaves the editor
    this.renderHighlightedContent();
  }

  onEditorPaste(event: ClipboardEvent): void {
    event.preventDefault();
    const text = event.clipboardData?.getData('text/plain') || '';
    document.execCommand('insertText', false, text);
  }

  private renderHighlightedContent(): void {
    const editor = this.editorRef?.nativeElement;
    if (!editor) return;

    const html = this.getHighlightedHtml();
    editor.innerHTML = html;

    // Force browser reflow to ensure styles are applied immediately
    // This fixes the issue where monospace font isn't applied until window focus changes
    void editor.offsetHeight;

    // Trigger Angular change detection
    this.cdr.detectChanges();
  }

  private getPlainTextFromEditor(editor: HTMLElement): string {
    let text = '';
    const walk = (node: Node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        text += node.textContent || '';
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        const el = node as HTMLElement;
        const tag = el.tagName.toLowerCase();

        if ((tag === 'div' || tag === 'p') && text.length > 0 && !text.endsWith('\n')) {
          text += '\n';
        }

        for (let i = 0; i < node.childNodes.length; i++) {
          walk(node.childNodes[i]);
        }

        if (tag === 'br') {
          text += '\n';
        }
      }
    };

    for (let i = 0; i < editor.childNodes.length; i++) {
      walk(editor.childNodes[i]);
    }

    return text;
  }

  private updateLinesFromText(text: string): void {
    const newLines = text.split('\n');
    this.lines = newLines.map((t, row) => {
      const letter = new Letter(t);
      letter.index = new Index(row, 0);
      return letter;
    });
    this.lineCount = this.lines.length;
    this.lineChanged.emit(this.lines);
  }

  private refreshLinesFromText(): void {
    this.updateLinesFromText(this.textContent);
  }

  // --- Actions ---

  applyNormalization(): void {
    if (!this.lines || this.lines.length === 0 || this.isNormalizing) return;

    this.isNormalizing = true;
    this.normalizeResult = null;

    const lineTexts = this.lines.map(l => l.letter);
    this.originalLines = [...lineTexts];

    this.curedService.applyPostProcessing(lineTexts).subscribe(
      result => {
        this.isNormalizing = false;

        const totalCorrections = result.corrections.reduce(
          (sum, c) => sum + c.corrections_count, 0
        );

        if (totalCorrections > 0) {
          this.normalizedLines = result.lines;

          this.suppressUpdate = true;
          this.textContent = result.lines.join('\n');
          this.renderHighlightedContent();
          this.suppressUpdate = false;

          this.lines = result.lines.map((text, row) => {
            const letter = new Letter(text);
            letter.index = new Index(row, 0);
            return letter;
          });
          this.lineCount = this.lines.length;
          this.lineChanged.emit(this.lines);

          this.normalizeCount = totalCorrections;
          this.normalizeResult = 'applied';
          this.isNormalized = true;
        } else {
          this.normalizeResult = 'none';
          this.originalLines = null;
          this.normalizedLines = null;
        }

        setTimeout(() => { this.normalizeResult = null; }, 5000);
      },
      error => {
        this.isNormalizing = false;
        this.originalLines = null;
        console.error('Normalization failed:', error);
      }
    );
  }

  toggleNormalization(): void {
    if (!this.originalLines || !this.normalizedLines) return;

    this.isNormalized = !this.isNormalized;
    const linesToShow = this.isNormalized ? this.normalizedLines : this.originalLines;

    this.suppressUpdate = true;
    this.textContent = linesToShow.join('\n');
    this.renderHighlightedContent();
    this.suppressUpdate = false;

    this.lines = linesToShow.map((text, row) => {
      const letter = new Letter(text);
      letter.index = new Index(row, 0);
      return letter;
    });
    this.lineCount = this.lines.length;
    this.lineChanged.emit(this.lines);
  }

  removeEmptyLines(): void {
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
    this.renderHighlightedContent();
    this.suppressUpdate = false;
    this.lineChanged.emit(this.lines);
    this.normalizeResult = null;
  }

  get numberStyleLabel(): string {
    return this.numberStyle === 'plain' ? '1' : "1'";
  }

  toggleNumberStyle(): void {
    this.numberStyle = this.numberStyle === 'plain' ? 'prime' : 'plain';
  }

  addLineNumbers(): void {
    if (!this.lines || this.lines.length === 0) return;
    const suffix = this.numberStyle === 'prime' ? "'" : '';
    const numbered = this.lines.map((l, i) => {
      const num = `${(this.startNumber || 1) + i}${suffix}. `;
      const text = l.letter.replace(/^\d+'?\.\s*/, '');
      const letter = new Letter(num + text);
      letter.index = new Index(i, 0);
      return letter;
    });
    this.lines = numbered;
    this.lineCount = numbered.length;
    this.suppressUpdate = true;
    this.textContent = numbered.map(l => l.letter).join('\n');
    this.renderHighlightedContent();
    this.suppressUpdate = false;
    this.lineChanged.emit(this.lines);
  }

  // --- Find & Replace ---

  toggleFindReplace(): void {
    this.showFindReplace = !this.showFindReplace;
    if (!this.showFindReplace) {
      this.findText = '';
      this.replaceText = '';
      this.matchCount = 0;
    }
  }

  onKeydown(event: KeyboardEvent): void {
    if ((event.ctrlKey || event.metaKey) && event.key === 'h') {
      event.preventDefault();
      this.showFindReplace = true;
    }
  }

  onFindChanged(): void {
    this.updateMatchCount();
  }

  private updateMatchCount(): void {
    if (!this.findText) {
      this.matchCount = 0;
      return;
    }
    try {
      const regex = this.buildRegex(this.findText);
      if (!regex) {
        this.matchCount = 0;
        return;
      }
      const matches = this.textContent.match(regex);
      this.matchCount = matches ? matches.length : 0;
    } catch {
      this.matchCount = 0;
    }
  }

  private buildRegex(pattern: string): RegExp | null {
    if (!pattern) return null;
    try {
      const flags = 'g' + (this.caseSensitive ? '' : 'i');
      if (this.useRegex) {
        return new RegExp(pattern, flags);
      } else {
        const escaped = pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        return new RegExp(escaped, flags);
      }
    } catch {
      return null;
    }
  }

  replaceNext(): void {
    if (!this.findText) return;
    const regex = this.buildRegex(this.findText);
    if (!regex) return;

    const singleMatch = this.useRegex
      ? new RegExp(this.findText, this.caseSensitive ? '' : 'i')
      : new RegExp(this.findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), this.caseSensitive ? '' : 'i');

    const match = this.textContent.match(singleMatch);
    if (match && match.index !== undefined) {
      const matchStart = match.index;
      const matchEnd = matchStart + match[0].length;
      this.textContent =
        this.textContent.substring(0, matchStart) +
        this.replaceText +
        this.textContent.substring(matchEnd);
      this.renderHighlightedContent();
      this.refreshLinesFromText();
      this.updateMatchCount();
    }
  }

  replaceAll(): void {
    if (!this.findText) return;
    const regex = this.buildRegex(this.findText);
    if (!regex) return;
    this.textContent = this.textContent.replace(regex, this.replaceText);
    this.renderHighlightedContent();
    this.refreshLinesFromText();
    this.updateMatchCount();
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

  // --- Theme ---

  toggleDarkMode(): void {
    this.darkMode = !this.darkMode;
  }

  // --- Highlighting ---

  private getHighlightedHtml(): string {
    if (!this.textContent) {
      return '';
    }

    let html = this.escapeHtml(this.textContent);

    // Markdown formatting for 'norm' mode
    if (this.viewMode === 'norm') {
      // Bold notation **text** - render as bold (must be before italic to avoid conflicts)
      html = html.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');

      // Italic notation _text_ (Nemotron format) - render as italics
      html = html.replace(/_([^_\n]+)_/g, '<i class="hl-italic">$1</i>');

      // Italic notation *text* (alternative format) - render as italics
      html = html.replace(/\*([^*\n]+)\*/g, '<i class="hl-italic">$1</i>');

      // Superscript <sup>text</sup> - render as superscript (escaped version)
      html = html.replace(/&lt;sup&gt;([^&]+)&lt;\/sup&gt;/g, '<sup>$1</sup>');

      // Subscript <sub>text</sub> - render as subscript (escaped version)
      html = html.replace(/&lt;sub&gt;([^&]+)&lt;\/sub&gt;/g, '<sub>$1</sub>');

      // Line break <br> - render as line break (escaped version)
      html = html.replace(/&lt;br&gt;/g, '<br>');
    }

    // Square brackets (damage/break) - red
    html = html.replace(/\[/g, '<span class="hl-square">[</span>');
    html = html.replace(/\]/g, '<span class="hl-square">]</span>');

    // Parentheses (supplied by context) - purple
    html = html.replace(/\(/g, '<span class="hl-paren">(</span>');
    html = html.replace(/\)/g, '<span class="hl-paren">)</span>');

    // Angle brackets (omitted by scribe) - blue
    html = html.replace(/&lt;/g, '<span class="hl-angle">&lt;</span>');
    html = html.replace(/&gt;/g, '<span class="hl-angle">&gt;</span>');

    // Curly braces (determinative) - green
    html = html.replace(/\{/g, '<span class="hl-curly">{</span>');
    html = html.replace(/\}/g, '<span class="hl-curly">}</span>');

    // Half brackets (partially damaged) - orange
    html = html.replace(/⸢/g, '<span class="hl-half">⸢</span>');
    html = html.replace(/⸣/g, '<span class="hl-half">⸣</span>');

    // Convert newlines to <br>
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
}
