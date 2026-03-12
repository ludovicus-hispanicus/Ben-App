import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import {
  BatchRecognitionRequest,
  BatchRecognitionResponse,
  BatchRecognitionStatus,
  BatchRecognitionJobSummary,
  LocalFolderInfo,
  VllmStatus,
} from '../models/batch-recognition';

@Injectable({ providedIn: 'root' })
export class BatchRecognitionService {
  private baseUrl = '/batch-recognition';

  constructor(private http: HttpClient) {}

  startBatch(request: BatchRecognitionRequest): Observable<BatchRecognitionResponse> {
    return this.http.post<BatchRecognitionResponse>(
      `${environment.apiUrl}${this.baseUrl}/start`,
      request
    );
  }

  getJobStatus(jobId: string): Observable<BatchRecognitionStatus> {
    return this.http.get<BatchRecognitionStatus>(
      `${environment.apiUrl}${this.baseUrl}/${jobId}/status`
    );
  }

  listJobs(limit: number = 20): Observable<BatchRecognitionJobSummary[]> {
    return this.http.get<BatchRecognitionJobSummary[]>(
      `${environment.apiUrl}${this.baseUrl}/jobs`,
      { params: { limit: limit.toString() } }
    );
  }

  cancelJob(jobId: string): Observable<{ success: boolean; message: string }> {
    return this.http.post<{ success: boolean; message: string }>(
      `${environment.apiUrl}${this.baseUrl}/${jobId}/cancel`,
      {}
    );
  }

  getUsage(days: number = 7): Observable<any[]> {
    return this.http.get<any[]>(
      `${environment.apiUrl}${this.baseUrl}/usage`,
      { params: { days: days.toString() } }
    );
  }

  getVllmStatus(): Observable<VllmStatus> {
    return this.http.get<VllmStatus>(
      `${environment.apiUrl}${this.baseUrl}/vllm-status`
    );
  }

  browseLocalFolder(path?: string): Observable<LocalFolderInfo> {
    const params: any = {};
    if (path) { params.path = path; }
    return this.http.get<LocalFolderInfo>(
      `${environment.apiUrl}${this.baseUrl}/browse-local`,
      { params }
    );
  }
}
