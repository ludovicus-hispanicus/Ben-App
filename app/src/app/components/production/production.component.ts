import { Component, EventEmitter, HostListener, OnInit, OnDestroy, Output, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';
import { PDFDocumentProxy } from 'ng2-pdf-viewer';
import { ProductionService, GroupedText, ProductionText, SourceTextContent, TranslationContent, UploadedImage, KwicResult } from '../../services/production.service';
import { DatasetService } from '../../services/dataset.service';
import { DatasetPreview } from '../../models/cured';
import { CuredService } from '../../services/cured.service';
import { SelectedPdf } from '../cure-d/cured.component';
import { AtfConverterService } from '../../services/atf-converter.service';
import { NotificationService } from '../../services/notification.service';
import { EblService, EblStatus, EblConfig, ValidationResult } from '../../services/ebl.service';
import { TextEditorComponent } from '../cure-d/text-editor/text-editor.component';
import { CanvasType, CanvasMode, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';
import { MatDialog } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';
import { ImageBrowserDialogComponent } from '../common/image-browser-dialog/image-browser-dialog.component';
import { SelectedPage } from '../../models/pages';
import { PagesService } from '../../services/pages.service';

type ViewMode = 'dashboard' | 'editor';

// ATF Help content types
interface AtfHelpItem {
    notation: string;
    description: string;
    example?: string;
}

interface AtfHelpSection {
    id: string;
    title: string;
    keywords: string[];
    introduction: string;  // Full explanatory text
    items: AtfHelpItem[];
}

// Full ATF Help Content with explanatory text
const ATF_HELP_CONTENT: AtfHelpSection[] = [
    {
        id: 'damage',
        title: '1. Damage & Uncertainty Flags',
        keywords: ['damage', 'damaged', 'uncertain', 'correction', 'collated', 'flags', 'hash', 'question'],
        introduction: `Damage flags are suffixes added directly after a sign to indicate its physical or reading condition. These flags can be combined (e.g., #? for damaged and uncertain). The flags appear immediately after the sign with no space.`,
        items: [
            { notation: '#', description: 'Damaged sign - the sign is partially broken but can still be identified', example: 'LUGAL#' },
            { notation: '?', description: 'Uncertain reading - the reading is not certain, possibly another sign', example: 'LUGAL?' },
            { notation: '!', description: 'Correction/emendation - what the scribe wrote is corrected by the editor', example: 'LUGAL!' },
            { notation: '*', description: 'Collated - the reading has been verified by examining the original tablet', example: 'LUGAL*' },
            { notation: '#?', description: 'Damaged and uncertain - sign is broken AND reading is uncertain', example: 'LUGAL#?' },
            { notation: '#!', description: 'Damaged but corrected - sign is broken but a correction is proposed', example: 'LUGAL#!' },
        ]
    },
    {
        id: 'brackets',
        title: '2. Brackets - Breaks & Omissions',
        keywords: ['bracket', 'broken', 'missing', 'omission', 'omitted', 'lacuna', 'gap', 'lost', 'restoration', 'square', 'angle', 'half'],
        introduction: `Brackets indicate different types of missing, damaged, or problematic text. Square brackets [...] mark physical breaks; half brackets ⸢...⸣ mark partially visible signs; angle brackets <...> mark omissions; and double angle brackets <<...>> mark erasures by the ancient scribe.`,
        items: [
            { notation: '[...]', description: 'Broken away - text physically lost due to tablet damage. Content inside may be restored.', example: '[a]-na' },
            { notation: '[x]', description: 'One unreadable sign in a break', example: 'a-[x]-na' },
            { notation: '[x x x]', description: 'Multiple unreadable signs (count them)', example: '[x x x]' },
            { notation: '⸢...⸣ or (...)', description: 'Half brackets - signs partially visible/damaged but legible', example: '⸢a⸣-na' },
            { notation: '<...>', description: 'Accidental omission - the scribe forgot to write this', example: 'a-<na>' },
            { notation: '<(...)>', description: 'Intentional omission - scribe deliberately left out (abbreviation)', example: '<(LUGAL)>' },
            { notation: '<<...>>', description: 'Erased by scribe - ancient deletion, text may still be readable', example: '<<LUGAL>>' },
            { notation: '{...}', description: 'Determinative - semantic classifier, not pronounced', example: '{d}MARDUK' },
            { notation: '{{...}}', description: 'Gloss - ancient explanatory note or addition', example: '{{gloss}}' },
        ]
    },
    {
        id: 'erasure',
        title: '3. Erasures & Over-writing',
        keywords: ['erasure', 'erased', 'correction', 'overwrite', 'over erasure', 'palimpsest', 'scraped', 'rasure'],
        introduction: `Erasures occur when the ancient scribe deliberately removed text, sometimes writing new text over the erased area. The notation uses degree signs (°) to delimit the erasure, with a backslash (\\) separating what was erased from what was written over it.`,
        items: [
            { notation: '°X\\Y°', description: 'X was erased and Y was written over the erasure', example: '°LUGAL\\DUMU°' },
            { notation: '°X\\°', description: 'X was erased, nothing written over (blank erasure)', example: '°LUGAL\\°' },
            { notation: '°\\Y°', description: 'Something was erased (illegible), Y written over', example: '°\\DUMU°' },
            { notation: '°\\°', description: 'Erasure where neither original nor replacement is legible', example: '°\\°' },
        ]
    },
    {
        id: 'special-signs',
        title: '4. Special Signs & Unknowns',
        keywords: ['unclear', 'unidentified', 'unknown', 'illegible', 'traces', 'special', 'ellipsis'],
        introduction: `When signs cannot be read or identified, special markers indicate the degree of visibility. Lowercase 'x' means traces are visible; uppercase 'X' means a sign is visible but unidentifiable; ellipsis '...' indicates an unknown number of signs.`,
        items: [
            { notation: 'x', description: 'Unclear sign - traces are visible but the sign cannot be read', example: 'a-x-na' },
            { notation: 'X', description: 'Unidentified sign - a sign is clearly visible but cannot be identified', example: 'a-X-na' },
            { notation: 'n', description: 'Unknown number of signs (variable placeholder)', example: '[n signs]' },
            { notation: '...', description: 'Ellipsis - unknown/unspecified number of signs missing', example: '[...]' },
            { notation: '($___$)', description: 'Blank space intentionally left by the scribe (vacat)', example: '($___$)' },
            { notation: ':', description: 'Word divider - a colon or vertical wedge separating words', example: 'a-na : LUGAL' },
        ]
    },
    {
        id: 'determinatives',
        title: '5. Determinatives (Semantic Classifiers)',
        keywords: ['determinative', 'classifier', 'semantic', 'divine', 'god', 'person', 'male', 'female', 'place', 'city', 'wood', 'stone', 'metal', 'dingir'],
        introduction: `Determinatives are signs placed before or after words to indicate their semantic category. They were not pronounced but helped readers understand the type of word (divine name, personal name, place, material, etc.). They are written in curly braces {}.`,
        items: [
            { notation: '{d}', description: 'Divine name (DINGIR) - marks names of gods', example: '{d}MARDUK' },
            { notation: '{m}', description: 'Male personal name', example: '{m}na-bi-um' },
            { notation: '{f}', description: 'Female personal name (MUNUS)', example: '{f}ta-ra-am' },
            { notation: '{1}', description: 'Personal name (gender unspecified)', example: '{1}PN' },
            { notation: '{ki}', description: 'Place name / geographic name', example: '{ki}ba-bi-lam' },
            { notation: '{kur}', description: 'Country or land name', example: '{kur}URI' },
            { notation: '{uru}', description: 'City name', example: '{uru}NIBRU' },
            { notation: '{lú}', description: 'Person, profession, or occupation', example: '{lú}SANGA' },
            { notation: '{munus}', description: 'Woman or female profession', example: '{munus}LUKUR' },
            { notation: '{giš}', description: 'Wooden object (GIŠ)', example: '{giš}TUKUL' },
            { notation: '{na₄}', description: 'Stone or stone object', example: '{na₄}KIŠIB' },
            { notation: '{kuš}', description: 'Leather object', example: '{kuš}E.SIR₂' },
            { notation: '{tug₂}', description: 'Cloth or textile', example: '{tug₂}TUG₂' },
            { notation: '{uzu}', description: 'Meat or body part', example: '{uzu}SA' },
            { notation: '{u₂}', description: 'Plant or herb', example: '{u₂}NUMUN' },
            { notation: '{iti}', description: 'Month name', example: '{iti}BARA₂' },
            { notation: '{mul}', description: 'Star or constellation', example: '{mul}AN.TA.GUB' },
            { notation: '{id₂}', description: 'River or canal (ÍD)', example: '{id₂}IDIGNA' },
            { notation: '{dug}', description: 'Vessel or container (pottery)', example: '{dug}UTUL' },
            { notation: '{urudu}', description: 'Copper/bronze object', example: '{urudu}HA.ZI.IN' },
        ]
    },
    {
        id: 'structure',
        title: '6. Structure Lines (@-lines)',
        keywords: ['structure', 'tablet', 'obverse', 'reverse', 'column', 'edge', 'surface', 'seal', 'envelope', 'prism', 'at-line'],
        introduction: `Structure lines begin with @ and define the physical organization of the tablet. They indicate which object is being described, which surface is being read, and how the text is divided into columns. Structure lines do not contain transliterated text.`,
        items: [
            { notation: '@tablet', description: 'Declares the object as a tablet', example: '@tablet' },
            { notation: '@envelope', description: 'Declares an envelope (outer clay casing)', example: '@envelope' },
            { notation: '@prism', description: 'Declares a prism (multi-sided object)', example: '@prism' },
            { notation: '@bulla', description: 'Declares a bulla (clay seal/tag)', example: '@bulla' },
            { notation: '@fragment', description: 'Declares a fragment with description', example: '@fragment a' },
            { notation: '@object X', description: 'Generic object with description', example: '@object cone' },
            { notation: '@obverse', description: 'Front surface of the tablet', example: '@obverse' },
            { notation: '@reverse', description: 'Back surface of the tablet', example: '@reverse' },
            { notation: '@left', description: 'Left edge', example: '@left' },
            { notation: '@right', description: 'Right edge', example: '@right' },
            { notation: '@top', description: 'Top edge', example: '@top' },
            { notation: '@bottom', description: 'Bottom edge', example: '@bottom' },
            { notation: '@edge a', description: 'Named edge (for complex objects)', example: '@edge a' },
            { notation: '@face a', description: 'Named face (for prisms)', example: '@face a' },
            { notation: '@surface a', description: 'Named surface (generic)', example: '@surface a' },
            { notation: '@column N', description: 'Column number (N = 1, 2, 3...)', example: '@column 1' },
            { notation: '@seal N', description: 'Seal impression area (N = 1, 2...)', example: '@seal 1' },
        ]
    },
    {
        id: 'state',
        title: '7. State Lines ($-lines)',
        keywords: ['state', 'broken', 'blank', 'ruling', 'missing', 'illegible', 'traces', 'effaced', 'lacuna', 'gap', 'dollar'],
        introduction: `State lines begin with $ and describe the physical condition of the tablet at a given point. They indicate breaks, blank spaces, ruling lines, and other non-textual features. State lines can use strict syntax or free text in parentheses.`,
        items: [
            { notation: '$ N lines broken', description: 'Indicates N lines are completely broken/missing', example: '$ 3 lines broken' },
            { notation: '$ N lines missing', description: 'Indicates N lines are missing', example: '$ 5 lines missing' },
            { notation: '$ rest of X broken', description: 'Rest of the surface is broken', example: '$ rest of obverse broken' },
            { notation: '$ beginning of X broken', description: 'Beginning of surface is broken', example: '$ beginning of reverse broken' },
            { notation: '$ start of X broken', description: 'Start of surface is broken', example: '$ start of column 1 broken' },
            { notation: '$ end of X broken', description: 'End of surface is broken', example: '$ end of obverse broken' },
            { notation: '$ N lines blank', description: 'N blank lines (uninscribed)', example: '$ 2 lines blank' },
            { notation: '$ rest of X blank', description: 'Rest of surface is blank', example: '$ rest of reverse blank' },
            { notation: '$ single ruling', description: 'Single horizontal line drawn by scribe', example: '$ single ruling' },
            { notation: '$ double ruling', description: 'Double horizontal line', example: '$ double ruling' },
            { notation: '$ triple ruling', description: 'Triple horizontal line', example: '$ triple ruling' },
            { notation: '$ traces', description: 'Only traces of signs visible', example: '$ traces' },
            { notation: '$ illegible', description: 'Text is present but illegible', example: '$ illegible' },
            { notation: '$ effaced', description: 'Text deliberately erased in antiquity', example: '$ effaced' },
            { notation: '$ (free text)', description: 'Free description in parentheses', example: '$ (seal impression here)' },
        ]
    },
    {
        id: 'line-numbers',
        title: '8. Line Numbers',
        keywords: ['line', 'number', 'prime', 'sub-line', 'numbering'],
        introduction: `Every text line must begin with a line number followed by a period. Prime marks (') indicate the tablet is broken at the beginning, so line 1' means "first preserved line." Sub-line letters (a, b, c) handle insertions or corrections.`,
        items: [
            { notation: '1.', description: 'Line 1 (standard line number)', example: '1. a-na LUGAL' },
            { notation: '1\'.', description: 'Line 1 prime - first preserved line when beginning is broken', example: '1\'. [...] LUGAL' },
            { notation: '1\'\'.', description: 'Line 1 double prime - for second fragment/section', example: '1\'\'. text' },
            { notation: '1a.', description: 'Sub-line 1a - for interlinear insertions', example: '1a. inserted text' },
            { notation: '1b.', description: 'Sub-line 1b - second insertion after line 1', example: '1b. more text' },
            { notation: '1-2.', description: 'Lines 1-2 - when one physical line spans two logical lines', example: '1-2. very long line' },
        ]
    },
    {
        id: 'languages',
        title: '9. Language Shifts',
        keywords: ['language', 'akkadian', 'sumerian', 'shift', 'switch', 'bilingual', 'percent'],
        introduction: `Language markers begin with % and indicate which language the following text is in. These are used in bilingual or multilingual texts, or when the default language changes. The marker applies until another marker is used.`,
        items: [
            { notation: '%akk', description: 'Switch to Akkadian', example: '%akk a-na LUGAL' },
            { notation: '%sux', description: 'Switch to Sumerian', example: '%sux lugal-e' },
            { notation: '%es', description: 'Emesal (Sumerian cultic dialect)', example: '%es ga-ša-an' },
            { notation: '%sb', description: 'Standard Babylonian', example: '%sb text' },
            { notation: '%n', description: 'Normalized/Transliteration', example: '%n ana šarrim' },
            { notation: '%grc', description: 'Greek', example: '%grc text' },
        ]
    },
    {
        id: 'readings',
        title: '10. Sign Readings & Values',
        keywords: ['reading', 'value', 'sign', 'subscript', 'index', 'homophone', 'logogram', 'syllable'],
        introduction: `Cuneiform signs can be read as logograms (representing whole words, written UPPERCASE) or syllabically (representing sounds, written lowercase). Subscript numbers distinguish homophones (signs with the same sound). Signs are joined with hyphens within a word, periods between logograms, and spaces between words.`,
        items: [
            { notation: 'SIGN', description: 'Logogram - uppercase indicates the sign is read as a word', example: 'LUGAL (= king)' },
            { notation: 'sign', description: 'Syllabic value - lowercase indicates phonetic reading', example: 'lu-gal' },
            { notation: 'sign₂', description: 'Subscript index for homophones (du, du₂, du₃...)', example: 'du₃' },
            { notation: 'sign-sign', description: 'Hyphen joins syllables of the same word', example: 'a-na' },
            { notation: 'SIGN.SIGN', description: 'Period joins logograms in a compound', example: 'AN.ŠAR₂' },
            { notation: 'SIGNxSIGN', description: 'Compound sign (signs written together)', example: 'UD×BAD' },
            { notation: '|SIGN|', description: 'Complex grapheme (non-standard compound)', example: '|UD.DU|' },
            { notation: 'sign+sign', description: 'Ligature (signs merged into one)', example: 'an+na' },
        ]
    },
    {
        id: 'numbers',
        title: '11. Numbers & Metrological Systems',
        keywords: ['number', 'numeral', 'digit', 'count', 'sexagesimal', 'measure'],
        introduction: `Cuneiform uses different number systems depending on what is being counted. The most common is the sexagesimal (base-60) system. Numbers are written with the count followed by the system name in parentheses.`,
        items: [
            { notation: '1(diš)', description: 'Number 1 in the diš system (basic counting)', example: '1(diš) LUGAL' },
            { notation: '1(u)', description: 'Number 10 (u = 10)', example: '1(u) UDU' },
            { notation: '1(geš₂)', description: 'Number 60 (geš₂ = 60)', example: '1(geš₂)' },
            { notation: '1(šar₂)', description: 'Number 3600 (šar₂ = 60×60)', example: '1(šar₂)' },
            { notation: 'n(diš)', description: 'Unknown number', example: 'n(diš)' },
            { notation: '1/2(diš)', description: 'Fraction (half)', example: '1/2(diš)' },
        ]
    },
    {
        id: 'comments',
        title: '12. Comments & Notes',
        keywords: ['comment', 'note', 'annotation', 'editor'],
        introduction: `Comments can be added to provide additional information that is not part of the transliteration itself. Hash comments (#) are for inline notes.`,
        items: [
            { notation: '# comment', description: 'Comment line (not part of text)', example: '# This line is damaged' },
            { notation: '#note: text', description: 'Editorial note', example: '#note: collated 2024' },
        ]
    },
];

// Helper function to get all content as searchable text
function getSectionSearchText(section: AtfHelpSection): string {
    const itemTexts = section.items.map(item =>
        `${item.notation} ${item.description} ${item.example || ''}`
    ).join(' ');
    return `${section.title} ${section.keywords.join(' ')} ${section.introduction} ${itemTexts}`.toLowerCase();
}

@Component({
    selector: 'app-production',
    templateUrl: './production.component.html',
    styleUrls: ['./production.component.scss']
})
export class ProductionComponent implements OnInit, OnDestroy {
    // View state
    @Output() viewModeChange = new EventEmitter<ViewMode>();
    private _viewMode: ViewMode = 'dashboard';
    get viewMode(): ViewMode { return this._viewMode; }
    set viewMode(value: ViewMode) {
        this._viewMode = value;
        this.viewModeChange.emit(value);
    }

    // Dashboard data
    groupedTexts: GroupedText[] = [];
    filteredGroups: GroupedText[] = [];
    expandedGroups: Set<string> = new Set();
    searchQuery: string = '';
    isLoading: boolean = false;

    // Badge filters
    activeFilters = {
        identifierTypes: new Set<string>(),
        labels: new Set<string>(),
        curation: null as 'curated' | 'not_curated' | null,
        datasetId: null as number | null,
        dateRange: null as 'today' | 'week' | 'month' | 'year' | null,
        status: null as 'not_merged' | 'merged' | 'exported' | null
    };
    availableLabels: string[] = [];
    availableDatasets: DatasetPreview[] = [];

    // Museum data for grid grouping
    museumMap: Map<string, string> = new Map();
    groupedByMuseum: { abbreviation: string; fullName: string; items: GroupedText[] }[] = [];
    selectedMuseum: { abbreviation: string; fullName: string; items: GroupedText[] } | null = null;

    // Editor state
    currentProductionText: ProductionText | null = null;
    currentSources: SourceTextContent[] = [];
    currentTranslations: TranslationContent[] = [];
    editorMode: 'transliteration' | 'translation' = 'transliteration';
    selectedSourceIndex: number = 0;
    editorContent: string = '';
    translationContent: string = '';
    hasUnsavedChanges: boolean = false;
    currentIdentifier: string = '';
    currentIdentifierType: string = '';
    // Track uploaded images: maps source index -> image_id
    uploadedImageIds: Map<number, string> = new Map();
    // Files pending upload (when no production text exists yet)
    pendingImageUploads: { file: File, label: string }[] = [];

    // eBL Integration
    eblStatus: EblStatus | null = null;
    eblConnected: boolean = false;
    showEblSettings: boolean = false;
    showAdvancedEblSettings: boolean = false;
    showValidationResults: boolean = false;
    isValidating: boolean = false;
    isExporting: boolean = false;
    isPullingFromEbl: boolean = false;
    isSavingEblConfig: boolean = false;
    validationResult: ValidationResult | null = null;
    // Export error overlay
    showExportErrorOverlay: boolean = false;
    exportErrorTitle: string = '';
    exportErrorMessage: string = '';
    exportErrorHelp: string = '';
    exportValidationErrors: string[] = [];
    eblConfig: EblConfig = {
        api_url: 'https://www.ebl.lmu.de/api',
        access_token: ''
    };
    isOAuthPending: boolean = false;
    oAuthError: string | null = null;
    authMethod: 'oauth' | 'manual' | null = null;
    private oauthPollInterval: any = null;
    // Login form
    eblUsername: string = '';
    eblPassword: string = '';
    isLoggingIn: boolean = false;
    loginError: string | null = null;
    private eblStatusSubscription: Subscription | null = null;

    // Live validation
    liveValidationEnabled: boolean = true;
    private validationSubject = new Subject<string>();
    private validationSubscription: Subscription | null = null;

    // eBL content pulled from server
    pulledIntroduction: string = '';
    pulledNotes: string = '';

    // Validation panel resize
    validationPanelHeight: number = 200;
    private isResizingValidation: boolean = false;
    private resizeStartY: number = 0;
    private resizeStartHeight: number = 0;

    // Image upload / PDF page selection
    showPdfPageSelector: boolean = false;
    isUploadingImage: boolean = false;
    pdfSrc: Uint8Array | null = null;
    pdfFile: File | null = null;
    pdfTotalPages: number = 0;
    pdfPageNumbers: number[] = [];
    pdfVisiblePageNumbers: number[] = [];
    pdfGoToPageInput: number = 1;
    readonly PDF_PAGE_WINDOW_SIZE = 10;

    // Text Editor
    @ViewChild('textEditor') textEditor: TextEditorComponent;
    @ViewChild('sourceCanvas') sourceCanvas: FabricCanvasComponent;
    canvasTypeViewOnly = CanvasType.SingleSelection;
    CanvasMode = CanvasMode;
    sourceImageDataUrls: Map<number, string> = new Map();
    // Original (unrotated) image data URLs
    private sourceOriginalDataUrls: Map<number, string> = new Map();
    // Per-source viewport state (zoom + pan position)
    private sourceViewports: Map<number, number[]> = new Map();
    // Per-source guide lines (persisted in localStorage)
    private sourceGuides: Map<number, any[]> = new Map();
    // Per-source rotation count (0=0°, 1=90°, 2=180°, 3=270°) — persisted in localStorage
    private sourceRotations: Map<number, number> = new Map();

    // Resizable panels
    leftPanelWidth: number = 45;
    private isResizing: boolean = false;
    private resizeHandler: (e: MouseEvent | TouchEvent) => void;
    private resizeEndHandler: () => void;

    // KWIC concordance search
    kwicResults: KwicResult[] = [];
    kwicSearchActive: boolean = false;
    kwicSearchQuery: string = '';
    isSearchingKwic: boolean = false;

    // ATF Help drawer
    showAtfHelp: boolean = false;
    atfHelpSearchQuery: string = '';
    atfHelpSections: AtfHelpSection[] = ATF_HELP_CONTENT;

    constructor(
        private productionService: ProductionService,
        private datasetService: DatasetService,
        private curedService: CuredService,
        private atfConverter: AtfConverterService,
        private route: ActivatedRoute,
        private router: Router,
        private notificationService: NotificationService,
        private eblService: EblService,
        private dialog: MatDialog,
        private http: HttpClient,
        private pagesService: PagesService
    ) {}

    @HostListener('window:beforeunload', ['$event'])
    onBeforeUnload(event: BeforeUnloadEvent): void {
        if (this.hasUnsavedChanges) {
            event.preventDefault();
            event.returnValue = '';
        }
    }

    @HostListener('document:keydown', ['$event'])
    onKeyDown(event: KeyboardEvent): void {
        if ((event.ctrlKey || event.metaKey) && event.key === 's') {
            event.preventDefault();
            if (this.viewMode === 'editor') {
                this.saveContent();
            }
        }
        // F1 for ATF Help
        if (event.key === 'F1') {
            event.preventDefault();
            if (this.viewMode === 'editor') {
                this.toggleAtfHelp();
            }
        }
    }

    ngOnInit(): void {
        // Subscribe to eBL status
        this.eblStatusSubscription = this.eblService.status$.subscribe(status => {
            this.eblStatus = status;
            this.eblConnected = status?.connected ?? false;
            this.authMethod = status?.auth_method ?? null;
        });

        // Set up live validation with debounce
        this.validationSubscription = this.validationSubject.pipe(
            debounceTime(500), // Wait 500ms after user stops typing
            distinctUntilChanged()
        ).subscribe(content => {
            if (this.liveValidationEnabled && content.trim()) {
                this.performLiveValidation(content);
            }
        });

        // Load museum data for grouping
        this.loadMuseumData();

        // Load datasets for filter
        this.datasetService.list().subscribe(datasets => {
            this.availableDatasets = datasets;
        });

        this.route.queryParams.subscribe(params => {
            if (params['library_project'] && params['library_page']) {
                this.loadFromLibrary(params['library_project'], parseInt(params['library_page']));
            } else if (params['productionId']) {
                this.openProductionText(parseInt(params['productionId']));
            } else if (params['identifier']) {
                this.openByIdentifier(params['identifier'], params['type'] || 'museum');
            } else {
                this.loadDashboard();
            }
        });
    }

    ngOnDestroy(): void {
        if (this.eblStatusSubscription) {
            this.eblStatusSubscription.unsubscribe();
        }
        if (this.validationSubscription) {
            this.validationSubscription.unsubscribe();
        }
        this.cancelOAuth();
    }

    // ==========================================
    // Dashboard Methods
    // ==========================================

    loadDashboard(): void {
        this.viewMode = 'dashboard';
        this.isLoading = true;

        this.productionService.getGroupedData().subscribe({
            next: (data) => {
                this.groupedTexts = data;
                this.computeAvailableLabels();
                this.applyFilter();
                this.isLoading = false;
            },
            error: (err) => {
                console.error('Failed to load grouped data:', err);
                this.notificationService.showError('Failed to load data');
                this.isLoading = false;
            }
        });
    }

    applyFilter(): void {
        const query = this.searchQuery.trim().toLowerCase();
        const { identifierTypes, labels, curation, datasetId, dateRange, status } = this.activeFilters;
        const dateCutoff = this.getDateCutoff(dateRange);

        this.filteredGroups = this.groupedTexts.filter(g => {
            // Text search
            if (query) {
                const matchesText =
                    g.identifier.toLowerCase().includes(query) ||
                    g.identifier_type?.toLowerCase().includes(query) ||
                    this.museumMap.get(g.identifier.split('.')[0] || '')?.toLowerCase().includes(query) ||
                    g.parts.some(p =>
                        (p.labels || []).some(l => l.toLowerCase().includes(query)) ||
                        p.label?.toLowerCase().includes(query) ||
                        p.part?.toLowerCase().includes(query)
                    );
                if (!matchesText) return false;
            }

            // Identifier type filter
            if (identifierTypes.size > 0 && !identifierTypes.has(g.identifier_type)) return false;

            // Label filter
            if (labels.size > 0 && !g.parts.some(p =>
                (p.labels || []).some(l => labels.has(l)) || labels.has(p.label)
            )) return false;

            // Curation filter
            if (curation === 'curated' && !g.parts.some(p => p.is_curated)) return false;
            if (curation === 'not_curated' && g.parts.some(p => p.is_curated)) return false;

            // Dataset filter
            if (datasetId !== null) {
                if (datasetId === -1) {
                    // "Unassigned" — no dataset
                    if (!g.parts.some(p => !p.dataset_id)) return false;
                } else {
                    if (!g.parts.some(p => p.dataset_id === datasetId)) return false;
                }
            }

            // Date filter
            if (dateCutoff) {
                if (!g.parts.some(p => {
                    const d = new Date(p.last_modified);
                    return !isNaN(d.getTime()) && d >= dateCutoff;
                })) return false;
            }

            // Status filter
            if (status === 'exported' && !g.is_exported) return false;
            if (status === 'merged' && (!g.has_production_text || g.is_exported)) return false;
            if (status === 'not_merged' && g.has_production_text) return false;

            return true;
        });

        this.groupByMuseum();
    }

    private getDateCutoff(range: 'today' | 'week' | 'month' | 'year' | null): Date | null {
        if (!range) return null;
        const now = new Date();
        switch (range) {
            case 'today':
                return new Date(now.getFullYear(), now.getMonth(), now.getDate());
            case 'week':
                const weekAgo = new Date(now);
                weekAgo.setDate(weekAgo.getDate() - 7);
                return weekAgo;
            case 'month':
                const monthAgo = new Date(now);
                monthAgo.setMonth(monthAgo.getMonth() - 1);
                return monthAgo;
            case 'year':
                const yearAgo = new Date(now);
                yearAgo.setFullYear(yearAgo.getFullYear() - 1);
                return yearAgo;
            default:
                return null;
        }
    }

    computeAvailableLabels(): void {
        const labelSet = new Set<string>();
        for (const g of this.groupedTexts) {
            for (const p of g.parts) {
                if (p.labels) {
                    p.labels.forEach(l => { if (l) labelSet.add(l); });
                } else if (p.label) {
                    labelSet.add(p.label);
                }
            }
        }
        this.availableLabels = Array.from(labelSet).sort();
    }

    toggleIdentifierType(type: string): void {
        if (this.activeFilters.identifierTypes.has(type)) {
            this.activeFilters.identifierTypes.delete(type);
        } else {
            this.activeFilters.identifierTypes.add(type);
        }
        this.applyFilter();
    }

    toggleLabel(label: string): void {
        if (this.activeFilters.labels.has(label)) {
            this.activeFilters.labels.delete(label);
        } else {
            this.activeFilters.labels.add(label);
        }
        this.applyFilter();
    }

    toggleCuration(value: 'curated' | 'not_curated'): void {
        this.activeFilters.curation = this.activeFilters.curation === value ? null : value;
        this.applyFilter();
    }

    toggleDataset(datasetId: number): void {
        this.activeFilters.datasetId = this.activeFilters.datasetId === datasetId ? null : datasetId;
        this.applyFilter();
    }

    toggleDateRange(range: 'today' | 'week' | 'month' | 'year'): void {
        this.activeFilters.dateRange = this.activeFilters.dateRange === range ? null : range;
        this.applyFilter();
    }

    toggleStatus(value: 'not_merged' | 'merged' | 'exported'): void {
        this.activeFilters.status = this.activeFilters.status === value ? null : value;
        this.applyFilter();
    }

    hasActiveFilters(): boolean {
        return this.activeFilters.identifierTypes.size > 0 ||
            this.activeFilters.labels.size > 0 ||
            this.activeFilters.curation !== null ||
            this.activeFilters.datasetId !== null ||
            this.activeFilters.dateRange !== null ||
            this.activeFilters.status !== null ||
            this.searchQuery.trim().length > 0;
    }

    clearFilters(): void {
        this.activeFilters.identifierTypes.clear();
        this.activeFilters.labels.clear();
        this.activeFilters.curation = null;
        this.activeFilters.datasetId = null;
        this.activeFilters.dateRange = null;
        this.activeFilters.status = null;
        this.searchQuery = '';
        this.applyFilter();
    }

    getDatasetName(datasetId: number): string {
        if (datasetId === -1) return 'Unassigned';
        const dataset = this.availableDatasets.find(p => p.dataset_id === datasetId);
        return dataset ? dataset.name : `Dataset ${datasetId}`;
    }

    // ==========================================
    // KWIC Concordance Search
    // ==========================================

    searchKwic(): void {
        const query = this.searchQuery.trim();
        if (query.length < 2) {
            this.clearKwicSearch();
            return;
        }

        this.isSearchingKwic = true;
        this.kwicSearchQuery = query;

        this.productionService.searchKwic(query).subscribe({
            next: (results) => {
                this.kwicResults = results;
                this.kwicSearchActive = true;
                this.isSearchingKwic = false;
            },
            error: (err) => {
                console.error('KWIC search failed:', err);
                this.notificationService.showError('Search failed');
                this.isSearchingKwic = false;
            }
        });
    }

    clearKwicSearch(): void {
        this.kwicSearchActive = false;
        this.kwicResults = [];
        this.kwicSearchQuery = '';
    }

    openKwicResult(result: KwicResult): void {
        this.router.navigate(['/cured'], {
            queryParams: { identifier: result.identifier, type: result.identifier_type }
        });
    }

    highlightKwicMatch(line: string): string {
        if (!this.kwicSearchQuery) return line;
        const safe = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const escaped = this.kwicSearchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escaped})`, 'gi');
        return safe.replace(regex, '<mark>$1</mark>');
    }

    selectMuseum(museum: { abbreviation: string; fullName: string; items: GroupedText[] }): void {
        this.selectedMuseum = museum;
    }

    /**
     * Load museum abbreviations and full names from the server.
     */
    loadMuseumData(): void {
        this.curedService.getMuseums().subscribe({
            next: (museums) => {
                this.museumMap = new Map(Object.entries(museums));
            },
            error: () => {
                // Silently fail - will use abbreviations without full names
                this.museumMap = new Map();
            }
        });
    }

    /**
     * Group the filtered texts by museum abbreviation for grid display.
     */
    groupByMuseum(): void {
        const groups = new Map<string, GroupedText[]>();

        // Group texts by museum abbreviation
        for (const item of this.filteredGroups) {
            const abbrev = this.getMuseumAbbreviation(item.identifier);
            if (!groups.has(abbrev)) {
                groups.set(abbrev, []);
            }
            groups.get(abbrev).push(item);
        }

        // Convert to array and sort
        this.groupedByMuseum = Array.from(groups.entries())
            .map(([abbreviation, items]) => ({
                abbreviation,
                fullName: this.museumMap.get(abbreviation) || abbreviation,
                items: items.sort((a, b) => {
                    // Sort by number extracted from identifier
                    const numA = this.getIdentifierNumber(a.identifier);
                    const numB = this.getIdentifierNumber(b.identifier);
                    return numA - numB;
                })
            }))
            .sort((a, b) => a.abbreviation.localeCompare(b.abbreviation));

        // Auto-select first museum if none selected or previous selection no longer exists
        if (this.groupedByMuseum.length > 0) {
            if (!this.selectedMuseum || !this.groupedByMuseum.find(m => m.abbreviation === this.selectedMuseum.abbreviation)) {
                this.selectedMuseum = this.groupedByMuseum[0];
            } else {
                // Refresh the reference to the updated data
                this.selectedMuseum = this.groupedByMuseum.find(m => m.abbreviation === this.selectedMuseum.abbreviation);
            }
        } else {
            this.selectedMuseum = null;
        }
    }

    /**
     * Extract museum abbreviation from identifier.
     * Handles formats like "MS.2225", "MS.2225-0", "LB 1", "LB1" -> abbreviation
     */
    getMuseumAbbreviation(identifier: string): string {
        // First, remove part suffix like "-0", "-1" at the end
        let cleanId = identifier.replace(/-\d+$/, '');

        // Handle dot-separated format: "MS.2225" -> "MS"
        const dotIndex = cleanId.indexOf('.');
        if (dotIndex > 0) {
            return cleanId.substring(0, dotIndex);
        }

        // Handle space-separated format: "LB 1" -> "LB"
        const parts = cleanId.trim().split(/\s+/);
        if (parts.length > 1) {
            parts.pop();
            return parts.join(' ') || 'Other';
        }

        // Handle no-separator format: "LB1" -> "LB" (extract leading letters)
        const letterMatch = cleanId.match(/^([A-Za-z]+)/);
        if (letterMatch) {
            return letterMatch[1].toUpperCase();
        }

        return cleanId || 'Other';
    }

    /**
     * Extract number from identifier for sorting.
     * "MS.2225-0" -> 2225, "LB 1" -> 1, "LB1" -> 1
     */
    getIdentifierNumber(identifier: string): number {
        // Remove part suffix like "-0", "-1"
        const cleanId = identifier.replace(/-\d+$/, '');

        // Handle dot-separated: extract number after dot
        const dotMatch = cleanId.match(/\.(\d+)/);
        if (dotMatch) {
            return parseInt(dotMatch[1], 10);
        }

        // Handle space-separated or no-separator: extract first number sequence
        const numMatch = cleanId.match(/(\d+)/);
        return numMatch ? parseInt(numMatch[1], 10) : 0;
    }

    /**
     * Get the museum number for grid display (abbreviation + number).
     * "MS.2225-0" -> "MS.2225", "LB.2126-0" -> "LB.2126"
     */
    getGridItemLabel(identifier: string): string {
        // Remove part suffix like "-0", "-1"
        return identifier.replace(/-\d+$/, '');
    }

    /**
     * Get transliteration info string for a group.
     * Shows parts count and total lines (excluding translations).
     */
    getPartsInfo(group: GroupedText): string {
        // Exclude translation parts from transliteration count
        const transliterationParts = group.parts.filter(p => p.label !== 'translation');
        const partsCount = transliterationParts.length;
        const totalLines = transliterationParts.reduce((sum, p) => sum + (p.lines_count || 0), 0);
        const partsLabel = partsCount === 1 ? 'part' : 'parts';
        return `${partsCount} ${partsLabel} · ${totalLines} lines`;
    }

    /**
     * Get translation info string for a group.
     * Checks if any part has label "translation".
     */
    getTranslationInfo(group: GroupedText): string {
        const translationParts = group.parts.filter(p => p.label === 'translation');
        if (translationParts.length > 0) {
            const totalLines = translationParts.reduce((sum, p) => sum + (p.lines_count || 0), 0);
            const partsLabel = translationParts.length === 1 ? 'part' : 'parts';
            return `${translationParts.length} ${partsLabel} · ${totalLines} lines`;
        }
        return '—';
    }

    /**
     * Get status icon for a group.
     * Not merged: >< (merge symbol), Merged: ● (filled circle), Exported: ✓ (checkmark)
     */
    getStatusIcon(group: GroupedText): string {
        if (group.is_exported) {
            return '✓';  // Exported - green checkmark
        } else if (group.has_production_text) {
            return '●';  // Merged but not exported - orange filled circle
        } else {
            return '><';  // Not merged - two arrows pointing inward (to merge)
        }
    }

    /**
     * Get tooltip text for a card.
     */
    getCardTooltip(group: GroupedText): string {
        let status: string;
        if (group.is_exported) {
            status = 'Exported';
        } else if (group.has_production_text) {
            status = 'Merged (not exported)';
        } else {
            status = 'Not merged';
        }

        const transliterationParts = group.parts.filter(p => p.label !== 'translation');
        const translationParts = group.parts.filter(p => p.label === 'translation');
        const transLines = transliterationParts.reduce((sum, p) => sum + (p.lines_count || 0), 0);
        const translationLines = translationParts.reduce((sum, p) => sum + (p.lines_count || 0), 0);
        const transPartsLabel = transliterationParts.length === 1 ? 'part' : 'parts';
        const translationPartsLabel = translationParts.length === 1 ? 'part' : 'parts';

        let tooltip = `${group.identifier}\nTransliteration: ${transliterationParts.length} ${transPartsLabel}, ${transLines} lines`;
        if (translationParts.length > 0) {
            tooltip += `\nTranslation: ${translationParts.length} ${translationPartsLabel}, ${translationLines} lines`;
        }
        tooltip += `\nStatus: ${status}`;
        return tooltip;
    }

    toggleGroup(identifier: string): void {
        if (this.expandedGroups.has(identifier)) {
            this.expandedGroups.delete(identifier);
        } else {
            this.expandedGroups.add(identifier);
        }
    }

    isGroupExpanded(identifier: string): boolean {
        return this.expandedGroups.has(identifier);
    }

    openGroup(group: GroupedText): void {
        if (group.has_production_text && group.production_id) {
            this.router.navigate(['/cured'], {
                queryParams: { productionId: group.production_id }
            });
        } else {
            this.router.navigate(['/cured'], {
                queryParams: { identifier: group.identifier, type: group.identifier_type }
            });
        }
    }

    createProductionText(group: GroupedText): void {
        // Only include transliteration parts, not translations
        const sourceTextIds = group.parts.filter(p => p.label !== 'translation').map(p => p.text_id);

        this.productionService.createProductionText(
            group.identifier,
            group.identifier_type,
            sourceTextIds
        ).subscribe({
            next: (prodText) => {
                this.notificationService.showSuccess('Production text created');
                this.router.navigate(['/cured'], {
                    queryParams: { productionId: prodText.production_id }
                });
            },
            error: (err) => {
                console.error('Failed to create production text:', err);
                this.notificationService.showError('Failed to create production text');
            }
        });
    }

    // ==========================================
    // Editor Methods
    // ==========================================

    openProductionText(productionId: number): void {
        this.viewMode = 'editor';
        this.isLoading = true;
        // Clear pulled eBL content when opening a new text
        this.pulledIntroduction = '';
        this.pulledNotes = '';

        this.productionService.getProductionText(productionId).subscribe({
            next: (prodText) => {
                this.currentProductionText = prodText;
                this.currentIdentifier = prodText.identifier;
                this.currentIdentifierType = prodText.identifier_type;
                this.editorContent = prodText.content;
                // Store saved translation content to use after loading sources
                const savedTranslationContent = prodText.translation_content;
                this.hasUnsavedChanges = false;
                this.loadSources(productionId, savedTranslationContent);
            },
            error: (err) => {
                console.error('Failed to load production text:', err);
                this.notificationService.showError('Failed to load production text');
                this.isLoading = false;
            }
        });
    }

    openByIdentifier(identifier: string, identifierType: string): void {
        this.viewMode = 'editor';
        this.isLoading = true;
        this.currentIdentifier = identifier;
        this.currentIdentifierType = identifierType;
        this.currentProductionText = null;
        this.editorContent = '';
        this.uploadedImageIds.clear();
        this.pendingImageUploads = [];
        // Clear pulled eBL content when opening a new text
        this.pulledIntroduction = '';
        this.pulledNotes = '';

        // Load sources from training data (separated into transliterations and translations)
        this.productionService.getSourcesByIdentifier(identifier).subscribe({
            next: (response) => {
                // Sources are transliterations (with images)
                this.currentSources = response.sources.map(p => ({
                    text_id: p.text_id,
                    transliteration_id: p.transliteration_id,
                    part: p.part,
                    lines: p.lines || [],
                    image_name: p.image_name || '',
                    source: p.source || '',
                    label: p.label || ''
                }));
                this.sortSources();
                // Translations are separate (text only)
                this.currentTranslations = response.translations || [];
                this.translationContent = this.formatTranslationText();
                this.loadSourceImages();

                // Generate initial editor content from transliteration sources only
                this.generateInitialContent();

                this.isLoading = false;
            },
            error: (err) => {
                console.error('Failed to load sources:', err);
                this.isLoading = false;
            }
        });
    }

    private sortSources(): void {
        this.currentSources.sort((a, b) => {
            // Training before translation
            const aIsTranslation = a.label === 'translation' ? 1 : 0;
            const bIsTranslation = b.label === 'translation' ? 1 : 0;
            if (aIsTranslation !== bIsTranslation) return aIsTranslation - bIsTranslation;
            // Then by part alphanumerically
            return (a.part || '').localeCompare(b.part || '', undefined, { numeric: true });
        });
    }

    /**
     * Generate initial editor content from source transliterations.
     */
    private generateInitialContent(): void {
        const mergedLines: string[] = [];
        // Only use one transliteration per part (prefer CuReD source)
        const seenParts = new Set<string>();
        const sortedSources = [...this.currentSources]
            .filter(s => s.text_id !== -1) // exclude uploaded images
            .sort((a, b) => {
                const partCmp = a.part.localeCompare(b.part);
                if (partCmp !== 0) return partCmp;
                // Prefer CuReD source
                if (a.source === 'cured' && b.source !== 'cured') return -1;
                if (a.source !== 'cured' && b.source === 'cured') return 1;
                return 0;
            });

        for (const source of sortedSources) {
            const partKey = `${source.text_id}_${source.part}`;
            if (seenParts.has(partKey)) continue;
            seenParts.add(partKey);

            if (source.lines && source.lines.length > 0) {
                if (source.part) {
                    mergedLines.push(`# Part ${source.part}`);
                }
                mergedLines.push(...source.lines);
                mergedLines.push('');
            }
        }

        this.editorContent = mergedLines.join('\n').trim();
    }

    loadSources(productionId: number, savedTranslationContent?: string): void {
        this.productionService.getProductionSources(productionId).subscribe({
            next: (response) => {
                // Sources are transliterations (with images)
                this.currentSources = response.sources;
                this.sortSources();
                // Translations are separate (text only, no images)
                this.currentTranslations = response.translations;
                // Use saved translation content if available, otherwise format from sources
                this.translationContent = savedTranslationContent || this.formatTranslationText();
                this.selectedSourceIndex = 0;
                this.uploadedImageIds.clear();
                this.pendingImageUploads = [];
                this.loadSourceImages();
                // Also load uploaded images from the production text
                this.loadUploadedImages();
                // Load saved annotations from localStorage
                this.loadGuidesFromStorage();
                this.loadRotationsFromStorage();
                this.isLoading = false;
            },
            error: (err) => {
                console.error('Failed to load sources:', err);
                this.isLoading = false;
            }
        });
    }

    private loadUploadedImages(): void {
        if (!this.currentProductionText?.uploaded_images) {
            return;
        }

        for (const uploadedImage of this.currentProductionText.uploaded_images) {
            const newIndex = this.currentSources.length;

            // Add to sources
            const newSource: SourceTextContent = {
                text_id: -1,
                transliteration_id: -1,
                part: uploadedImage.label,
                lines: [],
                image_name: uploadedImage.image_name
            };
            this.currentSources.push(newSource);
            this.uploadedImageIds.set(newIndex, uploadedImage.image_id);

            // Load the image from backend
            this.productionService.getUploadedImage(
                this.currentProductionText!.production_id,
                uploadedImage.image_id
            ).subscribe({
                next: (blob) => {
                    const reader = new FileReader();
                    reader.onload = () => {
                        const dataUrl = reader.result as string;
                        this.sourceImageDataUrls.set(newIndex, dataUrl);
                        if (newIndex === this.selectedSourceIndex) {
                            this.loadImageIntoCanvas(dataUrl);
                        }
                    };
                    reader.readAsDataURL(blob);
                },
                error: (err) => {
                    console.error(`Failed to load uploaded image ${uploadedImage.image_id}:`, err);
                }
            });
        }
    }

    loadSourceImages(): void {
        this.sourceImageDataUrls.clear();
        this.currentSources.forEach((source, index) => {
            // Skip uploaded images (text_id === -1), they are loaded separately
            if (source.text_id === -1) {
                return;
            }
            this.curedService.getImage(source.text_id, source.transliteration_id).subscribe({
                next: (blob) => {
                    const reader = new FileReader();
                    reader.onload = () => {
                        const dataUrl = reader.result as string;
                        this.sourceImageDataUrls.set(index, dataUrl);
                        if (index === this.selectedSourceIndex) {
                            this.loadImageIntoCanvas(dataUrl);
                        }
                    };
                    reader.readAsDataURL(blob);
                },
                error: (err) => {
                    console.error(`Failed to load image for source ${index}:`, err);
                }
            });
        });
    }

    getSourceTabLabel(source: SourceTextContent, index: number): string {
        const part = source.part || `${index + 1}`;
        // Translation images
        if (source.label === 'translation') {
            return `Translation ${part}`;
        }
        // Uploaded images
        if (source.text_id === -1) {
            return source.image_name || `Image ${index + 1}`;
        }
        // Training (transliteration) sources
        const samePart = this.currentSources.filter(s => s.part === source.part && s.text_id !== -1 && s.label !== 'translation');
        if (samePart.length > 1 && source.source) {
            return `Training ${part} (${source.source})`;
        }
        return `Training ${part}`;
    }

    deleteSource(index: number, event: Event): void {
        event.stopPropagation();
        const source = this.currentSources[index];
        if (!source) return;

        const label = this.getSourceTabLabel(source, index);
        const isUploaded = this.uploadedImageIds.has(index);
        const warning = isUploaded
            ? `Remove "${label}" from this production text?`
            : `Remove "${label}" from this production text?\n\nThis will remove the source reference. The original training data will not be deleted.`;

        if (!confirm(warning)) return;

        if (isUploaded) {
            // Delete uploaded image from backend
            const imageId = this.uploadedImageIds.get(index);
            if (!imageId || !this.currentProductionText) return;
            this.productionService.deleteUploadedImage(
                this.currentProductionText.production_id, imageId
            ).subscribe({
                next: () => this.removeSourceFromList(index),
                error: (err) => {
                    console.error('Failed to delete image:', err);
                    this.notificationService.showError('Failed to delete image');
                }
            });
        } else if (this.currentProductionText) {
            // Remove source reference from production text
            this.productionService.removeSource(
                this.currentProductionText.production_id,
                source.text_id,
                source.transliteration_id
            ).subscribe({
                next: () => this.removeSourceFromList(index),
                error: (err) => {
                    console.error('Failed to remove source:', err);
                    this.notificationService.showError('Failed to remove source');
                }
            });
        } else {
            // No production text yet, just remove locally
            this.removeSourceFromList(index);
        }
    }

    private removeSourceFromList(index: number): void {
        this.currentSources.splice(index, 1);
        this.sourceImageDataUrls.delete(index);
        this.sourceViewports.delete(index);
        this.uploadedImageIds.delete(index);

        // Rebuild maps with corrected indices
        const newUploads = new Map<number, string>();
        this.uploadedImageIds.forEach((id, idx) => {
            newUploads.set(idx > index ? idx - 1 : idx, id);
        });
        this.uploadedImageIds = newUploads;

        const newUrls = new Map<number, string>();
        this.sourceImageDataUrls.forEach((url, idx) => {
            newUrls.set(idx > index ? idx - 1 : idx, url);
        });
        this.sourceImageDataUrls = newUrls;

        // Adjust selected index
        if (this.selectedSourceIndex >= this.currentSources.length) {
            this.selectedSourceIndex = Math.max(0, this.currentSources.length - 1);
        }
        const dataUrl = this.sourceImageDataUrls.get(this.selectedSourceIndex);
        if (dataUrl) {
            this.loadImageIntoCanvas(dataUrl);
        }
    }

    selectSource(index: number): void {
        // Save current state before switching
        this.saveCurrentViewport();
        this.saveCurrentGuides();
        this.selectedSourceIndex = index;
        const dataUrl = this.sourceImageDataUrls.get(index);
        if (dataUrl) {
            setTimeout(() => this.loadImageIntoCanvas(dataUrl, index), 0);
        }
    }

    private saveCurrentViewport(): void {
        if (this.sourceCanvas) {
            const vpt = this.sourceCanvas.getViewportTransform();
            if (vpt) {
                this.sourceViewports.set(this.selectedSourceIndex, vpt);
            }
        }
    }

    startResize(event: MouseEvent | TouchEvent): void {
        event.preventDefault();
        this.isResizing = true;

        const container = (event.target as HTMLElement).closest('.editor-content') as HTMLElement;
        if (!container) return;

        const containerRect = container.getBoundingClientRect();

        this.resizeHandler = (e: MouseEvent | TouchEvent) => {
            if (!this.isResizing) return;

            const clientX = e instanceof MouseEvent ? e.clientX : e.touches[0].clientX;
            const newWidth = ((clientX - containerRect.left) / containerRect.width) * 100;

            this.leftPanelWidth = Math.max(20, Math.min(80, newWidth));
        };

        this.resizeEndHandler = () => {
            this.isResizing = false;
            document.removeEventListener('mousemove', this.resizeHandler);
            document.removeEventListener('mouseup', this.resizeEndHandler);
            document.removeEventListener('touchmove', this.resizeHandler);
            document.removeEventListener('touchend', this.resizeEndHandler);

            // Update canvas size to fit new panel width, preserving zoom/pan
            if (this.sourceCanvas) {
                this.saveCurrentViewport();
                const dataUrl = this.sourceImageDataUrls.get(this.selectedSourceIndex);
                if (dataUrl) {
                    setTimeout(() => this.loadImageIntoCanvas(dataUrl), 100);
                }
            }
        };

        document.addEventListener('mousemove', this.resizeHandler);
        document.addEventListener('mouseup', this.resizeEndHandler);
        document.addEventListener('touchmove', this.resizeHandler);
        document.addEventListener('touchend', this.resizeEndHandler);
    }

    activateGuideMode(): void {
        if (this.sourceCanvas?.allowedActions?.some(a => a.name === CanvasMode.Guide)) {
            this.sourceCanvas.changeMode(CanvasMode.Guide);
        }
    }

    onGuideStrokeChange(event: Event): void {
        const val = +(event.target as HTMLInputElement).value;
        this.sourceCanvas?.setGuideStrokeWidth(val);
    }

    onGuidesChanged(guides: any[]): void {
        this.sourceGuides.set(this.selectedSourceIndex, guides);
        this.persistGuidesToStorage();
    }

    private saveCurrentGuides(): void {
        if (this.sourceCanvas) {
            const guides = this.sourceCanvas.getGuides();
            if (guides.length > 0) {
                this.sourceGuides.set(this.selectedSourceIndex, guides);
            } else {
                this.sourceGuides.delete(this.selectedSourceIndex);
            }
            this.persistGuidesToStorage();
        }
    }

    private loadGuidesForSource(index: number): void {
        if (!this.sourceCanvas) return;
        const guides = this.sourceGuides.get(index);
        if (guides && guides.length) {
            this.sourceCanvas.loadGuides(guides);
        } else {
            this.sourceCanvas.clearGuides();
        }
    }

    private get guidesStorageKey(): string {
        const prodId = this.currentProductionText?.production_id || 'draft';
        return `prod_guides_${prodId}`;
    }

    private persistGuidesToStorage(): void {
        const data: { [key: number]: any[] } = {};
        this.sourceGuides.forEach((guides, idx) => {
            if (guides.length > 0) data[idx] = guides;
        });
        if (Object.keys(data).length > 0) {
            localStorage.setItem(this.guidesStorageKey, JSON.stringify(data));
        } else {
            localStorage.removeItem(this.guidesStorageKey);
        }
    }

    private loadGuidesFromStorage(): void {
        try {
            const raw = localStorage.getItem(this.guidesStorageKey);
            if (!raw) return;
            const data = JSON.parse(raw);
            this.sourceGuides.clear();
            Object.keys(data).forEach(key => {
                this.sourceGuides.set(+key, data[key]);
            });
        } catch (e) {
            // ignore invalid data
        }
    }

    // ── Rotation persistence ──

    private get rotationsStorageKey(): string {
        const prodId = this.currentProductionText?.production_id || 'draft';
        return `prod_rotations_${prodId}`;
    }

    private persistRotationsToStorage(): void {
        const data: { [key: number]: number } = {};
        this.sourceRotations.forEach((count, idx) => {
            if (count > 0) data[idx] = count;
        });
        if (Object.keys(data).length > 0) {
            localStorage.setItem(this.rotationsStorageKey, JSON.stringify(data));
        } else {
            localStorage.removeItem(this.rotationsStorageKey);
        }
    }

    private loadRotationsFromStorage(): void {
        try {
            const raw = localStorage.getItem(this.rotationsStorageKey);
            if (!raw) return;
            const data = JSON.parse(raw);
            this.sourceRotations.clear();
            Object.keys(data).forEach(key => {
                this.sourceRotations.set(+key, data[key]);
            });
        } catch (e) {
            // ignore
        }
    }

    /** Apply N×90° clockwise rotations to a data URL. */
    private applyRotations(dataUrl: string, count: number): Promise<string> {
        if (count <= 0) return Promise.resolve(dataUrl);
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                let src: HTMLCanvasElement | HTMLImageElement = img;
                let w = img.width, h = img.height;
                for (let i = 0; i < count; i++) {
                    const offscreen = document.createElement('canvas');
                    const ctx = offscreen.getContext('2d');
                    offscreen.width = h;
                    offscreen.height = w;
                    ctx.translate(h, 0);
                    ctx.rotate(Math.PI / 2);
                    ctx.drawImage(src, 0, 0);
                    src = offscreen;
                    [w, h] = [h, w];
                }
                resolve((src as HTMLCanvasElement).toDataURL('image/png'));
            };
            img.src = dataUrl;
        });
    }

    onSourceImageRotated(rotatedDataUrl: string): void {
        // Update cached data URL so rotation persists when switching tabs
        this.sourceImageDataUrls.set(this.selectedSourceIndex, rotatedDataUrl);
        // Track rotation count and persist
        const current = this.sourceRotations.get(this.selectedSourceIndex) || 0;
        this.sourceRotations.set(this.selectedSourceIndex, (current + 1) % 4);
        this.persistRotationsToStorage();
    }

    private loadImageIntoCanvas(dataUrl: string, sourceIndex?: number): void {
        if (!this.sourceCanvas) return;
        const idx = sourceIndex ?? this.selectedSourceIndex;

        // Store original if not yet stored
        if (!this.sourceOriginalDataUrls.has(idx)) {
            this.sourceOriginalDataUrls.set(idx, dataUrl);
        }

        // Apply saved rotation from original
        const original = this.sourceOriginalDataUrls.get(idx) || dataUrl;
        const rotCount = this.sourceRotations.get(idx) || 0;
        if (rotCount > 0) {
            this.applyRotations(original, rotCount).then(rotatedUrl => {
                this.sourceImageDataUrls.set(idx, rotatedUrl);
                this.doLoadImageIntoCanvas(rotatedUrl, idx);
            });
        } else {
            this.doLoadImageIntoCanvas(dataUrl, idx);
        }
    }

    private doLoadImageIntoCanvas(dataUrl: string, idx: number): void {
        this.sourceCanvas.props.canvasImage = dataUrl;
        this.sourceCanvas.setCanvasImage();
        const availableHeight = window.innerHeight - 130;
        const sourcePanel = document.querySelector('.source-panel');
        const availableWidth = sourcePanel ? sourcePanel.clientWidth : window.innerWidth * 0.45;
        this.sourceCanvas.props.canvasHeight = availableHeight;
        this.sourceCanvas.props.canvasWidth = availableWidth;
        this.sourceCanvas.forceCanvasSize();

        const savedVpt = this.sourceViewports.get(idx);
        if (savedVpt) {
            this.sourceCanvas.restoreViewportTransform(savedVpt);
        } else {
            this.sourceCanvas.forceZoomOut(0.5);
        }

        // Restore guides for this source
        this.loadGuidesForSource(idx);
    }

    onEditorContentChange(content: string): void {
        this.editorContent = content;
        this.hasUnsavedChanges = true;
        // Trigger live validation
        this.validationSubject.next(content);
    }

    saveContent(): void {
        if (!this.currentProductionText) {
            // Create new production text first
            // Filter out uploaded images (text_id === -1) from source text IDs
            const sourceTextIds = [...new Set(this.currentSources
                .filter(s => s.text_id !== -1)
                .map(s => s.text_id))];
            this.productionService.createProductionText(
                this.currentIdentifier,
                this.currentIdentifierType,
                sourceTextIds,
                this.editorContent
            ).subscribe({
                next: (prodText) => {
                    this.currentProductionText = prodText;
                    this.hasUnsavedChanges = false;
                    this.notificationService.showSuccess('Production text created and saved');
                    // Upload any pending images now that we have a production text
                    this.uploadPendingImages();
                },
                error: (err) => {
                    console.error('Failed to create production text:', err);
                    this.notificationService.showError('Failed to save');
                }
            });
        } else {
            // Update existing
            this.productionService.updateProductionText(
                this.currentProductionText.production_id,
                this.editorContent,
                this.translationContent
            ).subscribe({
                next: (prodText) => {
                    this.currentProductionText = prodText;
                    this.hasUnsavedChanges = false;
                    this.notificationService.showSuccess('Saved');
                },
                error: (err) => {
                    console.error('Failed to save:', err);
                    this.notificationService.showError('Failed to save');
                }
            });
        }
    }

    regenerateContent(): void {
        if (!this.currentProductionText) {
            // Generate from sources
            const mergedLines: string[] = [];
            const sortedSources = [...this.currentSources].sort((a, b) => a.part.localeCompare(b.part));

            for (const source of sortedSources) {
                if (source.part) {
                    mergedLines.push(`# Part ${source.part}`);
                }
                mergedLines.push(...source.lines);
                mergedLines.push('');
            }

            this.editorContent = mergedLines.join('\n').trim();
            this.hasUnsavedChanges = true;
        } else {
            this.productionService.regenerateProductionContent(this.currentProductionText.production_id).subscribe({
                next: (prodText) => {
                    this.currentProductionText = prodText;
                    this.editorContent = prodText.content;
                    this.hasUnsavedChanges = false;
                    this.notificationService.showSuccess('Content regenerated');
                },
                error: (err) => {
                    console.error('Failed to regenerate:', err);
                    this.notificationService.showError('Failed to regenerate');
                }
            });
        }
    }

    /**
     * Set the editor mode (transliteration or translation).
     */
    setEditorMode(mode: 'transliteration' | 'translation'): void {
        this.editorMode = mode;
    }

    /**
     * Check if translations are available.
     */
    hasTranslations(): boolean {
        return this.currentTranslations && this.currentTranslations.length > 0;
    }

    /**
     * Format translation text for the editor.
     * Combines all translation parts into a single text block.
     */
    private formatTranslationText(): string {
        if (!this.currentTranslations || this.currentTranslations.length === 0) {
            return '';
        }

        const parts: string[] = [];
        for (const trans of this.currentTranslations) {
            if (trans.part) {
                parts.push(`# Part ${trans.part}`);
            }
            parts.push(...trans.lines);
            parts.push('');
        }
        return parts.join('\n').trim();
    }

    /**
     * Get translation line count for display.
     */
    getTranslationLineCount(): number {
        if (!this.currentTranslations) return 0;
        return this.currentTranslations.reduce((sum, t) => sum + (t.lines?.length || 0), 0);
    }

    /**
     * Get transliteration line count for display.
     */
    getTransliterationLineCount(): number {
        return this.editorContent ? this.editorContent.split('\n').length : 0;
    }

    /**
     * Handle translation content changes from the editor.
     */
    onTranslationContentChange(content: string): void {
        this.translationContent = content;
        this.hasUnsavedChanges = true;
    }

    /**
     * Insert translation lines into the transliteration using eBL ATF format.
     *
     * eBL format:
     * - Single line translation: #tr.en: text  (placed after the line)
     * - Multi-line range (e.g., lines 1-2): #tr.en.(2): text  (placed after line 1, referencing end line 2)
     *
     * Translation source lines can have formats like:
     *   "1 Translation text" or "1-2 Translation text" or "#tr.en: 1-2 Translation text"
     */
    insertTranslation(): void {
        if (!this.translationContent || this.translationContent.trim() === '') {
            this.notificationService.showWarning('No translation content to insert');
            return;
        }

        if (!this.editorContent || this.editorContent.trim() === '') {
            this.notificationService.showWarning('No transliteration content to merge with');
            return;
        }

        const translitLines = this.editorContent.split('\n');
        const rawTransLines = this.translationContent.split('\n');

        // 1. Build a map from displayed line label (e.g. "1'", "13'", "2") to transliteration array index.
        //    The label is what appears at the start of each line: number + optional prime.
        const translitLabelToIndex: Map<string, number> = new Map();
        let currentSection = '';
        for (let i = 0; i < translitLines.length; i++) {
            const trimmed = translitLines[i].trim().toLowerCase();
            const secMatch = trimmed.match(/^[\$@](reverse|obverse|left|right|top|bottom|edge|seal|column)/);
            if (secMatch) {
                currentSection = secMatch[1];
                continue;
            }
            // Extract line label: "1'." or "1." or "16" at start of line (use trimmed for whitespace tolerance)
            const lineMatch = trimmed.match(/^(\d+'?)\.\s/);
            if (lineMatch) {
                const label = lineMatch[1]; // e.g. "1'", "13'", "2"
                if (!translitLabelToIndex.has(label)) {
                    translitLabelToIndex.set(label, i);
                }
            }
        }

        // 2. Parse translation lines, splitting embedded ranges
        const parsedTranslations: {
            startLabel: string;   // e.g. "2'", "13'", "3"
            endLabel: string;     // e.g. "4'", "2", "4"
            cleanedText: string;
            isRange: boolean;
        }[] = [];

        for (const rawLine of rawTransLines) {
            const trimmed = rawLine.trim();
            if (trimmed === '' || trimmed.startsWith('# ')) continue;

            // Skip section markers in translation (they're for readability, we use line labels)
            const sectionMatch = trimmed.match(/^@(reverse|obverse|left|right|top|bottom|edge)/i);
            if (sectionMatch) continue;

            // Split line if it contains embedded ranges
            const subLines = this.splitEmbeddedRanges(trimmed);

            for (const subLine of subLines) {
                const parsed = this.parseTranslationLineByLabel(subLine);
                if (parsed) {
                    parsedTranslations.push(parsed);
                }
            }
        }

        if (parsedTranslations.length === 0) {
            this.notificationService.showWarning('No translation lines could be parsed');
            return;
        }

        // 3. Build map: transliteration line index → translations to insert after it
        const translationsAfterIndex: Map<number, string[]> = new Map();

        for (const parsed of parsedTranslations) {
            const insertAfterIndex = translitLabelToIndex.get(parsed.startLabel);
            if (insertAfterIndex === undefined) continue;

            if (!translationsAfterIndex.has(insertAfterIndex)) {
                translationsAfterIndex.set(insertAfterIndex, []);
            }

            // Determine end label's section prefix for eBL format
            let formattedLine: string;
            if (parsed.isRange) {
                const endSectionPrefix = this.getSectionPrefixForLabel(parsed.endLabel, translitLines);
                formattedLine = `#tr.en.(${endSectionPrefix}${parsed.endLabel}): ${parsed.cleanedText}`;
            } else {
                formattedLine = `#tr.en: ${parsed.cleanedText}`;
            }
            translationsAfterIndex.get(insertAfterIndex)!.push(formattedLine);
        }

        // 4. Create merged content with translations interleaved
        const mergedLines: string[] = [];
        let insertedCount = 0;

        for (let i = 0; i < translitLines.length; i++) {
            mergedLines.push(translitLines[i]);
            if (translationsAfterIndex.has(i)) {
                for (const transLine of translationsAfterIndex.get(i)!) {
                    mergedLines.push(transLine);
                    insertedCount++;
                }
            }
        }

        // 5. Append any unmatched translations at the end
        for (const parsed of parsedTranslations) {
            if (!translitLabelToIndex.has(parsed.startLabel)) {
                const formattedLine = parsed.isRange
                    ? `#tr.en.(${parsed.endLabel}): ${parsed.cleanedText}`
                    : `#tr.en: ${parsed.cleanedText}`;
                mergedLines.push(formattedLine);
                insertedCount++;
            }
        }

        this.editorContent = mergedLines.join('\n');
        this.hasUnsavedChanges = true;

        // Switch to transliteration mode to show the merged content
        this.editorMode = 'transliteration';

        this.notificationService.showSuccess(`Inserted ${insertedCount} translation lines`);
    }

    /**
     * Parse a translation line by its label (e.g., "2'–4'", "13'–2", "3-4").
     * Returns start/end labels as strings preserving primes.
     */
    private parseTranslationLineByLabel(line: string): { startLabel: string; endLabel: string; cleanedText: string; isRange: boolean } | null {
        // Remove #tr.XX: prefix if present
        let text = line;
        const trMatch = line.match(/^#tr\.\w+(?:\.\([^)]+\))?:\s*/);
        if (trMatch) {
            text = line.substring(trMatch[0].length);
        }

        // Match: "1'–2" or "13'–2" or "3-4" or "1'." or "3" etc.
        // startNum + optional prime + optional (dash/endash + endNum + optional prime) + optional period + space + text
        const numMatch = text.match(/^(\d+'?)(?:[–\-](\d+'?))?\.?\s+(.*)$/);
        if (!numMatch) return null;

        const startLabel = numMatch[1];  // e.g. "2'", "13'", "3"
        const endLabel = numMatch[2] || startLabel;  // e.g. "4'", "2", "4"
        const cleanedText = numMatch[3];
        const isRange = startLabel !== endLabel;

        return { startLabel, endLabel, cleanedText, isRange };
    }

    /**
     * Find the eBL section prefix for a given line label by scanning transliteration.
     * E.g., if label "2" appears after @reverse, returns "r ".
     */
    private getSectionPrefixForLabel(label: string, translitLines: string[]): string {
        let currentSection = 'obverse';
        for (const line of translitLines) {
            const trimmed = line.trim().toLowerCase();
            const secMatch = trimmed.match(/^[\$@](reverse|obverse|left|right|top|bottom|edge|seal|column)/);
            if (secMatch) {
                currentSection = secMatch[1];
                continue;
            }
            // Use trimmed line for matching to handle leading whitespace
            const lineMatch = trimmed.match(/^(\d+'?)\.\s/);
            if (lineMatch && lineMatch[1] === label) {
                return this.getSectionPrefix(currentSection);
            }
        }
        // Fallback: if label not found, return prefix based on last known section
        console.warn(`[getSectionPrefixForLabel] label "${label}" not found, using last section "${currentSection}"`);
        return this.getSectionPrefix(currentSection);
    }

    /**
     * Split a translation line that contains embedded ranges.
     * e.g., "4–5 If text; 6–7 the king..." → ["4–5 If text;", "6–7 the king..."]
     * Only splits on en-dash ranges (N–M) to avoid false positives with hyphens in text.
     */
    private splitEmbeddedRanges(line: string): string[] {
        // Split before embedded range patterns: digit(s) + optional prime + en-dash + digit(s)
        // preceded by whitespace. Use lookahead to keep the range in the result.
        const parts = line.split(/\s+(?=\d+'?\u2013\d+'?\.?\s)/);
        return parts.filter(p => p.trim().length > 0);
    }

    /**
     * Parse line numbers from a transliteration line.
     * Handles formats like: "1.", "1'.", "1-3.", "1-3'."
     * Returns an array of all line numbers covered by this line.
     */
    private parseLineNumbers(line: string): number[] {
        // Match patterns like: 1. 1'. 1-3. 1-3'. Also handle spaces and various formats
        const match = line.match(/^(\d+)(?:[–-](\d+))?'?\.\s/);
        if (!match) return [];

        const start = parseInt(match[1], 10);
        const end = match[2] ? parseInt(match[2], 10) : start;

        const nums: number[] = [];
        for (let i = start; i <= end; i++) {
            nums.push(i);
        }
        return nums;
    }

    /**
     * Parse a translation line and return start line, end line, and cleaned text.
     * Handles formats:
     *   "1–2 text"    (en-dash range)
     *   "1-2 text"    (hyphen range)
     *   "4'–5'. text" (primed numbers with en-dash)
     *   "13 text"     (single line)
     *   "1'. text"    (single primed line)
     *   "#tr.en: 1-2 text" (with prefix)
     */
    private parseAndCleanTranslationLine(line: string): { startLineNum: number; endLineNum: number; cleanedText: string; hasPrime: boolean } {
        // Remove #tr.XX: or #tr.XX.(N): prefix if present
        let text = line;
        const trMatch = line.match(/^#tr\.\w+(?:\.\(\d+\))?:\s*/);
        if (trMatch) {
            text = line.substring(trMatch[0].length);
        }

        // Match line number at start with optional primes and en-dash/hyphen:
        // "1–2 text", "4'–5'. text", "13 text", "1'. text"
        const numMatch = text.match(/^(\d+)(')?(?:[–\-](\d+)(')?)?\.?\s+(.*)$/);
        if (!numMatch) {
            return { startLineNum: 0, endLineNum: 0, cleanedText: text, hasPrime: false };
        }

        const startLineNum = parseInt(numMatch[1], 10);
        const hasPrime = !!(numMatch[2] || numMatch[4]); // prime on start or end number
        const endLineNum = numMatch[3] ? parseInt(numMatch[3], 10) : startLineNum;
        const cleanedText = numMatch[5];

        return { startLineNum, endLineNum, cleanedText, hasPrime };
    }

    private getSectionPrefix(section: string): string {
        const prefixes: { [key: string]: string } = {
            'obverse': 'o ',
            'reverse': 'r ',
            'bottom': 'b.e. ',
            'left': 'l.e. ',
            'right': 'r.e. ',
            'top': 't.e. ',
            'edge': 'e. ',
            'seal': 'seal ',
        };
        return prefixes[section] || '';
    }

    backToDashboard(): void {
        if (this.hasUnsavedChanges) {
            if (!confirm('You have unsaved changes. Discard them?')) {
                return;
            }
        }
        this.router.navigate(['/cured']);
    }

    exportContent(): void {
        const blob = new Blob([this.editorContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${this.currentIdentifier}_production.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // ==========================================
    // eBL Integration Methods
    // ==========================================

    toggleLiveValidation(): void {
        this.liveValidationEnabled = !this.liveValidationEnabled;
        if (this.liveValidationEnabled && this.editorContent.trim()) {
            // Trigger validation immediately when enabled
            this.validationSubject.next(this.editorContent);
        } else if (!this.liveValidationEnabled) {
            // Clear validation results when disabled
            this.validationResult = null;
        }
    }

    toggleAtfHelp(): void {
        this.showAtfHelp = !this.showAtfHelp;
        if (!this.showAtfHelp) {
            // Reset search when closing
            this.atfHelpSearchQuery = '';
            this.atfHelpSections = ATF_HELP_CONTENT;
        }
    }

    filterAtfHelp(): void {
        const query = this.atfHelpSearchQuery.toLowerCase().trim();
        if (!query) {
            this.atfHelpSections = ATF_HELP_CONTENT;
            return;
        }

        // Filter sections that match the query
        this.atfHelpSections = ATF_HELP_CONTENT.filter(section => {
            const searchText = getSectionSearchText(section);
            return searchText.includes(query);
        });
    }

    scrollToSection(sectionId: string): void {
        const element = document.getElementById('help-' + sectionId);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    highlightText(text: string): string {
        if (!this.atfHelpSearchQuery || !text) {
            return text;
        }
        const query = this.atfHelpSearchQuery.trim();
        if (!query) {
            return text;
        }
        // Escape special regex characters
        const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escapedQuery})`, 'gi');
        return text.replace(regex, '<mark class="search-highlight">$1</mark>');
    }

    // ==========================================
    // Validation Panel Resize Methods
    // ==========================================

    onValidationResizeStart(event: MouseEvent): void {
        event.preventDefault();
        this.isResizingValidation = true;
        this.resizeStartY = event.clientY;
        this.resizeStartHeight = this.validationPanelHeight;

        // Add document-level listeners for smooth dragging
        document.addEventListener('mousemove', this.onValidationResizeMove);
        document.addEventListener('mouseup', this.onValidationResizeEnd);
    }

    private onValidationResizeMove = (event: MouseEvent): void => {
        if (!this.isResizingValidation) return;

        const deltaY = this.resizeStartY - event.clientY;
        const newHeight = Math.max(60, Math.min(400, this.resizeStartHeight + deltaY));
        this.validationPanelHeight = newHeight;
    };

    private onValidationResizeEnd = (): void => {
        this.isResizingValidation = false;
        document.removeEventListener('mousemove', this.onValidationResizeMove);
        document.removeEventListener('mouseup', this.onValidationResizeEnd);
    };

    private performLiveValidation(content: string): void {
        this.isValidating = true;
        this.eblService.validateAtf(content, this.currentIdentifier).subscribe({
            next: (result) => {
                this.validationResult = result;
                this.isValidating = false;
            },
            error: (err) => {
                console.error('Live validation failed:', err);
                this.isValidating = false;
            }
        });
    }

    validateAtf(): void {
        if (!this.editorContent.trim()) {
            this.notificationService.showWarning('No content to validate');
            return;
        }

        this.isValidating = true;
        this.eblService.validateAtf(this.editorContent, this.currentIdentifier).subscribe({
            next: (result) => {
                this.validationResult = result;
                this.showValidationResults = true;
                this.isValidating = false;

                if (result.valid) {
                    this.notificationService.showSuccess('ATF validation passed');
                } else {
                    this.notificationService.showWarning(`ATF validation found ${result.errors.length} error(s)`);
                }
            },
            error: (err) => {
                console.error('Validation failed:', err);
                this.notificationService.showError('Validation failed');
                this.isValidating = false;
            }
        });
    }

    /**
     * Pull transliteration from eBL and load it into the editor.
     * This fetches the current version from eBL and overwrites local content.
     */
    pullFromEbl(): void {
        if (!this.eblConnected) {
            this.notificationService.showError('eBL is not connected. Please configure credentials first.');
            this.openEblSettings();
            return;
        }

        if (!this.currentIdentifier) {
            this.notificationService.showError('No identifier set. Please set a fragment number first.');
            return;
        }

        // Confirmation dialog since this will overwrite local content
        const hasLocalContent = this.editorContent.trim().length > 0;
        if (hasLocalContent) {
            const confirmMessage = `Pull from eBL?\n\nThis will download the current transliteration for "${this.currentIdentifier}" from eBL and REPLACE your local content.\n\nYour current local changes will be lost.\n\nContinue?`;
            if (!confirm(confirmMessage)) {
                return;
            }
        }

        this.isPullingFromEbl = true;
        this.eblService.getFragment(this.currentIdentifier).subscribe({
            next: (fragment: any) => {
                this.isPullingFromEbl = false;

                // Build summary of what was pulled
                const pulledFields: string[] = [];

                if (fragment.transliteration) {
                    // Load the transliteration into the editor
                    this.editorContent = fragment.transliteration;
                    this.hasUnsavedChanges = true;

                    // Trigger live validation
                    this.validationSubject.next(this.editorContent);

                    pulledFields.push(`transliteration (${fragment.transliteration.split('\n').length} lines)`);
                }

                if (fragment.introduction) {
                    this.pulledIntroduction = fragment.introduction;
                    pulledFields.push('introduction');
                } else {
                    this.pulledIntroduction = '';
                }

                if (fragment.notes) {
                    this.pulledNotes = fragment.notes;
                    pulledFields.push('notes');
                } else {
                    this.pulledNotes = '';
                }

                if (pulledFields.length > 0) {
                    this.notificationService.showSuccess(`Pulled from eBL: ${pulledFields.join(', ')}`);
                } else {
                    this.notificationService.showWarning('Fragment exists but has no content on eBL');
                }
            },
            error: (err) => {
                this.isPullingFromEbl = false;
                console.error('Pull from eBL failed:', err);

                if (err.status === 404) {
                    this.notificationService.showError(`Fragment "${this.currentIdentifier}" not found on eBL`);
                } else if (err.status === 401) {
                    this.notificationService.showError('eBL token expired. Please refresh your credentials.');
                } else {
                    this.notificationService.showError('Failed to pull from eBL: ' + (err.error?.detail || err.message || 'Unknown error'));
                }
            }
        });
    }

    exportToEbl(): void {
        if (!this.eblConnected) {
            this.notificationService.showError('eBL is not connected. Please configure credentials first.');
            this.openEblSettings();
            return;
        }

        if (!this.editorContent.trim()) {
            this.notificationService.showWarning('No content to export');
            return;
        }

        if (!this.currentIdentifier) {
            this.notificationService.showError('No identifier set for this text');
            return;
        }

        // Confirmation dialog to prevent accidental exports
        const confirmMessage = `Export to eBL?\n\nThis will upload the transliteration for "${this.currentIdentifier}" to the eBL platform.\n\n⚠️ WARNING: This will OVERWRITE any existing content on eBL for this fragment, including changes made by other users.\n\nContinue?`;
        if (!confirm(confirmMessage)) {
            return;
        }

        // First validate
        this.isExporting = true;
        this.eblService.exportToEbl(
            this.currentIdentifier,
            this.editorContent
        ).subscribe({
            next: (result) => {
                this.isExporting = false;
                if (result.success) {
                    this.notificationService.showSuccess(result.message);

                    // Mark production text as exported
                    if (this.currentProductionText?.production_id) {
                        this.productionService.markExported(this.currentProductionText.production_id).subscribe({
                            next: () => {
                                console.log('Production text marked as exported');
                            },
                            error: (err) => {
                                console.warn('Failed to mark as exported:', err);
                            }
                        });
                    }

                    if (result.fragment_url) {
                        // Optionally open the fragment in a new tab
                        if (confirm(`Export successful! Open ${result.fragment_url} in eBL?`)) {
                            window.open(result.fragment_url, '_blank');
                        }
                    }
                } else {
                    // Show detailed error message based on error code
                    this.handleExportError(result);
                }
            },
            error: (err) => {
                console.error('Export failed:', err);
                this.notificationService.showError('Export to eBL failed: Network error');
                this.isExporting = false;
            }
        });
    }

    /**
     * Handle export errors with appropriate UI feedback
     */
    private handleExportError(result: any): void {
        let errorTitle = 'Export Failed';

        // Add error code badge if available
        if (result.error_code) {
            switch (result.error_code) {
                case 'NO_PERMISSION':
                    errorTitle = '403 - No Write Permission';
                    break;
                case 'TOKEN_EXPIRED':
                    errorTitle = '401 - Token Expired';
                    break;
                case 'NOT_FOUND':
                    errorTitle = '404 - Fragment Not Found';
                    break;
                case 'VALIDATION_ERROR':
                    errorTitle = '422 - Validation Error';
                    break;
                case 'NETWORK_ERROR':
                    errorTitle = 'Network Error';
                    break;
                case 'API_ERROR':
                    errorTitle = `API Error (${result.status_code || 'Unknown'})`;
                    break;
            }
        }

        // Store error details for overlay
        this.exportErrorTitle = errorTitle;
        this.exportErrorMessage = result.message || 'An error occurred during export';
        this.exportErrorHelp = result.help || '';
        this.exportValidationErrors = result.validation_errors || [];

        // Show the error overlay
        this.showExportErrorOverlay = true;

        // If there are validation errors, also update the live validation panel
        if (result.validation_errors && result.validation_errors.length > 0) {
            // Use structured validation_details if available (has accurate line numbers)
            const errors = result.validation_details
                ? result.validation_details.map((d: any) => ({ line: d.line || 0, column: d.column || undefined, message: d.message }))
                : result.validation_errors.map((err: string, idx: number) => ({ line: idx + 1, message: err }));

            this.validationResult = {
                valid: false,
                errors: errors,
                error_strings: result.validation_errors,
                warnings: [],
                parsed_lines: 0,
                validation_source: 'ebl_api'
            };
            // Enable live validation panel to show the errors
            this.liveValidationEnabled = true;
        }

        // Also show notification
        this.notificationService.showError(errorTitle);
    }

    /**
     * Close the export error overlay
     */
    closeExportErrorOverlay(): void {
        this.showExportErrorOverlay = false;
        this.exportErrorTitle = '';
        this.exportErrorMessage = '';
        this.exportErrorHelp = '';
        this.exportValidationErrors = [];
    }

    openEblSettings(): void {
        this.showEblSettings = true;
        // Refresh status
        this.eblService.checkStatus().subscribe();
    }

    closeEblSettings(): void {
        this.showEblSettings = false;
    }

    extractTokenFromJson(value: string): void {
        if (!value) return;
        const trimmed = value.trim();
        // If it looks like JSON (starts with {), try to extract access_token
        if (trimmed.startsWith('{')) {
            try {
                const parsed = JSON.parse(trimmed);
                const token = this.findAccessToken(parsed);
                if (token) {
                    this.eblConfig.access_token = token;
                }
            } catch (e) {
                // Not valid JSON, leave as-is (user is typing a raw token)
            }
        }
    }

    private findAccessToken(obj: any): string | null {
        if (!obj || typeof obj !== 'object') return null;
        // Direct access_token field
        if (typeof obj.access_token === 'string' && obj.access_token.length > 20) {
            return obj.access_token;
        }
        // Search nested objects (e.g. { body: { access_token: "..." } })
        for (const key of Object.keys(obj)) {
            if (typeof obj[key] === 'object' && obj[key] !== null) {
                const found = this.findAccessToken(obj[key]);
                if (found) return found;
            }
        }
        return null;
    }

    saveEblConfig(): void {
        this.isSavingEblConfig = true;
        this.eblService.configure(this.eblConfig).subscribe({
            next: (result) => {
                this.isSavingEblConfig = false;
                if (result.success) {
                    this.notificationService.showSuccess('eBL configuration saved');
                    this.closeEblSettings();
                } else {
                    this.notificationService.showError(result.message);
                }
            },
            error: (err) => {
                console.error('Failed to save eBL config:', err);
                this.notificationService.showError('Failed to save eBL configuration');
                this.isSavingEblConfig = false;
            }
        });
    }

    connectViaOAuth(): void {
        this.isOAuthPending = true;
        this.oAuthError = null;

        this.eblService.startOAuth().subscribe({
            next: () => {
                // Start polling for OAuth completion
                let elapsed = 0;
                this.oauthPollInterval = setInterval(() => {
                    elapsed += 2000;
                    if (elapsed > 120000) {
                        // Timeout after 2 minutes
                        this.cancelOAuth();
                        this.oAuthError = 'Login timed out. Please try again.';
                        return;
                    }
                    this.eblService.getOAuthStatus().subscribe({
                        next: (status) => {
                            if (!status.oauth_pending) {
                                // OAuth flow completed (success or error)
                                this.cancelOAuth();
                                if (status.authenticated) {
                                    this.notificationService.showSuccess('Connected to eBL');
                                    this.eblService.checkStatus().subscribe();
                                    this.closeEblSettings();
                                } else if (status.oauth_error) {
                                    this.oAuthError = status.oauth_error;
                                }
                            }
                        },
                        error: () => {
                            // Polling error, keep trying
                        }
                    });
                }, 2000);
            },
            error: (err) => {
                this.isOAuthPending = false;
                this.oAuthError = 'Failed to start login flow';
                console.error('OAuth start failed:', err);
            }
        });
    }

    loginWithCredentials(): void {
        if (!this.eblUsername || !this.eblPassword) {
            this.loginError = 'Please enter email and password';
            return;
        }
        this.isLoggingIn = true;
        this.loginError = null;

        this.eblService.login(this.eblUsername, this.eblPassword).subscribe({
            next: () => {
                this.isLoggingIn = false;
                this.eblPassword = '';
                this.notificationService.showSuccess('Connected to eBL');
                this.closeEblSettings();
            },
            error: (err) => {
                this.isLoggingIn = false;
                this.loginError = err.error?.detail || 'Login failed. Check your credentials.';
                console.error('Login failed:', err);
            }
        });
    }

    cancelOAuth(): void {
        if (this.oauthPollInterval) {
            clearInterval(this.oauthPollInterval);
            this.oauthPollInterval = null;
        }
        this.isOAuthPending = false;
    }

    disconnectEbl(): void {
        this.eblService.disconnect().subscribe({
            next: () => {
                this.notificationService.showSuccess('Disconnected from eBL');
                this.authMethod = null;
            },
            error: (err) => {
                console.error('Disconnect failed:', err);
                this.notificationService.showError('Failed to disconnect');
            }
        });
    }

    closeValidationResults(): void {
        this.showValidationResults = false;
        this.validationResult = null;
    }

    getValidationSourceLabel(): string {
        if (!this.validationResult) return '';
        switch (this.validationResult.validation_source) {
            case 'ebl_api':
                return 'eBL API';
            case 'local_lark':
                return 'Local (Lark)';
            case 'local_basic':
                return 'Local (Basic)';
            case 'local':
                return 'Local';
            default:
                return this.validationResult.validation_source;
        }
    }

    getValidationSourceTooltip(): string {
        if (!this.validationResult) return '';
        switch (this.validationResult.validation_source) {
            case 'ebl_api':
                return 'Validated by eBL API with full sign verification';
            case 'local_lark':
                return 'Validated locally using eBL-ATF grammar (syntax only, no sign verification)';
            case 'local_basic':
                return 'Basic validation (bracket checking only)';
            case 'local':
                return 'Local validation';
            default:
                return '';
        }
    }

    /**
     * Get human-readable error strings for display.
     * Uses error_strings if available, otherwise formats from structured errors.
     */
    getErrorStrings(): string[] {
        if (!this.validationResult) return [];

        // Use error_strings if available (preferred for display)
        if (this.validationResult.error_strings && this.validationResult.error_strings.length > 0) {
            return this.validationResult.error_strings;
        }

        // Fallback: format from structured errors
        return this.validationResult.errors.map(err => {
            if (typeof err === 'string') {
                return err;
            }
            const col = err.column ? `, col ${err.column}` : '';
            return `Line ${err.line}${col}: ${err.message}`;
        });
    }

    // ==========================================
    // Image Upload Methods
    // ==========================================

    closePdfPageSelector(): void {
        this.showPdfPageSelector = false;
        this.pdfSrc = null;
        this.pdfFile = null;
        this.pdfTotalPages = 0;
        this.pdfPageNumbers = [];
        this.pdfVisiblePageNumbers = [];
        this.pdfGoToPageInput = 1;
        this.isUploadingImage = false;
    }

    handleImageFileInput(event: Event): void {
        const input = event.target as HTMLInputElement;
        const file = input?.files?.[0];
        if (file) {
            this.processUploadedFile(file);
        }
        // Reset input so same file can be selected again
        input.value = '';
    }

    private processUploadedFile(file: File): void {
        const fileName = file.name.toLowerCase();

        if (fileName.endsWith('.pdf')) {
            this.loadPDFFile(file);
        } else if (fileName.endsWith('.png') || fileName.endsWith('.jpg') || fileName.endsWith('.jpeg')) {
            this.addImageAsSource(file);
        } else {
            this.notificationService.showError('Unsupported file type. Please use PDF, PNG, or JPG.');
        }
    }

    private loadPDFFile(file: File): void {
        this.pdfFile = file;
        this.pdfTotalPages = 0;
        this.pdfPageNumbers = [];
        this.pdfVisiblePageNumbers = [];
        this.showPdfPageSelector = true;

        const fileReader = new FileReader();
        fileReader.addEventListener('load', () => {
            this.pdfSrc = new Uint8Array(fileReader.result as ArrayBuffer);
        });
        fileReader.readAsArrayBuffer(file);
    }

    afterPdfLoadComplete(pdf: PDFDocumentProxy): void {
        this.pdfTotalPages = pdf.numPages;
        this.pdfPageNumbers = Array.from({ length: pdf.numPages }, (_, i) => i + 1);
        this.pdfGoToPageInput = 1;
        this.updateVisiblePdfPages(1);
    }

    updateVisiblePdfPages(targetPage: number): void {
        if (this.pdfTotalPages === 0) return;

        let startPage = Math.max(1, targetPage - 4);
        let endPage = Math.min(this.pdfTotalPages, startPage + this.PDF_PAGE_WINDOW_SIZE - 1);

        if (endPage - startPage + 1 < this.PDF_PAGE_WINDOW_SIZE) {
            startPage = Math.max(1, endPage - this.PDF_PAGE_WINDOW_SIZE + 1);
        }

        this.pdfVisiblePageNumbers = [];
        for (let i = startPage; i <= endPage; i++) {
            this.pdfVisiblePageNumbers.push(i);
        }
    }

    jumpToPdfPage(): void {
        const page = Math.max(1, Math.min(this.pdfTotalPages, this.pdfGoToPageInput || 1));
        this.pdfGoToPageInput = page;
        this.updateVisiblePdfPages(page);
    }

    nextPdfPageWindow(): void {
        const lastVisible = this.pdfVisiblePageNumbers[this.pdfVisiblePageNumbers.length - 1];
        if (lastVisible < this.pdfTotalPages) {
            this.updateVisiblePdfPages(lastVisible + 1);
            this.pdfGoToPageInput = this.pdfVisiblePageNumbers[0];
        }
    }

    prevPdfPageWindow(): void {
        const firstVisible = this.pdfVisiblePageNumbers[0];
        if (firstVisible > 1) {
            const newTarget = Math.max(1, firstVisible - this.PDF_PAGE_WINDOW_SIZE);
            this.updateVisiblePdfPages(newTarget);
            this.pdfGoToPageInput = this.pdfVisiblePageNumbers[0];
        }
    }

    selectPdfPage(page: number): void {
        if (!this.pdfFile) return;

        this.isUploadingImage = true;
        const selectedPdf = new SelectedPdf(this.pdfFile, page);

        this.curedService.convertPdf(selectedPdf).subscribe({
            next: (blob) => {
                if (blob) {
                    const imageFile = new File([blob], `page-${page}.png`, { type: 'image/png' });
                    this.addImageAsSource(imageFile);
                }
                this.isUploadingImage = false;
            },
            error: (err) => {
                console.error('Failed to convert PDF page:', err);
                this.notificationService.showError('Failed to convert PDF page');
                this.isUploadingImage = false;
            }
        });
    }

    private loadFromLibrary(projectId: string, pageNumber: number): void {
        const imageUrl = this.pagesService.getPageImageUrl(projectId, pageNumber);
        this.http.get(imageUrl, { responseType: 'blob' }).subscribe({
            next: (blob) => {
                const file = new File([blob], `page_${pageNumber}.png`, { type: 'image/png' });
                this.addImageAsSource(file);
            },
            error: () => {
                this.notificationService.showError('Failed to load image from library');
                this.loadDashboard();
            }
        });
    }

    browseServerImages(): void {
        const dialogRef = this.dialog.open(ImageBrowserDialogComponent, {
            width: '1000px', height: '720px'
        });
        dialogRef.afterClosed().subscribe((result: SelectedPage[] | null) => {
            if (!result || result.length === 0) return;
            const page = result[0];
            this.http.get(page.image_url, { responseType: 'blob' }).subscribe(blob => {
                const file = new File([blob], page.filename, { type: 'image/png' });
                this.addImageAsSource(file);
            });
        });
    }

    private addImageAsSource(file: File): void {
        const newIndex = this.currentSources.length;
        const label = `Uploaded ${this.getNextUploadedImageNumber()}`;

        // Add to sources
        const newSource: SourceTextContent = {
            text_id: -1, // Temporary ID for uploaded images
            transliteration_id: -1,
            part: label,
            lines: [],
            image_name: file.name
        };
        this.currentSources.push(newSource);

        // Create data URL for immediate display in canvas
        const reader = new FileReader();
        reader.onload = () => {
            const dataUrl = reader.result as string;
            this.sourceImageDataUrls.set(newIndex, dataUrl);
            if (newIndex === this.selectedSourceIndex) {
                this.loadImageIntoCanvas(dataUrl);
            }
        };
        reader.readAsDataURL(file);

        // Select the new source
        this.selectedSourceIndex = newIndex;

        // Close PDF page selector if open
        if (this.showPdfPageSelector) {
            this.closePdfPageSelector();
        }

        // If we have a production text, upload to backend immediately
        if (this.currentProductionText) {
            this.uploadImageToBackend(file, label, newIndex);
        } else {
            // Store for later upload when production text is created
            this.pendingImageUploads.push({ file, label });
            this.hasUnsavedChanges = true;
            this.notificationService.showSuccess('Image added (will be saved with text)');
        }
    }

    private getNextUploadedImageNumber(): number {
        // Count existing uploaded images
        let maxNum = 0;
        for (const source of this.currentSources) {
            if (source.text_id === -1 && source.part.startsWith('Uploaded ')) {
                const num = parseInt(source.part.replace('Uploaded ', ''), 10);
                if (!isNaN(num) && num > maxNum) {
                    maxNum = num;
                }
            }
        }
        return maxNum + 1;
    }

    private uploadImageToBackend(file: File, label: string, sourceIndex: number): void {
        this.isUploadingImage = true;

        this.productionService.uploadImage(
            this.currentProductionText!.production_id,
            file,
            label
        ).subscribe({
            next: (uploadedImage) => {
                this.uploadedImageIds.set(sourceIndex, uploadedImage.image_id);
                this.isUploadingImage = false;
                this.notificationService.showSuccess('Image saved');
            },
            error: (err) => {
                console.error('Failed to upload image:', err);
                this.notificationService.showError('Failed to save image');
                this.isUploadingImage = false;
            }
        });
    }

    private uploadPendingImages(): void {
        if (!this.currentProductionText || this.pendingImageUploads.length === 0) {
            return;
        }

        // Upload all pending images
        for (const pending of this.pendingImageUploads) {
            // Find the source index for this pending image
            const sourceIndex = this.currentSources.findIndex(
                s => s.text_id === -1 && s.part === pending.label
            );
            if (sourceIndex !== -1) {
                this.uploadImageToBackend(pending.file, pending.label, sourceIndex);
            }
        }

        // Clear pending uploads
        this.pendingImageUploads = [];
    }
}
