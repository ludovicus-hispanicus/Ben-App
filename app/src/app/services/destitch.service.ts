import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import {
  DestitchClassifyRequest,
  DestitchClassification,
  DestitchSplitRequest,
  DestitchSplitByPathRequest,
  DestitchResult,
  DestitchBatchStartRequest,
  DestitchBatchStartResponse,
  DestitchBatchStatus,
  DestitchBatchJobSummary,
  LocalFolderInfo,
} from '../models/destitch';

@Injectable({ providedIn: 'root' })
export class DestitchService {
  private base = '/destitch';
  private batchBase = '/destitch-batch';

  constructor(private http: HttpClient) {}

  classify(body: DestitchClassifyRequest): Observable<DestitchClassification> {
    return this.http.post<DestitchClassification>(
      `${environment.apiUrl}${this.base}/classify`,
      body,
    );
  }

  split(body: DestitchSplitRequest): Observable<DestitchResult> {
    return this.http.post<DestitchResult>(
      `${environment.apiUrl}${this.base}/split`,
      body,
    );
  }

  splitByPath(body: DestitchSplitByPathRequest): Observable<DestitchResult> {
    return this.http.post<DestitchResult>(
      `${environment.apiUrl}${this.base}/split-by-path`,
      body,
    );
  }

  startBatch(body: DestitchBatchStartRequest): Observable<DestitchBatchStartResponse> {
    return this.http.post<DestitchBatchStartResponse>(
      `${environment.apiUrl}${this.batchBase}/start`,
      body,
    );
  }

  getBatchStatus(jobId: string): Observable<DestitchBatchStatus> {
    return this.http.get<DestitchBatchStatus>(
      `${environment.apiUrl}${this.batchBase}/${jobId}/status`,
    );
  }

  listJobs(limit = 20): Observable<DestitchBatchJobSummary[]> {
    return this.http.get<DestitchBatchJobSummary[]>(
      `${environment.apiUrl}${this.batchBase}/jobs`,
      { params: { limit: limit.toString() } },
    );
  }

  cancelJob(jobId: string): Observable<{ success: boolean; message?: string; error?: string }> {
    return this.http.post<{ success: boolean; message?: string; error?: string }>(
      `${environment.apiUrl}${this.batchBase}/${jobId}/cancel`,
      {},
    );
  }

  browseLocalFolder(path?: string, includeImages = false): Observable<LocalFolderInfo> {
    const params: any = {};
    if (path) { params.path = path; }
    if (includeImages) { params.include_images = 'true'; }
    return this.http.get<LocalFolderInfo>(
      `${environment.apiUrl}${this.batchBase}/browse-local`,
      { params },
    );
  }
}
