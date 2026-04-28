import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';

// ── Interfaces ──

export interface AtfToken {
    index: number;
    raw: string;
    cleaned: string;
    is_determinative: boolean;
    is_number: boolean;
    is_damaged: boolean;
    is_uncertain: boolean;
    is_broken: boolean;
    is_logogram: boolean;
    is_complex: boolean;
    detected_suffix: string;
    suffix_lemma: string;
    match_level: string;  // "exact", "suggestion", "none"
    lemma_candidates: string[];
    morph_analysis: { lemma_id: string; root: string; stem: string; tense: string; person: string; form: string }[];
    detected_enclitic: string;
}

export interface AtfLine {
    line_number: string;
    raw_text: string;
    tokens: AtfToken[];
    line_type: string;
    atf_index: number;
}

export interface TokenizedText {
    lines: AtfLine[];
    content_hash: string;
}

export interface LemmaAssignment {
    value: string;
    unique_lemma: string[];
    // Suggestion metadata (populated by ORACC import)
    is_suggestion?: boolean;
    suggestion_source?: string;   // e.g., "atf_import"
    oracc_guideword?: string;     // English translation (e.g., "command")
    oracc_citation?: string;      // Akkadian citation form (e.g., "amātu")
    oracc_pos?: string;           // ORACC POS tag (e.g., "N", "V")
}

export interface LineLemmatization {
    line_number: string;
    tokens: LemmaAssignment[];
}

export interface TextLemmatization {
    production_id: number;
    content_hash: string;
    lines: LineLemmatization[];
    last_modified: string;
    ai_suggested: boolean;
}

export interface WordEntry {
    word_id: string;
    lemma: string[];
    homonym: string;
    pos: string[];
    guide_word: string;
    roots: string[];
    forms: string[];
    origin: string;
}

export interface DictionaryStatus {
    downloaded: boolean;
    word_count: number;
    last_updated: string;
    index_size: number;
}

export interface DownloadProgress {
    downloading: boolean;
    progress: number;
    total: number;
}

// ── Service ──

@Injectable({ providedIn: 'root' })
export class LemmatizationService {

    private baseUrl = `${environment.apiUrl}/lemmatization`;

    // Observable state
    private dictionaryStatusSubject = new BehaviorSubject<DictionaryStatus | null>(null);
    dictionaryStatus$ = this.dictionaryStatusSubject.asObservable();

    constructor(private http: HttpClient) {}

    // ── Tokenization ──

    tokenize(atfText: string): Observable<TokenizedText> {
        return this.http.post<TokenizedText>(`${this.baseUrl}/tokenize`, {
            atf_text: atfText
        });
    }

    // ── Dictionary ──

    getDictionaryStatus(): Observable<DictionaryStatus> {
        return this.http.get<DictionaryStatus>(`${this.baseUrl}/dictionary/status`).pipe(
            tap(status => this.dictionaryStatusSubject.next(status))
        );
    }

    downloadDictionary(): Observable<any> {
        return this.http.post(`${this.baseUrl}/dictionary/download`, {});
    }

    getDownloadProgress(): Observable<DownloadProgress> {
        return this.http.get<DownloadProgress>(`${this.baseUrl}/dictionary/download/progress`);
    }

    lookupWord(form: string): Observable<WordEntry[]> {
        return this.http.get<WordEntry[]>(`${this.baseUrl}/dictionary/lookup/${encodeURIComponent(form)}`);
    }

    getWordEntry(wordId: string): Observable<WordEntry> {
        return this.http.get<WordEntry>(`${this.baseUrl}/dictionary/word/${encodeURIComponent(wordId)}`);
    }

    searchWords(query: string, limit: number = 20): Observable<WordEntry[]> {
        return this.http.post<WordEntry[]>(`${this.baseUrl}/dictionary/search`, { query, limit });
    }

    // ── Lemmatization CRUD ──

    getLemmatization(productionId: number): Observable<TextLemmatization> {
        return this.http.get<TextLemmatization>(`${this.baseUrl}/${productionId}`);
    }

    saveLemmatization(productionId: number, data: TextLemmatization): Observable<TextLemmatization> {
        return this.http.put<TextLemmatization>(`${this.baseUrl}/${productionId}`, {
            production_id: data.production_id,
            content_hash: data.content_hash,
            lines: data.lines,
            ai_suggested: data.ai_suggested
        });
    }

    deleteLemmatization(productionId: number): Observable<any> {
        return this.http.delete(`${this.baseUrl}/${productionId}`);
    }

    addCustomMapping(form: string, lemmaId: string): Observable<any> {
        return this.http.post(`${this.baseUrl}/dictionary/custom-mapping`, { form, lemma_id: lemmaId });
    }

    // ── AI Suggestions ──

    aiSuggest(productionId: number, atfText: string): Observable<TextLemmatization> {
        return this.http.post<TextLemmatization>(`${this.baseUrl}/${productionId}/ai-suggest`, {
            atf_text: atfText
        });
    }

    // ── eBL Export ──

    exportToEbl(productionId: number, fragmentNumber: string): Observable<any> {
        return this.http.post(`${this.baseUrl}/${productionId}/export-ebl`, {
            fragment_number: fragmentNumber
        });
    }
}
