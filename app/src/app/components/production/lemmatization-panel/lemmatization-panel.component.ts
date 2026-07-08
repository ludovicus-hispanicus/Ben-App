import { Component, ElementRef, EventEmitter, HostListener, Input, OnChanges, OnDestroy, OnInit, Output, QueryList, SimpleChanges, ViewChildren } from '@angular/core';
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
import { PromptDialogComponent } from '../../common/prompt-dialog/prompt-dialog.component';

@Component({
    selector: 'lemmatization-panel',
    templateUrl: './lemmatization-panel.component.html',
    styleUrls: ['./lemmatization-panel.component.scss']
})
export class LemmatizationPanelComponent implements OnInit, OnChanges, OnDestroy {

    @Input() atfText: string = '';
    @Input() productionId: number = 0;
    @Input() fragmentNumber: string = '';
    /**
     * Raw translation content (the same buffer the user edits in the
     * Translation tab). Used by the per-word "Ask AI" panel to look up the
     * translation for the selected line, *whether or not* the translation
     * has been merged into the transliteration via #tr.en lines.
     */
    @Input() translationContent: string = '';

    @Output() lemmatizationChanged = new EventEmitter<TextLemmatization>();

    // State
    tokenizedText: TokenizedText | null = null;
    lemmatization: TextLemmatization | null = null;
    dictionaryStatus: DictionaryStatus | null = null;

    /**
     * Per-line English translation, keyed by line_number (e.g., "1.", "2'.").
     * Sourced from inline #tr.en lines in the ATF (with the translationContent
     * buffer as a fallback) and rebuilt on every tokenize() so the panel can
     * show the translation beneath each transliteration line while the user
     * lemmatizes. Precomputed once per sync rather than parsed per render.
     */
    lineTranslations: { [lineNumber: string]: string } = {};

    isTokenizing = false;
    isDownloadingDict = false;
    isExporting = false;
    isSaving = false;
    isAutoSaving = false;

    // Per-word AI panel — opens inside the token overlay for the selected word.
    aiPanelOpen = false;
    aiPrompt = '';
    aiLoading = false;
    aiApiKey = '';
    /**
     * Responses cached per `provider:model` for the current token. Lets the
     * user compare what each model said without re-paying for the call.
     * Cleared on token-swap.
     */
    aiResponsesByModel: { [key: string]: string } = {};

    /**
     * Provider selector — values mirror CuReD's localStorage keys exactly so
     * the API keys the user already saved in the OCR settings are reused
     * here without re-entry. `backend` is the value sent to our endpoint.
     */
    readonly aiProviders: { value: string; label: string; backend: string }[] = [
        { value: 'gemini_vision', label: 'Gemini', backend: 'gemini' },
        { value: 'claude_vision', label: 'Claude', backend: 'anthropic' },
        { value: 'gpt4_vision',   label: 'OpenAI', backend: 'openai' },
        { value: 'grok_xai',      label: 'Grok',   backend: 'grok' },
    ];
    selectedAiProvider = 'gemini_vision';

    readonly aiSubModels: { [key: string]: { value: string; label: string; description: string }[] } = {
        'gemini_vision': [
            { value: 'gemini-2.5-flash-lite',         label: 'Gemini 2.5 Flash-Lite',  description: 'Cheapest' },
            { value: 'gemini-2.5-flash',              label: 'Gemini 2.5 Flash',       description: 'Fast' },
            { value: 'gemini-3.1-flash-lite-preview', label: 'Gemini 3.1 Flash-Lite',  description: 'New, fast' },
            { value: 'gemini-3.1-pro-preview',        label: 'Gemini 3.1 Pro',         description: 'Most capable' },
        ],
        'claude_vision': [
            { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5',  description: 'Fastest, cheapest' },
            { value: 'claude-sonnet-4-6',         label: 'Claude Sonnet 4.6', description: 'Balanced' },
            { value: 'claude-opus-4-8',           label: 'Claude Opus 4.8',   description: 'Most intelligent' },
        ],
        'gpt4_vision': [
            { value: 'gpt-4o',      label: 'GPT-4o',      description: 'Omni' },
            { value: 'gpt-4o-mini', label: 'GPT-4o Mini', description: 'Cheap' },
            { value: 'gpt-4.1',     label: 'GPT-4.1',     description: 'Smartest' },
        ],
        // xAI Grok via the OpenAI-compatible endpoint at api.x.ai/v1.
        // Models per https://docs.x.ai/developers/models (April 2026).
        'grok_xai': [
            { value: 'grok-4-1-fast-non-reasoning', label: 'Grok 4.1 Fast',           description: 'Fast, 2M context' },
            { value: 'grok-4-1-fast-reasoning',     label: 'Grok 4.1 Fast Reasoning', description: 'Agentic, 2M context' },
            { value: 'grok-4',                      label: 'Grok 4',                  description: 'Flagship reasoning' },
            { value: 'grok-4.20',                   label: 'Grok 4.20',               description: 'Most intelligent' },
            { value: 'grok-code-fast-1',            label: 'Grok Code Fast 1',        description: 'Coding, 256K context' },
        ],
    };
    selectedAiSubModel = '';

    // Autosave: debounce changes and persist quietly. Flush on destroy so
    // toggling back to transliteration doesn't lose unsaved assignments.
    // Debounce is intentionally short — rapid sequential edits (accept +
    // propagate) used to coalesce into a single save 800ms after the LAST
    // edit, leaving a wide window where ngOnDestroy could fire before the
    // save did. 300ms keeps the rate-limiting benefit while shrinking the
    // race window dramatically.
    private autoSaveSubject = new Subject<void>();
    private autoSaveSubscription?: Subscription;
    private hasUnsavedChanges = false;
    private static readonly AUTOSAVE_DEBOUNCE_MS = 300;

    // Token selection popup
    selectedLine: AtfLine | null = null;
    selectedToken: AtfToken | null = null;
    selectedTokenLineIdx = -1;
    selectedTokenIdx = -1;
    popupVisible = false;
    popupX = 0;
    popupY = 0;
    // Whether the dropdown opens below or above the clicked line. Computed
    // from the available space so the dropdown stays inside the panel.
    popupOrientation: 'below' | 'above' = 'below';

    @ViewChildren('columnSearchInput') columnSearchInputs!: QueryList<ElementRef<HTMLInputElement>>;

    // Persistent "last viewed" marker — survives closePopup so the user can
    // see which token they just edited after dismissing the overlay.
    lastSelectedLine: AtfLine | null = null;
    lastSelectedToken: AtfToken | null = null;
    wordSearchQuery = '';
    searchResults: WordEntry[] = [];
    isSearching = false;

    // Suffix dictionary search (free-form lookup with suffix-entry priority)
    suffixSearchQuery = '';
    suffixSearchResults: WordEntry[] = [];
    isSearchingSuffix = false;

    // Per-column search state for the overlay layout. Index 0 = base, 1+ = suffix columns.
    columnQueries: string[] = [''];
    columnResults: WordEntry[][] = [[]];
    columnSearching: boolean[] = [false];
    // When true, render an extra trailing column for assigning the next part.
    // Hidden by default once the user has at least one part assigned — they
    // open it with the "+ Add suffix" button.
    showExtraColumn = true;

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

    /**
     * Click anywhere outside the dropdown closes it (same as Escape). We
     * skip clicks that should NOT dismiss:
     *   - inside the dropdown itself (`.token-overlay`)
     *   - on a token chip (handled by `onTokenClick`, which swaps selection
     *     while keeping the dropdown open)
     *   - inside any CDK overlay (e.g., the "Apply to similar tokens" dialog
     *     opens in a `.cdk-overlay-container` and its buttons must not close us)
     */
    @HostListener('document:mousedown', ['$event'])
    onDocumentMouseDown(event: MouseEvent): void {
        if (!this.popupVisible) return;
        const target = event.target as HTMLElement | null;
        if (!target) return;
        if (target.closest('.token-overlay')) return;
        if (target.closest('.token-chip')) return;
        if (target.closest('.cdk-overlay-container')) return;
        this.closePopup();
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
                    // After we know the current content_hash, see if there's
                    // an unsaved payload from a prior navigation to restore.
                    this._recoverPendingFromStash(data.content_hash);
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
        // Keep the per-line translation display in step with edits to either
        // the ATF (inline #tr.en lines) or the Translation tab buffer, without
        // forcing a full re-tokenize. Cheap parse over existing tokenized lines.
        if ((changes['atfText'] || changes['translationContent']) && this.tokenizedText) {
            this.buildLineTranslations();
        }
    }

    ngOnDestroy(): void {
        this.autoSaveSubscription?.unsubscribe();
        // Flush any pending autosave so toggling back to transliteration
        // or navigating away doesn't lose unsaved lemma assignments.
        //
        // We snapshot the productionId and lemmatization into locals BEFORE
        // subscribing because the component's fields may be torn down while
        // the HTTP request is still in flight. The HttpClient request itself
        // is owned by Angular's injector and survives the component, but
        // closures over `this.X` may not.
        //
        // We do NOT pre-emptively set hasUnsavedChanges=false: if the save
        // errors out, the flag is still true so a subsequent re-open of the
        // panel can detect and re-flush.
        if (this.hasUnsavedChanges && this.lemmatization && this.productionId) {
            const productionId = this.productionId;
            const payload = this.lemmatization;
            this.lemmatizationService.saveLemmatization(productionId, payload).subscribe({
                next: () => { this.hasUnsavedChanges = false; },
                error: (err) => {
                    // Component is gone — surface via console; the panel
                    // can re-flush on next mount because the in-memory
                    // state is preserved in localStorage as a safety net
                    // (see _stashPendingForRecovery below).
                    console.error('[LemPanel] Final flush save failed:', err);
                }
            });
            // Safety net: stash the unsaved payload in localStorage so it
            // can be recovered if the HTTP call dies during teardown.
            try {
                this._stashPendingForRecovery(productionId, payload);
            } catch (e) {
                console.warn('[LemPanel] Could not stash pending save:', e);
            }
        }
    }

    /**
     * Persist a snapshot of unsaved lemmatization changes to localStorage so
     * we can recover if ngOnDestroy's save request is interrupted by a
     * navigation. Picked up by ngOnInit when the same production_id opens.
     */
    private _stashPendingForRecovery(productionId: number, payload: TextLemmatization): void {
        const key = `lem_pending_${productionId}`;
        localStorage.setItem(key, JSON.stringify({
            saved_at: new Date().toISOString(),
            content_hash: payload.content_hash,
            lines: payload.lines,
            ai_suggested: payload.ai_suggested,
        }));
    }

    /**
     * On panel mount, check for a stashed unsaved payload from a prior
     * navigation and re-attempt the save if its content_hash still matches.
     * Removes the stash on success (or on hash mismatch — stale).
     */
    private _recoverPendingFromStash(currentHash: string): void {
        if (!this.productionId) return;
        const key = `lem_pending_${this.productionId}`;
        const raw = localStorage.getItem(key);
        if (!raw) return;
        try {
            const stashed = JSON.parse(raw);
            if (stashed.content_hash !== currentHash) {
                // ATF text changed since the stash — no longer applicable.
                localStorage.removeItem(key);
                return;
            }
            const recovered: TextLemmatization = {
                production_id: this.productionId,
                content_hash: stashed.content_hash,
                lines: stashed.lines,
                last_modified: stashed.saved_at || '',
                ai_suggested: !!stashed.ai_suggested,
            };
            console.log('[LemPanel] Recovering pending save from previous navigation');
            this.lemmatizationService.saveLemmatization(this.productionId, recovered).subscribe({
                next: (result) => {
                    this.lemmatization = result;
                    localStorage.removeItem(key);
                    this.showNotification('Recovered unsaved lemma changes from previous session', 'success');
                },
                error: (err) => {
                    console.error('[LemPanel] Recovery save failed; leaving stash for next attempt:', err);
                }
            });
        } catch (e) {
            console.warn('[LemPanel] Could not parse stashed pending save:', e);
            localStorage.removeItem(key);
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
        this._autoSaveEpoch++;
        this.autoSaveSubject.next();
    }

    private autoSave(): void {
        if (!this.lemmatization || !this.productionId || !this.hasUnsavedChanges) return;
        this.isAutoSaving = true;
        // Snapshot what we're about to send so a concurrent edit that arrives
        // mid-flight doesn't get wrongly marked as saved if the response comes
        // back AFTER the edit was applied.
        const payload = this.lemmatization;
        const editEpoch = ++this._autoSaveEpoch;
        this.lemmatizationService.saveLemmatization(this.productionId, payload).subscribe({
            next: (result) => {
                this.isAutoSaving = false;
                // Only clear hasUnsavedChanges when no edit happened during
                // the in-flight save. Otherwise the next debounce tick will
                // pick up the newer state.
                if (editEpoch === this._autoSaveEpoch) {
                    this.lemmatization = result;
                    this.hasUnsavedChanges = false;
                }
            },
            error: (err) => {
                this.isAutoSaving = false;
                // Keep hasUnsavedChanges=true so the next emitChange (or
                // ngOnDestroy flush) retries.
                console.error('[LemPanel] Autosave failed:', err);
                this.showNotification('Lemma autosave failed — your changes are not yet saved. Will retry.', 'error');
            }
        });
    }

    /** Monotonic counter incremented on every edit (emitChange) and on every
     * autoSave send. Used to skip the "next: clear hasUnsavedChanges" path
     * when a newer edit arrived while a save was in flight. */
    private _autoSaveEpoch = 0;

    // ── Tokenization ──

    tokenize(preserveAssignments: boolean = false): void {
        if (!this.atfText) return;
        this.isTokenizing = true;
        this.lemmatizationService.tokenize(this.atfText).subscribe({
            next: (result) => {
                this.tokenizedText = result;
                this.isTokenizing = false;
                this.buildLineTranslations();

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
        // transferring saved assignments by matching token values. We carry
        // the FULL LemmaAssignment object across the rebuild so per-token
        // metadata (ai_responses, suggestion fields) survives re-tokenization.
        if (!this.tokenizedText || !this.lemmatization) return;

        const savedMap = new Map<string, Map<string, LemmaAssignment[]>>();
        for (const line of this.lemmatization.lines) {
            const tokenMap = new Map<string, LemmaAssignment[]>();
            for (const tok of line.tokens) {
                if (!tokenMap.has(tok.value)) {
                    tokenMap.set(tok.value, []);
                }
                tokenMap.get(tok.value)!.push(tok);
            }
            const key = line.line_number;
            if (!savedMap.has(key)) {
                savedMap.set(key, tokenMap);
            } else {
                const existing = savedMap.get(key)!;
                for (const [val, toks] of tokenMap) {
                    if (!existing.has(val)) existing.set(val, []);
                    existing.get(val)!.push(...toks);
                }
            }
        }

        const newLines: LineLemmatization[] = [];
        for (const line of this.tokenizedText.lines) {
            if (line.line_type !== 'text') continue;

            const tokenMap = savedMap.get(line.line_number);
            const tokens: LemmaAssignment[] = line.tokens.map(t => {
                if (tokenMap) {
                    const queue = tokenMap.get(t.raw);
                    if (queue && queue.length > 0) {
                        const saved = queue.shift()!;
                        // Preserve any saved decision: a lemma, AI responses,
                        // or an explicit "No lemma" clear. The clear case is
                        // important — without it, the auto-assign branch
                        // below would refill the lemma the user just removed.
                        if (
                            (saved.unique_lemma && saved.unique_lemma.length > 0)
                            || saved.ai_responses
                            || saved.is_cleared
                        ) {
                            return {
                                ...saved,
                                value: t.raw,
                                unique_lemma: saved.unique_lemma || [],
                            };
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
        if (this.isUnlemmatizable(token)) return;

        this.selectedLine = line;
        this.selectedToken = token;
        this.selectedTokenLineIdx = lineIdx;
        this.selectedTokenIdx = tokenIdx;
        this.lastSelectedLine = line;
        this.lastSelectedToken = token;
        this.wordSearchQuery = '';
        this.searchResults = [];
        this.suffixSearchQuery = '';
        this.suffixSearchResults = [];
        // Pre-size column state to base + each existing suffix + one trailing
        // empty so the ngModel bindings on the overlay have valid entries
        // from the first render.
        const filled = (() => {
            if (!this.lemmatization) return 0;
            const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
            const linePos = textLines.indexOf(line);
            if (linePos < 0 || linePos >= this.lemmatization.lines.length) return 0;
            const lemmaLine = this.lemmatization.lines[linePos];
            return tokenIdx < lemmaLine.tokens.length ? lemmaLine.tokens[tokenIdx].unique_lemma.length : 0;
        })();
        // Show the empty trailing column on open only when nothing is assigned
        // yet (so the user has the base column to fill). For tokens that
        // already have parts, hide it until the user clicks "+ Add suffix".
        this.showExtraColumn = filled === 0;
        const colCount = Math.max(filled + (this.showExtraColumn ? 1 : 0), 1);
        this.columnQueries = Array.from({ length: colCount }, () => '');
        this.columnResults = Array.from({ length: colCount }, () => [] as WordEntry[]);
        this.columnSearching = Array.from({ length: colCount }, () => false);
        this.candidateEntries = [];

        // Reset the AI panel so it rebuilds the prompt from the new selection.
        // Restore any previously-saved responses for this token from the
        // LemmaAssignment so the user can revisit prior answers.
        this.aiPanelOpen = false;
        this.aiPrompt = '';
        this.aiLoading = false;
        const assignment = this.getCurrentAssignment();
        this.aiResponsesByModel = assignment?.ai_responses ? { ...assignment.ai_responses } : {};

        // Position the dropdown relative to the clicked line. The overlay
        // is now a child of .lemma-lines (the scroll container), so popupY
        // uses offsetTop in the lines' content coords — that way the
        // dropdown scrolls along with the line. The orientation decision
        // (below vs above) is still based on visible-viewport space so the
        // dropdown opens upward when the line sits near the bottom.
        const targetEl = event.target as HTMLElement;
        const lineEl = targetEl.closest('.lemma-line') as HTMLElement | null;
        const linesEl = targetEl.closest('.lemma-lines') as HTMLElement | null;
        if (lineEl && linesEl) {
            const lineRect = lineEl.getBoundingClientRect();
            const linesRect = linesEl.getBoundingClientRect();
            const spaceBelow = linesRect.bottom - lineRect.bottom;
            const spaceAbove = lineRect.top - linesRect.top;
            const preferBelow = spaceBelow >= 240 || spaceBelow >= spaceAbove;
            if (preferBelow) {
                this.popupOrientation = 'below';
                // Below: anchor at the line's bottom in content coords
                this.popupY = lineEl.offsetTop + lineEl.offsetHeight + 4;
            } else {
                this.popupOrientation = 'above';
                // Above: anchor at the line's top; CSS uses
                // transform: translateY(-100%) to flip the dropdown upward.
                this.popupY = Math.max(lineEl.offsetTop - 4, 0);
            }
        } else {
            this.popupOrientation = 'below';
            this.popupY = 8;
        }
        this.popupX = 0; // unused now — overlay is anchored by the CSS left/right %
        this.popupVisible = true;

        // Focus the base column's search input on the next tick (after Angular
        // renders the overlay and ViewChildren updates).
        setTimeout(() => {
            const first = this.columnSearchInputs?.first;
            if (first) first.nativeElement.focus();
        }, 0);

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
            // Manual assignment = explicit user decision. Clear any prior
            // suggestion flag so the chip stops rendering as unconfirmed.
            token.is_suggestion = false;
            token.suggestion_source = '';
            token.is_cleared = false;
            assignedLemma = token.unique_lemma;
        }

        // Capture values before closePopup nulls selectedToken
        const cleaned = this.selectedToken?.cleaned || '';
        const matchCount = !asSuffix && cleaned
            ? this.countSyncableMatches(cleaned, assignedLemma, textLineIdx, this.selectedTokenIdx)
            : 0;

        // If the token was unmatched/suggestion, save as custom mapping for future lookups
        if (this.selectedToken && !asSuffix &&
            (this.selectedToken.match_level === 'none' || this.selectedToken.match_level === 'unmatched')) {
            this.lemmatizationService.addCustomMapping(this.selectedToken.cleaned, lemmaId).subscribe();
        }

        this.emitChange();
        this.closePopup();

        // Offer to propagate if there are matching syncable tokens
        if (matchCount > 0) {
            const dialogRef = this.dialog.open(ConfirmDialogComponent, {
                data: {
                    title: 'Apply to similar tokens',
                    message: `Apply "${assignedLemma.join(', ')}" to ${matchCount} other "${cleaned}" token${matchCount > 1 ? 's' : ''}?`,
                    confirmText: 'Apply',
                    cancelText: 'Skip'
                }
            });
            dialogRef.afterClosed().subscribe(confirmed => {
                if (confirmed) {
                    const propagated = this.propagateChain(cleaned, assignedLemma, textLineIdx, this.selectedTokenIdx);
                    this.showNotification(`Applied to ${propagated} occurrence${propagated > 1 ? 's' : ''}`, 'success');
                    this.emitChange();
                }
            });
        }
    }

    /**
     * A target is "syncable" with the given chain — i.e., the user's manual
     * assignment should propagate to it — in any of these cases:
     *   1. Empty (no lemma assigned, even if previously cleared — the user's
     *      explicit assign overrides any prior "no").
     *   2. Strict prefix of the new chain (target has [base], new chain is
     *      [base, -suffix]).
     *   3. UNCONFIRMED SUGGESTION (is_suggestion=true). AI / ORACC priors
     *      that the user hasn't accepted yet are overridable by the user's
     *      explicit choice. Without this case, picking a different lemma to
     *      override an AI suggestion only updates the clicked token while
     *      the other 36 same-form suggestions stay on the wrong AI lemma.
     *
     * HUMAN-CONFIRMED assignments (unique_lemma set AND is_suggestion=false
     * AND not a strict prefix) are NOT syncable — those represent decisions
     * the user already made and should not be silently overwritten.
     */
    private isSyncableTarget(target: LemmaAssignment, fullChain: string[]): boolean {
        if (!target) return false;
        const existing = target.unique_lemma || [];
        if (existing.length === 0) return true;
        if (target.is_suggestion) return true;  // unconfirmed → overridable
        if (existing.length >= fullChain.length) return false;
        return existing.every((l, i) => l === fullChain[i]);
    }

    private countSyncableMatches(
        cleanedValue: string, fullChain: string[],
        skipLineIdx: number, skipTokenIdx: number,
    ): number {
        if (!this.tokenizedText || !this.lemmatization || fullChain.length === 0) return 0;
        const textLines = this.tokenizedText.lines.filter(l => l.line_type === 'text');
        let count = 0;
        for (let li = 0; li < textLines.length; li++) {
            const line = textLines[li];
            if (li >= this.lemmatization.lines.length) break;
            const lemmaLine = this.lemmatization.lines[li];
            for (let ti = 0; ti < line.tokens.length; ti++) {
                if (li === skipLineIdx && ti === skipTokenIdx) continue;
                const token = line.tokens[ti];
                if (this.isUnlemmatizable(token)) continue;
                if (token.cleaned !== cleanedValue) continue;
                if (ti >= lemmaLine.tokens.length) continue;
                if (this.isSyncableTarget(lemmaLine.tokens[ti], fullChain)) count++;
            }
        }
        return count;
    }

    /**
     * Push a full lemma chain to every syncable token sharing this cleaned
     * value. Used both for the initial base-lemma propagation and for the
     * cascading update when the user adds a suffix to make the chain
     * longer (so all already-propagated copies catch up).
     */
    private propagateChain(
        cleanedValue: string, fullChain: string[],
        skipLineIdx: number, skipTokenIdx: number,
    ): number {
        if (!this.tokenizedText || !this.lemmatization || fullChain.length === 0) return 0;
        const textLines = this.tokenizedText.lines.filter(l => l.line_type === 'text');
        let count = 0;
        for (let li = 0; li < textLines.length; li++) {
            const line = textLines[li];
            if (li >= this.lemmatization.lines.length) break;
            const lemmaLine = this.lemmatization.lines[li];
            for (let ti = 0; ti < line.tokens.length; ti++) {
                if (li === skipLineIdx && ti === skipTokenIdx) continue;
                const token = line.tokens[ti];
                if (this.isUnlemmatizable(token)) continue;
                if (token.cleaned !== cleanedValue) continue;
                if (ti >= lemmaLine.tokens.length) continue;
                const target = lemmaLine.tokens[ti];
                if (!this.isSyncableTarget(target, fullChain)) continue;
                target.unique_lemma = [...fullChain];
                target.is_cleared = false;
                // The user's manual propagate is an explicit confirmation —
                // clear the suggestion flag on overridden AI/ORACC priors so
                // the chip stops rendering as unconfirmed.
                target.is_suggestion = false;
                target.suggestion_source = '';
                count++;
            }
        }
        return count;
    }

    /** Count tokens with the same cleaned value that currently have any lemma assigned. */
    private countAssignedMatches(
        cleanedValue: string, skipLineIdx: number, skipTokenIdx: number,
    ): number {
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
                if (this.isUnlemmatizable(token)) continue;
                if (token.cleaned !== cleanedValue) continue;
                if (ti >= lemmaLine.tokens.length) continue;
                if ((lemmaLine.tokens[ti].unique_lemma || []).length > 0) count++;
            }
        }
        return count;
    }

    /**
     * Mirror of propagateChain for the "No lemma" path: clears every
     * matching token that has any lemma, marking them as explicitly cleared
     * so the auto-assign fallback doesn't refill them.
     */
    private propagateClear(
        cleanedValue: string, skipLineIdx: number, skipTokenIdx: number,
    ): number {
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
                if (this.isUnlemmatizable(token)) continue;
                if (token.cleaned !== cleanedValue) continue;
                if (ti >= lemmaLine.tokens.length) continue;
                const target = lemmaLine.tokens[ti];
                if ((target.unique_lemma || []).length === 0 && !target.is_cleared) continue;
                target.unique_lemma = [];
                target.is_cleared = true;
                target.is_suggestion = false;
                target.suggestion_source = '';
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
            const tok = lemmaLine.tokens[this.selectedTokenIdx];
            tok.unique_lemma = [];
            // Mark the clear as explicit so auto-assign doesn't refill it.
            tok.is_cleared = true;
            // Drop ATF-import suggestion metadata too, otherwise the chip
            // would still flag itself as a pending suggestion.
            tok.is_suggestion = false;
            tok.suggestion_source = '';
        }
        if (this.selectedToken) {
            this.selectedToken.is_complex = false;
            this.selectedToken.suffix_lemma = '';
        }

        // Capture before closePopup nulls selectedToken
        const cleaned = this.selectedToken?.cleaned || '';
        const matchCount = cleaned
            ? this.countAssignedMatches(cleaned, textLineIdx, this.selectedTokenIdx)
            : 0;

        this.emitChange();
        this.closePopup();

        // Mirror of the assign-side propagation: if other tokens with the
        // same cleaned value also have lemmas (likely auto-filled or
        // propagated earlier), offer to clear them in one go.
        if (matchCount > 0) {
            const dialogRef = this.dialog.open(ConfirmDialogComponent, {
                data: {
                    title: 'Clear similar tokens',
                    message: `Also remove the lemma from ${matchCount} other "${cleaned}" token${matchCount > 1 ? 's' : ''}?`,
                    confirmText: 'Clear all',
                    cancelText: 'Skip'
                }
            });
            dialogRef.afterClosed().subscribe(confirmed => {
                if (confirmed) {
                    const cleared = this.propagateClear(cleaned, textLineIdx, this.selectedTokenIdx);
                    this.showNotification(`Cleared ${cleared} occurrence${cleared > 1 ? 's' : ''}`, 'success');
                    this.emitChange();
                }
            });
        }
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

    // ── AI Suggestions (per-word, informational only) ──

    /**
     * Toggle the AI panel inside the token overlay. Pre-fills the prompt
     * textarea with sentence + translation + question template the first
     * time it's opened for the current selection. Also restores the user's
     * provider / sub-model / API key from localStorage (shared with CuReD).
     */
    toggleAiPanel(): void {
        if (this.aiPanelOpen) {
            this.aiPanelOpen = false;
            return;
        }
        this.aiPrompt = this.buildAiPromptTemplate();
        // Restore provider preference, defaulting to Gemini.
        this.selectedAiProvider = localStorage.getItem('lemma_ai_provider') || this.selectedAiProvider;
        this.loadAiProviderState();
        this.aiPanelOpen = true;
    }

    /** Cache key for the current selection — provider + sub-model. */
    get aiResponseKey(): string {
        return `${this.selectedAiProvider}:${this.selectedAiSubModel}`;
    }

    /** Cached response for the currently selected provider/model, if any. */
    get aiResponse(): string {
        return this.aiResponsesByModel[this.aiResponseKey] || '';
    }

    /** Sync sub-model + apiKey from localStorage when provider changes. */
    onAiProviderChange(): void {
        localStorage.setItem('lemma_ai_provider', this.selectedAiProvider);
        this.loadAiProviderState();
    }

    onAiSubModelChange(): void {
        if (this.selectedAiProvider && this.selectedAiSubModel) {
            localStorage.setItem('ocr_sub_model_' + this.selectedAiProvider, this.selectedAiSubModel);
        }
    }

    private loadAiProviderState(): void {
        const subs = this.aiSubModels[this.selectedAiProvider] || [];
        this.selectedAiSubModel =
            localStorage.getItem('ocr_sub_model_' + this.selectedAiProvider)
            || (subs[0]?.value || '');
        this.aiApiKey = localStorage.getItem('ocr_api_key_' + this.selectedAiProvider) || '';
    }

    /** Build the editable prompt from the current selection. */
    private buildAiPromptTemplate(): string {
        const word = this.selectedToken?.raw || this.selectedToken?.cleaned || '';
        const sentence = this.selectedLine?.raw_text?.trim() || '';
        const translation = this.extractTranslationForLine(this.selectedLine?.line_number || '');
        const lines = [
            'This is an Akkadian sentence about ____.',
            `Sentence: ${sentence}`,
            `Translation: ${translation || '(none provided)'}`,
            `Can you suggest a meaning and a grammar analysis for the word "${word}"?`
        ];
        return lines.join('\n');
    }

    /**
     * Precompute the per-line translation map for display. Runs once per
     * tokenize() (not per change-detection cycle) and reuses the same
     * extraction logic the "Ask AI" panel relies on, so the displayed English
     * matches the context the AI receives.
     */
    private buildLineTranslations(): void {
        this.lineTranslations = {};
        if (!this.tokenizedText) return;
        for (const line of this.tokenizedText.lines) {
            if (line.line_type !== 'text') continue;
            const tr = this.extractTranslationForLine(line.line_number);
            if (tr) this.lineTranslations[line.line_number] = tr;
        }
    }

    /** Template helper — translation to show beneath a text line, if any. */
    getLineTranslation(line: AtfLine): string {
        return this.lineTranslations[line.line_number] || '';
    }

    /**
     * Find the translation for the given ATF line number. Tries the standalone
     * translationContent buffer first (handles ranges like "2-3."), then falls
     * back to scanning atfText for inline #tr.en lines (post-merge).
     */
    private extractTranslationForLine(lineNumber: string): string {
        const target = (lineNumber || '').replace(/\.$/, '').trim();
        if (!target) return '';

        // 1. Translation buffer (preferred — works pre-merge)
        const fromTranslation = this.lookupInTranslationBuffer(this.translationContent, target);
        if (fromTranslation) return fromTranslation;

        // 2. Fallback: post-merge atf with inline #tr.en lines
        if (!this.atfText) return '';
        const lines = this.atfText.split('\n');
        // Prime(s) and sub-line letter in either order: "18'a" or "18a'".
        const lineLabelRe = /^\s*(\d+(?:['′]+[a-z]?|[a-z]['′]*)?)\.\s/;
        const trRe = /^\s*#tr\.\w+(?:\.\([^)]+\))?:\s*(.*)$/;

        let lineIdx = -1;
        for (let i = 0; i < lines.length; i++) {
            const m = lines[i].match(lineLabelRe);
            if (m && m[1] === target) { lineIdx = i; break; }
        }
        if (lineIdx < 0) return '';

        for (let i = lineIdx + 1; i < lines.length; i++) {
            const trim = lines[i].trim();
            if (!trim) continue;
            const tm = trim.match(trRe);
            if (tm) return tm[1].trim();
            if (lineLabelRe.test(lines[i])) break;
        }
        for (let i = lineIdx - 1; i >= Math.max(0, lineIdx - 12); i--) {
            const trim = lines[i].trim();
            const tm = trim.match(trRe);
            if (tm) return tm[1].trim();
        }
        return '';
    }

    /**
     * Scan a translation buffer (e.g., the Translation tab content) for the
     * given line label. Recognises both single labels ("22.", "1'.") and
     * ranges ("2-3.", "12'-15."). Returns the translation text on the line.
     */
    private lookupInTranslationBuffer(buffer: string, target: string): string {
        if (!buffer) return '';
        const lines = buffer.split('\n');
        const labelRe = /^\s*(\d+(?:['′]+[a-z]?|[a-z]['′]*)?(?:[–\-]\d+(?:['′]+[a-z]?|[a-z]['′]*)?)?)\.\s+(.*)$/;
        for (const raw of lines) {
            const m = raw.match(labelRe);
            if (!m) continue;
            if (this.lineLabelMatches(m[1], target)) {
                return m[2].trim();
            }
        }
        return '';
    }

    private lineLabelMatches(label: string, target: string): boolean {
        if (label === target) return true;
        // Range — "2-3", "2–3", "12'-15"
        const m = label.match(/^(\d+)('?)[–\-](\d+)('?)$/);
        if (!m) return false;
        const start = parseInt(m[1], 10);
        const end = parseInt(m[3], 10);
        const labelHasPrime = !!m[2] || !!m[4];
        const targetHasPrime = target.includes("'");
        if (labelHasPrime !== targetHasPrime) return false;
        const targetNum = parseInt(target.replace(/[^0-9]/g, ''), 10);
        return !isNaN(targetNum) && targetNum >= start && targetNum <= end;
    }

    submitAiSuggestion(): void {
        const prompt = (this.aiPrompt || '').trim();
        if (!prompt) return;
        // Persist the API key under the same localStorage entry CuReD uses
        // so the OCR side picks it up too.
        if (this.aiApiKey) {
            localStorage.setItem('ocr_api_key_' + this.selectedAiProvider, this.aiApiKey);
        }
        const providerEntry = this.aiProviders.find(p => p.value === this.selectedAiProvider);
        const cacheKey = this.aiResponseKey;
        this.aiLoading = true;
        // Drop the cached response for this model only; other models keep theirs.
        delete this.aiResponsesByModel[cacheKey];
        this.lemmatizationService.askAiAboutWord({
            prompt,
            provider: providerEntry?.backend,
            model: this.selectedAiSubModel || undefined,
            apiKey: this.aiApiKey || undefined,
        }).subscribe({
            next: (res) => {
                const text = res.response || '';
                this.aiResponsesByModel[cacheKey] = text;
                // Persist to the LemmaAssignment so the answer survives a
                // page reload — autosave handles the network round-trip.
                const assignment = this.getCurrentAssignment();
                if (assignment) {
                    if (!assignment.ai_responses) assignment.ai_responses = {};
                    assignment.ai_responses[cacheKey] = text;
                    this.emitChange();
                }
                this.aiLoading = false;
            },
            error: (err) => {
                this.aiLoading = false;
                this.showNotification('AI request failed: ' + (err.error?.detail || err.message), 'error');
            }
        });
    }

    /**
     * Replace the panel's lemmatization with a server-saved payload (typically
     * the result of a bulk AI run kicked off from the production component's
     * AI panel). Skips autosave because the server already persisted.
     * Re-runs tokenization with preserve=true so AI suggestion metadata is
     * kept while line/token structure is refreshed.
     */
    applyExternalLemmatization(replacement: TextLemmatization): void {
        this.lemmatization = replacement;
        this.lemmatizationChanged.emit(replacement);
        if (!this.tokenizedText) {
            this.tokenize(true);
        }
        const aiCount = replacement.lines.reduce(
            (n, l) => n + l.tokens.filter(t =>
                (t.unique_lemma?.length || 0) > 0 && t.suggestion_source === 'ai'
            ).length,
            0
        );
        if (aiCount > 0) {
            this.showNotification(`AI suggested lemmas for ${aiCount} token${aiCount === 1 ? '' : 's'}. Review and confirm.`, 'success');
        }
    }

    /** Return the LemmaAssignment object for the currently selected token. */
    private getCurrentAssignment(): LemmaAssignment | null {
        if (!this.lemmatization || !this.selectedLine) return null;
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(this.selectedLine);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return null;
        const lemmaLine = this.lemmatization.lines[linePos];
        if (this.selectedTokenIdx < 0 || this.selectedTokenIdx >= lemmaLine.tokens.length) return null;
        return lemmaLine.tokens[this.selectedTokenIdx];
    }

    // ── Suffix helpers ──

    // Each entry's lemma_id points to the actual *suffix* dictionary entry
    // (e.g., `-ka I` not the standalone pronoun `kâši I`).
    private static SUFFIX_INFO: { [key: string]: { description: string, lemma_id: string } } = {
        'šu':   { description: '3ms "his"',        lemma_id: '-šu I' },
        'ša':   { description: '3fs "her"',        lemma_id: '-ša I' },
        'ka':   { description: '2ms "your"',       lemma_id: '-ka I' },
        'ki':   { description: '2fs "your"',       lemma_id: '-ki I' },
        'ja':   { description: '1cs "my"',         lemma_id: '-ya I' },
        'ia':   { description: '1cs "my"',         lemma_id: '-ya I' },
        'i':    { description: '1cs "my"',         lemma_id: '-ī I' },
        'ni':   { description: '1cp "our"',        lemma_id: '-ni I' },
        'šunu': { description: '3mp "their"',      lemma_id: '-šunu I' },
        'šina': { description: '3fp "their"',      lemma_id: '-šina I' },
        'kunu': { description: '2mp "your (pl)"',  lemma_id: '-kunu I' },
        'kina': { description: '2fp "your (pl)"',  lemma_id: '-kināti I' },
        'ši':   { description: '3fs acc. "her"',   lemma_id: '-ši I' },
        'šim':  { description: '3fs dat. "to her"', lemma_id: '-šim I' },
        // Non-possessive bound morphemes, offered alongside the possessives.
        'ma':   { description: 'enclitic "-and/-but"', lemma_id: '-ma I' },
        'am':   { description: 'ventive',          lemma_id: '-am I' },
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

    // Cached so *ngFor sees a stable reference. Returning a fresh array on
    // every change-detection tick caused Angular to tear down and recreate
    // the suffix buttons, dropping the in-flight click event.
    private static readonly COMMON_SUFFIX_OPTIONS: { suffix: string, lemma_id: string, description: string }[] = (() => {
        const seen = new Set<string>();
        const options: { suffix: string, lemma_id: string, description: string }[] = [];
        const priority = ['šu', 'ša', 'ka', 'ki', 'ja', 'ni', 'šunu', 'šina', 'kunu', 'kina', 'ši', 'šim', 'ia', 'i', 'ma', 'am'];
        for (const suf of priority) {
            const info = LemmatizationPanelComponent.SUFFIX_INFO[suf];
            if (info && !seen.has(suf)) {
                seen.add(suf);
                options.push({ suffix: suf, lemma_id: info.lemma_id, description: info.description });
            }
        }
        return options;
    })();

    getAllSuffixOptions(): { suffix: string, lemma_id: string, description: string }[] {
        return LemmatizationPanelComponent.COMMON_SUFFIX_OPTIONS;
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
     * inside the suffix section. Handles three cases:
     *   - token not complex yet → mark complex with this suffix (base + suffix)
     *   - token has exactly 2 parts → swap the suffix lemma in place
     *   - token has 3+ parts already → append as an additional part
     *     (covers cases like i-la-am-ma → elû I, -am, -ma I)
     */
    assignSuffixFromEntry(entry: WordEntry): void {
        if (!this.selectedToken) return;
        let suffixLabel = entry.lemma && entry.lemma[0] ? entry.lemma[0] : entry.word_id;
        suffixLabel = suffixLabel.replace(/^[-–]/, '').replace(/\s+[IVX]+$/, '').trim();

        const current = this.getAssignedLemmas();
        if (current.length >= 2) {
            // Already has base + suffix — append as a third (or further) part
            this.appendLemmaPart(entry.word_id);
        } else if (this.selectedToken.is_complex) {
            this.selectedToken.detected_suffix = suffixLabel;
            this.selectedToken.suffix_lemma = entry.word_id;
            this.assignLemma(entry.word_id, /*asSuffix*/ true);
        } else {
            this.markAsComplex(suffixLabel, entry.word_id);
        }
        this.suffixSearchQuery = '';
        this.suffixSearchResults = [];
    }

    /** Read the unique_lemma array for the currently selected token. */
    getAssignedLemmas(): string[] {
        if (!this.lemmatization || !this.selectedLine) return [];
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(this.selectedLine);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return [];
        const lemmaLine = this.lemmatization.lines[linePos];
        if (this.selectedTokenIdx < 0 || this.selectedTokenIdx >= lemmaLine.tokens.length) return [];
        return lemmaLine.tokens[this.selectedTokenIdx].unique_lemma || [];
    }

    /**
     * Remove the lemma at `idx` from the selected token's unique_lemma array.
     * Adjusts the is_complex / suffix_lemma flags so the popup re-renders cleanly.
     */
    removeLemmaPart(idx: number): void {
        if (!this.lemmatization || !this.selectedLine) return;
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(this.selectedLine);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return;
        const lemmaLine = this.lemmatization.lines[linePos];
        if (this.selectedTokenIdx >= lemmaLine.tokens.length) return;
        const token = lemmaLine.tokens[this.selectedTokenIdx];
        if (idx < 0 || idx >= token.unique_lemma.length) return;
        token.unique_lemma.splice(idx, 1);
        if (this.selectedToken) {
            if (token.unique_lemma.length < 2) {
                this.selectedToken.is_complex = false;
                this.selectedToken.suffix_lemma = '';
                this.selectedToken.detected_suffix = '';
            } else {
                this.selectedToken.suffix_lemma = token.unique_lemma[1];
            }
        }
        this.emitChange();
    }

    /** Append an additional lemma to the selected token (for 3+ part words). */
    appendLemmaPart(lemmaId: string): void {
        if (!this.lemmatization || !this.selectedLine) return;
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(this.selectedLine);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return;
        const lemmaLine = this.lemmatization.lines[linePos];
        if (this.selectedTokenIdx >= lemmaLine.tokens.length) return;
        const token = lemmaLine.tokens[this.selectedTokenIdx];
        token.unique_lemma.push(lemmaId);
        if (this.selectedToken && token.unique_lemma.length >= 2) {
            this.selectedToken.is_complex = true;
            if (token.unique_lemma.length === 2) {
                this.selectedToken.suffix_lemma = token.unique_lemma[1];
            }
        }
        this.emitChange();
    }

    // ── Multi-column overlay support ──

    /**
     * Returns [0, 1, 2, …] for the columns to render. Includes a trailing
     * empty column only when `showExtraColumn` is true (toggled on by the
     * "+ Add suffix" button or by default when nothing is assigned yet).
     */
    getColumnIndices(): number[] {
        const filled = this.getAssignedLemmas().length;
        const count = Math.max(filled + (this.showExtraColumn ? 1 : 0), 1);
        const out: number[] = [];
        for (let i = 0; i < count; i++) out.push(i);
        return out;
    }

    /** Reveal an extra trailing column so the user can assign the next part. */
    addAnotherColumn(): void {
        this.showExtraColumn = true;
        this.ensureColumnState(this.getAssignedLemmas().length);
    }

    private ensureColumnState(idx: number): void {
        while (this.columnQueries.length <= idx) this.columnQueries.push('');
        while (this.columnResults.length <= idx) this.columnResults.push([]);
        while (this.columnSearching.length <= idx) this.columnSearching.push(false);
    }

    /**
     * Run a dictionary search for one column. Suffix columns (idx > 0) reorder
     * results so suffix-typed entries float to the top, while the base column
     * uses the dictionary's native ranking.
     */
    searchColumn(idx: number): void {
        this.ensureColumnState(idx);
        const q = (this.columnQueries[idx] || '').trim();
        if (q.length < 1) {
            this.columnResults[idx] = [];
            return;
        }
        this.columnSearching[idx] = true;
        this.lemmatizationService.searchWords(q, 50).subscribe({
            next: (results) => {
                if (idx > 0) {
                    results.sort((a, b) => {
                        const aIs = LemmatizationPanelComponent.isSuffixEntry(a) ? 0 : 1;
                        const bIs = LemmatizationPanelComponent.isSuffixEntry(b) ? 0 : 1;
                        return aIs - bIs;
                    });
                }
                this.columnResults[idx] = results;
                this.columnSearching[idx] = false;
            },
            error: () => { this.columnSearching[idx] = false; }
        });
    }

    /**
     * Set the lemma at a specific column position. Pads any gaps with empty
     * strings, trims trailing empties, and updates is_complex / suffix_lemma
     * flags so the rest of the popup reflects the new state.
     */
    assignToColumn(idx: number, lemmaId: string): void {
        if (!this.lemmatization || !this.selectedLine || !lemmaId) return;
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(this.selectedLine);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return;
        const lemmaLine = this.lemmatization.lines[linePos];
        if (this.selectedTokenIdx >= lemmaLine.tokens.length) return;
        const token = lemmaLine.tokens[this.selectedTokenIdx];

        const cleaned = this.selectedToken?.cleaned || '';

        while (token.unique_lemma.length <= idx) token.unique_lemma.push('');
        token.unique_lemma[idx] = lemmaId;
        // Drop trailing empty slots (e.g., user assigned to col 3 leaving col 2 empty)
        while (token.unique_lemma.length > 0 && !token.unique_lemma[token.unique_lemma.length - 1]) {
            token.unique_lemma.pop();
        }
        // Picking a lemma overrides any previous "No lemma" decision.
        token.is_cleared = false;

        if (this.selectedToken) {
            const len = token.unique_lemma.length;
            this.selectedToken.is_complex = len >= 2;
            this.selectedToken.suffix_lemma = len >= 2 ? token.unique_lemma[1] : '';
        }

        // For the base column, save unmatched/suggestion tokens as custom mappings
        // so future tokenization runs can reuse the user's choice. Mirrors the
        // behavior of the original assignLemma() flow.
        if (idx === 0 && this.selectedToken &&
            (this.selectedToken.match_level === 'none' || this.selectedToken.match_level === 'unmatched') &&
            this.selectedToken.cleaned) {
            this.lemmatizationService.addCustomMapping(this.selectedToken.cleaned, lemmaId).subscribe();
        }

        this.ensureColumnState(idx);
        this.columnQueries[idx] = '';
        this.columnResults[idx] = [];
        // Collapse the trailing empty column back to a "+ Add suffix" button
        // once the user has filled it — they re-open it explicitly to add more.
        this.showExtraColumn = false;

        this.emitChange();

        // Compute the full chain *after* the assignment so propagation can
        // also catch up tokens that were previously synced with a shorter
        // chain (e.g., adding a suffix to a complex word — earlier copies
        // that received just the base now upgrade to base + suffix).
        const fullChain = [...token.unique_lemma];
        const matchCount = cleaned
            ? this.countSyncableMatches(cleaned, fullChain, linePos, this.selectedTokenIdx)
            : 0;
        if (matchCount > 0) {
            const dialogRef = this.dialog.open(ConfirmDialogComponent, {
                data: {
                    title: 'Apply to similar tokens',
                    message: `Apply "${fullChain.join(', ')}" to ${matchCount} other "${cleaned}" token${matchCount > 1 ? 's' : ''}?`,
                    confirmText: 'Apply',
                    cancelText: 'Skip'
                }
            });
            dialogRef.afterClosed().subscribe(confirmed => {
                if (confirmed) {
                    const propagated = this.propagateChain(cleaned, fullChain, linePos, this.selectedTokenIdx);
                    this.showNotification(`Applied to ${propagated} occurrence${propagated > 1 ? 's' : ''}`, 'success');
                    this.emitChange();
                }
            });
        }
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
        if (!this.productionId) return;
        // Confirm the eBL fragment id before pushing — the local identifier
        // (often a CDLI P-number) may not match the eBL publication number,
        // so let the user override here. Default comes from the production
        // text's saved `ebl_fragment_number`, falling back to the identifier.
        //
        // Use a MatDialog rather than window.prompt(): Electron's renderer does
        // not implement window.prompt() (it returns null and logs a warning),
        // which silently aborted the export when running in the desktop app.
        const defaultId = this.fragmentNumber || '';
        this.dialog.open(PromptDialogComponent, {
            data: {
                title: 'Export to eBL',
                message: 'Confirm or edit the eBL fragment number for the lemmatization export:',
                value: defaultId,
                placeholder: 'e.g. K.1234',
                confirmText: 'Export',
                required: true,
            },
        }).afterClosed().subscribe((fragmentId: string | null) => {
            if (fragmentId === null || fragmentId === undefined) return; // user cancelled
            const fragment = fragmentId.trim();
            if (!fragment) {
                this.showNotification('Fragment number cannot be empty', 'error');
                return;
            }
            this.runExport(fragment);
        });
    }

    private runExport(fragment: string): void {
        if (!this.productionId) return;
        this.isExporting = true;
        this.showNotification('Exporting lemmatization to eBL...', 'info');

        // Save first, then export
        if (this.lemmatization) {
            this.lemmatizationService.saveLemmatization(this.productionId, this.lemmatization).subscribe({
                next: () => {
                    this.lemmatizationService.exportToEbl(this.productionId, fragment).subscribe({
                        next: (result: any) => {
                            this.isExporting = false;
                            const invalid: string[] = result?.invalid_lemmas || [];
                            if (invalid.length > 0) {
                                this.showNotification(
                                    `Lemmatization exported. ${invalid.length} unknown lemma id(s) were skipped: ${invalid.slice(0, 5).join(', ')}${invalid.length > 5 ? '…' : ''}`,
                                    'info',
                                );
                            } else {
                                this.showNotification('Lemmatization exported to eBL!', 'success');
                            }
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

    getTokenStatus(line: AtfLine, tokenIdx: number): 'assigned' | 'suggestion' | 'ambiguous' | 'unmatched' | 'skip' | 'atf_suggestion' | 'ai_suggestion' {
        const token = line.tokens[tokenIdx];
        if (this.isUnlemmatizable(token)) return 'skip';

        // Check lemmatization data — has the user assigned (or cleared) a lemma?
        if (this.lemmatization) {
            const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
            const linePos = textLines.indexOf(line);
            if (linePos >= 0 && linePos < this.lemmatization.lines.length) {
                const lemmaLine = this.lemmatization.lines[linePos];
                if (tokenIdx < lemmaLine.tokens.length) {
                    const assignment = lemmaLine.tokens[tokenIdx];
                    if (assignment.unique_lemma.length > 0) {
                        // Unconfirmed suggestions split by source so the panel
                        // can show AI vs ORACC in different colours.
                        if (assignment.is_suggestion) {
                            return assignment.suggestion_source === 'ai'
                                ? 'ai_suggestion'
                                : 'atf_suggestion';
                        }
                        return 'assigned';
                    }
                    // User explicitly said "no lemma" — render as unmatched
                    // and skip the auto-assigned-from-candidates fallback.
                    if (assignment.is_cleared) return 'unmatched';
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
     * Accept an ATF / AI suggestion — marks it as no longer a suggestion.
     * If other tokens share the same cleaned form AND the same proposed lemma
     * AND are still unconfirmed suggestions, offer (in a dialog) to accept
     * them in one batch. We do NOT auto-accept across different lemmas, even
     * if the form matches — those are genuine ambiguities the user should
     * decide individually.
     */
    acceptAtfSuggestion(): void {
        if (!this.lemmatization || !this.selectedLine) return;
        const textLines = this.tokenizedText?.lines.filter(l => l.line_type === 'text') || [];
        const linePos = textLines.indexOf(this.selectedLine);
        if (linePos < 0 || linePos >= this.lemmatization.lines.length) return;
        const lemmaLine = this.lemmatization.lines[linePos];
        if (this.selectedTokenIdx >= lemmaLine.tokens.length) return;

        const assignment = lemmaLine.tokens[this.selectedTokenIdx];
        const acceptedLemma = [...(assignment.unique_lemma || [])];
        const cleaned = this.selectedLine.tokens[this.selectedTokenIdx]?.cleaned || '';

        // Flip the current one first so subsequent counts don't include it.
        assignment.is_suggestion = false;
        assignment.suggestion_source = '';
        this.emitChange();

        if (!cleaned || acceptedLemma.length === 0) return;

        const matchCount = this.countIdenticalSuggestions(cleaned, acceptedLemma);
        if (matchCount <= 0) return;

        const lemmaLabel = acceptedLemma.join(', ');
        const dialogRef = this.dialog.open(ConfirmDialogComponent, {
            data: {
                title: 'Accept identical suggestions',
                message: `Also accept the other ${matchCount} "${cleaned}" suggestion${matchCount > 1 ? 's' : ''} with the same lemma "${lemmaLabel}"?`,
                confirmText: 'Accept all',
                cancelText: 'Skip'
            }
        });
        dialogRef.afterClosed().subscribe(confirmed => {
            if (!confirmed) return;
            const accepted = this.acceptIdenticalSuggestions(cleaned, acceptedLemma);
            this.showNotification(`Accepted ${accepted} identical suggestion${accepted === 1 ? '' : 's'}`, 'success');
            this.emitChange();
        });
    }

    /** Count tokens (excluding the just-accepted one) whose cleaned form
     * matches AND whose current unique_lemma equals `lemmaChain` AND that
     * are still flagged as suggestions. */
    private countIdenticalSuggestions(cleaned: string, lemmaChain: string[]): number {
        if (!this.tokenizedText || !this.lemmatization) return 0;
        const textLines = this.tokenizedText.lines.filter(l => l.line_type === 'text');
        let count = 0;
        for (let li = 0; li < textLines.length; li++) {
            const line = textLines[li];
            if (li >= this.lemmatization.lines.length) break;
            const lemmaLine = this.lemmatization.lines[li];
            for (let ti = 0; ti < line.tokens.length; ti++) {
                if (ti >= lemmaLine.tokens.length) break;
                const tok = line.tokens[ti];
                const asg = lemmaLine.tokens[ti];
                if (tok.cleaned !== cleaned) continue;
                if (!asg.is_suggestion) continue;
                if (!this.lemmaChainsEqual(asg.unique_lemma || [], lemmaChain)) continue;
                count++;
            }
        }
        return count;
    }

    /** Flip is_suggestion=false on every token matching the identical-
     * suggestion criteria. Returns the number of assignments updated. */
    private acceptIdenticalSuggestions(cleaned: string, lemmaChain: string[]): number {
        if (!this.tokenizedText || !this.lemmatization) return 0;
        const textLines = this.tokenizedText.lines.filter(l => l.line_type === 'text');
        let count = 0;
        for (let li = 0; li < textLines.length; li++) {
            const line = textLines[li];
            if (li >= this.lemmatization.lines.length) break;
            const lemmaLine = this.lemmatization.lines[li];
            for (let ti = 0; ti < line.tokens.length; ti++) {
                if (ti >= lemmaLine.tokens.length) break;
                const tok = line.tokens[ti];
                const asg = lemmaLine.tokens[ti];
                if (tok.cleaned !== cleaned) continue;
                if (!asg.is_suggestion) continue;
                if (!this.lemmaChainsEqual(asg.unique_lemma || [], lemmaChain)) continue;
                asg.is_suggestion = false;
                asg.suggestion_source = '';
                count++;
            }
        }
        return count;
    }

    private lemmaChainsEqual(a: string[], b: string[]): boolean {
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
        return true;
    }

    /**
     * Detect broken-sign placeholders that should NEVER be lemmatized:
     * pure "x" stand-ins for unreadable signs and bare ellipses (...).
     * Catches every variant the tokenizer produces — "x", "[x", "x]",
     * "x...", "[...]", "...]", etc. — by stripping brackets/dots/x and
     * checking whether anything readable remains.
     *
     * Equivalent to is_determinative / is_number — once true, the token
     * is treated as skip everywhere (UI status, propagation, counts).
     */
    private isBrokenPlaceholder(rawOrCleaned: string): boolean {
        const base = (rawOrCleaned || '')
            .replace(/[\[\]⌈⌉()<>°…]/g, '')   // brackets + ellipsis char
            .trim();
        if (!base) return true;
        // After removing the x/X placeholder character, dots, and whitespace,
        // nothing real is left → it's a placeholder.
        const meaningful = base.replace(/[xX\.\s]/g, '');
        return meaningful.length === 0;
    }

    /** Single funnel for "should this token be skipped for lemmatization?".
     * Use this everywhere instead of the inline is_determinative/is_number
     * checks so a future criterion only needs to land here. */
    private isUnlemmatizable(token: AtfToken): boolean {
        if (!token) return true;
        if (token.is_determinative || token.is_number) return true;
        // The tokenizer keeps `cleaned` as the form used for dictionary
        // lookup; check there first, then fall back to `raw` for safety.
        return this.isBrokenPlaceholder(token.cleaned) || this.isBrokenPlaceholder(token.raw);
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
        if (!this.lemmatization || !this.tokenizedText) return 0;
        // Walk via tokenizedText so we can apply isUnlemmatizable() and stay
        // aligned with what getTotalLemmatizableCount counts as the denominator.
        const textLines = this.tokenizedText.lines.filter(l => l.line_type === 'text');
        let count = 0;
        for (let li = 0; li < textLines.length; li++) {
            if (li >= this.lemmatization.lines.length) break;
            const tlLine = textLines[li];
            const lemmaLine = this.lemmatization.lines[li];
            for (let ti = 0; ti < tlLine.tokens.length; ti++) {
                if (ti >= lemmaLine.tokens.length) break;
                if (this.isUnlemmatizable(tlLine.tokens[ti])) continue;
                if ((lemmaLine.tokens[ti].unique_lemma || []).length > 0) count++;
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
                if (!this.isUnlemmatizable(token)) count++;
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
