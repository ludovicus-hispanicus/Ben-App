import { Component, EventEmitter, HostListener, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { Subject, Subscription } from 'rxjs';
import { debounceTime } from 'rxjs/operators';
import {
    LemmatizationService,
    TokenizedText, AtfLine, AtfToken,
    TextLemmatization, LineLemmatization, LemmaAssignment,
    WordEntry, DictionaryStatus
} from '../../../services/lemmatization.service';
import { ConfirmDialogComponent } from '../../common/confirm-dialog/confirm-dialog.component';

@Component({
    selector: 'lemmatization-panel',
    templateUrl: './lemmatization-panel.component.html',
    styleUrls: ['./lemmatization-panel.component.scss']
})
export class LemmatizationPanelComponent implements OnInit, OnChanges, OnDestroy {

    @Input() atfText: string = '';
    @Input() productionId: number = 0;
    @Input() fragmentNumber: string = '';

    @Output() lemmatizationChanged = new EventEmitter<TextLemmatization>();

    // State
    tokenizedText: TokenizedText | null = null;
    lemmatization: TextLemmatization | null = null;
    dictionaryStatus: DictionaryStatus | null = null;

    isTokenizing = false;
    isDownloadingDict = false;
    isAiSuggesting = false;
    isExporting = false;
    isSaving = false;
    isAutoSaving = false;

    // Autosave: debounce changes and persist quietly. Flush on destroy so
    // toggling back to transliteration doesn't lose unsaved assignments.
    private autoSaveSubject = new Subject<void>();
    private autoSaveSubscription?: Subscription;
    private hasUnsavedChanges = false;
    private static readonly AUTOSAVE_DEBOUNCE_MS = 800;

    // Token selection popup
    selectedLine: AtfLine | null = null;
    selectedToken: AtfToken | null = null;
    selectedTokenLineIdx = -1;
    selectedTokenIdx = -1;
    popupVisible = false;
    popupX = 0;
    popupY = 0;
    wordSearchQuery = '';
    searchResults: WordEntry[] = [];
    isSearching = false;

    // Suffix dictionary search (free-form lookup with suffix-entry priority)
    suffixSearchQuery = '';
    suffixSearchResults: WordEntry[] = [];
    isSearchingSuffix = false;

    // Candidate entries loaded for selected token
    candidateEntries: WordEntry[] = [];

    // Notification
    notification: string = '';
    notificationType: 'success' | 'error' | 'info' = 'info';

    @HostListener('document:keydown.escape')
    onEscapeKey(): void {
        if (this.popupVisible) {
            this.closePopup();
        }
    }

    constructor(
        private lemmatizationService: LemmatizationService,
        private dialog: MatDialog
    ) {}

    ngOnInit(): void {
        this.autoSaveSubscription = this.autoSaveSubject.pipe(
            debounceTime(LemmatizationPanelComponent.AUTOSAVE_DEBOUNCE_MS)
        ).subscribe(() => this.autoSave());

        this.lemmatizationService.getDictionaryStatus().subscribe(status => {
            this.dictionaryStatus = status;
        });

        // Load existing lemmatization if available
        if (this.productionId) {
            console.log('[LemPanel] ngOnInit: loading lemmatization for', this.productionId);
            this.lemmatizationService.getLemmatization(this.productionId).subscribe({
                next: (data) => {
                    console.log('[LemPanel] Loaded saved lemmatization:', data.lines.length, 'lines, hash:', data.content_hash);
                    this.lemmatization = data;
                    // Tokenize to get line/token structure (candidates, morph analysis)
                    // But pass flag to preserve saved assignments
                    this.tokenize(true);
                },
                error: (err) => {
                    console.log('[LemPanel] No saved lemmatization found:', err.status);
                    // No saved lemmatization — tokenize fresh
                    this.tokenize(false);
                }
            });
        } else {
            console.log('[LemPanel] ngOnInit: no productionId, skipping');
        }
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['atfText'] && !changes['atfText'].firstChange) {
            // Text changed — check if re-sync needed
            if (this.tokenizedText && this.lemmatization) {
                // Hash mismatch means text was edited
                // Don't auto-retokenize — show a sync button
            }
        }
    }

    ngOnDestroy(): void {
        this.autoSaveSubscription?.unsubscribe();
        // Flush any pending autosave so toggling back to transliteration
        // doesn't lose unsaved lemma assignments.
        if (this.hasUnsavedChanges && this.lemmatization && this.productionId) {
            this.lemmatizationService.saveLemmatization(this.productionId, this.lemmatization).subscribe({
                error: (err) => console.error('[LemPanel] Final flush save failed:', err)
            });
            this.hasUnsavedChanges = false;
        }
    }

    /**
     * Single funnel for change events: emits to the parent and schedules a
     * debounced autosave. Use instead of calling `lemmatizationChanged.emit` directly.
     */
    private emitChange(): void {
        if (!this.lemmatization) return;
        this.lemmatizationChanged.emit(this.lemmatization);
        this.hasUnsavedChanges = true;
        this.autoSaveSubject.next();
    }

    private autoSave(): void {
        if (!this.lemmatization || !this.productionId || !this.hasUnsavedChanges) return;
        this.isAutoSaving = true;
        this.lemmatizationService.saveLemmatization(this.productionId, this.lemmatization).subscribe({
            next: (result) => {
                this.lemmatization = result;
                this.hasUnsavedChanges = false;
                this.isAutoSaving = false;
            },
            error: (err) => {
                this.isAutoSaving = false;
                console.error('[LemPanel] Autosave failed:', err);
            }
        });
    }

    // ── Tokenization ──

    tokenize(preserveAssignments: boolean = false): void {
        if (!this.atfText) return;
        this.isTokenizing = true;
        this.lemmatizationService.tokenize(this.atfText).subscribe({
            next: (result) => {
                this.tokenizedText = result;
                this.isTokenizing = false;

                if (preserveAssignments && this.lemmatization) {
                    // Realign saved assignments to match tokenizer's structure.
                    // The saved lemmatization may have different token counts per line
                    // (e.g., ORACC import splits tokens differently than ATF tokenizer).
                    this.alignSavedLemmatization();
                    return;
                } else if (this.lemmatization) {
                    // Manual sync requested — merge
                    this.mergeExistingLemmatization();
                } else {
                    // No existing lemmatization — create empty from tokens
                    this.initEmptyLemmatization();
                }
            },
            error: (err) => {
                this.isTokenizing = false;
                this.showNotification('Tokenization failed: ' + (err.error?.detail || err.message), 'error');
            }
        });
    }

    alignSavedLemmatization(): void {
        // Rebuild lemmatization structure aligned to tokenizer output,
        // transferring saved assignments by matching token values.
        if (!this.tokenizedText || !this.lemmatization) return;

        // Build a lookup: line_number → { token_value → unique_lemma[] }
        // Use an array of lemmas per value to handle duplicates on the same line
        const savedMap = new Map<string, Map<string, string[][]>>();
        for (const line of this.lemmatization.lines) {
            const tokenMap = new Map<string, string[][]>();
            for (const tok of line.tokens) {
                if (!tokenMap.has(tok.value)) {
                    tokenMap.set(tok.value, []);
                }
                tokenMap.get(tok.value)!.push(tok.unique_lemma);
            }
            // Accumulate under the same line number (some texts have duplicate line numbers)
            const key = line.line_number;
            if (!savedMap.has(key)) {
                savedMap.set(key, tokenMap);
            } else {
                // Merge token maps for duplicate line numbers
                const existing = savedMap.get(key)!;
                for (const [val, lemmas] of tokenMap) {
                    if (!existing.has(val)) {
                        existing.set(val, []);
                    }
                    existing.get(val)!.push(...lemmas);
                }
            }
        }

        const newLines: LineLemmatization[] = [];
        for (const line of this.tokenizedText.lines) {
            if (line.line_type !== 'text') continue;

            const tokenMap = savedMap.get(line.line_number);
            const tokens: LemmaAssignment[] = line.tokens.map(t => {
                if (tokenMap) {
                    const lemmaQueue = tokenMap.get(t.raw);
                    if (lemmaQueue && lemmaQueue.length > 0) {
                        const lemma = lemmaQueue.shift()!;
                        if (lemma.length > 0) {
                            return { value: t.raw, unique_lemma: lemma };
                        }
                    }
                }
                // No saved assignment — auto-assign if single exact match
                const isExact = t.match_level === 'exact';
                if (isExact && t.lemma_candidates.length === 1) {
                    return { value: t.raw, unique_lemma: [t.lemma_candidates[0]] };
                }
                return { value: t.raw, unique_lemma: [] };
            });
            newLines.push({ line_number: line.line_number, tokens });
        }

        this.lemmatization = {
            ...this.lemmatization,
            content_hash: this.tokenizedText.content_hash,
            lines: newLines
        };
    }

    initEmptyLemmatization(): void {
        if (!this.tokenizedText) return;
        const lines: LineLemmatization[] = [];
        for (const line of this.tokenizedText.lines) {
            if (line.line_type !== 'text') continue;
            const tokens: LemmaAssignment[] = line.tokens.map(t => {
                const isExact = t.match_level === 'exact';

                if (isExact && t.is_complex && t.lemma_candidates.length >= 1 && t.suffix_lemma) {
                    // Exact complex token: auto-assign base + suffix
                    return { value: t.raw, unique_lemma: [t.lemma_candidates[0], t.suffix_lemma] };
                } else if (isExact && t.lemma_candidates.length === 1) {
                    // Exact single match: auto-assign
                    return { value: t.raw, unique_lemma: [t.lemma_candidates[0]] };
                }
                // Suggestions and no-match: leave unassigned (user must confirm)
                return { value: t.raw, unique_lemma: [] };
            });
            lines.push({ line_number: line.line_number, tokens });
        }
        this.lemmatization = {
            production_id: this.productionId,
            content_hash: this.tokenizedText.content_hash,
            lines,
            last_modified: '',
            ai_suggested: false
        };
    }

    mergeExistingLemmatization(): void {
        // Preserve lemma assignments for lines that haven't changed
        if (!this.tokenizedText || !this.lemmatization) return;

        const oldLineMap = new Map<string, LineLemmatization>();
        for (const line of this.lemmatization.lines) {
            oldLineMap.set(line.line_number, line);
        }

        const newLines: LineLemmatization[] = [];
        for (const line of this.tokenizedText.lines) {
            if (line.line_type !== 'text') continue;

            const oldLine = oldLineMap.get(line.line_number);
            if (oldLine) {
                // Try to match tokens by value
                const tokens: LemmaAssignment[] = line.tokens.map(t => {
                    const oldToken = oldLine.tokens.find(ot => ot.value === t.raw);
                    if (oldToken && oldToken.unique_lemma.length > 0) {
                        // Check if old lemma is an ORACC placeholder (contains "(...) [...]")
                        // and dictionary has a resolved candidate — upgrade it
                        const isOraccFormat = oldToken.unique_lemma[0].includes('(') &&
                                              oldToken.unique_lemma[0].includes('[');
                        if (isOraccFormat && t.lemma_candidates.length >= 1) {
                            return { value: t.raw, unique_lemma: [t.lemma_candidates[0]] };
                        }
                        return { value: t.raw, unique_lemma: oldToken.unique_lemma };
                    }
                    return {
                        value: t.raw,
                        unique_lemma: t.lemma_candidates.length === 1 ? [t.lemma_candidates[0]] : []
                    };
                });
                newLines.push({ line_number: line.line_number, tokens });
            } else {
                const tokens: LemmaAssignment[] = line.tokens.map(t => ({
                    value: t.raw,
                    unique_lemma: t.lemma_candidates.length === 1 ? [t.lemma_candidates[0]] : []
                }));
                newLines.push({ line_number: line.line_number, tokens });
            }
        }

        this.lemmatization = {
            ...this.lemmatization,
            content_hash: this.tokenizedText.content_hash,
            lines: newLines
        };
    }

    // ── Dictionary ──

    downloadDictionary(): void {
        this.isDownloadingDict = true;
        this.showNotification('Downloading eBL dictionary...', 'info');
        this.lemmatizationService.downloadDictionary().subscribe({
            next: (result) => {
                this.isDownloadingDict = false;
                if (result.status === 'complete') {
                    this.showNotification(`Dictionary downloaded: ${result.word_count} words`, 'success');
                    this.lemmatizationService.getDictionaryStatus().subscribe(s => this.dictionaryStatus = s);
                    // Re-tokenize to get candidates
                    this.tokenize();
                } else if (result.status === 'error') {
                    this.showNotification('Download failed: ' + result.error, 'error');
                }
            },
            error: (err) => {
                this.isDownloadingDict = false;
                this.showNotification('Download failed: ' + (err.error?.detail || err.message), 'error');
            }
        });
    }

    // ── Token Selection ──

    onTokenClick(event: MouseEvent, line: AtfLine, token: AtfToken, lineIdx: number, tokenIdx: number): void {
        if (token.is_determinative || token.is_number) return;

        this.selectedLine = line;
        this.selectedToken = token;
        this.selectedTokenLineIdx = lineIdx;
        this.selectedTokenIdx = tokenIdx;
        this.wordSearchQuery = '';
        this.searchResults = [];
        this.suffixSearchQuery = '';
        this.suffixSearchResults = [];
        this.candidateEntries = [];

        // Position popup near the clicked token
        const rect = (event.target as HTMLElement).getBoundingClientRect();
        this.popupX = rect.left;
        this.popupY = rect.bottom + 4;
        this.popupVisible = true;

        // Collect all candidate IDs: from tokenizer + from current lemmatization
        const candidateIds = new Set<string>(token.lemma_candidates || []);

        // Also include the currently assigned lemma (if any)
        const assignedLemma = this.getTokenLemma(line, tokenIdx);
        if (assignedLemma) {
            for (const lid of assignedLemma.split(', ')) {
                if (lid.trim()) candidateIds.add(lid.trim());
            }
        }

        // Load candidate word entries
        if (candidateIds.size > 0) {
            for (const cid of candidateIds) {
                this.lemmatizationService.getWordEntry(cid).subscribe({
                    next: (entry) => this.candidateEntries.push(entry),
                    error: (err) => {
                        console.warn(`Failed to load word entry '${cid}':`, err);
                    }
                });
            }
        }
    }

    closePopup(): void {
        this.popupVisible = false;
        this.selectedToken = null;
        this.selectedLine = null;
    }

    assignLemma(lemmaId: string, asSuffix: boolean = false): void {
        if (!this.lemmatization || this.selectedTokenLineIdx < 0 || this.selectedTokenIdx < 0) return;

        // Find the corresponding line in lemmatization
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const textLineIdx = textLines.findIndex(l => l === this.selectedLine);
        if (textLineIdx < 0 || textLineIdx >= this.lemmatization.lines.length) return;

        const lemmaLine = this.lemmatization.lines[textLineIdx];
        let assignedLemma: string[] = [];
        if (this.selectedTokenIdx < lemmaLine.tokens.length) {
            const token = lemmaLine.tokens[this.selectedTokenIdx];
            if (asSuffix) {
                // Replace or add suffix lemma (keep base lemma)
                const baseLemma = token.unique_lemma.length > 0 ? token.unique_lemma[0] : '';
                token.unique_lemma = baseLemma ? [baseLemma, lemmaId] : [lemmaId];
            } else if (this.selectedToken?.is_complex && this.selectedToken.suffix_lemma) {
                // Complex token: set as base lemma, keep existing suffix
                const existingSuffix = token.unique_lemma.length > 1 ? token.unique_lemma[1] : this.selectedToken.suffix_lemma;
                token.unique_lemma = [lemmaId, existingSuffix];
            } else {
                token.unique_lemma = [lemmaId];
            }
            assignedLemma = token.unique_lemma;
        }

        // Capture values before closePopup nulls selectedToken
        const cleaned = this.selectedToken?.cleaned || '';
        const matchCount = !asSuffix && cleaned
            ? this.countMatchingUnassigned(cleaned, textLineIdx, this.selectedTokenIdx)
            : 0;

        // If the token was unmatched/suggestion, save as custom mapping for future lookups
        if (this.selectedToken && !asSuffix &&
            (this.selectedToken.match_level === 'none' || this.selectedToken.match_level === 'unmatched')) {
            this.lemmatizationService.addCustomMapping(this.selectedToken.cleaned, lemmaId).subscribe();
        }

        this.emitChange();
        this.closePopup();

        // Offer to propagate if there are matching unassigned tokens
        if (matchCount > 0) {
            const dialogRef = this.dialog.open(ConfirmDialogComponent, {
                data: {
                    title: 'Apply to similar tokens',
                    message: `Apply "${lemmaId}" to ${matchCount} other unassigned "${cleaned}" token${matchCount > 1 ? 's' : ''}?`,
                    confirmText: 'Apply',
                    cancelText: 'Skip'
                }
            });
            dialogRef.afterClosed().subscribe(confirmed => {
                if (confirmed) {
                    const propagated = this.propagateLemma(cleaned, assignedLemma, textLineIdx, this.selectedTokenIdx);
                    this.showNotification(`Applied to ${propagated} occurrence${propagated > 1 ? 's' : ''}`, 'success');
                    this.emitChange();
                }
            });
        }
    }

    /**
     * Count unassigned tokens with the same cleaned value (excluding the given token).
     */
    private countMatchingUnassigned(cleanedValue: string, skipLineIdx: number, skipTokenIdx: number): number {
        if (!this.tokenizedText || !this.lemmatization) return 0;

        const textLines = this.tokenizedText.lines.filter(l => l.line_type === 'text');
        let count = 0;

        for (let li = 0; li < textLines.length; li++) {
            const line = textLines[li];
            if (li >= this.lemmatization.lines.length) break;
            const lemmaLine = this.lemmatization.lines[li];

            for (let ti = 0; ti < line.tokens.length; ti++) {
                if (li === skipLineIdx && ti === skipTokenIdx) continue;
                const token = line.tokens[ti];
                if (token.is_determinative || token.is_number) continue;
                if (token.cleaned !== cleanedValue) continue;
                if (ti >= lemmaLine.tokens.length) continue;
                if (lemmaLine.tokens[ti].unique_lemma.length > 0) continue;
                count++;
            }
        }
        return count;
    }

    /**
     * Propagate a lemma assignment to all unassigned tokens with the same cleaned value.
     * Returns the number of tokens that were updated.
     */
    private propagateLemma(
        cleanedValue: string, lemma: string[],
        skipLineIdx: number, skipTokenIdx: number
    ): number {
        if (!this.tokenizedText || !this.lemmatization) return 0;

        const textLines = this.tokenizedText.lines.filter(l => l.line_type === 'text');
        let count = 0;

        for (let li = 0; li < textLines.length; li++) {
            const line = textLines[li];
            if (li >= this.lemmatization.lines.length) break;
            const lemmaLine = this.lemmatization.lines[li];

            for (let ti = 0; ti < line.tokens.length; ti++) {
                // Skip the token we just assigned
                if (li === skipLineIdx && ti === skipTokenIdx) continue;

                const token = line.tokens[ti];
                if (token.is_determinative || token.is_number) continue;
                if (token.cleaned !== cleanedValue) continue;

                // Only propagate to unassigned tokens
                if (ti >= lemmaLine.tokens.length) continue;
                if (lemmaLine.tokens[ti].unique_lemma.length > 0) continue;

                lemmaLine.tokens[ti].unique_lemma = [...lemma];
                count++;
            }
        }
        return count;
    }

    clearLemma(): void {
        if (!this.lemmatization || this.selectedTokenLineIdx < 0 || this.selectedTokenIdx < 0) return;

        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const textLineIdx = textLines.findIndex(l => l === this.selectedLine);
        if (textLineIdx < 0 || textLineIdx >= this.lemmatization.lines.length) return;

        const lemmaLine = this.lemmatization.lines[textLineIdx];
        if (this.selectedTokenIdx < lemmaLine.tokens.length) {
            lemmaLine.tokens[this.selectedTokenIdx].unique_lemma = [];
        }

        this.emitChange();
        this.closePopup();
    }

    searchDictionary(): void {
        if (!this.wordSearchQuery || this.wordSearchQuery.length < 2) return;
        this.isSearching = true;
        this.lemmatizationService.searchWords(this.wordSearchQuery).subscribe({
            next: (results) => {
                this.searchResults = results;
                this.isSearching = false;
            },
            error: () => {
                this.isSearching = false;
            }
        });
    }

    // ── AI Suggestions ──

    aiSuggest(): void {
        if (!this.atfText || !this.productionId) return;
        this.isAiSuggesting = true;
        this.showNotification('Getting AI suggestions...', 'info');
        this.lemmatizationService.aiSuggest(this.productionId, this.atfText).subscribe({
            next: (result) => {
                this.lemmatization = result;
                this.isAiSuggesting = false;
                this.showNotification('AI suggestions applied', 'success');
                this.emitChange();
            },
            error: (err) => {
                this.isAiSuggesting = false;
                this.showNotification('AI suggestion failed: ' + (err.error?.detail || err.message), 'error');
            }
        });
    }

    // ── Suffix helpers ──

    private static SUFFIX_INFO: { [key: string]: { description: string, lemma_id: string } } = {
        'šu': { description: '3ms "his"', lemma_id: 'šū I' },
        'ša': { description: '3fs "her"', lemma_id: 'šī I' },
        'ka': { description: '2ms "your"', lemma_id: 'kâši I' },
        'ki': { description: '2fs "your"', lemma_id: 'kâši I' },
        'ja': { description: '1cs "my"', lemma_id: 'yâši I' },
        'ia': { description: '1cs "my"', lemma_id: 'yâši I' },
        'i':  { description: '1cs "my"', lemma_id: 'yâši I' },
        'ni': { description: '1cp "our"', lemma_id: 'niāti I' },
        'šunu': { description: '3mp "their"', lemma_id: 'šunu I' },
        'šina': { description: '3fp "their"', lemma_id: 'šina I' },
        'kunu': { description: '2mp "your (pl)"', lemma_id: 'kunu I' },
        'kina': { description: '2fp "your (pl)"', lemma_id: 'kina I' },
    };

    getUniqueMorphAnalyses(): any[] {
        if (!this.selectedToken?.morph_analysis?.length) return [];
        const seen = new Set<string>();
        const result: any[] = [];
        for (const m of this.selectedToken.morph_analysis) {
            const key = `${m.stem}-${m.tense}-${m.person}`;
            if (!seen.has(key)) {
                seen.add(key);
                result.push(m);
            }
        }
        return result;
    }

    getMorphForCandidate(wordId: string): string {
        if (!this.selectedToken?.morph_analysis?.length) return '';
        // Find morph analysis matching this candidate
        const matches = this.selectedToken.morph_analysis.filter(m => m.lemma_id === wordId);
        if (matches.length > 0) {
            const m = matches[0];
            const parts: string[] = [];
            if (m.stem) parts.push(m.stem);
            if (m.tense) parts.push(this.formatTense(m.tense));
            if (m.person) parts.push(m.person);
            return parts.join(' ');
        }
        return '';
    }

    formatTense(tense: string): string {
        const labels: Record<string, string> = {
            'pret': 'Preterite',
            'dur': 'Durative',
            'perf': 'Perfect',
            'imp': 'Imperative',
            'inf': 'Infinitive',
            'ptcp': 'Participle',
            'stat': 'Stative',
            'vadj': 'Verbal Adj.',
        };
        return labels[tense] || tense;
    }

    getAllSuffixOptions(): { suffix: string, lemma_id: string, description: string }[] {
        const seen = new Set<string>();
        const options: { suffix: string, lemma_id: string, description: string }[] = [];
        // Show common suffixes first (not single-char ambiguous ones)
        const priority = ['šu', 'ša', 'ka', 'ki', 'ja', 'ni', 'šunu', 'šina', 'kunu', 'kina', 'ia', 'i'];
        for (const suf of priority) {
            const info = LemmatizationPanelComponent.SUFFIX_INFO[suf];
            if (info && !seen.has(suf)) {
                seen.add(suf);
                options.push({ suffix: suf, lemma_id: info.lemma_id, description: info.description });
            }
        }
        return options;
    }

    /**
     * Free dictionary search for the suffix section. Reuses the regular
     * dictionary search but ranks suffix entries (lemma starts with `-`,
     * or guide_word marks as "suff.") to the top so the user can pick any
     * suffix from the dictionary, not just the curated quick-pick list.
     */
    searchSuffix(): void {
        const q = this.suffixSearchQuery.trim();
        if (q.length < 1) {
            this.suffixSearchResults = [];
            return;
        }
        this.isSearchingSuffix = true;
        this.lemmatizationService.searchWords(q, 50).subscribe({
            next: (results) => {
                results.sort((a, b) => {
                    const aIs = LemmatizationPanelComponent.isSuffixEntry(a) ? 0 : 1;
                    const bIs = LemmatizationPanelComponent.isSuffixEntry(b) ? 0 : 1;
                    return aIs - bIs;
                });
                this.suffixSearchResults = results;
                this.isSearchingSuffix = false;
            },
            error: () => { this.isSearchingSuffix = false; }
        });
    }

    /** Pre-load common suffix entries (lemmas starting with `-`) on demand. */
    browseAllSuffixes(): void {
        this.isSearchingSuffix = true;
        this.suffixSearchQuery = '-';
        this.lemmatizationService.searchWords('-', 100).subscribe({
            next: (results) => {
                this.suffixSearchResults = results.filter(LemmatizationPanelComponent.isSuffixEntry);
                this.isSearchingSuffix = false;
            },
            error: () => { this.isSearchingSuffix = false; }
        });
    }

    /**
     * Treat an entry as a suffix when its lemma form begins with `-`, or its
     * guide word is annotated with `suff.` (the eBL marking for suffixes).
     */
    private static isSuffixEntry(e: WordEntry): boolean {
        if (e.lemma && e.lemma.length > 0 && /^[-–]/.test(e.lemma[0])) return true;
        if (e.guide_word && /\bsuff\b/i.test(e.guide_word)) return true;
        return false;
    }

    /**
     * Assign a suffix from a dictionary entry — used by the free-search results
     * inside the suffix section. Handles both "mark as complex" (when token
     * isn't yet complex) and "swap suffix lemma" (when it already is).
     */
    assignSuffixFromEntry(entry: WordEntry): void {
        if (!this.selectedToken) return;
        // Display label: prefer the lemma form without leading hyphen,
        // fall back to the word_id stripped of homonym roman numeral.
        let suffixLabel = entry.lemma && entry.lemma[0] ? entry.lemma[0] : entry.word_id;
        suffixLabel = suffixLabel.replace(/^[-–]/, '').replace(/\s+[IVX]+$/, '').trim();

        if (this.selectedToken.is_complex) {
            // Already complex — swap the suffix lemma in place
            this.selectedToken.detected_suffix = suffixLabel;
            this.selectedToken.suffix_lemma = entry.word_id;
            this.assignLemma(entry.word_id, /*asSuffix*/ true);
        } else {
            // Not yet complex — mark as complex with this suffix
            this.markAsComplex(suffixLabel, entry.word_id);
        }
        this.suffixSearchQuery = '';
        this.suffixSearchResults = [];
    }

    markAsComplex(suffix: string, suffixLemmaId: string): void {
        console.log('markAsComplex called:', suffix, suffixLemmaId, this.selectedToken?.raw);
        if (!this.selectedToken || !this.lemmatization) {
            console.log('markAsComplex: no selectedToken or lemmatization');
            return;
        }

        // Update the lemmatization first (before changing the token, which triggers re-render)
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const textLineIdx = textLines.findIndex(l => l === this.selectedLine);
        if (textLineIdx >= 0 && textLineIdx < this.lemmatization.lines.length) {
            const lemmaLine = this.lemmatization.lines[textLineIdx];
            if (this.selectedTokenIdx < lemmaLine.tokens.length) {
                const token = lemmaLine.tokens[this.selectedTokenIdx];
                const baseLemma = token.unique_lemma.length > 0 ? token.unique_lemma[0] : '';
                token.unique_lemma = baseLemma ? [baseLemma, suffixLemmaId] : [suffixLemmaId];
            }
        }

        // Now mark the token as complex (this will re-render the popup)
        this.selectedToken.is_complex = true;
        this.selectedToken.detected_suffix = suffix;
        this.selectedToken.suffix_lemma = suffixLemmaId;

        this.emitChange();
        // Don't close popup — let user see the result and optionally change the base lemma
    }

    getSuffixDescription(suffix: string): string {
        const info = LemmatizationPanelComponent.SUFFIX_INFO[suffix];
        return info ? info.description : '';
    }

    getSuffixAlternatives(currentSuffix: string): { lemma_id: string, description: string }[] {
        // Return all suffix options except the currently assigned one
        const alternatives: { lemma_id: string, description: string }[] = [];
        const currentLemma = LemmatizationPanelComponent.SUFFIX_INFO[currentSuffix]?.lemma_id;
        const seen = new Set<string>();

        for (const [suffix, info] of Object.entries(LemmatizationPanelComponent.SUFFIX_INFO)) {
            if (info.lemma_id === currentLemma || seen.has(info.lemma_id)) continue;
            seen.add(info.lemma_id);
            alternatives.push({ lemma_id: info.lemma_id, description: `-${suffix} ${info.description}` });
        }
        return alternatives;
    }

    // ── Save ──

    save(): void {
        if (!this.lemmatization || !this.productionId) return;
        this.isSaving = true;
        this.lemmatizationService.saveLemmatization(this.productionId, this.lemmatization).subscribe({
            next: (result) => {
                this.lemmatization = result;
                this.hasUnsavedChanges = false;
                this.isSaving = false;
                this.showNotification('Lemmatization saved', 'success');
            },
            error: (err) => {
                this.isSaving = false;
                this.showNotification('Save failed: ' + (err.error?.detail || err.message), 'error');
            }
        });
    }

    // ── eBL Export ──

    exportToEbl(): void {
        if (!this.productionId || !this.fragmentNumber) return;
        this.isExporting = true;
        this.showNotification('Exporting lemmatization to eBL...', 'info');

        // Save first, then export
        if (this.lemmatization) {
            this.lemmatizationService.saveLemmatization(this.productionId, this.lemmatization).subscribe({
                next: () => {
                    this.lemmatizationService.exportToEbl(this.productionId, this.fragmentNumber).subscribe({
                        next: (result) => {
                            this.isExporting = false;
                            this.showNotification('Lemmatization exported to eBL!', 'success');
                        },
                        error: (err) => {
                            this.isExporting = false;
                            this.showNotification('Export failed: ' + (err.error?.detail || err.message), 'error');
                        }
                    });
                },
                error: (err) => {
                    this.isExporting = false;
                    this.showNotification('Save before export failed: ' + (err.error?.detail || err.message), 'error');
                }
            });
        }
    }

    // ── Clear All ──

    clearAll(): void {
        this.initEmptyLemmatization();
        this.emitChange();
        this.showNotification('All lemma assignments cleared', 'info');
    }

    // ── Helpers ──

    getTokenStatus(line: AtfLine, tokenIdx: number): 'assigned' | 'suggestion' | 'ambiguous' | 'unmatched' | 'skip' | 'atf_suggestion' {
        const token = line.tokens[tokenIdx];
        if (token.is_determinative || token.is_number) return 'skip';

        // Check lemmatization data — has the user assigned a lemma?
        if (this.lemmatization) {
            const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
            const linePos = textLines.indexOf(line);
            if (linePos >= 0 && linePos < this.lemmatization.lines.length) {
                const lemmaLine = this.lemmatization.lines[linePos];
                if (tokenIdx < lemmaLine.tokens.length) {
                    const assignment = lemmaLine.tokens[tokenIdx];
                    if (assignment.unique_lemma.length > 0) {
                        // ATF import suggestions are not yet accepted
                        if (assignment.is_suggestion) return 'atf_suggestion';
                        return 'assigned';
                    }
                }
            }
        }

        // No assignment yet — check match level
        if (token.lemma_candidates.length === 0) return 'unmatched';
        if (token.match_level === 'suggestion') return 'suggestion';
        if (token.lemma_candidates.length >= 2) return 'ambiguous';
        return 'assigned'; // Single exact candidate auto-assigned
    }

    /**
     * Get ATF import suggestion data for a token, if any.
     */
    getAtfSuggestion(line: AtfLine, tokenIdx: number): LemmaAssignment | null {
        if (!this.lemmatization) return null;
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(line);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return null;
        const lemmaLine = this.lemmatization.lines[linePos];
        if (tokenIdx >= lemmaLine.tokens.length) return null;
        const assignment = lemmaLine.tokens[tokenIdx];
        if (assignment.is_suggestion) return assignment;
        return null;
    }

    /**
     * Accept an ATF import suggestion — marks it as no longer a suggestion.
     */
    acceptAtfSuggestion(): void {
        if (!this.lemmatization || !this.selectedLine) return;
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(this.selectedLine);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return;
        const lemmaLine = this.lemmatization.lines[linePos];
        if (this.selectedTokenIdx >= lemmaLine.tokens.length) return;
        const assignment = lemmaLine.tokens[this.selectedTokenIdx];
        assignment.is_suggestion = false;
        assignment.suggestion_source = '';
        this.emitChange();
    }

    getTokenLemma(line: AtfLine, tokenIdx: number): string {
        if (!this.lemmatization) return '';
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(line);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return '';
        const lemmaLine = this.lemmatization.lines[linePos];
        if (tokenIdx >= lemmaLine.tokens.length) return '';
        return lemmaLine.tokens[tokenIdx].unique_lemma.join(', ');
    }

    getLemmatizedCount(): number {
        if (!this.lemmatization) return 0;
        let count = 0;
        for (const line of this.lemmatization.lines) {
            for (const token of line.tokens) {
                if (token.unique_lemma.length > 0) count++;
            }
        }
        return count;
    }

    getTotalLemmatizableCount(): number {
        if (!this.tokenizedText) return 0;
        let count = 0;
        for (const line of this.tokenizedText.lines) {
            if (line.line_type !== 'text') continue;
            for (const token of line.tokens) {
                if (!token.is_determinative && !token.is_number) count++;
            }
        }
        return count;
    }

    get needsSync(): boolean {
        if (!this.tokenizedText || !this.lemmatization) return false;
        return this.tokenizedText.content_hash !== this.lemmatization.content_hash;
    }

    showNotification(message: string, type: 'success' | 'error' | 'info'): void {
        this.notification = message;
        this.notificationType = type;
        setTimeout(() => this.notification = '', 4000);
    }
}
