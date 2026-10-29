import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { environment } from 'src/environments/environment';
import { ModuleService } from '../../services/module.service';

interface DashboardSummary {
  recent_texts: Array<{ text_id: number; transliteration_id: number | null; label: string; dataset: string | null;
                        last_modified: string; lines: number; curated: boolean }>;
  data: { datasets: number; texts: number; curated_texts: number; curated_lines: number;
          per_dataset: Array<{ dataset_id: number; name: string; texts: number; curated: number; curated_lines: number }> };
  engines: { kraken?: { active_model: string | null }; layout?: { active_model: string | null };
             ollama?: { running: boolean; vision_models: number } };
  activity: Array<{ kind: string; when: string; title: string; detail: string; status: string }>;
}

interface NewsResponse {
  enabled: boolean;
  entries: Array<{ date: string; title: string; body: string }>;
  error: string | null;
  installed_version: string;
  latest_version: string | null;
  release_url: string | null;
  update_available: boolean;
}

/** The start page: entry points, recent work, data, engine status, activity and news. */
@Component({
  selector: 'app-admin-panel',
  templateUrl: './admin-panel.component.html',
  styleUrls: ['./admin-panel.component.scss']
})
export class AdminPanelComponent implements OnInit {
  summary: DashboardSummary | null = null;
  summaryError = false;
  news: NewsResponse | null = null;
  /** News dated after the last visit are marked as new. */
  newsSeenUntil = '';

  // Cloud API keys are kept in this browser (see CuReD), so their state is read here
  readonly cloudApis = [
    { key: 'gemini_vision', label: 'Gemini' },
    { key: 'claude_vision', label: 'Claude' },
    { key: 'gpt4_vision', label: 'OpenAI' },
    { key: 'grok_xai', label: 'Grok' },
  ];

  constructor(public router: Router, public moduleService: ModuleService, private http: HttpClient) { }

  ngOnInit(): void {
    this.http.get<DashboardSummary>(`${environment.apiUrl}/dashboard/summary`).subscribe({
      next: (s) => this.summary = s,
      error: () => this.summaryError = true,
    });
    this.newsSeenUntil = this.storageGet('ben_news_seen_until') || '';
    this.http.get<NewsResponse>(`${environment.apiUrl}/dashboard/news`).subscribe({
      next: (n) => {
        this.news = n;
        const newest = n.entries[0]?.date;
        if (newest) this.storageSet('ben_news_seen_until', newest);
      },
      error: () => this.news = null,
    });
  }

  hasApiKey(provider: string): boolean {
    return !!this.storageGet('ocr_api_key_' + provider);
  }

  get apiKeysSet(): string[] {
    return this.cloudApis.filter(a => this.hasApiKey(a.key)).map(a => a.label);
  }

  isNewNews(date: string): boolean {
    return !!this.newsSeenUntil && date > this.newsSeenUntil;
  }

  openText(t: DashboardSummary['recent_texts'][0]): void {
    const queryParams: any = t.transliteration_id
      ? { textId: t.text_id, transId: t.transliteration_id, returnTo: '/', returnLabel: 'Dashboard' }
      : { textId: t.text_id };
    this.router.navigate(['/cured'], { queryParams });
  }

  openDataset(datasetId: number): void {
    this.router.navigate(['/cured'], { queryParams: { dataset: datasetId } });
  }

  activityIcon(kind: string): string {
    return kind === 'batch' ? 'batch_prediction' : kind === 'layout_training' ? 'grid_view' : 'model_training';
  }

  percent(part: number, whole: number): number {
    return whole ? Math.round(part / whole * 100) : 0;
  }

  private storageGet(key: string): string | null {
    try { return localStorage.getItem(key); } catch { return null; }
  }

  private storageSet(key: string, value: string): void {
    try { localStorage.setItem(key, value); } catch { /* private mode */ }
  }
}
